# 用 PostgreSQL 实现 T07 片段领取与心跳：队列锁内把 queued 转为 running，建立唯一片段与租约。
# 领取同时创建初始预算授权引用，返回服务端 ExecutionContext；不执行模型、工具或交易。
# 心跳与领取都先锁任务行，再用数据库 clock_timestamp() 判断租约；客户端时间不参与放行。
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent_runs.budget import initial_budget_limits
from app.agent_runs.contracts import RUNNABLE_RUN_STATUSES, AgentRunError, RunStatus
from app.agent_runs.events import RunEventType
from app.agent_runs.segments import (
    EMPTY_TOOL_CATALOG_SHA256,
    LEASE_SECONDS,
    ExecutionContext,
    RunFence,
    graph_namespace,
)
from app.infrastructure.persistence.agent_run_repository import (
    append_run_event,
    load_run_snapshot,
)
from app.infrastructure.persistence.models.agent_attempts import BudgetAuthorizationRecord
from app.infrastructure.persistence.models.agent_runs import AgentRunQueueRecord, AgentRunRecord
from app.infrastructure.persistence.models.agent_segments import AgentSegmentRecord
from app.shared.agent_types import require_utc


# 片段领取/续租仓储；owner 由 worker 实例持有，lease_epoch 每次领取递增。
# T07 尚未登记工具目录，使用空目录指纹；T09 注入真实目录指纹后无需改变接口。
class SqlAlchemyAgentSegmentRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lease_seconds: int = LEASE_SECONDS,
        tool_catalog_sha256: str = EMPTY_TOOL_CATALOG_SHA256,
        policy_version: str = "interactive_planning_v1",
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("片段租约必须为正秒数")
        self._factory = session_factory
        self._lease = timedelta(seconds=lease_seconds)
        self._tool_catalog_sha256 = tool_catalog_sha256
        self._policy_version = policy_version

    # 在队列单例锁内领取最早的 queued 任务；同任务唯一 running 片段防止重复 owner。
    async def claim(self, owner: UUID) -> ExecutionContext | None:
        try:
            async with self._factory() as session, session.begin():
                await _lock_queue(session)
                run = await session.scalar(
                    select(AgentRunRecord)
                    .where(
                        AgentRunRecord.status == RunStatus.QUEUED.value,
                        AgentRunRecord.owner.is_(None),
                        AgentRunRecord.lease_expires_at.is_(None),
                    )
                    .order_by(AgentRunRecord.created_at, AgentRunRecord.id)
                    .with_for_update(skip_locked=True)
                )
                if run is None:
                    return None

                active_segment = await session.scalar(
                    select(AgentSegmentRecord.id).where(
                        AgentSegmentRecord.run_id == run.id,
                        AgentSegmentRecord.status == "running",
                    )
                )
                if active_segment is not None:
                    raise AgentRunError("integrity_violation")

                snapshot = await load_run_snapshot(session, run.workspace_id, run.id)
                if snapshot is None or snapshot.status is not RunStatus.QUEUED:
                    raise AgentRunError("integrity_violation")

                database_now = await read_database_now(session)
                segment_id = uuid4()
                authorization_id = await _initial_budget_authorization_id(
                    session,
                    run,
                    database_now,
                )
                run.status = RunStatus.RUNNING.value
                run.owner = owner
                run.lease_epoch += 1
                run.lease_expires_at = database_now + self._lease
                run.started_at = run.started_at or database_now
                run.updated_at = database_now
                run.state_version += 1
                namespace = graph_namespace(
                    RunFence(
                        workspace_id=run.workspace_id,
                        run_id=run.id,
                        revision=run.revision,
                        segment_id=segment_id,
                        owner=owner,
                        lease_epoch=run.lease_epoch,
                    )
                )
                session.add(
                    AgentSegmentRecord(
                        id=segment_id,
                        workspace_id=run.workspace_id,
                        run_id=run.id,
                        revision=run.revision,
                        owner=owner,
                        lease_epoch=run.lease_epoch,
                        graph_namespace=namespace,
                        status="running",
                        outcome_kind=None,
                        outcome={},
                        safe_reason=None,
                        started_at=database_now,
                        heartbeat_at=database_now,
                        lease_expires_at=run.lease_expires_at,
                        finished_at=None,
                    )
                )
                await session.flush()
                await append_run_event(
                    session,
                    run_id=run.id,
                    workspace_id=run.workspace_id,
                    revision=run.revision,
                    event_type=RunEventType.RUN_STARTED,
                    payload={"status": "running"},
                    occurred_at=database_now,
                )
                return ExecutionContext(
                    fence=RunFence(
                        workspace_id=run.workspace_id,
                        run_id=run.id,
                        revision=run.revision,
                        segment_id=segment_id,
                        owner=owner,
                        lease_epoch=run.lease_epoch,
                    ),
                    strategy_ref=snapshot.input.strategy,
                    tool_catalog_sha256=self._tool_catalog_sha256,
                    policy_version=self._policy_version,
                    budget_authorization_id=authorization_id,
                )
        except AgentRunError:
            raise
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 续租前核对 owner/代次/修订/片段与数据库当前时刻；任一失配返回 False 而不延长租约。
    async def heartbeat(self, fence: RunFence) -> bool:
        try:
            async with self._factory() as session, session.begin():
                run = await _lock_owned_run(session, fence)
                if run is None:
                    return False
                database_now = await read_database_now(session)
                if not _run_fence_valid(run, fence, database_now):
                    return False
                segment = await session.get(AgentSegmentRecord, fence.segment_id)
                if segment is None or not _segment_fence_valid(segment, fence, database_now):
                    return False
                # 取消请求在心跳边界停止续租并触发 worker 收尾，不能靠继续延长租约等待模型结束。
                if run.cancel_requested_at is not None:
                    return False
                run.lease_expires_at = database_now + self._lease
                segment.heartbeat_at = database_now
                segment.lease_expires_at = run.lease_expires_at
                return True
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 只读读取片段快照，供测试与后续诊断；跨工作台返回 None。
    async def get_segment(
        self,
        workspace_id: UUID,
        run_id: UUID,
        segment_id: UUID,
    ) -> AgentSegmentRecord | None:
        try:
            async with self._factory() as session:
                return await session.scalar(
                    select(AgentSegmentRecord).where(
                        AgentSegmentRecord.id == segment_id,
                        AgentSegmentRecord.workspace_id == workspace_id,
                        AgentSegmentRecord.run_id == run_id,
                    )
                )
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None


# 队列单例锁与 enqueue/响应/领取共用，保证可运行容量和顺序一致。
async def _lock_queue(session: AsyncSession) -> None:
    queue = await session.scalar(
        select(AgentRunQueueRecord).where(AgentRunQueueRecord.id == 1).with_for_update()
    )
    if queue is None:
        raise AgentRunError("integrity_violation")


async def _lock_owned_run(session: AsyncSession, fence: RunFence) -> AgentRunRecord | None:
    return await session.scalar(
        select(AgentRunRecord)
        .where(
            AgentRunRecord.id == fence.run_id,
            AgentRunRecord.workspace_id == fence.workspace_id,
        )
        .with_for_update()
    )


async def read_database_now(session: AsyncSession) -> datetime:
    value = await session.scalar(text("SELECT clock_timestamp()"))
    if not isinstance(value, datetime):
        raise AgentRunError("integrity_violation")
    return require_utc(value)


# 首次领取时建立不可变初始预算授权；后续由 T05 账本复用同一行，不能重复创建。
async def _initial_budget_authorization_id(
    session: AsyncSession,
    run: AgentRunRecord,
    now: datetime,
) -> UUID:
    existing = await session.scalar(
        select(BudgetAuthorizationRecord).where(
            BudgetAuthorizationRecord.run_id == run.id,
            BudgetAuthorizationRecord.kind == "initial",
        )
    )
    if existing is not None:
        return existing.id
    limits = initial_budget_limits()
    authorization_id = uuid4()
    session.add(
        BudgetAuthorizationRecord(
            id=authorization_id,
            workspace_id=run.workspace_id,
            run_id=run.id,
            kind="initial",
            model_calls=limits.model_calls,
            tool_calls=limits.tool_calls,
            input_tokens=limits.input_tokens,
            output_tokens=limits.output_tokens,
            active_seconds=limits.active_seconds,
            transport_calls=limits.transport_calls,
            authorization_ref=None,
            reason=None,
            created_at=now,
        )
    )
    await session.flush()
    return authorization_id


def _run_fence_valid(run: AgentRunRecord, fence: RunFence, database_now: datetime) -> bool:
    return (
        run.status in {item.value for item in RUNNABLE_RUN_STATUSES}
        and run.status == RunStatus.RUNNING.value
        and run.owner == fence.owner
        and run.lease_epoch == fence.lease_epoch
        and run.revision == fence.revision
        and run.lease_expires_at is not None
        and run.lease_expires_at > database_now
    )


def _segment_fence_valid(
    segment: AgentSegmentRecord,
    fence: RunFence,
    database_now: datetime,
) -> bool:
    return (
        segment.workspace_id == fence.workspace_id
        and segment.run_id == fence.run_id
        and segment.revision == fence.revision
        and segment.owner == fence.owner
        and segment.lease_epoch == fence.lease_epoch
        and segment.graph_namespace == graph_namespace(fence)
        and segment.status == "running"
        and segment.lease_expires_at is not None
        and segment.lease_expires_at > database_now
    )


__all__ = ["SqlAlchemyAgentSegmentRepository"]
