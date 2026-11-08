# 验证策略目录的 SQL 事务：发布不可变、请求幂等、停用保留历史与组合冻结。
# 测试使用专用测试库的随机 schema；直接 SQL 更新用于证明数据库触发器也拒绝改写发布版本。
# 所有策略文本与参数均为合成夹具，不包含用户策略算法、凭证或真实财务资料。
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.research_strategies import (
    StrategyCatalogRequestRecord,
    StrategyDefinitionRecord,
    StrategyVersionRecord,
)
from app.infrastructure.persistence.strategy_catalog import SqlAlchemyStrategyCatalog
from app.market.contracts import MarketTimeframe
from app.research.strategies.contracts import (
    StrategyCapability,
    StrategyComponent,
    StrategyConflictError,
    StrategyDraft,
    StrategyIntegrityError,
    StrategyKind,
    StrategyNotAvailableError,
    StrategyVersion,
    strategy_draft_sha256,
)
from app.shared.agent_types import PageQuery

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)


class Database(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


# 固定时钟让发布时间和请求重放具备可重复证据；不代表真实服务使用客户端时钟。
def _clock() -> datetime:
    return NOW


# 空参数 Schema 用于组合组成，证明组成引用冻结而不要求组成自身有可执行参数。
def _empty_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
        "required": [],
    }


# 构造单策略草稿；测试通过覆盖字段验证修订哈希和请求内容冲突。
def _draft(
    *,
    strategy_id: UUID | None = None,
    name: str = "技术突破规则",
    evaluator_id: str = "technical_breakout_v1",
    parameter_schema: dict[str, Any] | None = None,
    kind: StrategyKind = StrategyKind.SINGLE,
    components: tuple[StrategyComponent, ...] = (),
    composition_rules: str | None = None,
    state_version: int = 0,
) -> StrategyDraft:
    return StrategyDraft(
        draft_id=uuid4(),
        strategy_id=strategy_id or uuid4(),
        name=name,
        method_text="仅使用已收盘 K 线的成交量突破与结构位方法。",
        kind=kind,
        components=components,
        composition_rules=composition_rules,
        parameter_schema=parameter_schema or _empty_schema(),
        supported_symbols=("BTCUSDT",),
        supported_timeframes=(
            MarketTimeframe.H1,
            MarketTimeframe.H4,
            MarketTimeframe.D1,
        ),
        warmup_candles=60,
        evaluator_id=evaluator_id,
        capabilities=(
            StrategyCapability.RESEARCH,
            StrategyCapability.PRICE_CANDIDATE,
            StrategyCapability.MANUAL_PLANNING,
        ),
        risk_notes="合成测试策略，不产生真实计划。",
        state_version=state_version,
    )


# 创建并发布一个可复用版本，返回发布对象供组合或归档测试引用。
async def _published(
    catalog: SqlAlchemyStrategyCatalog,
    workspace_id: UUID,
    *,
    strategy_id: UUID | None = None,
    name: str = "技术突破规则",
    evaluator_id: str = "technical_breakout_v1",
    parameter_schema: dict[str, Any] | None = None,
) -> StrategyVersion:
    draft = await catalog.create_draft(
        workspace_id,
        _draft(
            strategy_id=strategy_id,
            name=name,
            evaluator_id=evaluator_id,
            parameter_schema=parameter_schema,
        ),
        request_id=uuid4(),
    )
    return await catalog.publish(
        workspace_id,
        draft.draft_id,
        expected_version=0,
        request_id=uuid4(),
    )


# 发布后草稿不可再改，数据库触发器拒绝直接改写发布版本；请求重放返回同一版本。
@pytest.mark.asyncio
async def test_publish_freezes_version_and_replays_same_request(
    migrated_database: Database,
) -> None:
    catalog = SqlAlchemyStrategyCatalog(migrated_database.session_factory, clock=_clock)
    workspace_id = uuid4()
    draft = _draft()
    created = await catalog.create_draft(workspace_id, draft, request_id=uuid4())
    publish_request = uuid4()

    published = await catalog.publish(
        workspace_id,
        created.draft_id,
        expected_version=0,
        request_id=publish_request,
    )
    replayed = await catalog.publish(
        workspace_id,
        created.draft_id,
        expected_version=0,
        request_id=publish_request,
    )

    assert published.ref.version_id == created.draft_id
    assert published.ref.sha256 == strategy_draft_sha256(created)
    assert published.ref.sha256 != strategy_draft_sha256(
        _draft(
            strategy_id=draft.strategy_id,
            name=draft.name + " 修订",
        )
    )
    assert replayed == published
    assert await catalog.get_published(workspace_id, published.ref) == published

    with pytest.raises(StrategyConflictError):
        await catalog.update_draft(
            workspace_id,
            created.draft_id,
            _draft(strategy_id=draft.strategy_id),
            expected_version=0,
            request_id=uuid4(),
        )

    async with migrated_database.session_factory() as session:
        try:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(
                    update(StrategyVersionRecord)
                    .where(StrategyVersionRecord.id == published.ref.version_id)
                    .values(sha256="f" * 64)
                )
                await session.commit()
        finally:
            await session.rollback()

    async with migrated_database.session_factory() as session:
        try:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(
                    delete(StrategyVersionRecord).where(
                        StrategyVersionRecord.id == published.ref.version_id
                    )
                )
                await session.commit()
        finally:
            await session.rollback()


# 同一请求键重放同一内容；不同内容或过期版本必须作为冲突拒绝，不静默覆盖。
@pytest.mark.asyncio
async def test_duplicate_request_and_stale_expected_version_are_conflicts(
    migrated_database: Database,
) -> None:
    catalog = SqlAlchemyStrategyCatalog(migrated_database.session_factory, clock=_clock)
    workspace_id = uuid4()
    request_id = uuid4()
    draft = _draft()

    first = await catalog.create_draft(workspace_id, draft, request_id=request_id)
    replay = await catalog.create_draft(workspace_id, draft, request_id=request_id)
    assert replay == first

    with pytest.raises(StrategyConflictError):
        await catalog.create_draft(
            workspace_id,
            _draft(strategy_id=draft.strategy_id, name="不同内容"),
            request_id=request_id,
        )

    with pytest.raises(StrategyConflictError):
        await catalog.publish(
            workspace_id,
            first.draft_id,
            expected_version=99,
            request_id=uuid4(),
        )


# 停用后新执行取不到发布版本，但历史列表仍能读取并显示归档状态；旧请求重放不重复执行。
@pytest.mark.asyncio
async def test_archive_blocks_new_execution_and_keeps_history(
    migrated_database: Database,
) -> None:
    catalog = SqlAlchemyStrategyCatalog(migrated_database.session_factory, clock=_clock)
    workspace_id = uuid4()
    draft = _draft()
    created = await catalog.create_draft(workspace_id, draft, request_id=uuid4())
    published = await catalog.publish(
        workspace_id,
        created.draft_id,
        expected_version=0,
        request_id=uuid4(),
    )
    archive_request = uuid4()

    await catalog.archive(
        workspace_id,
        published.strategy_id,
        expected_version=published.state_version,
        request_id=archive_request,
    )
    await catalog.archive(
        workspace_id,
        published.strategy_id,
        expected_version=published.state_version,
        request_id=archive_request,
    )

    with pytest.raises(StrategyNotAvailableError):
        await catalog.get_published(workspace_id, published.ref)

    page = await catalog.list_versions(workspace_id, PageQuery(page=1, page_size=10))
    assert page.total == 1
    assert page.items[0].ref == published.ref
    assert page.items[0].archived is True

    with pytest.raises(StrategyNotAvailableError):
        await catalog.create_draft(
            workspace_id,
            _draft(strategy_id=published.strategy_id, name="归档后的新草稿"),
            request_id=uuid4(),
        )


# 组合发布冻结已发布组成引用；未发布或哈希不匹配的组成不能被当作同一版本使用。
@pytest.mark.asyncio
async def test_composite_publish_freezes_published_component_refs(
    migrated_database: Database,
) -> None:
    catalog = SqlAlchemyStrategyCatalog(migrated_database.session_factory, clock=_clock)
    workspace_id = uuid4()
    first = await _published(catalog, workspace_id, name="趋势组成")
    second = await _published(catalog, workspace_id, name="确认组成")
    frozen_components = (
        StrategyComponent(role="trend", strategy_ref=first.ref, parameters={}),
        StrategyComponent(role="confirmation", strategy_ref=second.ref, parameters={}),
    )

    composite_draft = await catalog.create_draft(
        workspace_id,
        _draft(
            kind=StrategyKind.COMPOSITE,
            components=frozen_components,
            composition_rules="仅由已登记测试评估器解释。",
            evaluator_id="test_composite_v1",
        ),
        request_id=uuid4(),
    )
    composite = await catalog.publish(
        workspace_id,
        composite_draft.draft_id,
        expected_version=0,
        request_id=uuid4(),
    )

    assert composite.components == frozen_components
    assert tuple(component.strategy_ref for component in composite.components) == (
        first.ref,
        second.ref,
    )

    unresolved = _draft(
        kind=StrategyKind.COMPOSITE,
        components=(
            StrategyComponent(role="trend", strategy_ref=first.ref, parameters={}),
            StrategyComponent(
                role="confirmation",
                strategy_ref=second.ref.model_copy(update={"sha256": "0" * 64}),
                parameters={},
            ),
        ),
        composition_rules="使用被篡改的组成哈希。",
        evaluator_id="test_composite_v1",
    )
    unresolved_draft = await catalog.create_draft(workspace_id, unresolved, request_id=uuid4())
    with pytest.raises(StrategyIntegrityError):
        await catalog.publish(
            workspace_id,
            unresolved_draft.draft_id,
            expected_version=0,
            request_id=uuid4(),
        )


# 历史列表按发布时间稳定分页；组合版本只返回已发布版本，不泄露草稿。
@pytest.mark.asyncio
async def test_list_versions_paginates_published_versions(
    migrated_database: Database,
) -> None:
    catalog = SqlAlchemyStrategyCatalog(migrated_database.session_factory, clock=_clock)
    workspace_id = uuid4()
    first = await _published(catalog, workspace_id, name="版本一")
    second = await _published(catalog, workspace_id, name="版本二")

    page_one = await catalog.list_versions(workspace_id, PageQuery(page=1, page_size=1))
    page_two = await catalog.list_versions(workspace_id, PageQuery(page=2, page_size=1))

    assert page_one.total == 2
    assert len(page_one.items) == 1
    assert len(page_two.items) == 1
    assert {page_one.items[0].ref.version_id, page_two.items[0].ref.version_id} == {
        first.ref.version_id,
        second.ref.version_id,
    }


# 复制草稿并只改可编辑字段；用于并发 update 的同内容请求。
def _revised(draft: StrategyDraft, *, name: str) -> StrategyDraft:
    payload = draft.model_dump(mode="python", by_alias=False)
    payload["name"] = name
    return StrategyDraft.model_validate(payload)


# 统计指定 request_id 的幂等记录数；并发成功后必须只有一条。
async def _request_count(factory: async_sessionmaker[AsyncSession], request_id: UUID) -> int:
    async with factory() as session:
        value = await session.scalar(
            select(func.count())
            .select_from(StrategyCatalogRequestRecord)
            .where(StrategyCatalogRequestRecord.request_id == request_id)
        )
    return value or 0


# 两个相同 publish 请求并发：第二个必须重放第一个结果，不能因已发布状态报冲突。
@pytest.mark.asyncio
async def test_concurrent_same_publish_request_replays_success(
    migrated_database: Database,
) -> None:
    catalog = SqlAlchemyStrategyCatalog(migrated_database.session_factory, clock=_clock)
    workspace_id = uuid4()
    draft = await catalog.create_draft(workspace_id, _draft(), request_id=uuid4())
    request_id = uuid4()

    async with migrated_database.session_factory() as blocker, blocker.begin():
        row = await blocker.execute(
            select(StrategyVersionRecord)
            .where(StrategyVersionRecord.id == draft.draft_id)
            .with_for_update()
        )
        assert row.scalar_one_or_none() is not None
        tasks = [
            asyncio.create_task(
                catalog.publish(
                    workspace_id,
                    draft.draft_id,
                    expected_version=0,
                    request_id=request_id,
                )
            )
            for _ in range(2)
        ]
        await asyncio.sleep(0.2)
        assert all(not task.done() for task in tasks)

    first, second = await asyncio.gather(*tasks)
    assert first.ref == second.ref
    assert first.state_version == second.state_version == 1
    assert await _request_count(migrated_database.session_factory, request_id) == 1
    async with migrated_database.session_factory() as session:
        rows = (
            await session.scalars(
                select(StrategyVersionRecord).where(
                    StrategyVersionRecord.strategy_id == draft.strategy_id
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].state == "published"


# 两个相同 update_draft 请求并发：只能递增一次并返回同一个草稿结果。
@pytest.mark.asyncio
async def test_concurrent_same_update_request_replays_success(
    migrated_database: Database,
) -> None:
    catalog = SqlAlchemyStrategyCatalog(migrated_database.session_factory, clock=_clock)
    workspace_id = uuid4()
    draft = await catalog.create_draft(workspace_id, _draft(), request_id=uuid4())
    revised = _revised(draft, name="并发更新")
    request_id = uuid4()

    async with migrated_database.session_factory() as blocker, blocker.begin():
        row = await blocker.execute(
            select(StrategyVersionRecord)
            .where(StrategyVersionRecord.id == draft.draft_id)
            .with_for_update()
        )
        assert row.scalar_one_or_none() is not None
        tasks = [
            asyncio.create_task(
                catalog.update_draft(
                    workspace_id,
                    draft.draft_id,
                    revised,
                    expected_version=0,
                    request_id=request_id,
                )
            )
            for _ in range(2)
        ]
        await asyncio.sleep(0.2)
        assert all(not task.done() for task in tasks)

    first, second = await asyncio.gather(*tasks)
    assert first == second
    assert first.state_version == 1
    assert await _request_count(migrated_database.session_factory, request_id) == 1
    async with migrated_database.session_factory() as session:
        stored = await session.get(StrategyVersionRecord, draft.draft_id)
        assert stored is not None
        assert stored.state_version == 1
        assert stored.document["name"] == "并发更新"


# 两个相同 archive 请求并发：只归档一次，第二个请求重放成功且不重复递增代次。
@pytest.mark.asyncio
async def test_concurrent_same_archive_request_replays_success(
    migrated_database: Database,
) -> None:
    catalog = SqlAlchemyStrategyCatalog(migrated_database.session_factory, clock=_clock)
    workspace_id = uuid4()
    draft = await catalog.create_draft(workspace_id, _draft(), request_id=uuid4())
    published = await catalog.publish(
        workspace_id,
        draft.draft_id,
        expected_version=0,
        request_id=uuid4(),
    )
    request_id = uuid4()

    async with migrated_database.session_factory() as blocker, blocker.begin():
        row = await blocker.execute(
            select(StrategyDefinitionRecord)
            .where(StrategyDefinitionRecord.id == published.strategy_id)
            .with_for_update()
        )
        assert row.scalar_one_or_none() is not None
        tasks = [
            asyncio.create_task(
                catalog.archive(
                    workspace_id,
                    published.strategy_id,
                    expected_version=published.state_version,
                    request_id=request_id,
                )
            )
            for _ in range(2)
        ]
        await asyncio.sleep(0.2)
        assert all(not task.done() for task in tasks)

    results = await asyncio.gather(*tasks)
    assert results == [None, None]
    assert await _request_count(migrated_database.session_factory, request_id) == 1
    async with migrated_database.session_factory() as session:
        definition = await session.get(StrategyDefinitionRecord, published.strategy_id)
        assert definition is not None
        assert definition.archived_at is not None
        assert definition.state_version == published.state_version + 1


# create_draft 也有同类并发缺口：相同请求必须只创建一次并返回同一草稿。
@pytest.mark.asyncio
async def test_concurrent_same_create_request_replays_success(
    migrated_database: Database,
) -> None:
    catalog = SqlAlchemyStrategyCatalog(migrated_database.session_factory, clock=_clock)
    workspace_id = uuid4()
    existing = await catalog.create_draft(workspace_id, _draft(), request_id=uuid4())
    new_draft = _draft(strategy_id=existing.strategy_id, name="并发草稿")
    request_id = uuid4()

    async with migrated_database.session_factory() as blocker, blocker.begin():
        row = await blocker.execute(
            select(StrategyDefinitionRecord)
            .where(StrategyDefinitionRecord.id == existing.strategy_id)
            .with_for_update()
        )
        assert row.scalar_one_or_none() is not None
        tasks = [
            asyncio.create_task(
                catalog.create_draft(workspace_id, new_draft, request_id=request_id)
            )
            for _ in range(2)
        ]
        await asyncio.sleep(0.2)
        assert all(not task.done() for task in tasks)

    first, second = await asyncio.gather(*tasks)
    assert first == second == new_draft
    assert await _request_count(migrated_database.session_factory, request_id) == 1
    async with migrated_database.session_factory() as session:
        rows = (
            await session.scalars(
                select(StrategyVersionRecord).where(StrategyVersionRecord.id == new_draft.draft_id)
            )
        ).all()
        assert len(rows) == 1


# 同一请求键用于不同操作或工作台仍是真实冲突，不能被并发重放路径吞掉。
@pytest.mark.asyncio
async def test_request_key_rejects_different_operation_and_workspace(
    migrated_database: Database,
) -> None:
    catalog = SqlAlchemyStrategyCatalog(migrated_database.session_factory, clock=_clock)
    workspace_id = uuid4()
    request_id = uuid4()
    draft = await catalog.create_draft(workspace_id, _draft(), request_id=request_id)

    with pytest.raises(StrategyConflictError):
        await catalog.publish(
            workspace_id,
            draft.draft_id,
            expected_version=0,
            request_id=request_id,
        )
    with pytest.raises(StrategyConflictError):
        await catalog.create_draft(uuid4(), _draft(), request_id=request_id)


# 相同 request_id 但内容不同，即使并发也只能有一个成功，另一个必须返回真实冲突。
@pytest.mark.asyncio
async def test_concurrent_same_request_different_content_is_conflict(
    migrated_database: Database,
) -> None:
    catalog = SqlAlchemyStrategyCatalog(migrated_database.session_factory, clock=_clock)
    workspace_id = uuid4()
    existing = await catalog.create_draft(workspace_id, _draft(), request_id=uuid4())
    request_id = uuid4()
    first_draft = _draft(strategy_id=existing.strategy_id, name="并发内容甲")
    second_draft = _draft(strategy_id=existing.strategy_id, name="并发内容乙")

    async with migrated_database.session_factory() as blocker, blocker.begin():
        row = await blocker.execute(
            select(StrategyDefinitionRecord)
            .where(StrategyDefinitionRecord.id == existing.strategy_id)
            .with_for_update()
        )
        assert row.scalar_one_or_none() is not None
        tasks = [
            asyncio.create_task(
                catalog.create_draft(workspace_id, first_draft, request_id=request_id)
            ),
            asyncio.create_task(
                catalog.create_draft(workspace_id, second_draft, request_id=request_id)
            ),
        ]
        await asyncio.sleep(0.2)
        assert all(not task.done() for task in tasks)

    results = await asyncio.gather(*tasks, return_exceptions=True)
    successes = [result for result in results if isinstance(result, StrategyDraft)]
    conflicts = [result for result in results if isinstance(result, StrategyConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert await _request_count(migrated_database.session_factory, request_id) == 1
