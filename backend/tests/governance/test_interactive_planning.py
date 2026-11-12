# 验证 T07 交互式规划治理类别：策略能力、四阶段审计前缀与异常经协调器收尾。
# 协调器使用纯替身，不连接数据库；真实事务/租约/审计原子性由 persistence 用例证明。
# 本测试不调用真实模型、工具、MCP、私有账户或交易执行。
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.agent_runs.segments import (
    ExecutionContext,
    RunFence,
    SegmentOutcome,
    SegmentOutcomeKind,
)
from app.governance.audit import (
    HarnessAuditEvent,
    HarnessAuditEventKind,
    HarnessAuditRun,
    HarnessEvaluation,
    HarnessEvaluationDecision,
    HarnessEventDetails,
    HarnessInitiatorKind,
)
from app.governance.contracts import GovernanceCapability, GovernanceRunKind
from app.governance.interactive_planning import (
    INTERACTIVE_PLANNING_POLICY,
    GovernedSegmentExecutor,
)
from app.shared.agent_types import VersionRef


# 构造服务端已装配的片段上下文；只使用合成版本引用。
def _context() -> ExecutionContext:
    return ExecutionContext(
        fence=RunFence(
            workspace_id=uuid4(),
            run_id=uuid4(),
            revision=1,
            segment_id=uuid4(),
            owner=uuid4(),
            lease_epoch=2,
        ),
        strategy_ref=VersionRef(version_id=uuid4(), sha256="a" * 64),
        tool_catalog_sha256="b" * 64,
        policy_version=INTERACTIVE_PLANNING_POLICY.version,
        budget_authorization_id=uuid4(),
    )


# 审计协调器替身：只记录适配器请求，证明运行时确实按四阶段协议调用。
class FakeAuditCoordinator:
    def __init__(self) -> None:
        self.requested: list[tuple[RunFence, HarnessAuditRun, HarnessAuditEvent]] = []
        self.evaluations: list[tuple[RunFence, HarnessEvaluation, HarnessAuditEvent]] = []
        self.started: list[tuple[RunFence, HarnessAuditEvent]] = []
        self.failures: list[tuple[RunFence, HarnessAuditEvent]] = []
        self.failure_committed = True

    async def create_requested_run(
        self,
        fence: RunFence,
        run: HarnessAuditRun,
        event: HarnessAuditEvent,
    ) -> None:
        self.requested.append((fence, run, event))

    async def append_policy_evaluation(
        self,
        fence: RunFence,
        evaluation: HarnessEvaluation,
        event: HarnessAuditEvent,
    ) -> None:
        self.evaluations.append((fence, evaluation, event))

    async def append_started_event(self, fence: RunFence, event: HarnessAuditEvent) -> None:
        self.started.append((fence, event))

    async def commit_audit_failure(self, fence: RunFence, event: HarnessAuditEvent) -> bool:
        self.failures.append((fence, event))
        return self.failure_committed

    async def get_audit_trace(self, run_id: UUID) -> None:
        _ = run_id
        return None


class CompletingRunner:
    def __init__(self) -> None:
        self.contexts: list[ExecutionContext] = []

    async def run(self, context: ExecutionContext) -> SegmentOutcome:
        self.contexts.append(context)
        return SegmentOutcome(kind=SegmentOutcomeKind.COMPLETED)


class FailingRunner:
    async def run(self, context: ExecutionContext) -> SegmentOutcome:
        _ = context
        raise RuntimeError("synthetic runner failure")


def test_interactive_planning_policy_registers_only_governed_capabilities() -> None:
    # 新类别必须使用独立序列化值；策略显式列出研究与规划能力，不能默认放行任意工具。
    assert GovernanceRunKind.INTERACTIVE_PLANNING.value == "interactive_planning"
    assert INTERACTIVE_PLANNING_POLICY.run_kind is GovernanceRunKind.INTERACTIVE_PLANNING
    assert INTERACTIVE_PLANNING_POLICY.version == "interactive_planning_v1"
    assert INTERACTIVE_PLANNING_POLICY.allowed_symbols == ("BTCUSDT", "ETHUSDT")
    capabilities = set(INTERACTIVE_PLANNING_POLICY.allowed_capabilities)
    assert {
        GovernanceCapability.READ_PUBLIC_MARKET,
        GovernanceCapability.CALL_RESEARCH_MODEL,
        GovernanceCapability.READ_RESEARCH_KNOWLEDGE,
        GovernanceCapability.READ_STRATEGY_CATALOG,
        GovernanceCapability.EVALUATE_SELECTED_STRATEGY,
        GovernanceCapability.REQUEST_MANUAL_PLANNING,
        GovernanceCapability.USE_REGISTERED_RESEARCH_TOOL,
    } <= capabilities
    assert "access_private_account" not in {item.value for item in capabilities}


@pytest.mark.asyncio
async def test_governed_executor_writes_requested_authorized_and_started_prefix() -> None:
    context = _context()
    coordinator = FakeAuditCoordinator()
    runner = CompletingRunner()
    executor = GovernedSegmentExecutor(
        runner=runner,
        coordinator=coordinator,
        clock=lambda: datetime.now(UTC),
    )

    result = await executor.run(
        context,
        symbol="BTCUSDT",
        requested_at=datetime.now(UTC),
    )

    assert result.terminal_committed is False
    assert result.outcome is not None
    assert result.outcome.kind is SegmentOutcomeKind.COMPLETED
    assert runner.contexts == [context]

    assert len(coordinator.requested) == 1
    _, run, requested_event = coordinator.requested[0]
    assert run.run_id == context.fence.segment_id
    assert run.run_kind is GovernanceRunKind.INTERACTIVE_PLANNING
    assert run.initiator_kind is HarnessInitiatorKind.MANUAL_API
    assert requested_event.kind is HarnessAuditEventKind.REQUESTED
    assert requested_event.sequence == 0

    assert len(coordinator.evaluations) == 1
    _, evaluation, authorized_event = coordinator.evaluations[0]
    assert evaluation.decision is HarnessEvaluationDecision.PASSED
    assert authorized_event.kind is HarnessAuditEventKind.POLICY_AUTHORIZED
    assert authorized_event.sequence == 1

    assert len(coordinator.started) == 1
    _, started_event = coordinator.started[0]
    assert started_event.kind is HarnessAuditEventKind.WORKFLOW_STARTED
    assert started_event.sequence == 2
    assert started_event.details == HarnessEventDetails(
        workflow_kind=GovernanceRunKind.INTERACTIVE_PLANNING
    )


@pytest.mark.asyncio
async def test_governed_executor_routes_runner_failure_through_coordinator() -> None:
    context = _context()
    coordinator = FakeAuditCoordinator()
    executor = GovernedSegmentExecutor(
        runner=FailingRunner(),
        coordinator=coordinator,
        clock=lambda: datetime.now(UTC),
    )

    result = await executor.run(
        context,
        symbol="BTCUSDT",
        requested_at=datetime.now(UTC),
    )

    assert result.terminal_committed is True
    assert result.outcome is None
    assert len(coordinator.failures) == 1
    _, event = coordinator.failures[0]
    assert event.kind is HarnessAuditEventKind.WORKFLOW_FAILED
    assert event.sequence == 3
    assert event.error_code == "workflow_exception"
    assert event.details.error_type == "RuntimeError"


@pytest.mark.asyncio
async def test_governed_executor_reports_uncommitted_failure_for_worker_fallback() -> None:
    # 协调器无法取得合法围栏时不伪造提交；worker 需保留运行中状态交给恢复器。
    context = _context()
    coordinator = FakeAuditCoordinator()
    coordinator.failure_committed = False
    executor = GovernedSegmentExecutor(
        runner=FailingRunner(),
        coordinator=coordinator,
        clock=lambda: datetime.now(UTC),
    )

    with pytest.raises(RuntimeError):
        await executor.run(
            context,
            symbol="BTCUSDT",
            requested_at=datetime.now(UTC),
        )
    assert len(coordinator.failures) == 1


@pytest.mark.asyncio
async def test_governed_executor_does_not_turn_worker_cancellation_into_failure() -> None:
    # 心跳失败/停机取消协程不是业务失败：不得写 workflow_failed，保留 running 交恢复器。
    context = _context()
    coordinator = FakeAuditCoordinator()

    class CancelledRunner:
        async def run(self, context: ExecutionContext) -> SegmentOutcome:
            _ = context
            raise asyncio.CancelledError

    executor = GovernedSegmentExecutor(
        runner=CancelledRunner(),
        coordinator=coordinator,
        clock=lambda: datetime.now(UTC),
    )

    with pytest.raises(asyncio.CancelledError):
        await executor.run(
            context,
            symbol="BTCUSDT",
            requested_at=datetime.now(UTC),
        )
    assert coordinator.failures == []


@pytest.mark.asyncio
async def test_governed_executor_passes_waiting_outcome_without_committing() -> None:
    interaction_id = uuid4()
    context = _context()
    coordinator = FakeAuditCoordinator()

    class WaitingRunner:
        async def run(self, context: ExecutionContext) -> SegmentOutcome:
            _ = context
            return SegmentOutcome(
                kind=SegmentOutcomeKind.WAIT_APPROVAL,
                preparing_interaction_id=interaction_id,
            )

    executor = GovernedSegmentExecutor(
        runner=WaitingRunner(),
        coordinator=coordinator,
        clock=lambda: datetime.now(UTC),
    )
    result = await executor.run(
        context,
        symbol="BTCUSDT",
        requested_at=datetime.now(UTC),
    )
    assert result.outcome is not None
    assert result.outcome.preparing_interaction_id == interaction_id
    assert result.terminal_committed is False
    assert coordinator.failures == []
