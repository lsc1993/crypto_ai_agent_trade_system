# 用 PostgreSQL 事务实现 C4 Agent 任务仓储：请求幂等、不可变修订、全局可运行容量与事件分页。
# 入队顺序固定为请求锁 -> 重放检查 -> 会话/父任务解析 -> 队列锁 -> 任务/修订/请求/事件提交。
# 同一 request_id 先查已提交映射，因此队列已满时仍能重放原任务；不同请求键不按币种合并。
# 该仓储不解析策略参数、不调用模型/工具、不访问私有账户或交易执行。
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent_runs.contracts import (
    RUNNABLE_CAPACITY,
    RUNNABLE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    AgentRunError,
    RunInput,
    RunQuality,
    RunSnapshot,
    RunStatus,
    run_input_sha256,
)
from app.agent_runs.events import (
    RunEvent,
    RunEventPage,
    RunEventType,
    build_enqueue_events,
)
from app.infrastructure.persistence.models.agent_runs import (
    AgentRunEventRecord,
    AgentRunQueueRecord,
    AgentRunRecord,
    AgentRunRequestRecord,
    AgentRunRevisionRecord,
    AgentThreadRecord,
)
from app.shared.agent_types import ArtifactRef, ProductKey, require_utc

_MAX_EVENT_PAGE = 100


# SQL Agent 任务仓储；clock 可注入以稳定事件时刻和测试快照。
class SqlAlchemyAgentRunRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    # 服务端时间必须为 UTC；客户端时间不能用于证明任务时刻。
    def _now(self) -> datetime:
        return require_utc(self._clock())

    # 创建任务；同键同内容重放原结果，同键异内容返回稳定冲突。
    async def enqueue(self, workspace_id: UUID, data: RunInput) -> RunSnapshot:
        # 深度复制，避免调用方在事务提交后修改嵌套参数字典影响已保存请求。
        normalized = data.model_copy(deep=True)
        request_sha = run_input_sha256(workspace_id, normalized)
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                await _lock_request(session, workspace_id, normalized.request_id)
                replay = await _load_request(session, workspace_id, normalized.request_id)
                if replay is not None:
                    if replay.request_sha256 != request_sha:
                        raise AgentRunError("request_conflict")
                    snapshot = await _load_snapshot(session, workspace_id, replay.run_id)
                    if snapshot is None:
                        raise AgentRunError("integrity_violation")
                    return snapshot

                thread_id = await _resolve_thread(
                    session,
                    workspace_id,
                    normalized,
                    now,
                )
                await _lock_queue(session)
                runnable_count = await session.scalar(
                    select(func.count())
                    .select_from(AgentRunRecord)
                    .where(
                        AgentRunRecord.status.in_([item.value for item in RUNNABLE_RUN_STATUSES])
                    )
                )
                if runnable_count is not None and runnable_count >= RUNNABLE_CAPACITY:
                    raise AgentRunError("queue_full")

                run_id = uuid4()
                run = AgentRunRecord(
                    id=run_id,
                    workspace_id=workspace_id,
                    thread_id=thread_id,
                    parent_run_id=normalized.parent_run_id,
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
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    finished_at=None,
                )
                session.add(run)
                # 先落任务行，保证修订/请求/事件的 FK 在同一事务自动 flush 时已有父行。
                await session.flush()
                session.add(
                    AgentRunRevisionRecord(
                        run_id=run_id,
                        revision=1,
                        input=cast(
                            dict[str, object],
                            normalized.model_dump(mode="json", by_alias=False),
                        ),
                        sha256=request_sha,
                        created_at=now,
                    )
                )
                session.add(
                    AgentRunRequestRecord(
                        workspace_id=workspace_id,
                        request_id=normalized.request_id,
                        run_id=run_id,
                        request_sha256=request_sha,
                        created_at=now,
                    )
                )
                session.add_all(
                    _event_rows(
                        run_id=run_id,
                        workspace_id=workspace_id,
                        revision=1,
                        product=normalized.product,
                        occurred_at=now,
                        input_sha256=request_sha,
                        strategy_version_id=normalized.strategy.version_id,
                    )
                )
                thread = await session.get(AgentThreadRecord, thread_id)
                if thread is None:
                    raise AgentRunError("integrity_violation")
                thread.updated_at = now
                await session.flush()
                snapshot = await _load_snapshot(session, workspace_id, run_id)
                if snapshot is None:
                    raise AgentRunError("integrity_violation")
                return snapshot
        except AgentRunError:
            raise
        except IntegrityError:
            # 唯一约束兜底并发同键；请求锁已提交读取后仍失败时只接受同内容重放。
            replayed = await self._replay(workspace_id, normalized.request_id, request_sha)
            if replayed is not None:
                return replayed
            raise AgentRunError("storage_unavailable") from None
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 读取任务并校验当前修订指纹；跨工作台按不存在处理，不泄露任务是否存在。
    async def get(self, workspace_id: UUID, run_id: UUID) -> RunSnapshot | None:
        try:
            async with self._factory() as session:
                return await _load_snapshot(session, workspace_id, run_id)
        except AgentRunError:
            raise
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 按任务内序号读取安全事件；先校验任务归属，再返回游标分页。
    async def list_events(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        after_seq: int = 0,
        limit: int = 50,
    ) -> RunEventPage:
        if after_seq < 0 or not 1 <= limit <= _MAX_EVENT_PAGE:
            raise AgentRunError("invalid_event_page")
        try:
            async with self._factory() as session:
                owned_run_id = await session.scalar(
                    select(AgentRunRecord.id).where(
                        AgentRunRecord.id == run_id,
                        AgentRunRecord.workspace_id == workspace_id,
                    )
                )
                if owned_run_id is None:
                    raise AgentRunError("run_not_found")
                rows = list(
                    (
                        await session.scalars(
                            select(AgentRunEventRecord)
                            .where(
                                AgentRunEventRecord.run_id == run_id,
                                AgentRunEventRecord.sequence > after_seq,
                            )
                            .order_by(AgentRunEventRecord.sequence)
                            .limit(limit + 1)
                        )
                    ).all()
                )
                events = tuple(_event_from_row(row) for row in rows[:limit])
                next_after = events[-1].sequence if len(rows) > limit else None
                return RunEventPage(items=events, next_after=next_after)
        except AgentRunError:
            raise
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 唯一约束冲突后的独立事务重放；内容不同仍返回冲突而不是伪成功。
    async def _replay(
        self,
        workspace_id: UUID,
        request_id: UUID,
        request_sha: str,
    ) -> RunSnapshot | None:
        try:
            async with self._factory() as session:
                replay = await _load_request(session, workspace_id, request_id)
                if replay is None:
                    return None
                if replay.request_sha256 != request_sha:
                    raise AgentRunError("request_conflict")
                return await _load_snapshot(session, workspace_id, replay.run_id)
        except AgentRunError:
            raise
        except SQLAlchemyError:
            return None


# 解析/验证有效会话与父任务；父任务必须终态且属于同一会话，避免并行子任务借用旧上下文。
async def _resolve_thread(
    session: AsyncSession,
    workspace_id: UUID,
    data: RunInput,
    now: datetime,
) -> UUID:
    parent: AgentRunRecord | None = None
    if data.parent_run_id is not None:
        parent = await session.scalar(
            select(AgentRunRecord)
            .where(
                AgentRunRecord.id == data.parent_run_id,
                AgentRunRecord.workspace_id == workspace_id,
            )
            .with_for_update(read=True)
        )
        if parent is None:
            raise AgentRunError("parent_not_found")
        if parent.status not in {item.value for item in TERMINAL_RUN_STATUSES}:
            raise AgentRunError("parent_not_terminal")

    thread_id = data.thread_id
    if parent is not None:
        if thread_id is None:
            thread_id = parent.thread_id
        elif thread_id != parent.thread_id:
            raise AgentRunError("thread_conflict")

    if thread_id is None:
        thread = AgentThreadRecord(
            id=uuid4(),
            workspace_id=workspace_id,
            created_at=now,
            updated_at=now,
        )
        session.add(thread)
        await session.flush()
        return thread.id

    thread = await session.get(AgentThreadRecord, thread_id)
    if thread is None or thread.workspace_id != workspace_id:
        raise AgentRunError("thread_not_found")
    return thread.id


# 请求级事务锁串行化同一工作台/请求键；必须在队列容量检查之前以便满队列重放。
async def _lock_request(session: AsyncSession, workspace_id: UUID, request_id: UUID) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:request_key, 0))"),
        {"request_key": f"agent-run-request:{workspace_id}:{request_id}"},
    )


# 读取请求幂等映射；不存在返回 None，存在则由调用方核对内容指纹。
async def _load_request(
    session: AsyncSession,
    workspace_id: UUID,
    request_id: UUID,
) -> AgentRunRequestRecord | None:
    return await session.scalar(
        select(AgentRunRequestRecord).where(
            AgentRunRequestRecord.workspace_id == workspace_id,
            AgentRunRequestRecord.request_id == request_id,
        )
    )


# 锁定单例队列行；容量判断与插入必须在同一事务内完成。
async def _lock_queue(session: AsyncSession) -> None:
    queue = await session.scalar(
        select(AgentRunQueueRecord).where(AgentRunQueueRecord.id == 1).with_for_update()
    )
    if queue is None:
        raise AgentRunError("integrity_violation")


# 从任务行和当前修订构造对外快照；任何正文/指纹/引用不一致按不变量破坏处理。
async def _load_snapshot(
    session: AsyncSession,
    workspace_id: UUID,
    run_id: UUID,
) -> RunSnapshot | None:
    run = await session.get(AgentRunRecord, run_id)
    if run is None or run.workspace_id != workspace_id:
        return None
    revision = await session.scalar(
        select(AgentRunRevisionRecord).where(
            AgentRunRevisionRecord.run_id == run_id,
            AgentRunRevisionRecord.revision == run.revision,
        )
    )
    if revision is None:
        raise AgentRunError("integrity_violation")
    try:
        run_input = RunInput.model_validate(revision.input)
        status = RunStatus(run.status)
        result_refs = tuple(ArtifactRef.model_validate(item) for item in run.result_refs)
    except (ValueError, TypeError) as error:
        raise AgentRunError("integrity_violation") from error
    if run_input_sha256(workspace_id, run_input) != revision.sha256:
        raise AgentRunError("integrity_violation")
    try:
        return RunSnapshot(
            run_id=run.id,
            workspace_id=run.workspace_id,
            thread_id=run.thread_id,
            parent_run_id=run.parent_run_id,
            revision=run.revision,
            status=status,
            state_version=run.state_version,
            input=run_input,
            received_message_seq=run.received_message_seq,
            applied_message_seq=run.applied_message_seq,
            current_interaction_id=run.current_interaction_id,
            result_refs=result_refs,
            result_quality=cast(RunQuality | None, run.result_quality),
            created_at=run.created_at,
            updated_at=run.updated_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )
    except ValidationError as error:
        raise AgentRunError("integrity_violation") from error


# 将领域事件转成 ORM 行；事件载荷已在 events.py 按类型白名单校验。
def _event_rows(
    *,
    run_id: UUID,
    workspace_id: UUID,
    revision: int,
    product: ProductKey,
    occurred_at: datetime,
    input_sha256: str,
    strategy_version_id: UUID,
) -> list[AgentRunEventRecord]:
    events = build_enqueue_events(
        run_id=run_id,
        revision=revision,
        product=product,
        occurred_at=occurred_at,
        input_sha256=input_sha256,
        strategy_version_id=strategy_version_id,
    )
    return [
        AgentRunEventRecord(
            run_id=event.run_id,
            sequence=event.sequence,
            workspace_id=workspace_id,
            revision=event.revision,
            event_type=event.event_type.value,
            occurred_at=event.occurred_at,
            payload=cast(dict[str, object], event.payload),
            projection_version=event.projection_version,
        )
        for event in events
    ]


# 解析事件行并重新校验白名单载荷；未知类型或多余字段不能被当作安全事件返回。
def _event_from_row(row: AgentRunEventRecord) -> RunEvent:
    try:
        return RunEvent(
            run_id=row.run_id,
            revision=row.revision,
            sequence=row.sequence,
            event_type=RunEventType(row.event_type),
            occurred_at=row.occurred_at,
            payload=cast(dict[str, JsonValue], row.payload),
            projection_version=row.projection_version,
        )
    except (ValueError, ValidationError, TypeError) as error:
        raise AgentRunError("integrity_violation") from error


__all__ = ["SqlAlchemyAgentRunRepository"]
