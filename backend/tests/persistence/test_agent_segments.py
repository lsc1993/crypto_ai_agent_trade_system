# 使用真实 PostgreSQL 验证 T07 片段租约、四阶段审计与业务终态/等待的原子提交。
# 覆盖领取、心跳、失租迟到写入、消息待应用、用户取消、审计前缀缺失与恢复规则。
# 所有任务输入/材料/产物均为合成值；不调用模型、工具、私有账户或交易执行。
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from app.agent.interactive.ports import SegmentRunner
from app.agent.interactive.worker import InteractiveAgentWorker
from app.agent_runs.contracts import AgentRunError, RunInput, RunStatus
from app.agent_runs.decisions import ControlAction
from app.agent_runs.events import RunEventType
from app.agent_runs.interactions import InteractionDraft, InteractionStatus
from app.agent_runs.messages import MessageKind, UserMessage
from app.agent_runs.segments import (
    CompletionDecisionKind,
    ExecutionContext,
    RunFence,
    SegmentOutcome,
    SegmentOutcomeKind,
    SegmentStatus,
)
from app.governance.audit import (
    HarnessAuditEvent,
    HarnessAuditEventKind,
    HarnessAuditRun,
    HarnessEvaluation,
    HarnessEvaluationDecision,
    HarnessEvaluationDetails,
    HarnessEventDetails,
    HarnessInitiatorKind,
    policy_sha256,
    request_sha256,
)
from app.governance.contracts import GovernanceRunKind, GovernanceRunRequest
from app.governance.interactive_planning import INTERACTIVE_PLANNING_POLICY
from app.infrastructure.persistence.agent_commit_coordinator import (
    SqlAlchemyAgentCommitCoordinator,
)
from app.infrastructure.persistence.agent_interaction_repository import (
    SqlAlchemyAgentInteractionRepository,
    SqlAlchemyAgentMessageRepository,
)
from app.infrastructure.persistence.agent_run_repository import SqlAlchemyAgentRunRepository
from app.infrastructure.persistence.harness_audit_repository import (
    SqlAlchemyHarnessAuditRepository,
)
from app.infrastructure.persistence.models.agent_runs import AgentRunRecord
from app.infrastructure.persistence.models.agent_segments import AgentSegmentRecord
from app.market.contracts import MarketTimeframe
from app.shared.agent_types import ArtifactRef, ProductKey, VersionRef
from tests.conftest import MigratedDatabase


# 构造合成任务输入；策略版本与目标均为测试值，不含真实账户或财务数据。
def _run_input() -> RunInput:
    return RunInput(
        request_id=uuid4(),
        product=ProductKey(
            venue="binance_usdm",
            symbol="BTCUSDT",
            settlement="USDT",
            kind="linear_perpetual",
        ),
        timeframes=(MarketTimeframe.H1,),
        goal="合成研究目标",
        strategy=VersionRef(version_id=uuid4(), sha256="a" * 64),
        parameters={"threshold": "1"},
    )


def _coordinator(
    database: MigratedDatabase,
    *,
    lease_seconds: int = 30,
) -> SqlAlchemyAgentCommitCoordinator:
    return SqlAlchemyAgentCommitCoordinator(
        database.session_factory,
        clock=lambda: datetime.now(UTC),
        lease_seconds=lease_seconds,
    )


def _worker(
    database: MigratedDatabase,
    coordinator: SqlAlchemyAgentCommitCoordinator,
    executor: Any,
) -> InteractiveAgentWorker:
    return InteractiveAgentWorker(
        run_repository=SqlAlchemyAgentRunRepository(database.session_factory),
        segment_repository=coordinator,
        executor=executor,
        owner=uuid4(),
        heartbeat_interval=0.01,
        poll_interval=0.01,
    )


def _executor(
    coordinator: SqlAlchemyAgentCommitCoordinator,
    runner: SegmentRunner,
) -> Any:
    from app.governance.interactive_planning import GovernedSegmentExecutor

    return GovernedSegmentExecutor(
        runner=runner,
        coordinator=coordinator,
        clock=lambda: datetime.now(UTC),
    )


# 完成片段并携带一个不透明产物引用；不内嵌财务或订单内容。
class CompletingRunner:
    def __init__(self, artifact: ArtifactRef | None = None) -> None:
        self.artifact = artifact
        self.calls = 0

    async def run(self, context: ExecutionContext) -> SegmentOutcome:
        _ = context
        self.calls += 1
        refs = (self.artifact,) if self.artifact is not None else ()
        return SegmentOutcome(kind=SegmentOutcomeKind.COMPLETED, artifact_refs=refs)


# 准备一个仅本地可见的 preparing 待办，再返回等待片段结果。
class WaitingRunner:
    def __init__(self, interactions: SqlAlchemyAgentInteractionRepository) -> None:
        self._interactions = interactions
        self.interaction_id: UUID | None = None

    async def run(self, context: ExecutionContext) -> SegmentOutcome:
        draft = InteractionDraft(
            request_id=uuid4(),
            action=ControlAction.ADOPT_MANUAL_PLAN,
            material_hash="c" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            safe_reason="plan_ready",
        )
        interaction = await self._interactions.prepare(context.fence, draft)
        self.interaction_id = interaction.interaction_id
        return SegmentOutcome(
            kind=SegmentOutcomeKind.WAIT_APPROVAL,
            preparing_interaction_id=interaction.interaction_id,
        )


async def _segment(database: MigratedDatabase, run_id: UUID) -> AgentSegmentRecord:
    async with database.session_factory() as session:
        row = await session.scalar(
            select(AgentSegmentRecord).where(AgentSegmentRecord.run_id == run_id)
        )
    assert row is not None
    return row


async def _expire_leases(database: MigratedDatabase, run_id: UUID, segment_id: UUID) -> None:
    # 测试直接推进数据库租约到期时间，避免真实等待 30 秒；仍由仓储的数据库时钟判定合法性。
    past = datetime.now(UTC) - timedelta(seconds=1)
    async with database.session_factory() as session, session.begin():
        await session.execute(
            update(AgentRunRecord).where(AgentRunRecord.id == run_id).values(lease_expires_at=past)
        )
        await session.execute(
            update(AgentSegmentRecord)
            .where(AgentSegmentRecord.id == segment_id)
            .values(lease_expires_at=past)
        )


def _fence_for_segment(segment: AgentSegmentRecord) -> RunFence:
    return RunFence(
        workspace_id=segment.workspace_id,
        run_id=segment.run_id,
        revision=segment.revision,
        segment_id=segment.id,
        owner=segment.owner,
        lease_epoch=segment.lease_epoch,
    )


async def _write_audit_prefix(
    coordinator: SqlAlchemyAgentCommitCoordinator,
    context: ExecutionContext,
    data: RunInput,
    *,
    through: int,
) -> None:
    # through=1 只写 requested；2 加 policy_authorized；3 加 workflow_started。
    now = datetime.now(UTC)
    request = GovernanceRunRequest(
        run_id=context.fence.segment_id,
        kind=GovernanceRunKind.INTERACTIVE_PLANNING,
        symbol=data.product.symbol,
        requested_at=now,
    )
    run = HarnessAuditRun(
        run_id=request.run_id,
        run_kind=request.kind,
        policy_version=INTERACTIVE_PLANNING_POLICY.version,
        policy_sha256=policy_sha256(INTERACTIVE_PLANNING_POLICY),
        symbol=request.symbol,
        requested_at=request.requested_at,
        initiator_kind=HarnessInitiatorKind.MANUAL_API,
        request_sha256=request_sha256(request, INTERACTIVE_PLANNING_POLICY.version),
    )
    await coordinator.create_requested_run(
        context.fence,
        run,
        HarnessAuditEvent(
            run_id=run.run_id,
            sequence=0,
            kind=HarnessAuditEventKind.REQUESTED,
            occurred_at=now,
            duration_ms=0,
            error_code=None,
            details=HarnessEventDetails(workflow_kind=GovernanceRunKind.INTERACTIVE_PLANNING),
        ),
    )
    if through < 2:
        return
    await coordinator.append_policy_evaluation(
        context.fence,
        HarnessEvaluation(
            run_id=run.run_id,
            sequence=0,
            evaluator_name="policy_allowlist",
            evaluator_version="1",
            decision=HarnessEvaluationDecision.PASSED,
            reason_code=None,
            evaluated_at=now,
            details=HarnessEvaluationDetails(
                declared_capability_count=len(INTERACTIVE_PLANNING_POLICY.allowed_capabilities),
                allowed_capability_count=len(INTERACTIVE_PLANNING_POLICY.allowed_capabilities),
            ),
        ),
        HarnessAuditEvent(
            run_id=run.run_id,
            sequence=1,
            kind=HarnessAuditEventKind.POLICY_AUTHORIZED,
            occurred_at=now,
            duration_ms=0,
            error_code=None,
            details=HarnessEventDetails(
                allowed_capability_count=len(INTERACTIVE_PLANNING_POLICY.allowed_capabilities)
            ),
        ),
    )
    if through < 3:
        return
    await coordinator.append_started_event(
        context.fence,
        HarnessAuditEvent(
            run_id=run.run_id,
            sequence=2,
            kind=HarnessAuditEventKind.WORKFLOW_STARTED,
            occurred_at=now,
            duration_ms=0,
            error_code=None,
            details=HarnessEventDetails(workflow_kind=GovernanceRunKind.INTERACTIVE_PLANNING),
        ),
    )


@pytest.mark.asyncio
async def test_worker_commits_completed_segment_with_four_phase_audit(
    migrated_database: MigratedDatabase,
) -> None:
    factory = migrated_database.session_factory
    workspace = uuid4()
    runs = SqlAlchemyAgentRunRepository(factory)
    data = _run_input()
    created = await runs.enqueue(workspace, data)
    coordinator = _coordinator(migrated_database)
    artifact = ArtifactRef(artifact_id=uuid4(), sha256="d" * 64)
    runner = CompletingRunner(artifact)
    worker = _worker(migrated_database, coordinator, _executor(coordinator, runner))

    assert await worker.run_once() is True

    saved = await runs.get(workspace, created.run_id)
    assert saved is not None
    assert saved.status is RunStatus.COMPLETED
    assert saved.result_refs == (artifact,)
    assert saved.result_quality == "complete"
    assert saved.finished_at is not None

    segment = await _segment(migrated_database, created.run_id)
    assert segment.status == SegmentStatus.COMPLETED.value
    assert segment.outcome_kind == SegmentOutcomeKind.COMPLETED.value
    assert segment.finished_at is not None
    assert segment.lease_expires_at is None

    trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(segment.id)
    assert trace is not None
    assert [event.kind for event in trace.events] == [
        HarnessAuditEventKind.REQUESTED,
        HarnessAuditEventKind.POLICY_AUTHORIZED,
        HarnessAuditEventKind.WORKFLOW_STARTED,
        HarnessAuditEventKind.WORKFLOW_COMPLETED,
    ]
    assert (
        sum(event.kind is HarnessAuditEventKind.WORKFLOW_COMPLETED for event in trace.events) == 1
    )

    events = await runs.list_events(workspace, created.run_id, limit=100)
    types = [event.event_type for event in events.items]
    assert RunEventType.RUN_STARTED in types
    assert types[-1] is RunEventType.RUN_TERMINATED
    assert events.items[-1].payload == {"status": "completed"}

    # 旧 worker 在 owner 释放后迟到提交不能覆盖已完成的业务终态。
    stale = await coordinator.commit(
        _fence_for_segment(segment),
        SegmentOutcome(kind=SegmentOutcomeKind.COMPLETED),
    )
    assert stale.kind is CompletionDecisionKind.LEASE_LOST


@pytest.mark.asyncio
async def test_concurrent_claims_assign_exactly_one_owner(
    migrated_database: MigratedDatabase,
) -> None:
    factory = migrated_database.session_factory
    workspace = uuid4()
    runs = SqlAlchemyAgentRunRepository(factory)
    created = await runs.enqueue(workspace, _run_input())
    first = _coordinator(migrated_database)
    second = _coordinator(migrated_database)
    owner_one, owner_two = uuid4(), uuid4()

    results = await asyncio.gather(first.claim(owner_one), second.claim(owner_two))
    contexts = [item for item in results if item is not None]
    assert len(contexts) == 1
    winner = contexts[0]
    assert winner.fence.run_id == created.run_id
    saved = await runs.get(workspace, created.run_id)
    assert saved is not None and saved.status is RunStatus.RUNNING
    assert saved.started_at is not None

    async with factory() as session:
        active_segments = list(
            (
                await session.scalars(
                    select(AgentSegmentRecord).where(
                        AgentSegmentRecord.run_id == created.run_id,
                        AgentSegmentRecord.status == SegmentStatus.RUNNING.value,
                    )
                )
            ).all()
        )
    assert len(active_segments) == 1
    assert active_segments[0].owner == winner.fence.owner
    events = await runs.list_events(workspace, created.run_id, limit=100)
    assert [item.event_type for item in events.items].count(RunEventType.RUN_STARTED) == 1


@pytest.mark.asyncio
async def test_concurrent_commits_commit_once_and_reject_late_owner(
    migrated_database: MigratedDatabase,
) -> None:
    factory = migrated_database.session_factory
    workspace = uuid4()
    runs = SqlAlchemyAgentRunRepository(factory)
    data = _run_input()
    created = await runs.enqueue(workspace, data)
    coordinator = _coordinator(migrated_database)
    context = await coordinator.claim(uuid4())
    assert context is not None
    execution = await _executor(coordinator, CompletingRunner()).run(
        context,
        symbol=data.product.symbol,
        requested_at=datetime.now(UTC),
    )
    assert execution.outcome is not None

    decisions = await asyncio.gather(
        coordinator.commit(context.fence, execution.outcome),
        coordinator.commit(context.fence, execution.outcome),
    )
    assert sorted(decision.kind.value for decision in decisions) == [
        CompletionDecisionKind.COMMITTED.value,
        CompletionDecisionKind.LEASE_LOST.value,
    ]
    saved = await runs.get(workspace, created.run_id)
    assert saved is not None and saved.status is RunStatus.COMPLETED
    trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(context.fence.segment_id)
    assert trace is not None
    assert (
        sum(event.kind is HarnessAuditEventKind.WORKFLOW_COMPLETED for event in trace.events) == 1
    )
    events = await runs.list_events(workspace, created.run_id, limit=100)
    assert [item.event_type for item in events.items].count(RunEventType.RUN_TERMINATED) == 1


@pytest.mark.asyncio
async def test_waiting_commit_publishes_pending_only_after_atomic_commit(
    migrated_database: MigratedDatabase,
) -> None:
    factory = migrated_database.session_factory
    workspace = uuid4()
    runs = SqlAlchemyAgentRunRepository(factory)
    data = _run_input()
    created = await runs.enqueue(workspace, data)
    coordinator = _coordinator(migrated_database)
    interactions = SqlAlchemyAgentInteractionRepository(factory)
    runner = WaitingRunner(interactions)
    owner = uuid4()
    context = await coordinator.claim(owner)
    assert context is not None
    assert context.fence.run_id == created.run_id

    execution = await _executor(coordinator, runner).run(
        context,
        symbol=data.product.symbol,
        requested_at=datetime.now(UTC),
    )
    assert execution.outcome is not None
    assert runner.interaction_id is not None

    before = await interactions.list_interactions(workspace, created.run_id)
    assert len(before) == 1
    assert before[0].status is InteractionStatus.PREPARING
    assert before[0].can_respond is False
    before_run = await runs.get(workspace, created.run_id)
    assert before_run is not None and before_run.status is RunStatus.RUNNING
    assert before_run.current_interaction_id is None
    trace_before = await SqlAlchemyHarnessAuditRepository(factory).get_trace(
        context.fence.segment_id
    )
    assert trace_before is not None and len(trace_before.events) == 3

    decision = await coordinator.commit(context.fence, execution.outcome)
    assert decision.kind is CompletionDecisionKind.COMMITTED

    after = await interactions.list_interactions(workspace, created.run_id)
    assert after[0].status is InteractionStatus.PENDING
    assert after[0].can_respond is True
    assert after[0].published_at is not None
    after_run = await runs.get(workspace, created.run_id)
    assert after_run is not None
    assert after_run.status is RunStatus.WAITING_APPROVAL
    assert after_run.current_interaction_id == runner.interaction_id
    assert after_run.current_interaction_id is not None

    segment = await _segment(migrated_database, created.run_id)
    assert segment.status == SegmentStatus.WAITING_APPROVAL.value
    assert segment.lease_expires_at is None
    trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(segment.id)
    assert trace is not None
    assert trace.events[-1].kind is HarnessAuditEventKind.WORKFLOW_COMPLETED
    events = await runs.list_events(workspace, created.run_id, limit=100)
    assert RunEventType.INTERACTION_PENDING in [item.event_type for item in events.items]
    assert RunEventType.RUN_WAITING in [item.event_type for item in events.items]


@pytest.mark.asyncio
async def test_expired_lease_cannot_commit_and_recovery_requeues(
    migrated_database: MigratedDatabase,
) -> None:
    factory = migrated_database.session_factory
    workspace = uuid4()
    runs = SqlAlchemyAgentRunRepository(factory)
    created = await runs.enqueue(workspace, _run_input())
    coordinator = _coordinator(migrated_database)
    context = await coordinator.claim(uuid4())
    assert context is not None

    assert await coordinator.heartbeat(context.fence) is True
    await _expire_leases(migrated_database, created.run_id, context.fence.segment_id)
    assert await coordinator.heartbeat(context.fence) is False

    stale = await coordinator.commit(
        context.fence,
        SegmentOutcome(kind=SegmentOutcomeKind.COMPLETED),
    )
    assert stale.kind is CompletionDecisionKind.LEASE_LOST
    unchanged = await runs.get(workspace, created.run_id)
    assert unchanged is not None and unchanged.status is RunStatus.RUNNING

    assert await coordinator.recover_expired() == 1
    recovered = await runs.get(workspace, created.run_id)
    assert recovered is not None
    assert recovered.status is RunStatus.QUEUED
    assert recovered.finished_at is None
    segment = await _segment(migrated_database, created.run_id)
    assert segment.status == SegmentStatus.INTERRUPTED.value
    assert segment.lease_expires_at is None
    assert segment.safe_reason == "lease_expired"
    events = await runs.list_events(workspace, created.run_id, limit=100)
    assert events.items[-1].event_type is RunEventType.RUN_REQUEUED
    assert events.items[-1].payload == {"reason": "lease_expired"}

    # 新 owner 接管后，旧 worker 的迟到写入仍必须被拒绝，不能覆盖新片段。
    new_context = await coordinator.claim(uuid4())
    assert new_context is not None
    assert new_context.fence.segment_id != context.fence.segment_id
    late = await coordinator.commit(
        context.fence,
        SegmentOutcome(kind=SegmentOutcomeKind.COMPLETED),
    )
    assert late.kind is CompletionDecisionKind.LEASE_LOST
    after_takeover = await runs.get(workspace, created.run_id)
    assert after_takeover is not None and after_takeover.status is RunStatus.RUNNING


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("through", "expected_event_count", "terminal_error_code"),
    [
        (1, 1, None),
        (2, 2, None),
        (3, 4, "lease_expired"),
    ],
)
async def test_recovery_only_appends_failed_terminal_after_started_prefix(
    migrated_database: MigratedDatabase,
    through: int,
    expected_event_count: int,
    terminal_error_code: str | None,
) -> None:
    factory = migrated_database.session_factory
    workspace = uuid4()
    runs = SqlAlchemyAgentRunRepository(factory)
    data = _run_input()
    created = await runs.enqueue(workspace, data)
    coordinator = _coordinator(migrated_database)
    context = await coordinator.claim(uuid4())
    assert context is not None
    await _write_audit_prefix(coordinator, context, data, through=through)
    await _expire_leases(migrated_database, created.run_id, context.fence.segment_id)

    assert await coordinator.recover_expired() == 1
    trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(context.fence.segment_id)
    assert trace is not None
    assert len(trace.events) == expected_event_count
    if terminal_error_code is None:
        assert all(
            event.kind is not HarnessAuditEventKind.WORKFLOW_FAILED for event in trace.events
        )
    else:
        assert trace.events[-1].kind is HarnessAuditEventKind.WORKFLOW_FAILED
        assert trace.events[-1].error_code == terminal_error_code
    recovered = await runs.get(workspace, created.run_id)
    assert recovered is not None and recovered.status is RunStatus.QUEUED


@pytest.mark.asyncio
async def test_commit_event_failure_rolls_back_business_audit_and_owner(
    migrated_database: MigratedDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = migrated_database.session_factory
    workspace = uuid4()
    runs = SqlAlchemyAgentRunRepository(factory)
    data = _run_input()
    created = await runs.enqueue(workspace, data)
    coordinator = _coordinator(migrated_database)
    context = await coordinator.claim(uuid4())
    assert context is not None
    execution = await _executor(coordinator, CompletingRunner()).run(
        context,
        symbol=data.product.symbol,
        requested_at=datetime.now(UTC),
    )
    assert execution.outcome is not None

    def unavailable(*args: object, **kwargs: object) -> None:
        _ = args, kwargs
        raise AgentRunError("storage_unavailable")

    monkeypatch.setattr(
        "app.infrastructure.persistence.agent_commit_coordinator.append_run_event",
        unavailable,
    )
    with pytest.raises(AgentRunError):
        await coordinator.commit(context.fence, execution.outcome)

    # 事件写入失败必须回滚业务状态、审计序号 3 与 owner 释放，不能留下半提交。
    saved = await runs.get(workspace, created.run_id)
    assert saved is not None and saved.status is RunStatus.RUNNING
    segment = await _segment(migrated_database, created.run_id)
    assert segment.status == SegmentStatus.RUNNING.value
    assert segment.lease_expires_at is not None
    trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(context.fence.segment_id)
    assert trace is not None
    assert [event.kind for event in trace.events] == [
        HarnessAuditEventKind.REQUESTED,
        HarnessAuditEventKind.POLICY_AUTHORIZED,
        HarnessAuditEventKind.WORKFLOW_STARTED,
    ]


@pytest.mark.asyncio
async def test_expired_preparing_material_cannot_be_published_for_review(
    migrated_database: MigratedDatabase,
) -> None:
    factory = migrated_database.session_factory
    workspace = uuid4()
    runs = SqlAlchemyAgentRunRepository(factory)
    data = _run_input()
    created = await runs.enqueue(workspace, data)
    coordinator = _coordinator(migrated_database)
    context = await coordinator.claim(uuid4())
    assert context is not None
    interactions = SqlAlchemyAgentInteractionRepository(factory)

    class ShortLivedWaitingRunner:
        async def run(self, context: ExecutionContext) -> SegmentOutcome:
            draft = InteractionDraft(
                request_id=uuid4(),
                action=ControlAction.ADOPT_MANUAL_PLAN,
                material_hash="c" * 64,
                expires_at=datetime.now(UTC) + timedelta(milliseconds=100),
                safe_reason="plan_ready",
            )
            interaction = await interactions.prepare(context.fence, draft)
            return SegmentOutcome(
                kind=SegmentOutcomeKind.WAIT_APPROVAL,
                preparing_interaction_id=interaction.interaction_id,
            )

    execution = await _executor(coordinator, ShortLivedWaitingRunner()).run(
        context,
        symbol=data.product.symbol,
        requested_at=datetime.now(UTC),
    )
    assert execution.outcome is not None
    await asyncio.sleep(0.2)

    decision = await coordinator.commit(context.fence, execution.outcome)
    assert decision.kind is CompletionDecisionKind.COMMITTED
    saved = await runs.get(workspace, created.run_id)
    assert saved is not None and saved.status is RunStatus.FAILED
    items = await interactions.list_interactions(workspace, created.run_id)
    assert len(items) == 1
    assert items[0].status is InteractionStatus.EXPIRED
    assert items[0].can_respond is False
    trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(context.fence.segment_id)
    assert trace is not None
    assert trace.events[-1].kind is HarnessAuditEventKind.WORKFLOW_FAILED
    assert trace.events[-1].error_code == "review_expired"


@pytest.mark.asyncio
async def test_messages_pending_defers_completion_and_keeps_message_unapplied(
    migrated_database: MigratedDatabase,
) -> None:
    factory = migrated_database.session_factory
    workspace = uuid4()
    runs = SqlAlchemyAgentRunRepository(factory)
    data = _run_input()
    created = await runs.enqueue(workspace, data)
    coordinator = _coordinator(migrated_database)
    context = await coordinator.claim(uuid4())
    assert context is not None
    execution = await _executor(coordinator, CompletingRunner()).run(
        context,
        symbol=data.product.symbol,
        requested_at=datetime.now(UTC),
    )
    messages = SqlAlchemyAgentMessageRepository(factory)
    await messages.record(
        workspace,
        created.run_id,
        UserMessage(request_id=uuid4(), kind=MessageKind.TEXT, text="补充研究上下文"),
    )

    decision = await coordinator.commit(context.fence, execution.outcome)  # type: ignore[arg-type]
    assert decision.kind is CompletionDecisionKind.MESSAGES_PENDING
    saved = await runs.get(workspace, created.run_id)
    assert saved is not None
    assert saved.status is RunStatus.QUEUED
    assert saved.received_message_seq == 1
    assert saved.applied_message_seq == 0
    segment = await _segment(migrated_database, created.run_id)
    assert segment.status == SegmentStatus.INTERRUPTED.value
    trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(context.fence.segment_id)
    assert trace is not None
    assert trace.events[-1].kind is HarnessAuditEventKind.WORKFLOW_FAILED
    assert trace.events[-1].error_code == "messages_pending"
    events = await runs.list_events(workspace, created.run_id, limit=100)
    assert events.items[-1].event_type is RunEventType.RUN_REQUEUED
    assert events.items[-1].payload == {"reason": "messages_pending"}


@pytest.mark.asyncio
async def test_cancel_requested_overrides_completed_outcome(
    migrated_database: MigratedDatabase,
) -> None:
    factory = migrated_database.session_factory
    workspace = uuid4()
    runs = SqlAlchemyAgentRunRepository(factory)
    data = _run_input()
    created = await runs.enqueue(workspace, data)
    coordinator = _coordinator(migrated_database)
    context = await coordinator.claim(uuid4())
    assert context is not None
    execution = await _executor(coordinator, CompletingRunner()).run(
        context,
        symbol=data.product.symbol,
        requested_at=datetime.now(UTC),
    )
    # 先记录未应用消息，再请求取消：最终提交必须取消，而不是被消息水位重排继续执行。
    messages = SqlAlchemyAgentMessageRepository(factory)
    await messages.record(
        workspace,
        created.run_id,
        UserMessage(request_id=uuid4(), kind=MessageKind.TEXT, text="取消前补充上下文"),
    )
    running = await runs.get(workspace, created.run_id)
    assert running is not None
    cancelled_snapshot = await runs.cancel(
        workspace,
        created.run_id,
        request_id=uuid4(),
        expected_version=running.state_version,
    )
    assert cancelled_snapshot.cancel_requested_at is not None
    # 心跳边界也必须检查取消：不再续租，由 worker 立即提交取消终态。
    assert await coordinator.heartbeat(context.fence) is False

    decision = await coordinator.commit(context.fence, execution.outcome)  # type: ignore[arg-type]
    assert decision.kind is CompletionDecisionKind.COMMITTED
    saved = await runs.get(workspace, created.run_id)
    assert saved is not None
    assert saved.status is RunStatus.CANCELLED
    assert saved.cancel_requested_at is None
    assert saved.received_message_seq == 1
    assert saved.applied_message_seq == 0
    events = await runs.list_events(workspace, created.run_id, limit=100)
    assert RunEventType.RUN_REQUEUED not in [item.event_type for item in events.items]
    trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(context.fence.segment_id)
    assert trace is not None
    assert trace.events[-1].kind is HarnessAuditEventKind.WORKFLOW_FAILED
    assert trace.events[-1].error_code == "user_cancelled"


@pytest.mark.asyncio
async def test_segment_schema_rejects_identity_rewrite_unreleased_finish_and_delete(
    migrated_database: MigratedDatabase,
) -> None:
    factory = migrated_database.session_factory
    workspace = uuid4()
    runs = SqlAlchemyAgentRunRepository(factory)
    created = await runs.enqueue(workspace, _run_input())
    coordinator = _coordinator(migrated_database)
    context = await coordinator.claim(uuid4())
    assert context is not None
    segment = await _segment(migrated_database, created.run_id)

    # 身份字段不可改写；每次失败后使用独立事务，避免 aborted transaction 干扰后续断言。
    async with factory() as session, session.begin():
        with pytest.raises(DBAPIError):
            await session.execute(
                update(AgentSegmentRecord)
                .where(AgentSegmentRecord.id == segment.id)
                .values(owner=uuid4())
            )
    async with factory() as session, session.begin():
        with pytest.raises(DBAPIError):
            await session.execute(
                update(AgentSegmentRecord)
                .where(AgentSegmentRecord.id == segment.id)
                .values(
                    status=SegmentStatus.COMPLETED.value,
                    finished_at=datetime.now(UTC),
                )
            )
    async with factory() as session, session.begin():
        with pytest.raises(DBAPIError):
            await session.execute(
                delete(AgentSegmentRecord).where(AgentSegmentRecord.id == segment.id)
            )
    assert (await _segment(migrated_database, created.run_id)).status == SegmentStatus.RUNNING.value


@pytest.mark.asyncio
async def test_completion_without_audit_prefix_fails_closed(
    migrated_database: MigratedDatabase,
) -> None:
    factory = migrated_database.session_factory
    workspace = uuid4()
    runs = SqlAlchemyAgentRunRepository(factory)
    created = await runs.enqueue(workspace, _run_input())
    coordinator = _coordinator(migrated_database)
    context = await coordinator.claim(uuid4())
    assert context is not None

    decision = await coordinator.commit(
        context.fence,
        SegmentOutcome(kind=SegmentOutcomeKind.COMPLETED),
    )
    assert decision.kind is CompletionDecisionKind.COMMITTED
    saved = await runs.get(workspace, created.run_id)
    assert saved is not None
    assert saved.status is RunStatus.FAILED
    assert saved.finished_at is not None
    segment = await _segment(migrated_database, created.run_id)
    assert segment.status == SegmentStatus.FAILED.value
    trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(context.fence.segment_id)
    assert trace is None
    events = await runs.list_events(workspace, created.run_id, limit=100)
    assert events.items[-1].event_type is RunEventType.RUN_TERMINATED
    assert events.items[-1].payload == {"status": "failed"}
