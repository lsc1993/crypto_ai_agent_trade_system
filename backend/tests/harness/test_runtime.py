from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
import structlog

from app.harness.contracts import (
    HarnessCapability,
    HarnessPolicy,
    HarnessPolicyViolation,
    HarnessRunKind,
    HarnessRunRequest,
)
from app.harness.policy import MARKET_RESEARCH_POLICY
from app.harness.runtime import HarnessRuntime
from app.market.contracts import ContractSymbol

REQUEST = HarnessRunRequest(
    run_id=UUID("00000000-0000-0000-0000-000000000902"),
    kind=HarnessRunKind.MARKET_RESEARCH,
    symbol=ContractSymbol.BTCUSDT,
    requested_at=datetime(2026, 8, 31, 12, tzinfo=UTC),
)


def _empty_calls() -> list[HarnessRunRequest]:
    return []


@dataclass
class RecordingWorkflow:
    required_capabilities: tuple[HarnessCapability, ...]
    calls: list[HarnessRunRequest] = field(default_factory=_empty_calls)
    kind: HarnessRunKind = HarnessRunKind.MARKET_RESEARCH

    async def run(self, request: HarnessRunRequest) -> str:
        self.calls.append(request)
        return "completed"


@dataclass
class FailingWorkflow(RecordingWorkflow):
    async def run(self, request: HarnessRunRequest) -> str:
        self.calls.append(request)
        raise RuntimeError("delegate exception message must not be logged")


def _workflow(
    required_capabilities: tuple[HarnessCapability, ...] = (
        HarnessCapability.READ_PUBLIC_MARKET,
    ),
) -> RecordingWorkflow:
    return RecordingWorkflow(required_capabilities=required_capabilities)


@pytest.mark.asyncio
async def test_runtime_runs_registered_workflow() -> None:
    workflow = _workflow()
    runtime = HarnessRuntime(
        policies=(MARKET_RESEARCH_POLICY,),
        workflows=(workflow,),
    )

    assert await runtime.run(REQUEST) == "completed"
    assert workflow.calls == [REQUEST]


@pytest.mark.asyncio
async def test_runtime_rejects_unknown_capability_before_delegation() -> None:
    workflow = _workflow(
        (
            HarnessCapability.READ_PUBLIC_MARKET,
            cast(HarnessCapability, "private_account"),
        )
    )
    runtime = HarnessRuntime(
        policies=(MARKET_RESEARCH_POLICY,),
        workflows=(workflow,),
    )

    with pytest.raises(HarnessPolicyViolation, match="capability_not_allowed"):
        await runtime.run(REQUEST)

    assert workflow.calls == []


@pytest.mark.asyncio
async def test_runtime_rejects_symbol_omitted_by_policy_before_delegation() -> None:
    workflow = _workflow()
    policy = HarnessPolicy(
        run_kind=HarnessRunKind.MARKET_RESEARCH,
        allowed_symbols=(ContractSymbol.ETHUSDT,),
        allowed_capabilities=(HarnessCapability.READ_PUBLIC_MARKET,),
    )
    runtime = HarnessRuntime(policies=(policy,), workflows=(workflow,))

    with pytest.raises(HarnessPolicyViolation, match="symbol_not_allowed"):
        await runtime.run(REQUEST)

    assert workflow.calls == []


@pytest.mark.asyncio
async def test_runtime_rejects_unregistered_kind() -> None:
    runtime = HarnessRuntime(policies=(), workflows=())

    with pytest.raises(HarnessPolicyViolation, match="run_kind_not_registered"):
        await runtime.run(REQUEST)


def test_runtime_rejects_duplicate_policy_and_workflow_registration() -> None:
    workflow = _workflow()

    with pytest.raises(ValueError, match="duplicate"):
        HarnessRuntime(
            policies=(MARKET_RESEARCH_POLICY, MARKET_RESEARCH_POLICY),
            workflows=(workflow,),
        )

    with pytest.raises(ValueError, match="duplicate"):
        HarnessRuntime(
            policies=(MARKET_RESEARCH_POLICY,),
            workflows=(workflow, workflow),
        )


@pytest.mark.asyncio
async def test_runtime_logs_only_safe_lifecycle_fields() -> None:
    workflow = FailingWorkflow(
        required_capabilities=(HarnessCapability.READ_PUBLIC_MARKET,)
    )
    runtime = HarnessRuntime(
        policies=(MARKET_RESEARCH_POLICY,),
        workflows=(workflow,),
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
