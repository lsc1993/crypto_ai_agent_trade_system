# 验证 C4 Agent 任务的 PostgreSQL 实现：请求幂等、不可变修订、队列容量、事件序与 fencing 字段。
# 测试只写合成请求和 UUID；不包含真实资金、账户、模型调用或交易请求。
# SQL 用例依赖显式专用测试库，并只操作本用例随机 schema，不接触业务库。
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent_runs.contracts import (
    AgentRunError,
    RunInput,
    RunStatus,
    canonical_run_input_json,
    legacy_run_input_sha256,
    run_input_sha256,
)
from app.agent_runs.events import RunEventType
from app.infrastructure.persistence import agent_run_repository
from app.infrastructure.persistence.agent_run_repository import (
    SqlAlchemyAgentRunRepository,
)
from app.infrastructure.persistence.base import Base
from app.infrastructure.persistence.models.agent_runs import (
    AgentArtifactRecord,
    AgentEvidenceEpochRecord,
    AgentRunEventRecord,
    AgentRunQueueRecord,
    AgentRunRecord,
    AgentRunRequestRecord,
    AgentRunRevisionRecord,
    AgentThreadRecord,
)
from app.market.contracts import MarketTimeframe
from app.shared.agent_types import ProductKey, VersionRef
from app.trade_planning.inputs import PlanningRefs

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)
LATER = datetime(2026, 11, 10, 13, tzinfo=UTC)
WORKSPACE_ID = uuid4()


# 测试夹具协议只暴露仓储所需的异步会话工厂，不依赖具体 MigratedDatabase 导入路径。
class Database(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


# 使用合成公开币种、策略版本和规划引用构造可持久化任务输入。
def _input(
    *,
    request_id: UUID | None = None,
    goal: str = "分析 BTCUSDT 当前结构与条件计划",
    thread_id: UUID | None = None,
    parent_run_id: UUID | None = None,
    parameters: dict[str, JsonValue] | None = None,
) -> RunInput:
    return RunInput(
        request_id=request_id or uuid4(),
        thread_id=thread_id,
        parent_run_id=parent_run_id,
        product=ProductKey(
            venue="binance_usdm",
            symbol="BTCUSDT",
            settlement="USDT",
            kind="linear_perpetual",
        ),
        timeframes=(MarketTimeframe.H1, MarketTimeframe.H4),
        goal=goal,
        strategy=VersionRef(version_id=uuid4(), sha256="a" * 64),
        parameters=parameters or {"lookback": 20},
        planning=PlanningRefs(
            profile=VersionRef(version_id=uuid4(), sha256="b" * 64),
            policy=VersionRef(version_id=uuid4(), sha256="c" * 64),
            venue_rules=VersionRef(version_id=uuid4(), sha256="d" * 64),
            costs=VersionRef(version_id=uuid4(), sha256="e" * 64),
            pool_id=uuid4(),
            pool_generation=1,
        ),
    )


# 每个用例显式使用固定时钟，便于比较事件顺序和快照时间。
def _repository(
    session_factory: async_sessionmaker[AsyncSession],
) -> SqlAlchemyAgentRunRepository:
    return SqlAlchemyAgentRunRepository(session_factory, clock=lambda: NOW)


# 统计表行数，用于证明失败事务没有留下半个任务或孤立事件。
async def _count(session_factory: async_sessionmaker[AsyncSession], model: type[Base]) -> int:
    async with session_factory() as session:
        value = await session.scalar(select(func.count()).select_from(model))
    return int(value or 0)


# 直接推进测试行状态；仅用于构造终态父任务和验证数据库约束。
async def _update_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    **values: object,
) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            update(AgentRunRecord).where(AgentRunRecord.id == run_id).values(**values)
        )


# 构造 T04 首轮格式的已提交行：修订/请求使用旧 Python JSON 指纹，不新增事件。
# 仅使用稳定数值（0.5）验证兼容读取，不伪造 JSONB 已规范化的历史表示。
async def _seed_legacy_hashed_run(
    session_factory: async_sessionmaker[AsyncSession],
    data: RunInput,
    legacy_sha: str,
) -> UUID:
    run_id = uuid4()
    thread_id = uuid4()
    async with session_factory() as session, session.begin():
        session.add(
            AgentThreadRecord(
                id=thread_id,
                workspace_id=WORKSPACE_ID,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            AgentRunRecord(
                id=run_id,
                workspace_id=WORKSPACE_ID,
                thread_id=thread_id,
                parent_run_id=None,
                revision=1,
                status=RunStatus.QUEUED.value,
                state_version=0,
                received_message_seq=0,
                applied_message_seq=0,
                current_interaction_id=None,
                result_refs=[],
                result_quality=None,
                error_code=None,
                owner=None,
                lease_epoch=0,
                lease_expires_at=None,
                created_at=NOW,
                updated_at=NOW,
                started_at=None,
                finished_at=None,
            )
        )
        await session.flush()
        session.add(
            AgentRunRevisionRecord(
                run_id=run_id,
                revision=1,
                input=cast(
                    dict[str, object],
                    data.model_dump(mode="json", by_alias=False),
                ),
                sha256=legacy_sha,
                created_at=NOW,
            )
        )
        session.add(
            AgentRunRequestRecord(
                workspace_id=WORKSPACE_ID,
                request_id=data.request_id,
                run_id=run_id,
                request_sha256=legacy_sha,
                created_at=NOW,
            )
        )
    return run_id


@pytest.mark.asyncio
async def test_enqueue_persists_run_immutable_revision_request_and_ordered_events(
    migrated_database: Database,
) -> None:
    repository = _repository(migrated_database.session_factory)
    data = _input()

    started = await repository.enqueue(WORKSPACE_ID, data)

    assert started.status is RunStatus.QUEUED
    assert started.revision == 1
    assert started.state_version == 0
    assert started.thread_id is not None
    assert started.input == data
    assert started.received_message_seq == 0
    assert started.applied_message_seq == 0

    # 新仓储实例模拟进程重启后重读；修订输入与请求映射必须仍可核对。
    reloaded = await _repository(migrated_database.session_factory).get(
        WORKSPACE_ID, started.run_id
    )
    assert reloaded == started

    page = await repository.list_events(WORKSPACE_ID, started.run_id)
    assert [item.sequence for item in page.items] == [1, 2]
    assert [item.event_type for item in page.items] == [
        RunEventType.RUN_QUEUED,
        RunEventType.REVISION_CREATED,
    ]
    serialized = json.dumps([item.model_dump(mode="json") for item in page.items])
    assert "10000.00" not in serialized
    assert '"quantity"' not in serialized
    assert '"margin"' not in serialized

    # 迁移保留 evidence/artifacts 前向表，T04 不应向其中写入占位成功产物。
    assert await _count(migrated_database.session_factory, AgentEvidenceEpochRecord) == 0
    assert await _count(migrated_database.session_factory, AgentArtifactRecord) == 0
    async with migrated_database.session_factory() as session:
        assert await session.get(AgentRunQueueRecord, 1) is not None


@pytest.mark.asyncio
async def test_same_request_replays_and_conflicts_without_symbol_merging(
    migrated_database: Database,
) -> None:
    repository = _repository(migrated_database.session_factory)
    data = _input()

    first = await repository.enqueue(WORKSPACE_ID, data)
    replay = await repository.enqueue(WORKSPACE_ID, data)
    assert replay.run_id == first.run_id
    assert replay == first
    assert len((await repository.list_events(WORKSPACE_ID, first.run_id)).items) == 2

    # 同一请求键但内容变化必须稳定冲突，不能静默复用旧任务。
    with pytest.raises(AgentRunError) as conflict:
        await repository.enqueue(WORKSPACE_ID, data.model_copy(update={"goal": "另一个目标"}))
    assert conflict.value.code == "request_conflict"

    # 不同请求键即使币种/参数完全一致也建立新任务，不按币种合并。
    separate = await repository.enqueue(
        WORKSPACE_ID,
        data.model_copy(update={"request_id": uuid4()}),
    )
    assert separate.run_id != first.run_id
    assert separate.thread_id != first.thread_id


@pytest.mark.asyncio
async def test_concurrent_same_request_creates_one_task_and_event_sequence(
    migrated_database: Database,
) -> None:
    # 同一 request_id/内容被多个页面并发提交时，只剩一个任务和一组 1..2 事件。
    repository = _repository(migrated_database.session_factory)
    data = _input()

    results = await asyncio.gather(
        repository.enqueue(WORKSPACE_ID, data),
        repository.enqueue(WORKSPACE_ID, data),
        repository.enqueue(WORKSPACE_ID, data),
    )

    assert len({item.run_id for item in results}) == 1
    assert await _count(migrated_database.session_factory, AgentRunRecord) == 1
    events = await repository.list_events(WORKSPACE_ID, results[0].run_id)
    assert [item.sequence for item in events.items] == [1, 2]


@pytest.mark.asyncio
async def test_jsonb_numeric_normalization_keeps_fingerprint_stable_for_reload_and_replay(
    migrated_database: Database,
) -> None:
    # PostgreSQL JSONB 会把 1e20 输出为整数、把 -0.0 输出为 0.0；指纹必须基于持久化后的
    # 规范表示，而不是首次 Python JSON 文本，否则合法请求会在入队/重读/重放时被误判篡改。
    parameters: dict[str, JsonValue] = {
        "big": 1e20,
        "negative_zero": -0.0,
        "fraction": 0.5,
        "nested": {
            "big": 1e20,
            "negative_zero": -0.0,
            "fraction": 0.5,
        },
    }
    data = _input(parameters=parameters)
    repository = _repository(migrated_database.session_factory)

    first = await repository.enqueue(WORKSPACE_ID, data)
    reloaded = await _repository(migrated_database.session_factory).get(WORKSPACE_ID, first.run_id)
    assert reloaded is not None
    assert reloaded.run_id == first.run_id

    # 同键同参重放不得新增任务或事件。
    replay = await repository.enqueue(WORKSPACE_ID, data)
    assert replay.run_id == first.run_id
    assert await _count(migrated_database.session_factory, AgentRunRecord) == 1
    events = await repository.list_events(WORKSPACE_ID, first.run_id)
    assert [item.sequence for item in events.items] == [1, 2]

    # 同键异参仍必须冲突，不能因数值规范化而错误放行。
    changed = data.model_copy(update={"parameters": {**parameters, "fraction": 0.6}})
    with pytest.raises(AgentRunError) as conflict:
        await repository.enqueue(WORKSPACE_ID, changed)
    assert conflict.value.code == "request_conflict"


@pytest.mark.asyncio
async def test_legacy_stable_hash_rows_stay_readable_without_rewriting_history(
    migrated_database: Database,
) -> None:
    # 首轮已提交行的 Python JSON 指纹仍应可读；只接受精确旧哈希，不重写修订/请求映射。
    data = _input(parameters={"fraction": 0.5, "nested": {"fraction": 0.5}})
    legacy_sha = legacy_run_input_sha256(WORKSPACE_ID, data)
    run_id = await _seed_legacy_hashed_run(
        migrated_database.session_factory,
        data,
        legacy_sha,
    )
    repository = _repository(migrated_database.session_factory)

    loaded = await repository.get(WORKSPACE_ID, run_id)
    assert loaded is not None
    assert loaded.run_id == run_id

    replay = await repository.enqueue(WORKSPACE_ID, data)
    assert replay.run_id == run_id
    assert await _count(migrated_database.session_factory, AgentRunRecord) == 1
    assert await _count(migrated_database.session_factory, AgentRunRevisionRecord) == 1
    assert await _count(migrated_database.session_factory, AgentRunRequestRecord) == 1


@pytest.mark.asyncio
async def test_legacy_normalized_numeric_rows_fail_closed_instead_of_replaying(
    migrated_database: Database,
) -> None:
    # 旧行写入前 Python 文本含 1e20，但 JSONB 只保留规范整数；原始表示不可恢复。
    # 兼容逻辑不得用当前重读值重算旧哈希后放行，否则等于取消完整性校验。
    data = _input(parameters={"big": 1e20})
    legacy_sha = legacy_run_input_sha256(WORKSPACE_ID, data)
    run_id = await _seed_legacy_hashed_run(
        migrated_database.session_factory,
        data,
        legacy_sha,
    )

    with pytest.raises(AgentRunError) as rejected:
        await _repository(migrated_database.session_factory).get(WORKSPACE_ID, run_id)
    assert rejected.value.code == "integrity_violation"


@pytest.mark.asyncio
async def test_default_resolution_replays_before_thread_creation(
    migrated_database: Database,
) -> None:
    repository = _repository(migrated_database.session_factory)
    request_id = uuid4()
    # 显式移除默认字段，模拟客户端第一次只提交必需字段。
    implicit_payload = _input(request_id=request_id).model_dump(mode="json", by_alias=False)
    implicit_payload.pop("analysis_mode", None)
    implicit_payload.pop("budget_profile", None)
    implicit = RunInput.model_validate(implicit_payload)

    first = await repository.enqueue(WORKSPACE_ID, implicit)
    explicit_payload = implicit.model_dump(mode="json", by_alias=False)
    explicit_payload["analysis_mode"] = "current"
    explicit_payload["budget_profile"] = "standard"
    explicit = RunInput.model_validate(explicit_payload)

    assert run_input_sha256(WORKSPACE_ID, canonical_run_input_json(implicit)) == run_input_sha256(
        WORKSPACE_ID, canonical_run_input_json(explicit)
    )
    replay = await repository.enqueue(WORKSPACE_ID, explicit)
    assert replay.run_id == first.run_id
    assert replay.thread_id == first.thread_id


@pytest.mark.asyncio
async def test_thread_continuity_parent_run_and_cross_workspace_isolation(
    migrated_database: Database,
) -> None:
    repository = _repository(migrated_database.session_factory)
    first = await repository.enqueue(WORKSPACE_ID, _input())

    # 同一会话内继续研究复用线程，不创建第二个会话。
    second = await repository.enqueue(WORKSPACE_ID, _input(thread_id=first.thread_id))
    assert second.thread_id == first.thread_id

    # 终态父任务可关联新的同会话任务；未终态父任务不能被并行子任务借用。
    await _update_run(
        migrated_database.session_factory,
        first.run_id,
        status="completed",
        finished_at=LATER,
        state_version=1,
    )
    child = await repository.enqueue(
        WORKSPACE_ID,
        _input(parent_run_id=first.run_id),
    )
    assert child.parent_run_id == first.run_id
    assert child.thread_id == first.thread_id

    with pytest.raises(AgentRunError) as not_terminal:
        await repository.enqueue(WORKSPACE_ID, _input(parent_run_id=second.run_id))
    assert not_terminal.value.code == "parent_not_terminal"

    # 跨工作台读取/继续默认按不存在处理，UUID 本身不授予访问权。
    other_workspace = uuid4()
    assert await repository.get(other_workspace, child.run_id) is None
    with pytest.raises(AgentRunError) as hidden:
        await repository.list_events(other_workspace, child.run_id)
    assert hidden.value.code == "run_not_found"
    with pytest.raises(AgentRunError) as foreign_thread:
        await repository.enqueue(other_workspace, _input(thread_id=first.thread_id))
    assert foreign_thread.value.code == "thread_not_found"

    # 相同 request_id 在不同工作台是不同幂等域，不泄露既有任务。
    cross_workspace = await repository.enqueue(
        other_workspace,
        _input(request_id=child.input.request_id),
    )
    assert cross_workspace.run_id != child.run_id


@pytest.mark.asyncio
async def test_concurrent_runnable_capacity_rejects_only_the_twenty_first(
    migrated_database: Database,
) -> None:
    repository = _repository(migrated_database.session_factory)

    results = await asyncio.gather(
        *[
            repository.enqueue(WORKSPACE_ID, _input(goal=f"合成目标 {index}"))
            for index in range(21)
        ],
        return_exceptions=True,
    )
    successes = [item for item in results if not isinstance(item, BaseException)]
    errors = [item for item in results if isinstance(item, AgentRunError)]
    assert len(successes) == 20
    assert len(errors) == 1
    assert errors[0].code == "queue_full"
    assert await _count(migrated_database.session_factory, AgentRunRecord) == 20


@pytest.mark.asyncio
async def test_waiting_tasks_do_not_consume_global_runnable_capacity(
    migrated_database: Database,
) -> None:
    workspace_id = uuid4()
    session_factory = migrated_database.session_factory
    async with session_factory() as session, session.begin():
        thread = AgentThreadRecord(
            id=uuid4(),
            workspace_id=workspace_id,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(thread)
        await session.flush()
        for _ in range(100):
            session.add(
                AgentRunRecord(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    thread_id=thread.id,
                    parent_run_id=None,
                    revision=1,
                    status="waiting_input",
                    state_version=1,
                    received_message_seq=0,
                    applied_message_seq=0,
                    current_interaction_id=uuid4(),
                    result_refs=[],
                    result_quality=None,
                    error_code=None,
                    owner=None,
                    lease_epoch=1,
                    lease_expires_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                    started_at=NOW,
                    finished_at=None,
                )
            )

    # 等待态不计入全局 20 个可运行槽；仍然可以排入 20 个新任务。
    repository = _repository(session_factory)
    for index in range(20):
        await repository.enqueue(workspace_id, _input(goal=f"等待后的新目标 {index}"))
    assert await _count(session_factory, AgentRunRecord) == 120


@pytest.mark.asyncio
async def test_event_pagination_and_cross_run_sequence_are_ordered(
    migrated_database: Database,
) -> None:
    repository = _repository(migrated_database.session_factory)
    first = await repository.enqueue(WORKSPACE_ID, _input())
    second = await repository.enqueue(WORKSPACE_ID, _input())

    page = await repository.list_events(WORKSPACE_ID, first.run_id, after_seq=0, limit=1)
    assert [item.sequence for item in page.items] == [1]
    assert page.next_after == 1

    page = await repository.list_events(WORKSPACE_ID, first.run_id, after_seq=1, limit=1)
    assert [item.sequence for item in page.items] == [2]
    assert page.next_after is None

    page = await repository.list_events(WORKSPACE_ID, first.run_id, after_seq=2)
    assert page.items == ()
    assert page.next_after is None

    # 每个任务独立分配序号，不因共享工作台而串号。
    assert [
        item.sequence for item in (await repository.list_events(WORKSPACE_ID, second.run_id)).items
    ] == [1, 2]

    for invalid in (0, 101):
        with pytest.raises(AgentRunError) as captured:
            await repository.list_events(WORKSPACE_ID, first.run_id, limit=invalid)
        assert captured.value.code == "invalid_event_page"


@pytest.mark.asyncio
async def test_failed_transaction_leaves_no_partial_task_or_event(
    migrated_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(migrated_database.session_factory)

    def fail_events(*args: object, **kwargs: object) -> object:
        raise RuntimeError("synthetic event failure")

    monkeypatch.setattr(agent_run_repository, "_event_rows", fail_events)
    with pytest.raises(RuntimeError, match="synthetic event failure"):
        await repository.enqueue(WORKSPACE_ID, _input())

    session_factory = migrated_database.session_factory
    assert await _count(session_factory, AgentThreadRecord) == 0
    assert await _count(session_factory, AgentRunRecord) == 0
    assert await _count(session_factory, AgentRunRevisionRecord) == 0
    assert await _count(session_factory, AgentRunRequestRecord) == 0
    assert await _count(session_factory, AgentRunEventRecord) == 0


@pytest.mark.asyncio
async def test_database_constraints_reject_lease_watermark_and_terminal_violations(
    migrated_database: Database,
) -> None:
    repository = _repository(migrated_database.session_factory)
    snapshot = await repository.enqueue(WORKSPACE_ID, _input())
    session_factory = migrated_database.session_factory

    with pytest.raises(DBAPIError):
        await _update_run(session_factory, snapshot.run_id, owner=uuid4())
    with pytest.raises(DBAPIError):
        await _update_run(session_factory, snapshot.run_id, status="running")
    with pytest.raises(DBAPIError):
        await _update_run(session_factory, snapshot.run_id, applied_message_seq=1)
    with pytest.raises(DBAPIError):
        await _update_run(session_factory, snapshot.run_id, status="completed")

    # 终态只能从非终态进入一次，之后任何修改都拒绝，避免旧批准/旧任务被重开。
    await _update_run(
        session_factory,
        snapshot.run_id,
        status="completed",
        finished_at=LATER,
        state_version=1,
    )
    with pytest.raises(DBAPIError, match="terminal"):
        await _update_run(
            session_factory,
            snapshot.run_id,
            status="queued",
            finished_at=None,
            state_version=2,
        )

    # 修订、请求映射和事件属于历史事实；UPDATE/DELETE 都必须由数据库拒绝。
    async with session_factory() as session, session.begin():
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(
                update(AgentRunRevisionRecord)
                .where(AgentRunRevisionRecord.run_id == snapshot.run_id)
                .values(sha256="f" * 64)
            )
    async with session_factory() as session, session.begin():
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(delete(AgentRunEventRecord))
    async with session_factory() as session, session.begin():
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(delete(AgentRunRequestRecord))
    async with session_factory() as session, session.begin():
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(delete(AgentRunRecord))

    # 允许删除的环境不存在：回退应通过关闭入口/迁移流程，而不是删除历史行。
    async with session_factory() as session:
        remaining = await session.scalar(select(func.count()).select_from(AgentRunRecord))
        assert remaining == 1
        await session.execute(text("SELECT 1"))


@pytest.mark.asyncio
async def test_committed_request_replay_reads_same_revision_after_new_repository(
    migrated_database: Database,
) -> None:
    data = _input()
    first = await _repository(migrated_database.session_factory).enqueue(WORKSPACE_ID, data)
    # 独立仓储/会话模拟进程重启；请求键映射与内容指纹必须足以恢复原任务。
    replay = await _repository(migrated_database.session_factory).enqueue(WORKSPACE_ID, data)
    assert replay.run_id == first.run_id
    assert replay.revision == 1
    assert replay.input == data
    assert replay.state_version == 0
