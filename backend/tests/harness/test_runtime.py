# 验证运行注册、策略准入、工作流委托与审计生命周期。
# 记录型及失败型替身观察事件顺序、拒绝原因和异常优先级。
# 审计写入故障必须阻断执行或覆盖工作流故障，安全日志不能携带原始上下文。
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

import pytest
import structlog

import app.harness.runtime as harness_runtime_module
from app.harness.audit import (
    HarnessAuditEvent,
    HarnessAuditEventKind,
    HarnessAuditRun,
    HarnessAuditStorageUnavailableError,
    HarnessAuditTrace,
    HarnessEvaluation,
    HarnessEvaluationDecision,
    HarnessInitiatorKind,
    policy_sha256,
    request_sha256,
)
from app.harness.contracts import (
    HarnessCapability,
    HarnessPolicy,
    HarnessPolicyViolation,
    HarnessRunKind,
    HarnessRunRequest,
)
from app.harness.policy import MARKET_RESEARCH_POLICY
from app.harness.runtime import HarnessRuntime
from app.main import create_app
from app.market.contracts import ContractSymbol

REQUEST = HarnessRunRequest(
    run_id=UUID("00000000-0000-0000-0000-000000000902"),
    kind=HarnessRunKind.MARKET_RESEARCH,
    symbol=ContractSymbol.BTCUSDT,
    requested_at=datetime(2026, 8, 31, 12, tzinfo=UTC),
)


def _empty_calls() -> list[HarnessRunRequest]:
    return []


def _empty_runs() -> list[HarnessAuditRun]:
    return []


def _empty_events() -> list[HarnessAuditEvent]:
    return []


def _empty_evaluations() -> list[HarnessEvaluation]:
    return []


def _empty_sequences() -> list[int]:
    return []


# 按阶段注入审计写入失败，并记录运行、评估和事件，检验失败关闭的执行边界。
@dataclass
class RecordingAuditRepository:
    fail_on: Literal["requested", "evaluation", "started", "failed"] | None = None
    runs: list[HarnessAuditRun] = field(default_factory=_empty_runs)
    events: list[HarnessAuditEvent] = field(default_factory=_empty_events)
    evaluations: list[HarnessEvaluation] = field(default_factory=_empty_evaluations)

    async def create_requested_run(
        self,
        run: HarnessAuditRun,
        event: HarnessAuditEvent,
    ) -> None:
        if self.fail_on == "requested":
            raise HarnessAuditStorageUnavailableError
        self.runs.append(run)
        self.events.append(event)

    async def append_policy_evaluation(
        self,
        evaluation: HarnessEvaluation,
        event: HarnessAuditEvent,
    ) -> None:
        if self.fail_on == "evaluation":
            raise HarnessAuditStorageUnavailableError
        self.evaluations.append(evaluation)
        self.events.append(event)

    async def append_event(self, event: HarnessAuditEvent) -> None:
        if self.fail_on == "started" and event.sequence == 2:
            raise HarnessAuditStorageUnavailableError
        if self.fail_on == "failed" and event.sequence == 3:
            raise HarnessAuditStorageUnavailableError
        self.events.append(event)

    async def get_trace(self, run_id: UUID) -> HarnessAuditTrace | None:
        del run_id
        return None


# 委托执行时读取已保存事件序号，直接观察审计是否先于工作流运行。
@dataclass
class RecordingWorkflow:
    required_capabilities: tuple[HarnessCapability, ...]
    audit_repository: RecordingAuditRepository | None = None
    calls: list[HarnessRunRequest] = field(default_factory=_empty_calls)
    event_sequences_at_call: list[int] = field(default_factory=_empty_sequences)
    kind: HarnessRunKind = HarnessRunKind.MARKET_RESEARCH

    async def run(self, request: HarnessRunRequest) -> str:
        if self.audit_repository is not None:
            self.event_sequences_at_call = [
                event.sequence for event in self.audit_repository.events
            ]
        self.calls.append(request)
        return "completed"


# 记录调用后抛出带敏感正文的异常，区分原异常传播与安全失败事件内容。
@dataclass
class FailingWorkflow(RecordingWorkflow):
    async def run(self, request: HarnessRunRequest) -> str:
        self.calls.append(request)
        raise RuntimeError("delegate exception message must not be logged")


def _workflow(
    required_capabilities: tuple[HarnessCapability, ...] = (
        HarnessCapability.READ_PUBLIC_MARKET,
    ),
    audit_repository: RecordingAuditRepository | None = None,
) -> RecordingWorkflow:
    return RecordingWorkflow(
        required_capabilities=required_capabilities,
        audit_repository=audit_repository,
    )


# 固定耗时时钟使审计持续时间可重复，委托前应已写请求、授权和启动事件。
@pytest.mark.asyncio
async def test_runtime_runs_registered_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    elapsed_ticks = iter((0.0, 1.0))
    monkeypatch.setattr(
        harness_runtime_module,
        "perf_counter",
        lambda: next(elapsed_ticks, 1.0),
    )
    audit = RecordingAuditRepository()
    workflow = _workflow(audit_repository=audit)
    runtime = HarnessRuntime(
        policies=(MARKET_RESEARCH_POLICY,),
        workflows=(workflow,),
        audit_repository=audit,
    )

    assert await runtime.run(REQUEST) == "completed"
    assert audit.runs == [
        HarnessAuditRun(
            run_id=REQUEST.run_id,
            run_kind=REQUEST.kind,
            policy_version=MARKET_RESEARCH_POLICY.version,
            policy_sha256=policy_sha256(MARKET_RESEARCH_POLICY),
            symbol=REQUEST.symbol,
            requested_at=REQUEST.requested_at,
            initiator_kind=HarnessInitiatorKind.MANUAL_API,
            request_sha256=request_sha256(REQUEST, MARKET_RESEARCH_POLICY.version),
        )
    ]
    assert [event.sequence for event in audit.events] == [0, 1, 2]
    assert [event.kind for event in audit.events] == [
        HarnessAuditEventKind.REQUESTED,
        HarnessAuditEventKind.POLICY_AUTHORIZED,
        HarnessAuditEventKind.WORKFLOW_STARTED,
    ]
    assert audit.events[1].duration_ms == 0
    assert audit.evaluations[0].decision is HarnessEvaluationDecision.PASSED
    # 替身在执行瞬间记录的事件位置证明审计先行，最终事件完整不能单独证明此顺序。
    assert workflow.event_sequences_at_call == [0, 1, 2]
    assert workflow.calls == [REQUEST]


# 故意绕过类型检查声明未知能力，运行时仍必须拒绝并保持委托零调用。
@pytest.mark.asyncio
async def test_runtime_rejects_unknown_capability_before_delegation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    elapsed_ticks = iter((0.0, 1.0))
    monkeypatch.setattr(
        harness_runtime_module,
        "perf_counter",
        lambda: next(elapsed_ticks, 1.0),
    )
    workflow = _workflow(
        (
            HarnessCapability.READ_PUBLIC_MARKET,
            cast(HarnessCapability, "private_account"),
        )
    )
    audit = RecordingAuditRepository()
    runtime = HarnessRuntime(
        policies=(MARKET_RESEARCH_POLICY,),
        workflows=(workflow,),
        audit_repository=audit,
    )

    with pytest.raises(HarnessPolicyViolation, match="capability_not_allowed"):
        await runtime.run(REQUEST)

    assert [event.kind for event in audit.events] == [
        HarnessAuditEventKind.REQUESTED,
        HarnessAuditEventKind.POLICY_REJECTED,
    ]
    assert audit.evaluations[0].decision is HarnessEvaluationDecision.REJECTED
    assert audit.evaluations[0].reason_code == "capability_not_allowed"
    assert audit.events[1].duration_ms == 0
    assert workflow.calls == []


@pytest.mark.asyncio
async def test_runtime_rejects_symbol_omitted_by_policy_before_delegation() -> None:
    workflow = _workflow()
    policy = HarnessPolicy(
        version="restricted_test_v1",
        run_kind=HarnessRunKind.MARKET_RESEARCH,
        allowed_symbols=(ContractSymbol.ETHUSDT,),
        allowed_capabilities=(HarnessCapability.READ_PUBLIC_MARKET,),
    )
    audit = RecordingAuditRepository()
    runtime = HarnessRuntime(
        policies=(policy,),
        workflows=(workflow,),
        audit_repository=audit,
    )

    with pytest.raises(HarnessPolicyViolation, match="symbol_not_allowed"):
        await runtime.run(REQUEST)

    assert [event.kind for event in audit.events] == [
        HarnessAuditEventKind.REQUESTED,
        HarnessAuditEventKind.POLICY_REJECTED,
    ]
    assert audit.evaluations[0].decision is HarnessEvaluationDecision.REJECTED
    assert audit.evaluations[0].reason_code == "symbol_not_allowed"
    assert workflow.calls == []


@pytest.mark.asyncio
async def test_runtime_allows_a_ready_symbol_from_the_research_directory() -> None:
    request = REQUEST.model_copy(update={"symbol": "SOLUSDT"})
    workflow = _workflow()
    audit = RecordingAuditRepository()
    runtime = HarnessRuntime(
        policies=(MARKET_RESEARCH_POLICY,),
        workflows=(workflow,),
        audit_repository=audit,
        symbol_authorizer=lambda symbol: _is_ready_directory_symbol(symbol),
    )

    assert await runtime.run(request) == "completed"
    assert workflow.calls == [request]


async def _is_ready_directory_symbol(symbol: str) -> bool:
    return symbol == "SOLUSDT"


@pytest.mark.asyncio
async def test_runtime_rejects_unregistered_kind() -> None:
    audit = RecordingAuditRepository()
    runtime = HarnessRuntime(policies=(), workflows=(), audit_repository=audit)

    with pytest.raises(HarnessPolicyViolation, match="run_kind_not_registered"):
        await runtime.run(REQUEST)

    assert audit.runs[0].policy_version == "unregistered"
    assert len(audit.runs[0].policy_sha256) == 64
    assert [event.kind for event in audit.events] == [
        HarnessAuditEventKind.REQUESTED,
        HarnessAuditEventKind.POLICY_REJECTED,
    ]
    assert audit.evaluations[0].reason_code == "run_kind_not_registered"


def test_runtime_rejects_duplicate_policy_and_workflow_registration() -> None:
    workflow = _workflow()
    audit = RecordingAuditRepository()

    with pytest.raises(ValueError, match="duplicate"):
        HarnessRuntime(
            policies=(MARKET_RESEARCH_POLICY, MARKET_RESEARCH_POLICY),
            workflows=(workflow,),
            audit_repository=audit,
        )

    with pytest.raises(ValueError, match="duplicate"):
        HarnessRuntime(
            policies=(MARKET_RESEARCH_POLICY,),
            workflows=(workflow, workflow),
            audit_repository=audit,
        )


@pytest.mark.asyncio
async def test_runtime_records_safe_workflow_failure_before_reraising() -> None:
    workflow = FailingWorkflow(
        required_capabilities=(HarnessCapability.READ_PUBLIC_MARKET,)
    )
    audit = RecordingAuditRepository()
    runtime = HarnessRuntime(
        policies=(MARKET_RESEARCH_POLICY,),
        workflows=(workflow,),
        audit_repository=audit,
    )

    with pytest.raises(RuntimeError, match="delegate exception message"):
        await runtime.run(REQUEST)

    failed = audit.events[-1]
    assert failed.sequence == 3
    assert failed.kind is HarnessAuditEventKind.WORKFLOW_FAILED
    assert failed.error_code == "workflow_exception"
    assert failed.details.error_type == "RuntimeError"
    assert "delegate exception message" not in failed.model_dump_json()
    assert workflow.calls == [REQUEST]


# 请求、策略评估或启动任一步审计失败，都必须阻断工作流执行。
@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["requested", "evaluation", "started"])
async def test_runtime_fails_closed_when_an_audit_write_fails(
    fail_on: Literal["requested", "evaluation", "started"],
) -> None:
    workflow = _workflow()
    audit = RecordingAuditRepository(fail_on=fail_on)
    runtime = HarnessRuntime(
        policies=(MARKET_RESEARCH_POLICY,),
        workflows=(workflow,),
        audit_repository=audit,
    )

    with pytest.raises(HarnessAuditStorageUnavailableError):
        await runtime.run(REQUEST)

    # 三个写入阶段均复用零调用断言，任何一步失败都不能以无审计方式继续执行。
    assert workflow.calls == []


# 工作流已失败后再模拟终态审计失败，存储错误优先上抛且日志不泄露两个异常正文。
@pytest.mark.asyncio
async def test_runtime_audit_failure_while_recording_workflow_failure_takes_precedence() -> None:
    workflow = FailingWorkflow(
        required_capabilities=(HarnessCapability.READ_PUBLIC_MARKET,)
    )
    audit = RecordingAuditRepository(fail_on="failed")
    runtime = HarnessRuntime(
        policies=(MARKET_RESEARCH_POLICY,),
        workflows=(workflow,),
        audit_repository=audit,
    )

    with structlog.testing.capture_logs() as logs:
        with pytest.raises(HarnessAuditStorageUnavailableError):
            await runtime.run(REQUEST)

    assert workflow.calls == [REQUEST]
    # 只能保留已写成功的前置事件，不能伪称失败终态也已持久化。
    assert [event.sequence for event in audit.events] == [0, 1, 2]
    rendered_logs = repr(logs)
    assert "delegate exception message" not in rendered_logs
    assert "Harness 审计存储不可用" not in rendered_logs
    assert "raw_context" not in rendered_logs
    assert {entry["event"] for entry in logs} == {
        "harness_run_started",
        "harness_run_failed",
        "harness_run_details",
    }
    failed_log = next(entry for entry in logs if entry["event"] == "harness_run_failed")
    assert failed_log["run_id"] == str(REQUEST.run_id)
    assert failed_log["kind"] == REQUEST.kind
    assert failed_log["symbol"] == REQUEST.symbol
    assert failed_log["phase"] == "failed"
    assert failed_log["error_type"] == "RuntimeError"
    assert "duration_ms" in failed_log


@pytest.mark.asyncio
async def test_runtime_logs_only_safe_lifecycle_fields() -> None:
    workflow = FailingWorkflow(
        required_capabilities=(HarnessCapability.READ_PUBLIC_MARKET,)
    )
    audit = RecordingAuditRepository()
    runtime = HarnessRuntime(
        policies=(MARKET_RESEARCH_POLICY,),
        workflows=(workflow,),
        audit_repository=audit,
    )

    with structlog.testing.capture_logs() as logs:
        with pytest.raises(RuntimeError, match="delegate exception message"):
            await runtime.run(REQUEST)

    rendered_logs = repr(logs)
    assert "delegate exception message" not in rendered_logs
    assert "raw_context" not in rendered_logs
    assert {entry["event"] for entry in logs} == {
        "harness_run_started",
        "harness_run_failed",
        "harness_run_details",
    }
    for entry in logs:
        assert entry["run_id"] == str(REQUEST.run_id)
        assert entry["kind"] == REQUEST.kind
        assert entry["symbol"] == REQUEST.symbol
        assert entry["phase"] in {"started", "failed", "details"}
        assert "duration_ms" in entry


# 先装配应用并预热日志缓存，再捕获第二次运行，避免安全日志断言只在冷启动时有效。
@pytest.mark.asyncio
async def test_runtime_logs_are_captured_after_application_logger_cache_is_warmed() -> None:
    create_app()
    workflow = _workflow()
    audit = RecordingAuditRepository()
    runtime = HarnessRuntime(
        policies=(MARKET_RESEARCH_POLICY,),
        workflows=(workflow,),
        audit_repository=audit,
    )

    await runtime.run(REQUEST)

    with structlog.testing.capture_logs() as logs:
        await runtime.run(REQUEST)

    assert {entry["event"] for entry in logs} == {
        "harness_run_started",
        "harness_run_completed",
        "harness_run_details",
    }
