# T07 片段提交协调器：唯一事务所有者，原子提交业务状态、pending 待办、片段、审计终态、
# 事件与 owner 释放。所有写入先锁任务行并用数据库 clock_timestamp() 核验 fence。
# 恢复器只对已 started 的 Harness 追加序号 3；缺前缀时保留中断事实，不伪造准入/开始。
# 本模块不调用模型、工具、账户或交易执行，只写本地任务/审计事实。
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent_runs.contracts import (
    WAITING_CAPACITY_PER_WORKSPACE,
    WAITING_RUN_STATUSES,
    AgentRunError,
    RunStatus,
)
from app.agent_runs.events import RunEventType
from app.agent_runs.interactions import InteractionStatus
from app.agent_runs.segments import (
    EMPTY_TOOL_CATALOG_SHA256,
    LEASE_SECONDS,
    CompletionDecision,
    CompletionDecisionKind,
    ExecutionContext,
    RunFence,
    SegmentOutcome,
    SegmentOutcomeKind,
    SegmentStatus,
    graph_namespace,
)
from app.governance.audit import (
    HarnessAuditEvent,
    HarnessAuditEventKind,
    HarnessAuditRun,
    HarnessAuditStorageUnavailableError,
    HarnessAuditTrace,
    HarnessEvaluation,
    HarnessEvaluationDecision,
    HarnessEvaluationDetails,
    HarnessEventDetails,
    HarnessInitiatorKind,
)
from app.governance.contracts import GovernanceRunKind
from app.infrastructure.persistence.agent_run_repository import append_run_event
from app.infrastructure.persistence.agent_segment_repository import (
    SqlAlchemyAgentSegmentRepository,
    read_database_now,
)
from app.infrastructure.persistence.models.agent_interactions import AgentInteractionRecord
from app.infrastructure.persistence.models.agent_runs import AgentRunQueueRecord, AgentRunRecord
from app.infrastructure.persistence.models.agent_segments import AgentSegmentRecord
from app.infrastructure.persistence.models.harness import (
    HarnessAuditEventRecord,
    HarnessAuditRunRecord,
    HarnessEvaluationRecord,
)
from app.shared.agent_types import ArtifactRef, require_utc

_ACTIVE_INTERACTION_STATUSES = ("preparing", "pending", "answered")
_AUDIT_TERMINAL_SEQUENCE = 3
_AUDIT_STARTED_SEQUENCE = 2


# SegmentRepository 的唯一 SQL 实现；owner/epoch 校验与审计序号写入共享同一事务边界。
# 领取/心跳委托给专用租约仓储，本类负责需要跨业务/审计表的原子提交与恢复。
class SqlAlchemyAgentCommitCoordinator:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
        lease_seconds: int = LEASE_SECONDS,
        tool_catalog_sha256: str = EMPTY_TOOL_CATALOG_SHA256,
        policy_version: str = "interactive_planning_v1",
    ) -> None:
        self._factory = session_factory
        # 审计事件时刻来自数据库当前时刻；注入 clock 仅保留服务端时钟替换点，
        # 租约合法性绝不能改用该值。
        self._clock = clock or (lambda: datetime.now(UTC))
        self._leases = SqlAlchemyAgentSegmentRepository(
            session_factory,
            lease_seconds=lease_seconds,
            tool_catalog_sha256=tool_catalog_sha256,
            policy_version=policy_version,
        )

    async def claim(self, owner: UUID) -> ExecutionContext | None:
        return await self._leases.claim(owner)

    async def heartbeat(self, fence: RunFence) -> bool:
        return await self._leases.heartbeat(fence)

    # 恢复过期 running 片段：先按真实审计前缀决定是否写序号 3，再把任务重新排队。
    # 已收到取消标记的运行直接安全取消；preparing 待办保留给新片段重新发布。
    async def recover_expired(self, *, limit: int = 50) -> int:
        if not 1 <= limit <= 100:
            raise ValueError("恢复批量必须在 1..100 之间")
        recovered = 0
        try:
            async with self._factory() as session, session.begin():
                database_now = await read_database_now(session)
                runs = list(
                    (
                        await session.scalars(
                            select(AgentRunRecord)
                            .where(
                                AgentRunRecord.status == RunStatus.RUNNING.value,
                                AgentRunRecord.lease_expires_at.is_not(None),
                                AgentRunRecord.lease_expires_at <= database_now,
                            )
                            .order_by(AgentRunRecord.lease_expires_at, AgentRunRecord.id)
                            .limit(limit)
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                )
                for run in runs:
                    segment = await _lock_active_segment(session, run.id)
                    # 行锁后必须重新采样数据库时刻：等待锁期间心跳/并发提交可能已推进租约或终态。
                    database_now = await read_database_now(session)
                    if run.status != RunStatus.RUNNING.value:
                        continue
                    if run.lease_expires_at is None or run.lease_expires_at > database_now:
                        continue
                    if (
                        segment is not None
                        and segment.lease_expires_at is not None
                        and segment.lease_expires_at > database_now
                    ):
                        continue
                    if run.cancel_requested_at is not None:
                        await _expire_active_interactions(
                            session,
                            run,
                            now=database_now,
                            reason="user_cancelled",
                        )
                        if segment is not None:
                            await _audit_terminal_outcome(
                                session,
                                segment_id=segment.id,
                                now=database_now,
                                kind=HarnessAuditEventKind.WORKFLOW_FAILED,
                                error_code="user_cancelled",
                                error_type="Cancelled",
                            )
                            _finish_segment(
                                segment,
                                status=SegmentStatus.INTERRUPTED,
                                outcome_kind=SegmentOutcomeKind.CANCELLED,
                                outcome_doc={"reason": "user_cancelled"},
                                safe_reason="user_cancelled",
                                now=database_now,
                            )
                        _terminate_run(
                            run,
                            status=RunStatus.CANCELLED,
                            now=database_now,
                            safe_reason="user_cancelled",
                            result_refs=(),
                            result_quality=None,
                        )
                        await append_run_event(
                            session,
                            run_id=run.id,
                            workspace_id=run.workspace_id,
                            revision=run.revision,
                            event_type=RunEventType.RUN_TERMINATED,
                            payload={"status": RunStatus.CANCELLED.value},
                            occurred_at=database_now,
                        )
                        recovered += 1
                        continue

                    if segment is None:
                        _terminate_run(
                            run,
                            status=RunStatus.FAILED,
                            now=database_now,
                            safe_reason="segment_missing",
                            result_refs=(),
                            result_quality=None,
                        )
                        await append_run_event(
                            session,
                            run_id=run.id,
                            workspace_id=run.workspace_id,
                            revision=run.revision,
                            event_type=RunEventType.RUN_TERMINATED,
                            payload={"status": RunStatus.FAILED.value},
                            occurred_at=database_now,
                        )
                        recovered += 1
                        continue
                    if segment.status != SegmentStatus.RUNNING.value:
                        _terminate_run(
                            run,
                            status=RunStatus.FAILED,
                            now=database_now,
                            safe_reason="segment_state_conflict",
                            result_refs=(),
                            result_quality=None,
                        )
                        await append_run_event(
                            session,
                            run_id=run.id,
                            workspace_id=run.workspace_id,
                            revision=run.revision,
                            event_type=RunEventType.RUN_TERMINATED,
                            payload={"status": RunStatus.FAILED.value},
                            occurred_at=database_now,
                        )
                        recovered += 1
                        continue

                    active = await _lock_active_interaction(session, run.id)
                    if active is not None and active.status != InteractionStatus.PREPARING.value:
                        # running 状态与 pending/answered 待办冲突时不继续执行，
                        # 写入真实失败终态并保留待办历史；不猜测用户是否已看到材料。
                        await _expire_active_interactions(
                            session,
                            run,
                            now=database_now,
                            reason="interaction_state_conflict",
                        )
                        await _audit_terminal_outcome(
                            session,
                            segment_id=segment.id,
                            now=database_now,
                            kind=HarnessAuditEventKind.WORKFLOW_FAILED,
                            error_code="interaction_state_conflict",
                            error_type="InteractionStateConflict",
                        )
                        _finish_segment(
                            segment,
                            status=SegmentStatus.FAILED,
                            outcome_kind=SegmentOutcomeKind.FAILED,
                            outcome_doc={"reason": "interaction_state_conflict"},
                            safe_reason="interaction_state_conflict",
                            now=database_now,
                        )
                        _terminate_run(
                            run,
                            status=RunStatus.FAILED,
                            now=database_now,
                            safe_reason="interaction_state_conflict",
                            result_refs=(),
                            result_quality=None,
                        )
                        await append_run_event(
                            session,
                            run_id=run.id,
                            workspace_id=run.workspace_id,
                            revision=run.revision,
                            event_type=RunEventType.RUN_TERMINATED,
                            payload={"status": RunStatus.FAILED.value},
                            occurred_at=database_now,
                        )
                        recovered += 1
                        continue

                    await _audit_terminal_outcome(
                        session,
                        segment_id=segment.id,
                        now=database_now,
                        kind=HarnessAuditEventKind.WORKFLOW_FAILED,
                        error_code="lease_expired",
                        error_type="LeaseExpired",
                    )
                    _finish_segment(
                        segment,
                        status=SegmentStatus.INTERRUPTED,
                        outcome_kind=None,
                        outcome_doc={"reason": "lease_expired"},
                        safe_reason="lease_expired",
                        now=database_now,
                    )
                    run.status = RunStatus.QUEUED.value
                    run.owner = None
                    run.lease_expires_at = None
                    run.cancel_requested_at = None
                    run.updated_at = database_now
                    run.state_version += 1
                    await append_run_event(
                        session,
                        run_id=run.id,
                        workspace_id=run.workspace_id,
                        revision=run.revision,
                        event_type=RunEventType.RUN_REQUEUED,
                        payload={"reason": "lease_expired"},
                        occurred_at=database_now,
                    )
                    recovered += 1
                return recovered
        except AgentRunError:
            raise
        except (ValidationError, ValueError, TypeError) as error:
            raise AgentRunError("integrity_violation") from error
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 提交片段结果；失租/冲突返回固定裁决而不是写入任何业务状态。
    async def commit(
        self,
        fence: RunFence,
        outcome: SegmentOutcome,
    ) -> CompletionDecision:
        return await self._commit(fence, outcome)

    # 运行器异常时由治理审计适配器调用：同一事务写序号 3 与业务失败终态。
    async def commit_audit_failure(
        self,
        fence: RunFence,
        event: HarnessAuditEvent,
    ) -> bool:
        decision = await self._commit(
            fence,
            SegmentOutcome(
                kind=SegmentOutcomeKind.FAILED,
                safe_reason=event.error_code or "workflow_exception",
            ),
            audit_error_code=event.error_code or "workflow_exception",
            audit_error_type=event.details.error_type or "WorkflowException",
        )
        return decision.kind is CompletionDecisionKind.COMMITTED

    # 四阶段审计写入都先核对当前 fence；每次写入独立提交，崩溃窗口由恢复器处理。
    async def create_requested_run(
        self,
        fence: RunFence,
        run: HarnessAuditRun,
        event: HarnessAuditEvent,
    ) -> None:
        try:
            async with self._factory() as session, session.begin():
                await _lock_live_fence(session, fence)
                _require_audit_event(
                    event,
                    sequence=0,
                    kind=HarnessAuditEventKind.REQUESTED,
                )
                if (
                    run.run_id != fence.segment_id
                    or event.run_id != fence.segment_id
                    or run.run_kind is not GovernanceRunKind.INTERACTIVE_PLANNING
                ):
                    raise AgentRunError("integrity_violation")
                existing = await session.get(HarnessAuditRunRecord, fence.segment_id)
                if existing is not None:
                    raise AgentRunError("integrity_violation")
                session.add(_audit_run_record(run))
                await session.flush()
                session.add(_audit_event_record(event))
        except AgentRunError:
            raise
        except SQLAlchemyError:
            raise HarnessAuditStorageUnavailableError from None

    async def append_policy_evaluation(
        self,
        fence: RunFence,
        evaluation: HarnessEvaluation,
        event: HarnessAuditEvent,
    ) -> None:
        try:
            async with self._factory() as session, session.begin():
                await _lock_live_fence(session, fence)
                _require_audit_event(
                    event,
                    sequence=1,
                    kind=HarnessAuditEventKind.POLICY_AUTHORIZED,
                )
                if evaluation.run_id != fence.segment_id or event.run_id != fence.segment_id:
                    raise AgentRunError("integrity_violation")
                if await session.get(HarnessAuditRunRecord, fence.segment_id) is None:
                    raise AgentRunError("integrity_violation")
                if not await _audit_sequence_exists(session, fence.segment_id, 0):
                    raise AgentRunError("integrity_violation")
                if await _audit_sequence_exists(session, fence.segment_id, 1):
                    raise AgentRunError("integrity_violation")
                session.add(_audit_evaluation_record(evaluation))
                session.add(_audit_event_record(event))
        except AgentRunError:
            raise
        except SQLAlchemyError:
            raise HarnessAuditStorageUnavailableError from None

    async def append_started_event(
        self,
        fence: RunFence,
        event: HarnessAuditEvent,
    ) -> None:
        try:
            async with self._factory() as session, session.begin():
                await _lock_live_fence(session, fence)
                _require_audit_event(
                    event,
                    sequence=_AUDIT_STARTED_SEQUENCE,
                    kind=HarnessAuditEventKind.WORKFLOW_STARTED,
                )
                if event.run_id != fence.segment_id:
                    raise AgentRunError("integrity_violation")
                if await session.get(HarnessAuditRunRecord, fence.segment_id) is None:
                    raise AgentRunError("integrity_violation")
                if not await _audit_sequence_exists(session, fence.segment_id, 1):
                    raise AgentRunError("integrity_violation")
                if await _audit_sequence_exists(session, fence.segment_id, 2):
                    raise AgentRunError("integrity_violation")
                session.add(_audit_event_record(event))
        except AgentRunError:
            raise
        except SQLAlchemyError:
            raise HarnessAuditStorageUnavailableError from None

    async def get_audit_trace(self, run_id: UUID) -> HarnessAuditTrace | None:
        try:
            async with self._factory() as session:
                run_record = await session.get(HarnessAuditRunRecord, run_id)
                if run_record is None:
                    return None
                events = tuple(
                    (
                        await session.scalars(
                            select(HarnessAuditEventRecord)
                            .where(HarnessAuditEventRecord.run_id == run_record.run_id)
                            .order_by(HarnessAuditEventRecord.sequence)
                        )
                    ).all()
                )
                evaluations = tuple(
                    (
                        await session.scalars(
                            select(HarnessEvaluationRecord)
                            .where(HarnessEvaluationRecord.run_id == run_record.run_id)
                            .order_by(HarnessEvaluationRecord.sequence)
                        )
                    ).all()
                )
        except SQLAlchemyError:
            raise HarnessAuditStorageUnavailableError from None
        try:
            return HarnessAuditTrace(
                run=HarnessAuditRun(
                    run_id=run_record.run_id,
                    run_kind=GovernanceRunKind(run_record.run_kind),
                    policy_version=run_record.policy_version,
                    policy_sha256=run_record.policy_sha256,
                    symbol=run_record.symbol,
                    requested_at=run_record.requested_at,
                    initiator_kind=HarnessInitiatorKind(run_record.initiator_kind),
                    request_sha256=run_record.request_sha256,
                ),
                events=tuple(_audit_event_from_record(row) for row in events),
                evaluations=tuple(_evaluation_from_record(row) for row in evaluations),
            )
        except (ValueError, ValidationError, TypeError) as error:
            raise AgentRunError("integrity_violation") from error

    # 内部提交协议；所有终态/等待/重排分支共享 fence、审计和 owner 释放。
    async def _commit(
        self,
        fence: RunFence,
        outcome: SegmentOutcome,
        *,
        audit_error_code: str | None = None,
        audit_error_type: str | None = None,
    ) -> CompletionDecision:
        try:
            async with self._factory() as session, session.begin():
                # 等待容量与可运行容量共用队列锁；必须在任务行锁之前取得，避免锁序反转。
                if outcome.kind in {
                    SegmentOutcomeKind.WAIT_INPUT,
                    SegmentOutcomeKind.WAIT_APPROVAL,
                }:
                    await _lock_agent_queue(session)
                run = await _lock_run(session, fence)
                if run is None:
                    return _lease_lost()
                database_now = await read_database_now(session)
                segment = await _lock_segment(session, fence.segment_id)
                if segment is None or not _fence_valid(run, segment, fence, database_now):
                    return _lease_lost()

                if outcome.applied_message_seq > run.received_message_seq:
                    await _fail_terminal(
                        session,
                        run=run,
                        segment=segment,
                        now=database_now,
                        reason="invalid_message_watermark",
                        write_audit=True,
                    )
                    return _committed(run.state_version)

                # 用户取消优先于消息待处理和等待发布：迟到取消不能被重排成继续执行。
                effective = outcome
                if run.cancel_requested_at is not None and outcome.kind not in {
                    SegmentOutcomeKind.FAILED,
                    SegmentOutcomeKind.CANCELLED,
                }:
                    effective = SegmentOutcome(
                        kind=SegmentOutcomeKind.CANCELLED,
                        safe_reason="user_cancelled",
                        applied_message_seq=outcome.applied_message_seq,
                    )

                waiting_or_complete = effective.kind in {
                    SegmentOutcomeKind.WAIT_INPUT,
                    SegmentOutcomeKind.WAIT_APPROVAL,
                    SegmentOutcomeKind.COMPLETED,
                    SegmentOutcomeKind.DEGRADED,
                }
                if waiting_or_complete and run.received_message_seq > run.applied_message_seq:
                    await _defer_run(
                        session,
                        run=run,
                        segment=segment,
                        now=database_now,
                        reason="messages_pending",
                    )
                    return CompletionDecision(
                        kind=CompletionDecisionKind.MESSAGES_PENDING,
                        safe_reason="messages_pending",
                    )

                if effective.kind in {
                    SegmentOutcomeKind.COMPLETED,
                    SegmentOutcomeKind.DEGRADED,
                }:
                    active = await _lock_active_interaction(session, run.id)
                    if active is not None:
                        await _defer_run(
                            session,
                            run=run,
                            segment=segment,
                            now=database_now,
                            reason="interaction_pending",
                        )
                        return CompletionDecision(
                            kind=CompletionDecisionKind.CONFLICT,
                            safe_reason="interaction_pending",
                        )
                    audit_result = await _audit_outcome(
                        session,
                        segment_id=segment.id,
                        outcome=effective,
                        now=database_now,
                        audit_error_code=audit_error_code,
                        audit_error_type=audit_error_type,
                    )
                    if audit_result != "written":
                        await _fail_terminal(
                            session,
                            run=run,
                            segment=segment,
                            now=database_now,
                            reason=(
                                "audit_prefix_missing"
                                if audit_result == "not_started"
                                else "audit_terminal_conflict"
                            ),
                            write_audit=False,
                        )
                        return _committed(run.state_version)
                    status = (
                        RunStatus.COMPLETED
                        if effective.kind is SegmentOutcomeKind.COMPLETED
                        else RunStatus.DEGRADED
                    )
                    _terminate_run(
                        run,
                        status=status,
                        now=database_now,
                        safe_reason=effective.safe_reason,
                        result_refs=effective.artifact_refs,
                        result_quality=(
                            "complete" if status is RunStatus.COMPLETED else "degraded"
                        ),
                    )
                    _finish_segment(
                        segment,
                        status=(
                            SegmentStatus.COMPLETED
                            if status is RunStatus.COMPLETED
                            else SegmentStatus.DEGRADED
                        ),
                        outcome_kind=effective.kind,
                        outcome_doc=effective.model_dump(mode="json"),
                        safe_reason=effective.safe_reason,
                        now=database_now,
                    )
                    await append_run_event(
                        session,
                        run_id=run.id,
                        workspace_id=run.workspace_id,
                        revision=run.revision,
                        event_type=RunEventType.RUN_TERMINATED,
                        payload={"status": status.value},
                        occurred_at=database_now,
                    )
                    return _committed(run.state_version)

                if effective.kind in {
                    SegmentOutcomeKind.WAIT_INPUT,
                    SegmentOutcomeKind.WAIT_APPROVAL,
                }:
                    interaction = await _lock_preparing_interaction(
                        session,
                        run,
                        effective.preparing_interaction_id,
                    )
                    if interaction is None:
                        await _fail_terminal(
                            session,
                            run=run,
                            segment=segment,
                            now=database_now,
                            reason="interaction_state_conflict",
                            write_audit=True,
                        )
                        return _committed(run.state_version)
                    if interaction.expires_at <= database_now:
                        # preparing 材料在长时间恢复后已失效，不能发布为可响应待办。
                        await _fail_terminal(
                            session,
                            run=run,
                            segment=segment,
                            now=database_now,
                            reason="review_expired",
                            write_audit=True,
                            interaction_reason="review_expired",
                        )
                        return _committed(run.state_version)
                    waiting_count = await session.scalar(
                        select(func.count())
                        .select_from(AgentRunRecord)
                        .where(
                            AgentRunRecord.workspace_id == run.workspace_id,
                            AgentRunRecord.status.in_(
                                [item.value for item in WAITING_RUN_STATUSES]
                            ),
                        )
                    )
                    if (
                        waiting_count is not None
                        and waiting_count >= WAITING_CAPACITY_PER_WORKSPACE
                    ):
                        await _fail_terminal(
                            session,
                            run=run,
                            segment=segment,
                            now=database_now,
                            reason="waiting_capacity_full",
                            write_audit=True,
                        )
                        return _committed(run.state_version)
                    audit_result = await _audit_outcome(
                        session,
                        segment_id=segment.id,
                        outcome=effective,
                        now=database_now,
                        audit_error_code=audit_error_code,
                        audit_error_type=audit_error_type,
                    )
                    if audit_result != "written":
                        await _fail_terminal(
                            session,
                            run=run,
                            segment=segment,
                            now=database_now,
                            reason=(
                                "audit_prefix_missing"
                                if audit_result == "not_started"
                                else "audit_terminal_conflict"
                            ),
                            write_audit=False,
                        )
                        return _committed(run.state_version)
                    interaction.status = InteractionStatus.PENDING.value
                    interaction.state_version += 1
                    interaction.published_at = database_now
                    run.status = (
                        RunStatus.WAITING_INPUT.value
                        if effective.kind is SegmentOutcomeKind.WAIT_INPUT
                        else RunStatus.WAITING_APPROVAL.value
                    )
                    run.current_interaction_id = interaction.id
                    run.owner = None
                    run.lease_expires_at = None
                    run.cancel_requested_at = None
                    run.updated_at = database_now
                    run.state_version += 1
                    _finish_segment(
                        segment,
                        status=(
                            SegmentStatus.WAITING_INPUT
                            if effective.kind is SegmentOutcomeKind.WAIT_INPUT
                            else SegmentStatus.WAITING_APPROVAL
                        ),
                        outcome_kind=effective.kind,
                        outcome_doc=effective.model_dump(mode="json"),
                        safe_reason=effective.safe_reason,
                        now=database_now,
                    )
                    await append_run_event(
                        session,
                        run_id=run.id,
                        workspace_id=run.workspace_id,
                        revision=run.revision,
                        event_type=RunEventType.INTERACTION_PENDING,
                        payload={
                            "interactionId": str(interaction.id),
                            "action": interaction.action,
                            "revision": run.revision,
                        },
                        occurred_at=database_now,
                    )
                    await append_run_event(
                        session,
                        run_id=run.id,
                        workspace_id=run.workspace_id,
                        revision=run.revision,
                        event_type=RunEventType.RUN_WAITING,
                        payload={"status": run.status},
                        occurred_at=database_now,
                    )
                    return _committed(run.state_version)

                # 失败/取消终态：只有已 started 的审计前缀才追加真实失败序号 3。
                await _expire_active_interactions(
                    session,
                    run,
                    now=database_now,
                    reason=(
                        "user_cancelled"
                        if effective.kind is SegmentOutcomeKind.CANCELLED
                        else "run_failed"
                    ),
                )
                await _audit_outcome(
                    session,
                    segment_id=segment.id,
                    outcome=effective,
                    now=database_now,
                    audit_error_code=audit_error_code,
                    audit_error_type=audit_error_type,
                )
                status = (
                    RunStatus.CANCELLED
                    if effective.kind is SegmentOutcomeKind.CANCELLED
                    else RunStatus.FAILED
                )
                _terminate_run(
                    run,
                    status=status,
                    now=database_now,
                    safe_reason=effective.safe_reason,
                    result_refs=effective.artifact_refs,
                    result_quality=None,
                )
                _finish_segment(
                    segment,
                    status=(
                        SegmentStatus.CANCELLED
                        if status is RunStatus.CANCELLED
                        else SegmentStatus.FAILED
                    ),
                    outcome_kind=effective.kind,
                    outcome_doc=effective.model_dump(mode="json"),
                    safe_reason=effective.safe_reason,
                    now=database_now,
                )
                await append_run_event(
                    session,
                    run_id=run.id,
                    workspace_id=run.workspace_id,
                    revision=run.revision,
                    event_type=RunEventType.RUN_TERMINATED,
                    payload={"status": status.value},
                    occurred_at=database_now,
                )
                return _committed(run.state_version)
        except AgentRunError:
            raise
        except IntegrityError:
            # 审计唯一键或任务状态的并发冲突不重写已提交事实；worker 交由恢复器处理。
            return CompletionDecision(
                kind=CompletionDecisionKind.CONFLICT,
                safe_reason="commit_conflict",
            )
        except (ValidationError, ValueError, TypeError) as error:
            raise AgentRunError("integrity_violation") from error
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None


# 锁任务与片段并核对数据库当前时刻；审计前缀写入与提交共用同一校验语义。
async def _lock_live_fence(
    session: AsyncSession,
    fence: RunFence,
) -> tuple[AgentRunRecord, AgentSegmentRecord]:
    run = await _lock_run(session, fence)
    if run is None:
        raise AgentRunError("lease_lost")
    database_now = await read_database_now(session)
    segment = await _lock_segment(session, fence.segment_id)
    if not _fence_valid(run, segment, fence, database_now):
        raise AgentRunError("lease_lost")
    assert segment is not None
    return run, segment


async def _lock_agent_queue(session: AsyncSession) -> None:
    queue = await session.scalar(
        select(AgentRunQueueRecord).where(AgentRunQueueRecord.id == 1).with_for_update()
    )
    if queue is None:
        raise AgentRunError("integrity_violation")


async def _lock_run(session: AsyncSession, fence: RunFence) -> AgentRunRecord | None:
    return await session.scalar(
        select(AgentRunRecord)
        .where(
            AgentRunRecord.id == fence.run_id,
            AgentRunRecord.workspace_id == fence.workspace_id,
        )
        .with_for_update()
    )


async def _lock_segment(session: AsyncSession, segment_id: UUID) -> AgentSegmentRecord | None:
    return await session.scalar(
        select(AgentSegmentRecord).where(AgentSegmentRecord.id == segment_id).with_for_update()
    )


async def _lock_active_segment(
    session: AsyncSession,
    run_id: UUID,
) -> AgentSegmentRecord | None:
    return await session.scalar(
        select(AgentSegmentRecord)
        .where(
            AgentSegmentRecord.run_id == run_id,
            AgentSegmentRecord.status == SegmentStatus.RUNNING.value,
        )
        .with_for_update()
    )


def _fence_valid(
    run: AgentRunRecord,
    segment: AgentSegmentRecord | None,
    fence: RunFence,
    database_now: datetime,
) -> bool:
    if (
        run.status != RunStatus.RUNNING.value
        or run.owner != fence.owner
        or run.lease_epoch != fence.lease_epoch
        or run.revision != fence.revision
        or run.lease_expires_at is None
        or run.lease_expires_at <= database_now
        or segment is None
    ):
        return False
    return (
        segment.id == fence.segment_id
        and segment.workspace_id == fence.workspace_id
        and segment.run_id == fence.run_id
        and segment.revision == fence.revision
        and segment.owner == fence.owner
        and segment.lease_epoch == fence.lease_epoch
        and segment.graph_namespace == graph_namespace(fence)
        and segment.status == SegmentStatus.RUNNING.value
        and segment.lease_expires_at is not None
        and segment.lease_expires_at > database_now
    )


async def _lock_active_interaction(
    session: AsyncSession,
    run_id: UUID,
) -> AgentInteractionRecord | None:
    return await session.scalar(
        select(AgentInteractionRecord)
        .where(
            AgentInteractionRecord.run_id == run_id,
            AgentInteractionRecord.status.in_(_ACTIVE_INTERACTION_STATUSES),
        )
        .with_for_update()
    )


async def _lock_preparing_interaction(
    session: AsyncSession,
    run: AgentRunRecord,
    interaction_id: UUID | None,
) -> AgentInteractionRecord | None:
    if interaction_id is None:
        return None
    return await session.scalar(
        select(AgentInteractionRecord)
        .where(
            AgentInteractionRecord.id == interaction_id,
            AgentInteractionRecord.workspace_id == run.workspace_id,
            AgentInteractionRecord.run_id == run.id,
            AgentInteractionRecord.revision == run.revision,
            AgentInteractionRecord.status == InteractionStatus.PREPARING.value,
        )
        .with_for_update()
    )


async def _expire_active_interactions(
    session: AsyncSession,
    run: AgentRunRecord,
    *,
    now: datetime,
    reason: str,
) -> None:
    rows = list(
        (
            await session.scalars(
                select(AgentInteractionRecord)
                .where(
                    AgentInteractionRecord.run_id == run.id,
                    AgentInteractionRecord.status.in_(_ACTIVE_INTERACTION_STATUSES),
                )
                .with_for_update()
            )
        ).all()
    )
    for row in rows:
        row.status = InteractionStatus.EXPIRED.value
        row.state_version += 1
        row.expired_at = now
        await append_run_event(
            session,
            run_id=run.id,
            workspace_id=run.workspace_id,
            revision=run.revision,
            event_type=RunEventType.INTERACTION_EXPIRED,
            payload={"interactionId": str(row.id), "reason": reason},
            occurred_at=now,
        )


async def _defer_run(
    session: AsyncSession,
    *,
    run: AgentRunRecord,
    segment: AgentSegmentRecord,
    now: datetime,
    reason: str,
) -> None:
    await _audit_terminal_outcome(
        session,
        segment_id=segment.id,
        now=now,
        kind=HarnessAuditEventKind.WORKFLOW_FAILED,
        error_code=reason,
        error_type="SegmentDeferred",
    )
    _finish_segment(
        segment,
        status=SegmentStatus.INTERRUPTED,
        outcome_kind=None,
        outcome_doc={"reason": reason},
        safe_reason=reason,
        now=now,
    )
    run.status = RunStatus.QUEUED.value
    run.owner = None
    run.lease_expires_at = None
    run.cancel_requested_at = None
    run.updated_at = now
    run.state_version += 1
    await append_run_event(
        session,
        run_id=run.id,
        workspace_id=run.workspace_id,
        revision=run.revision,
        event_type=RunEventType.RUN_REQUEUED,
        payload={"reason": reason},
        occurred_at=now,
    )


async def _fail_terminal(
    session: AsyncSession,
    *,
    run: AgentRunRecord,
    segment: AgentSegmentRecord,
    now: datetime,
    reason: str,
    write_audit: bool,
    interaction_reason: str | None = None,
) -> None:
    await _expire_active_interactions(
        session,
        run,
        now=now,
        reason=interaction_reason or reason,
    )
    if write_audit:
        await _audit_terminal_outcome(
            session,
            segment_id=segment.id,
            now=now,
            kind=HarnessAuditEventKind.WORKFLOW_FAILED,
            error_code=reason,
            error_type="SegmentFailed",
        )
    _finish_segment(
        segment,
        status=SegmentStatus.FAILED,
        outcome_kind=SegmentOutcomeKind.FAILED,
        outcome_doc={"reason": reason},
        safe_reason=reason,
        now=now,
    )
    _terminate_run(
        run,
        status=RunStatus.FAILED,
        now=now,
        safe_reason=reason,
        result_refs=(),
        result_quality=None,
    )
    await append_run_event(
        session,
        run_id=run.id,
        workspace_id=run.workspace_id,
        revision=run.revision,
        event_type=RunEventType.RUN_TERMINATED,
        payload={"status": RunStatus.FAILED.value},
        occurred_at=now,
    )


def _terminate_run(
    run: AgentRunRecord,
    *,
    status: RunStatus,
    now: datetime,
    safe_reason: str | None,
    result_refs: tuple[ArtifactRef, ...],
    result_quality: str | None,
) -> None:
    run.status = status.value
    run.result_refs = [cast(dict[str, object], ref.model_dump(mode="json")) for ref in result_refs]
    run.result_quality = result_quality
    run.error_code = (
        safe_reason
        if status in {RunStatus.FAILED, RunStatus.DEGRADED}
        else (safe_reason if status is RunStatus.CANCELLED else None)
    )
    run.current_interaction_id = None
    run.owner = None
    run.lease_expires_at = None
    run.cancel_requested_at = None
    run.finished_at = now
    run.updated_at = now
    run.state_version += 1


def _finish_segment(
    segment: AgentSegmentRecord,
    *,
    status: SegmentStatus,
    outcome_kind: SegmentOutcomeKind | None,
    outcome_doc: object,
    safe_reason: str | None,
    now: datetime,
) -> None:
    segment.status = status.value
    segment.outcome_kind = None if outcome_kind is None else outcome_kind.value
    segment.outcome = cast(dict[str, object], outcome_doc)
    segment.safe_reason = safe_reason
    segment.finished_at = now
    segment.lease_expires_at = None


async def _audit_outcome(
    session: AsyncSession,
    *,
    segment_id: UUID,
    outcome: SegmentOutcome,
    now: datetime,
    audit_error_code: str | None,
    audit_error_type: str | None,
) -> Literal["written", "missing_run", "not_started", "already_terminal"]:
    if outcome.kind in {
        SegmentOutcomeKind.COMPLETED,
        SegmentOutcomeKind.WAIT_INPUT,
        SegmentOutcomeKind.WAIT_APPROVAL,
    }:
        kind = HarnessAuditEventKind.WORKFLOW_COMPLETED
        error_code = None
        error_type = None
    elif outcome.kind is SegmentOutcomeKind.DEGRADED:
        kind = HarnessAuditEventKind.WORKFLOW_DEGRADED
        error_code = audit_error_code or outcome.safe_reason
        error_type = audit_error_type or "SegmentDegraded"
    elif outcome.kind is SegmentOutcomeKind.CANCELLED:
        kind = HarnessAuditEventKind.WORKFLOW_FAILED
        error_code = audit_error_code or outcome.safe_reason or "user_cancelled"
        error_type = audit_error_type or "Cancelled"
    else:
        kind = HarnessAuditEventKind.WORKFLOW_FAILED
        error_code = audit_error_code or outcome.safe_reason or "segment_failed"
        error_type = audit_error_type or "SegmentFailed"
    return await _audit_terminal_outcome(
        session,
        segment_id=segment_id,
        now=now,
        kind=kind,
        error_code=error_code,
        error_type=error_type,
    )


async def _audit_terminal_outcome(
    session: AsyncSession,
    *,
    segment_id: UUID,
    now: datetime,
    kind: HarnessAuditEventKind,
    error_code: str | None,
    error_type: str | None,
) -> Literal["written", "missing_run", "not_started", "already_terminal"]:
    harness_run = await session.get(HarnessAuditRunRecord, segment_id)
    if harness_run is None:
        return "missing_run"
    started = await session.scalar(
        select(HarnessAuditEventRecord.sequence).where(
            HarnessAuditEventRecord.run_id == segment_id,
            HarnessAuditEventRecord.sequence == _AUDIT_STARTED_SEQUENCE,
            HarnessAuditEventRecord.event_kind == HarnessAuditEventKind.WORKFLOW_STARTED.value,
        )
    )
    if started is None:
        return "not_started"
    existing = await session.scalar(
        select(HarnessAuditEventRecord.sequence).where(
            HarnessAuditEventRecord.run_id == segment_id,
            HarnessAuditEventRecord.sequence == _AUDIT_TERMINAL_SEQUENCE,
        )
    )
    if existing is not None:
        return "already_terminal"
    duration_ms = max(
        0,
        int((now - require_utc(harness_run.requested_at)).total_seconds() * 1000),
    )
    details = (
        HarnessEventDetails(error_type=error_type)
        if error_type is not None
        else HarnessEventDetails()
    )
    event = HarnessAuditEvent(
        run_id=segment_id,
        sequence=_AUDIT_TERMINAL_SEQUENCE,
        kind=kind,
        occurred_at=now,
        duration_ms=duration_ms,
        error_code=error_code,
        details=details,
    )
    session.add(_audit_event_record(event))
    return "written"


async def _audit_sequence_exists(
    session: AsyncSession,
    run_id: UUID,
    sequence: int,
) -> bool:
    found = await session.scalar(
        select(HarnessAuditEventRecord.sequence).where(
            HarnessAuditEventRecord.run_id == run_id,
            HarnessAuditEventRecord.sequence == sequence,
        )
    )
    return found is not None


def _require_audit_event(
    event: HarnessAuditEvent,
    *,
    sequence: int,
    kind: HarnessAuditEventKind,
) -> None:
    if event.sequence != sequence or event.kind is not kind:
        raise AgentRunError("integrity_violation")


def _committed(state_version: int) -> CompletionDecision:
    return CompletionDecision(
        kind=CompletionDecisionKind.COMMITTED,
        state_version=state_version,
    )


def _lease_lost() -> CompletionDecision:
    return CompletionDecision(
        kind=CompletionDecisionKind.LEASE_LOST,
        safe_reason="lease_lost",
    )


def _audit_run_record(run: HarnessAuditRun) -> HarnessAuditRunRecord:
    return HarnessAuditRunRecord(
        run_id=run.run_id,
        run_kind=run.run_kind.value,
        policy_version=run.policy_version,
        policy_sha256=run.policy_sha256,
        symbol=run.symbol,
        requested_at=run.requested_at,
        initiator_kind=run.initiator_kind.value,
        request_sha256=run.request_sha256,
    )


def _audit_event_record(event: HarnessAuditEvent) -> HarnessAuditEventRecord:
    return HarnessAuditEventRecord(
        run_id=event.run_id,
        sequence=event.sequence,
        event_kind=event.kind.value,
        occurred_at=event.occurred_at,
        duration_ms=event.duration_ms,
        error_code=event.error_code,
        details=event.details.model_dump(mode="json"),
    )


def _audit_evaluation_record(evaluation: HarnessEvaluation) -> HarnessEvaluationRecord:
    return HarnessEvaluationRecord(
        run_id=evaluation.run_id,
        sequence=evaluation.sequence,
        evaluator_name=evaluation.evaluator_name,
        evaluator_version=evaluation.evaluator_version,
        decision=evaluation.decision.value,
        reason_code=evaluation.reason_code,
        evaluated_at=evaluation.evaluated_at,
        details=evaluation.details.model_dump(mode="json"),
    )


def _audit_event_from_record(record: HarnessAuditEventRecord) -> HarnessAuditEvent:
    return HarnessAuditEvent(
        run_id=record.run_id,
        sequence=record.sequence,
        kind=HarnessAuditEventKind(record.event_kind),
        occurred_at=record.occurred_at,
        duration_ms=record.duration_ms,
        error_code=record.error_code,
        details=HarnessEventDetails.model_validate(record.details),
    )


def _evaluation_from_record(record: HarnessEvaluationRecord) -> HarnessEvaluation:
    return HarnessEvaluation(
        run_id=record.run_id,
        sequence=record.sequence,
        evaluator_name=cast(Literal["policy_allowlist"], record.evaluator_name),
        evaluator_version=cast(Literal["1"], record.evaluator_version),
        decision=HarnessEvaluationDecision(record.decision),
        reason_code=record.reason_code,
        evaluated_at=record.evaluated_at,
        details=HarnessEvaluationDetails.model_validate(record.details),
    )


__all__ = ["SqlAlchemyAgentCommitCoordinator"]
