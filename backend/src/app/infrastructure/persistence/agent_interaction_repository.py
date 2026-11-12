# 用 PostgreSQL 实现 C5 人工审核、连续消息与取消幂等仓储。
# 顺序固定为：队列锁（唤醒等待任务时）-> 任务行锁 -> 待办/反馈行锁 -> 同事务事件。
# 反馈只记录“用户决定”，不在此采纳计划、追加预算或执行交易；应用由 T07/T13 协调器完成。
# 消息正文不进入安全事件；审核材料只保存引用/指纹，不内嵌完整财务载荷。
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent_runs.contracts import (
    RUNNABLE_CAPACITY,
    RUNNABLE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    AgentRunError,
    RunSnapshot,
    RunStatus,
)
from app.agent_runs.decisions import ControlAction, ProposalDiff
from app.agent_runs.events import RunEventType
from app.agent_runs.interactions import (
    MAX_INTERACTION_LIFETIME_SECONDS,
    FeedbackReceipt,
    HumanInteraction,
    InteractionDecision,
    InteractionDraft,
    InteractionResponse,
    InteractionStatus,
    interaction_open_sha256,
    interaction_response_sha256,
)
from app.agent_runs.messages import (
    MessageReceipt,
    UserMessage,
    user_message_sha256,
)
from app.agent_runs.segments import RunFence
from app.infrastructure.persistence.agent_run_repository import (
    append_run_event,
    load_run_snapshot,
)
from app.infrastructure.persistence.models.agent_interactions import (
    AgentInteractionFeedbackRecord,
    AgentInteractionRecord,
    AgentUserMessageRecord,
)
from app.infrastructure.persistence.models.agent_runs import AgentRunQueueRecord, AgentRunRecord
from app.shared.agent_types import ArtifactRef, require_utc

_ACTIVE_INTERACTION_STATUSES = ("preparing", "pending", "answered")
_PENDING_INTERACTION_STATUSES = ("pending",)
_SAFE_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


# 围栏校验只需要不可变任务身份和取消标记；owner/租约仍由 T07 维护。
@dataclass(frozen=True)
class _FencedRun:
    id: UUID
    workspace_id: UUID
    revision: int
    cancel_requested_at: datetime | None


# SQL 人工审核仓储；clock 只用于审计时间，租约合法性始终由数据库 clock_timestamp() 判定。
class SqlAlchemyAgentInteractionRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return require_utc(self._clock())

    # 准备待办：同请求键幂等，单任务只允许一个 preparing/pending/answered 项。
    # 该操作只写 preparing；T07 coordinator 在图结束后原子发布 pending 并释放 owner。
    async def prepare(self, fence: RunFence, draft: InteractionDraft) -> HumanInteraction:
        now = self._now()
        if draft.expires_at <= now:
            raise AgentRunError("invalid_interaction")
        if draft.expires_at - now > timedelta(seconds=MAX_INTERACTION_LIFETIME_SECONDS):
            raise AgentRunError("invalid_interaction")
        request_sha = interaction_open_sha256(fence, draft)
        try:
            async with self._factory() as session, session.begin():
                run = await _lock_fenced_run(session, fence)
                if run.cancel_requested_at is not None:
                    raise AgentRunError("run_cancelling")
                existing = await session.scalar(
                    select(AgentInteractionRecord).where(
                        AgentInteractionRecord.workspace_id == fence.workspace_id,
                        AgentInteractionRecord.open_request_id == draft.request_id,
                    )
                )
                if existing is not None:
                    if (
                        existing.run_id != fence.run_id
                        or existing.revision != fence.revision
                        or existing.open_request_sha256 != request_sha
                    ):
                        raise AgentRunError("request_conflict")
                    return _human_from_row(existing)
                active = await session.scalar(
                    select(AgentInteractionRecord).where(
                        AgentInteractionRecord.run_id == fence.run_id,
                        AgentInteractionRecord.status.in_(_ACTIVE_INTERACTION_STATUSES),
                    )
                )
                if active is not None:
                    raise AgentRunError("interaction_active")

                interaction_id = uuid4()
                session.add(
                    AgentInteractionRecord(
                        id=interaction_id,
                        workspace_id=fence.workspace_id,
                        run_id=fence.run_id,
                        revision=fence.revision,
                        action=draft.action.value,
                        status=InteractionStatus.PREPARING.value,
                        material_hash=draft.material_hash,
                        state_version=0,
                        expires_at=draft.expires_at,
                        diffs=[
                            cast(dict[str, object], item.model_dump(mode="json"))
                            for item in draft.diffs
                        ],
                        material_refs=[
                            cast(dict[str, object], item.model_dump(mode="json"))
                            for item in draft.material_refs
                        ],
                        safe_reason=draft.safe_reason,
                        open_request_id=draft.request_id,
                        open_request_sha256=request_sha,
                        created_at=now,
                        published_at=None,
                        responded_at=None,
                        applied_at=None,
                        expired_at=None,
                    )
                )
                await session.flush()
                await append_run_event(
                    session,
                    run_id=fence.run_id,
                    workspace_id=fence.workspace_id,
                    revision=fence.revision,
                    event_type=RunEventType.INTERACTION_PREPARED,
                    payload={
                        "interactionId": str(interaction_id),
                        "action": draft.action.value,
                        "revision": fence.revision,
                    },
                    occurred_at=now,
                )
                row = await session.get(AgentInteractionRecord, interaction_id)
                if row is None:
                    raise AgentRunError("integrity_violation")
                return _human_from_row(row)
        except AgentRunError:
            raise
        except IntegrityError:
            raise AgentRunError("request_conflict") from None
        except (ValidationError, ValueError, TypeError) as error:
            raise AgentRunError("integrity_violation") from error
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 记录审核响应：CAS、材料指纹、有效期、单待办和请求幂等均在同一事务核对。
    # 响应只把任务转回 queued，adoption_applied 始终为 False，等待 worker 重验并应用。
    async def respond(
        self,
        workspace_id: UUID,
        run_id: UUID,
        response: InteractionResponse,
    ) -> FeedbackReceipt:
        request_sha = interaction_response_sha256(run_id, response)
        now = self._now()
        receipt: FeedbackReceipt | None = None
        expired = False
        try:
            async with self._factory() as session, session.begin():
                # 唤醒等待任务会增加可运行任务数；与 claim/enqueue 共用队列锁。
                await _lock_queue(session)
                run = await _lock_run(session, workspace_id, run_id)
                existing = await session.scalar(
                    select(AgentInteractionFeedbackRecord).where(
                        AgentInteractionFeedbackRecord.workspace_id == workspace_id,
                        AgentInteractionFeedbackRecord.request_id == response.request_id,
                    )
                )
                if existing is not None:
                    if (
                        existing.run_id != run_id
                        or existing.interaction_id != response.interaction_id
                        or existing.request_sha256 != request_sha
                    ):
                        raise AgentRunError("request_conflict")
                    return await _feedback_receipt(session, run, existing)

                if run.status in {item.value for item in TERMINAL_RUN_STATUSES}:
                    raise AgentRunError("run_terminal")

                interaction = await session.scalar(
                    select(AgentInteractionRecord)
                    .where(
                        AgentInteractionRecord.id == response.interaction_id,
                        AgentInteractionRecord.workspace_id == workspace_id,
                        AgentInteractionRecord.run_id == run_id,
                    )
                    .with_for_update()
                )
                if interaction is None:
                    raise AgentRunError("interaction_not_found")
                if interaction.status == InteractionStatus.EXPIRED.value:
                    raise AgentRunError("review_expired")
                if interaction.status != InteractionStatus.PENDING.value:
                    raise AgentRunError("review_conflict")
                if run.status not in {
                    RunStatus.WAITING_INPUT.value,
                    RunStatus.WAITING_APPROVAL.value,
                }:
                    raise AgentRunError("review_conflict")
                if interaction.revision != run.revision:
                    raise AgentRunError("review_conflict")
                if run.current_interaction_id != interaction.id:
                    raise AgentRunError("review_conflict")
                if response.reviewed_payload_hash != interaction.material_hash:
                    raise AgentRunError("review_conflict")
                if response.expected_state_version != interaction.state_version:
                    raise AgentRunError("review_conflict")
                _validate_decision_for_action(interaction.action, response.decision)

                database_now = await _database_now(session)
                if interaction.expires_at <= database_now:
                    await _expire_interaction_and_run(
                        session,
                        run=run,
                        interaction=interaction,
                        now=now,
                        reason="review_expired",
                    )
                    expired = True
                else:
                    runnable_count = await session.scalar(
                        select(func.count())
                        .select_from(AgentRunRecord)
                        .where(
                            AgentRunRecord.status.in_(
                                [item.value for item in RUNNABLE_RUN_STATUSES]
                            )
                        )
                    )
                    if runnable_count is not None and runnable_count >= RUNNABLE_CAPACITY:
                        raise AgentRunError("queue_full")

                    feedback_id = uuid4()
                    session.add(
                        AgentInteractionFeedbackRecord(
                            id=feedback_id,
                            workspace_id=workspace_id,
                            run_id=run_id,
                            interaction_id=interaction.id,
                            request_id=response.request_id,
                            request_sha256=request_sha,
                            decision=response.decision.value,
                            reviewed_payload_hash=response.reviewed_payload_hash,
                            message=response.message,
                            changes=[
                                cast(dict[str, object], item.model_dump(mode="json"))
                                for item in response.changes
                            ],
                            created_at=now,
                        )
                    )
                    interaction.status = InteractionStatus.ANSWERED.value
                    interaction.state_version += 1
                    interaction.responded_at = now
                    run.status = RunStatus.QUEUED.value
                    run.current_interaction_id = None
                    run.state_version += 1
                    run.updated_at = now
                    await append_run_event(
                        session,
                        run_id=run_id,
                        workspace_id=workspace_id,
                        revision=run.revision,
                        event_type=RunEventType.INTERACTION_RESPONDED,
                        payload={
                            "interactionId": str(interaction.id),
                            "decision": response.decision.value,
                            "revision": run.revision,
                        },
                        occurred_at=now,
                    )
                    await session.flush()
                    feedback = await session.get(
                        AgentInteractionFeedbackRecord,
                        feedback_id,
                    )
                    if feedback is None:
                        raise AgentRunError("integrity_violation")
                    receipt = await _feedback_receipt(session, run, feedback)
            if expired:
                # 过期状态已在事务内提交；响应本身不被接受，抛出稳定原因供 API 映射。
                raise AgentRunError("review_expired")
            if receipt is None:
                raise AgentRunError("integrity_violation")
            return receipt
        except AgentRunError:
            raise
        except IntegrityError:
            raise AgentRunError("request_conflict") from None
        except (ValidationError, ValueError, TypeError) as error:
            raise AgentRunError("integrity_violation") from error
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 只读列出任务历史待办；跨工作台按不存在处理，不泄露任务是否存在。
    async def list_interactions(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> tuple[HumanInteraction, ...]:
        try:
            async with self._factory() as session:
                owned = await session.scalar(
                    select(AgentRunRecord.id).where(
                        AgentRunRecord.id == run_id,
                        AgentRunRecord.workspace_id == workspace_id,
                    )
                )
                if owned is None:
                    raise AgentRunError("run_not_found")
                rows = list(
                    (
                        await session.scalars(
                            select(AgentInteractionRecord)
                            .where(
                                AgentInteractionRecord.workspace_id == workspace_id,
                                AgentInteractionRecord.run_id == run_id,
                            )
                            .order_by(AgentInteractionRecord.created_at)
                        )
                    ).all()
                )
                return tuple(_human_from_row(row) for row in rows)
        except AgentRunError:
            raise
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 过期扫描：只把仍等待且核验已过期的待办与任务置为 expired，并追加安全事件。
    async def expire_due(self, workspace_id: UUID, run_id: UUID) -> int:
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                run = await session.scalar(
                    select(AgentRunRecord)
                    .where(
                        AgentRunRecord.id == run_id,
                        AgentRunRecord.workspace_id == workspace_id,
                    )
                    .with_for_update()
                )
                if run is None:
                    return 0
                if run.status not in {
                    RunStatus.WAITING_INPUT.value,
                    RunStatus.WAITING_APPROVAL.value,
                }:
                    return 0
                interaction = await session.scalar(
                    select(AgentInteractionRecord)
                    .where(
                        AgentInteractionRecord.run_id == run_id,
                        AgentInteractionRecord.status.in_(_PENDING_INTERACTION_STATUSES),
                    )
                    .with_for_update()
                )
                if interaction is None:
                    return 0
                database_now = await _database_now(session)
                if interaction.expires_at > database_now:
                    return 0
                await _expire_interaction_and_run(
                    session,
                    run=run,
                    interaction=interaction,
                    now=now,
                    reason="review_expired",
                )
                await session.flush()
                return 1
        except AgentRunError:
            raise
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None


# SQL 连续消息仓储；消息正文只在本地表保存，事件和回执只暴露序号/水位。
class SqlAlchemyAgentMessageRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return require_utc(self._clock())

    # 记录用户消息：同请求键幂等，序号在任务行锁内单调分配，received 与 applied 分开。
    async def record(
        self,
        workspace_id: UUID,
        run_id: UUID,
        message: UserMessage,
    ) -> MessageReceipt:
        request_sha = user_message_sha256(run_id, message)
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                run = await _lock_run(session, workspace_id, run_id)
                existing = await session.scalar(
                    select(AgentUserMessageRecord).where(
                        AgentUserMessageRecord.workspace_id == workspace_id,
                        AgentUserMessageRecord.request_id == message.request_id,
                    )
                )
                if existing is not None:
                    if existing.run_id != run_id or existing.request_sha256 != request_sha:
                        raise AgentRunError("request_conflict")
                    return _message_receipt(existing, run)
                if run.status in {item.value for item in TERMINAL_RUN_STATUSES}:
                    raise AgentRunError("run_terminal")
                if run.cancel_requested_at is not None:
                    raise AgentRunError("run_cancelling")

                sequence = run.received_message_seq + 1
                message_id = uuid4()
                session.add(
                    AgentUserMessageRecord(
                        id=message_id,
                        workspace_id=workspace_id,
                        run_id=run_id,
                        sequence=sequence,
                        request_id=message.request_id,
                        request_sha256=request_sha,
                        kind=message.kind.value,
                        text=message.text,
                        planning_ref=(
                            cast(dict[str, object], message.planning_ref.model_dump(mode="json"))
                            if message.planning_ref is not None
                            else None
                        ),
                        received_at=now,
                        applied_at=None,
                    )
                )
                run.received_message_seq = sequence
                run.state_version += 1
                run.updated_at = now
                await append_run_event(
                    session,
                    run_id=run_id,
                    workspace_id=workspace_id,
                    revision=run.revision,
                    event_type=RunEventType.MESSAGE_RECORDED,
                    payload={"sequence": sequence},
                    occurred_at=now,
                )
                await session.flush()
                row = await session.get(AgentUserMessageRecord, message_id)
                if row is None:
                    raise AgentRunError("integrity_violation")
                return _message_receipt(row, run)
        except AgentRunError:
            raise
        except IntegrityError:
            raise AgentRunError("request_conflict") from None
        except (ValidationError, ValueError, TypeError) as error:
            raise AgentRunError("integrity_violation") from error
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 应用消息水位：必须由当前 worker 围栏推进，且不能超过已记录水位。
    async def mark_applied(self, fence: RunFence, up_to_seq: int) -> RunSnapshot:
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                run = await _lock_fenced_run(session, fence)
                if run.cancel_requested_at is not None:
                    raise AgentRunError("run_cancelling")
                database_run = await session.get(AgentRunRecord, run.id)
                if database_run is None:
                    raise AgentRunError("integrity_violation")
                if up_to_seq < database_run.applied_message_seq:
                    raise AgentRunError("invalid_message")
                if up_to_seq > database_run.received_message_seq:
                    raise AgentRunError("invalid_message")
                if up_to_seq == database_run.applied_message_seq:
                    snapshot = await load_run_snapshot(
                        session,
                        fence.workspace_id,
                        fence.run_id,
                    )
                    if snapshot is None:
                        raise AgentRunError("integrity_violation")
                    return snapshot
                await session.execute(
                    update(AgentUserMessageRecord)
                    .where(
                        AgentUserMessageRecord.run_id == fence.run_id,
                        AgentUserMessageRecord.sequence <= up_to_seq,
                        AgentUserMessageRecord.applied_at.is_(None),
                    )
                    .values(applied_at=now)
                )
                database_run.applied_message_seq = up_to_seq
                database_run.state_version += 1
                database_run.updated_at = now
                await append_run_event(
                    session,
                    run_id=fence.run_id,
                    workspace_id=fence.workspace_id,
                    revision=database_run.revision,
                    event_type=RunEventType.MESSAGE_APPLIED,
                    payload={"appliedSeq": up_to_seq},
                    occurred_at=now,
                )
                await session.flush()
                snapshot = await load_run_snapshot(
                    session,
                    fence.workspace_id,
                    fence.run_id,
                )
                if snapshot is None:
                    raise AgentRunError("integrity_violation")
                return snapshot
        except AgentRunError:
            raise
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None


# 锁定工作台内任务并返回可变行；跨工作台统一 run_not_found。
async def _lock_run(
    session: AsyncSession,
    workspace_id: UUID,
    run_id: UUID,
) -> AgentRunRecord:
    run = await session.scalar(
        select(AgentRunRecord)
        .where(
            AgentRunRecord.id == run_id,
            AgentRunRecord.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if run is None:
        raise AgentRunError("run_not_found")
    return run


# 锁定并核对 owner/租约代次/修订/数据库当前时刻；失败统一 lease_lost。
async def _lock_fenced_run(session: AsyncSession, fence: RunFence) -> _FencedRun:
    run = await session.scalar(
        select(AgentRunRecord)
        .where(
            AgentRunRecord.id == fence.run_id,
            AgentRunRecord.workspace_id == fence.workspace_id,
        )
        .with_for_update()
    )
    if run is None:
        raise AgentRunError("lease_lost")
    database_now = await _database_now(session)
    if (
        run.status != RunStatus.RUNNING.value
        or run.owner != fence.owner
        or run.lease_epoch != fence.lease_epoch
        or run.revision != fence.revision
        or run.lease_expires_at is None
        or run.lease_expires_at <= database_now
    ):
        raise AgentRunError("lease_lost")
    return _FencedRun(
        id=run.id,
        workspace_id=run.workspace_id,
        revision=run.revision,
        cancel_requested_at=run.cancel_requested_at,
    )


async def _database_now(session: AsyncSession) -> datetime:
    value = await session.scalar(text("SELECT clock_timestamp()"))
    if not isinstance(value, datetime):
        raise AgentRunError("integrity_violation")
    return require_utc(value)


# 队列单例锁与 enqueue/claim 共用；唤醒等待任务前检查可运行容量。
async def _lock_queue(session: AsyncSession) -> None:
    queue = await session.scalar(
        select(AgentRunQueueRecord).where(AgentRunQueueRecord.id == 1).with_for_update()
    )
    if queue is None:
        raise AgentRunError("integrity_violation")


# 用户决定必须与待办动作匹配；澄清只能补充输入，审批动作不能降级为自由文本。
def _validate_decision_for_action(action: str, decision: InteractionDecision) -> None:
    if action == "clarify":
        allowed = {InteractionDecision.PROVIDE_INPUT}
    else:
        allowed = {
            InteractionDecision.APPROVE,
            InteractionDecision.REJECT,
            InteractionDecision.REQUEST_CHANGES,
        }
    if decision not in allowed:
        raise AgentRunError("invalid_response")


# 将待办和等待任务置为过期；用于响应时发现过期及维护扫描，状态已提交后才抛错。
async def _expire_interaction_and_run(
    session: AsyncSession,
    *,
    run: AgentRunRecord,
    interaction: AgentInteractionRecord,
    now: datetime,
    reason: str,
) -> None:
    if not _SAFE_REASON.fullmatch(reason):
        raise AgentRunError("integrity_violation")
    interaction.status = InteractionStatus.EXPIRED.value
    interaction.state_version += 1
    interaction.expired_at = now
    run.status = RunStatus.EXPIRED.value
    run.current_interaction_id = None
    run.finished_at = now
    run.state_version += 1
    run.updated_at = now
    await append_run_event(
        session,
        run_id=run.id,
        workspace_id=run.workspace_id,
        revision=run.revision,
        event_type=RunEventType.INTERACTION_EXPIRED,
        payload={"interactionId": str(interaction.id), "reason": reason},
        occurred_at=now,
    )


# 构造反馈回执；回执状态固定为 recorded，计划采纳必须由后续协调器另行完成。
async def _feedback_receipt(
    session: AsyncSession,
    run: AgentRunRecord,
    feedback: AgentInteractionFeedbackRecord,
) -> FeedbackReceipt:
    interaction = await session.get(AgentInteractionRecord, feedback.interaction_id)
    if interaction is None:
        raise AgentRunError("integrity_violation")
    try:
        return FeedbackReceipt(
            request_id=feedback.request_id,
            interaction_id=feedback.interaction_id,
            run_id=feedback.run_id,
            decision=InteractionDecision(feedback.decision),
            receipt_state="recorded",
            adoption_applied=False,
            run_status=RunStatus(run.status),
            interaction_status=InteractionStatus(interaction.status),
            state_version=run.state_version,
            recorded_at=feedback.created_at,
        )
    except (ValidationError, ValueError) as error:
        raise AgentRunError("integrity_violation") from error


def _message_receipt(
    message: AgentUserMessageRecord,
    run: AgentRunRecord,
) -> MessageReceipt:
    try:
        return MessageReceipt(
            request_id=message.request_id,
            message_id=message.id,
            run_id=message.run_id,
            sequence=message.sequence,
            receipt_state="recorded",
            received_message_seq=run.received_message_seq,
            applied_message_seq=run.applied_message_seq,
            recorded_at=message.received_at,
        )
    except (ValidationError, ValueError) as error:
        raise AgentRunError("integrity_violation") from error


def _human_from_row(row: AgentInteractionRecord) -> HumanInteraction:
    try:
        return HumanInteraction(
            interaction_id=row.id,
            workspace_id=row.workspace_id,
            run_id=row.run_id,
            revision=row.revision,
            action=ControlAction(row.action),
            status=InteractionStatus(row.status),
            material_hash=row.material_hash,
            state_version=row.state_version,
            expires_at=row.expires_at,
            diffs=tuple(ProposalDiff.model_validate(item) for item in row.diffs),
            material_refs=tuple(ArtifactRef.model_validate(item) for item in row.material_refs),
            safe_reason=row.safe_reason,
            created_at=row.created_at,
            published_at=row.published_at,
            responded_at=row.responded_at,
            applied_at=row.applied_at,
            expired_at=row.expired_at,
        )
    except (ValidationError, ValueError, TypeError) as error:
        raise AgentRunError("integrity_violation") from error


__all__ = [
    "SqlAlchemyAgentInteractionRepository",
    "SqlAlchemyAgentMessageRepository",
]
