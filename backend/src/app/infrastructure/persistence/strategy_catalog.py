# 用 PostgreSQL 事务实现版本化策略目录：草稿、发布、停用、分页和请求幂等。
# 发布事务先锁定草稿行与策略定义，再校验组合组成，最后在同一事务写状态和请求结果。
# 已发布正文不可改；数据库触发器提供第二道保护。该仓储不访问账户、行情或交易执行。
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.research_strategies import (
    StrategyCatalogRequestRecord,
    StrategyDefinitionRecord,
    StrategyVersionRecord,
)
from app.research.strategies.contracts import (
    StrategyCatalogError,
    StrategyConflictError,
    StrategyDraft,
    StrategyIntegrityError,
    StrategyNotAvailableError,
    StrategyParameterError,
    StrategyVersion,
    strategy_draft_sha256,
    validate_parameters,
)
from app.shared.agent_types import (
    JsonObject,
    PageQuery,
    VersionPage,
    VersionRef,
    require_utc,
    sha256_json,
)

_ACTION_CREATE = "create_draft"
_ACTION_UPDATE = "update_draft"
_ACTION_PUBLISH = "publish"
_ACTION_ARCHIVE = "archive"


# 请求重放快照只保留已提交结果，不暴露 ORM 会话或异常。
@dataclass(frozen=True)
class _RequestSnapshot:
    result: dict[str, object] | None


# SQL 策略目录实现；clock 可注入以便测试固定发布时间，生产默认使用服务端 UTC。
class SqlAlchemyStrategyCatalog:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    # 服务端时间必须带时区 UTC；禁止用客户端时间证明发布/归档时序。
    def _now(self) -> datetime:
        return require_utc(self._clock())

    # 读取当前可执行发布版本；定义已归档时新执行不可用，但历史列表仍可读取。
    async def get_published(self, workspace_id: UUID, ref: VersionRef) -> StrategyVersion:
        try:
            async with self._factory() as session:
                row = await session.get(StrategyVersionRecord, ref.version_id)
                if row is None or row.workspace_id != workspace_id or row.state != "published":
                    raise StrategyNotAvailableError("策略发布版本不存在或不属于当前工作台")
                definition = await session.get(StrategyDefinitionRecord, row.strategy_id)
                if (
                    definition is None
                    or definition.workspace_id != workspace_id
                    or definition.archived_at is not None
                ):
                    raise StrategyNotAvailableError("策略已停用或不属于当前工作台")
                version = _version_from_row(row, definition)
                if version.ref != ref:
                    raise StrategyIntegrityError("策略版本指纹与请求引用不一致")
                return version
        except SQLAlchemyError:
            raise StrategyCatalogError(
                "策略目录读取不可用", code="strategy_catalog_unavailable"
            ) from None

    # 创建草稿：同 request_id 重放返回原草稿，内容不同或标识冲突拒绝。
    async def create_draft(
        self,
        workspace_id: UUID,
        draft: StrategyDraft,
        *,
        request_id: UUID,
    ) -> StrategyDraft:
        if draft.state_version != 0:
            raise StrategyConflictError("新草稿版本必须从零开始")
        request_sha = _request_sha(
            _ACTION_CREATE,
            workspace_id,
            {"draft": _draft_payload(draft)},
        )
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                replay = await _load_request(
                    session, request_id, workspace_id, _ACTION_CREATE, request_sha
                )
                if replay is not None:
                    return _draft_result(replay)
                if await session.get(StrategyVersionRecord, draft.draft_id) is not None:
                    raise StrategyConflictError("草稿标识已存在")
                definition = await session.get(
                    StrategyDefinitionRecord,
                    draft.strategy_id,
                    with_for_update=True,
                )
                if definition is None:
                    definition = StrategyDefinitionRecord(
                        id=draft.strategy_id,
                        workspace_id=workspace_id,
                        name=draft.name,
                        state_version=0,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(definition)
                else:
                    if definition.workspace_id != workspace_id:
                        raise StrategyNotAvailableError("策略不属于当前工作台")
                    if definition.archived_at is not None:
                        raise StrategyNotAvailableError("策略已停用，不能创建新草稿")
                    definition.name = draft.name
                    definition.updated_at = now
                payload = _draft_payload(draft)
                session.add(
                    StrategyVersionRecord(
                        id=draft.draft_id,
                        strategy_id=draft.strategy_id,
                        workspace_id=workspace_id,
                        state="draft",
                        state_version=draft.state_version,
                        document=cast(dict[str, object], payload),
                        sha256=strategy_draft_sha256(draft),
                        created_at=now,
                        updated_at=now,
                    )
                )
                _store_request(
                    session,
                    request_id=request_id,
                    workspace_id=workspace_id,
                    action=_ACTION_CREATE,
                    request_sha256=request_sha,
                    result=payload,
                    now=now,
                )
            return draft
        except IntegrityError:
            replayed = await self._replay_request(
                request_id, workspace_id, _ACTION_CREATE, request_sha
            )
            if replayed is not None:
                return _draft_result(replayed)
            raise StrategyConflictError("策略草稿写入冲突") from None
        except SQLAlchemyError:
            raise StrategyCatalogError(
                "策略目录写入不可用", code="strategy_catalog_unavailable"
            ) from None

    # 更新草稿：只允许同一 strategy_id 的草稿在 expected_version 匹配时递增版本。
    async def update_draft(
        self,
        workspace_id: UUID,
        draft_id: UUID,
        draft: StrategyDraft,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> StrategyDraft:
        request_sha = _request_sha(
            _ACTION_UPDATE,
            workspace_id,
            {
                "draftId": str(draft_id),
                "expectedVersion": expected_version,
                "draft": _draft_payload(draft),
            },
        )
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                replay = await _load_request(
                    session, request_id, workspace_id, _ACTION_UPDATE, request_sha
                )
                if replay is not None:
                    return _draft_result(replay)
                row = await _lock_version(session, workspace_id, draft_id)
                existing = _draft_from_row(row)
                if existing.state_version != expected_version:
                    raise StrategyConflictError("草稿版本已变化，请重新读取")
                if draft.draft_id != draft_id or draft.strategy_id != existing.strategy_id:
                    raise StrategyConflictError("草稿标识或策略身份不一致")
                definition = await _lock_definition(session, workspace_id, row.strategy_id)
                if definition.archived_at is not None:
                    raise StrategyNotAvailableError("策略已停用，不能修改草稿")
                updated = StrategyDraft.model_validate(
                    {
                        **_draft_payload(draft),
                        "draft_id": str(draft_id),
                        "strategy_id": str(existing.strategy_id),
                        "state_version": expected_version + 1,
                    }
                )
                payload = _draft_payload(updated)
                row.document = cast(dict[str, object], payload)
                row.sha256 = strategy_draft_sha256(updated)
                row.state_version = updated.state_version
                row.updated_at = now
                definition.name = updated.name
                definition.updated_at = now
                _store_request(
                    session,
                    request_id=request_id,
                    workspace_id=workspace_id,
                    action=_ACTION_UPDATE,
                    request_sha256=request_sha,
                    result=payload,
                    now=now,
                )
            return updated
        except IntegrityError:
            replayed = await self._replay_request(
                request_id, workspace_id, _ACTION_UPDATE, request_sha
            )
            if replayed is not None:
                return _draft_result(replayed)
            raise StrategyConflictError("策略草稿更新冲突") from None
        except SQLAlchemyError:
            raise StrategyCatalogError(
                "策略目录写入不可用", code="strategy_catalog_unavailable"
            ) from None

    # 发布草稿：冻结正文哈希、校验组合组成，并在同一事务更新目录代次和请求结果。
    async def publish(
        self,
        workspace_id: UUID,
        draft_id: UUID,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> StrategyVersion:
        request_sha = _request_sha(
            _ACTION_PUBLISH,
            workspace_id,
            {"draftId": str(draft_id), "expectedVersion": expected_version},
        )
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                replay = await _load_request(
                    session, request_id, workspace_id, _ACTION_PUBLISH, request_sha
                )
                if replay is not None:
                    return _version_result(replay)
                row = await _lock_version(session, workspace_id, draft_id)
                draft = _draft_from_row(row)
                if draft.state_version != expected_version:
                    raise StrategyConflictError("草稿版本已变化，请重新读取")
                definition = await _lock_definition(session, workspace_id, row.strategy_id)
                if definition.archived_at is not None:
                    raise StrategyNotAvailableError("策略已停用，不能发布新版本")
                await _verify_components(
                    session,
                    workspace_id=workspace_id,
                    draft=draft,
                )
                published = StrategyVersion.from_draft(
                    draft,
                    published_at=now,
                    state_version=definition.state_version + 1,
                )
                payload = _version_payload(published)
                row.state = "published"
                row.sha256 = published.ref.sha256
                row.state_version = published.state_version
                row.document = cast(dict[str, object], payload)
                row.published_at = now
                row.updated_at = now
                definition.state_version = published.state_version
                definition.name = published.name
                definition.updated_at = now
                _store_request(
                    session,
                    request_id=request_id,
                    workspace_id=workspace_id,
                    action=_ACTION_PUBLISH,
                    request_sha256=request_sha,
                    result=payload,
                    now=now,
                )
            return published
        except IntegrityError:
            replayed = await self._replay_request(
                request_id, workspace_id, _ACTION_PUBLISH, request_sha
            )
            if replayed is not None:
                return _version_result(replayed)
            raise StrategyConflictError("策略发布冲突") from None
        except SQLAlchemyError:
            raise StrategyCatalogError(
                "策略目录写入不可用", code="strategy_catalog_unavailable"
            ) from None

    # 归档策略定义：阻止新草稿/发布/执行，历史发布版本和旧计划引用继续可读。
    async def archive(
        self,
        workspace_id: UUID,
        strategy_id: UUID,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> None:
        request_sha = _request_sha(
            _ACTION_ARCHIVE,
            workspace_id,
            {"strategyId": str(strategy_id), "expectedVersion": expected_version},
        )
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                replay = await _load_request(
                    session, request_id, workspace_id, _ACTION_ARCHIVE, request_sha
                )
                if replay is not None:
                    return None
                definition = await session.get(
                    StrategyDefinitionRecord,
                    strategy_id,
                    with_for_update=True,
                )
                if definition is None or definition.workspace_id != workspace_id:
                    raise StrategyNotAvailableError("策略不存在或不属于当前工作台")
                if definition.state_version != expected_version:
                    raise StrategyConflictError("策略目录版本已变化，请重新读取")
                if definition.archived_at is None:
                    definition.archived_at = now
                    definition.state_version += 1
                    definition.updated_at = now
                _store_request(
                    session,
                    request_id=request_id,
                    workspace_id=workspace_id,
                    action=_ACTION_ARCHIVE,
                    request_sha256=request_sha,
                    result=None,
                    now=now,
                )
            return None
        except IntegrityError:
            replayed = await self._replay_request(
                request_id, workspace_id, _ACTION_ARCHIVE, request_sha
            )
            if replayed is not None:
                return None
            raise StrategyConflictError("策略归档冲突") from None
        except SQLAlchemyError:
            raise StrategyCatalogError(
                "策略目录写入不可用", code="strategy_catalog_unavailable"
            ) from None

    # 分页读取已发布历史（包括已归档定义）；不返回草稿，不删除历史引用。
    async def list_versions(
        self, workspace_id: UUID, query: PageQuery
    ) -> VersionPage[StrategyVersion]:
        if query.page < 1 or not 1 <= query.page_size <= 100:
            raise ValueError("策略目录分页无效")
        statement = (
            select(StrategyVersionRecord, StrategyDefinitionRecord)
            .join(
                StrategyDefinitionRecord,
                StrategyDefinitionRecord.id == StrategyVersionRecord.strategy_id,
            )
            .where(
                StrategyVersionRecord.workspace_id == workspace_id,
                StrategyVersionRecord.state == "published",
            )
        )
        try:
            async with self._factory() as session:
                rows = (
                    await session.execute(
                        statement.order_by(
                            StrategyVersionRecord.published_at.desc(),
                            StrategyVersionRecord.id.desc(),
                        )
                        .offset((query.page - 1) * query.page_size)
                        .limit(query.page_size)
                    )
                ).all()
                total = await session.scalar(
                    select(func.count())
                    .select_from(StrategyVersionRecord)
                    .where(
                        StrategyVersionRecord.workspace_id == workspace_id,
                        StrategyVersionRecord.state == "published",
                    )
                )
        except SQLAlchemyError:
            raise StrategyCatalogError(
                "策略目录读取不可用", code="strategy_catalog_unavailable"
            ) from None
        items = tuple(
            _version_from_row(version_row, definition_row) for version_row, definition_row in rows
        )
        return VersionPage(
            items=items,
            page=query.page,
            page_size=query.page_size,
            total=total or 0,
        )

    # 并发相同请求在唯一约束上失败后，重读已提交结果；内容不同按冲突处理。
    async def _replay_request(
        self,
        request_id: UUID,
        workspace_id: UUID,
        action: str,
        request_sha: str,
    ) -> _RequestSnapshot | None:
        try:
            async with self._factory() as session:
                return await _load_request(session, request_id, workspace_id, action, request_sha)
        except SQLAlchemyError:
            return None


# 读取并校验请求幂等记录；同一 request_id 不能对应不同工作台、操作或内容。
async def _load_request(
    session: AsyncSession,
    request_id: UUID,
    workspace_id: UUID,
    action: str,
    request_sha: str,
) -> _RequestSnapshot | None:
    record = await session.get(StrategyCatalogRequestRecord, request_id)
    if record is None:
        return None
    if (
        record.workspace_id != workspace_id
        or record.action != action
        or record.request_sha256 != request_sha
    ):
        raise StrategyConflictError("请求键已用于不同操作或内容")
    return _RequestSnapshot(result=record.result)


# 写入请求结果；result 为 None 表示成功但无返回体（归档）。
def _store_request(
    session: AsyncSession,
    *,
    request_id: UUID,
    workspace_id: UUID,
    action: str,
    request_sha256: str,
    result: JsonObject | None,
    now: datetime,
) -> None:
    session.add(
        StrategyCatalogRequestRecord(
            request_id=request_id,
            workspace_id=workspace_id,
            action=action,
            request_sha256=request_sha256,
            result=None if result is None else cast(dict[str, object], result),
            created_at=now,
        )
    )


# 规范化请求指纹覆盖操作、工作台和业务参数，不把 request_id 自身计入内容。
def _request_sha(action: str, workspace_id: UUID, payload: JsonObject) -> str:
    body: JsonObject = {
        "action": action,
        "workspaceId": str(workspace_id),
        "payload": payload,
    }
    return sha256_json(cast(JsonValue, body))


# 草稿持久化载荷；draft_id/state_version 参与行一致性校验，但不进入正文哈希。
def _draft_payload(draft: StrategyDraft) -> JsonObject:
    return cast(JsonObject, draft.model_dump(mode="json", by_alias=False))


# 发布版本持久化载荷；归档状态另由定义行派生，避免改写不可变正文。
def _version_payload(version: StrategyVersion) -> JsonObject:
    return cast(JsonObject, version.model_dump(mode="json", by_alias=False))


# 解析请求重放结果；损坏的历史结果不能被当作成功响应。
def _draft_result(snapshot: _RequestSnapshot) -> StrategyDraft:
    if snapshot.result is None:
        raise StrategyIntegrityError("草稿请求缺少已保存结果")
    return _parse_draft(snapshot.result)


def _version_result(snapshot: _RequestSnapshot) -> StrategyVersion:
    if snapshot.result is None:
        raise StrategyIntegrityError("发布请求缺少已保存结果")
    return _parse_version(snapshot.result, archived=False, archived_at=None)


# 将唯一行转为草稿并核对行上冗余字段，防止正文与状态列被分别改写。
def _draft_from_row(row: StrategyVersionRecord) -> StrategyDraft:
    if row.state != "draft":
        raise StrategyConflictError("只有草稿可以修改或发布")
    draft = _parse_draft(row.document)
    if (
        draft.draft_id != row.id
        or draft.strategy_id != row.strategy_id
        or draft.state_version != row.state_version
        or strategy_draft_sha256(draft) != row.sha256
    ):
        raise StrategyIntegrityError("草稿行与内容不一致")
    return draft


# 将发布行转为版本并核对行标识/指纹；归档状态从定义行派生，不改写正文。
def _version_from_row(
    row: StrategyVersionRecord, definition: StrategyDefinitionRecord
) -> StrategyVersion:
    if row.state != "published" or row.published_at is None:
        raise StrategyNotAvailableError("策略版本尚未发布")
    archived = definition.archived_at is not None
    version = _parse_version(
        row.document,
        archived=archived,
        archived_at=definition.archived_at,
    )
    if (
        version.ref.version_id != row.id
        or version.strategy_id != row.strategy_id
        or version.state_version != row.state_version
        or version.ref.sha256 != row.sha256
    ):
        raise StrategyIntegrityError("发布行与内容不一致")
    return version


# Pydantic 校验失败统一转为目录完整性错误，不把原始文档或异常细节回到 API。
def _parse_draft(document: dict[str, object]) -> StrategyDraft:
    try:
        return StrategyDraft.model_validate(document)
    except ValidationError as error:
        raise StrategyIntegrityError("草稿内容校验失败") from error


def _parse_version(
    document: dict[str, object],
    *,
    archived: bool,
    archived_at: datetime | None,
) -> StrategyVersion:
    payload = dict(document)
    payload["archived"] = archived
    payload["archived_at"] = None if archived_at is None else archived_at.isoformat()
    try:
        return StrategyVersion.model_validate(payload)
    except ValidationError as error:
        raise StrategyIntegrityError("发布内容校验失败") from error


# 版本行必须先按工作台读取并加锁；不存在或不属于当前工作台按不可用处理。
async def _lock_version(
    session: AsyncSession, workspace_id: UUID, draft_id: UUID
) -> StrategyVersionRecord:
    row = await session.scalar(
        select(StrategyVersionRecord)
        .where(
            StrategyVersionRecord.id == draft_id,
            StrategyVersionRecord.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if row is None:
        raise StrategyNotAvailableError("策略草稿不存在或不属于当前工作台")
    return row


# 定义行加锁用于目录代次和归档状态；版本行已在同一事务中锁定。
async def _lock_definition(
    session: AsyncSession, workspace_id: UUID, strategy_id: UUID
) -> StrategyDefinitionRecord:
    definition = await session.scalar(
        select(StrategyDefinitionRecord)
        .where(
            StrategyDefinitionRecord.id == strategy_id,
            StrategyDefinitionRecord.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if definition is None:
        raise StrategyNotAvailableError("策略定义不存在或不属于当前工作台")
    return definition


# 组合发布前逐一核对已发布组成版本、精确指纹、工作台、归档状态和参数 Schema。
async def _verify_components(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    draft: StrategyDraft,
) -> None:
    for component in draft.components:
        row = await session.get(StrategyVersionRecord, component.strategy_ref.version_id)
        if row is None or row.workspace_id != workspace_id or row.state != "published":
            raise StrategyIntegrityError("组合组成版本不可用")
        definition = await session.get(StrategyDefinitionRecord, row.strategy_id)
        if (
            definition is None
            or definition.workspace_id != workspace_id
            or definition.archived_at is not None
        ):
            raise StrategyIntegrityError("组合组成版本已停用")
        component_version = _version_from_row(row, definition)
        if component_version.ref != component.strategy_ref:
            raise StrategyIntegrityError("组合组成指纹不一致")
        if component_version.strategy_id == draft.strategy_id:
            raise StrategyIntegrityError("组合不能引用自身策略")
        try:
            validate_parameters(component_version.parameter_schema, component.parameters)
        except StrategyParameterError as error:
            raise StrategyIntegrityError("组合组成参数不符合其 Schema") from error


__all__ = ["SqlAlchemyStrategyCatalog"]
