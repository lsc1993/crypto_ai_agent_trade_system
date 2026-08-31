from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from app.harness.audit import (
    HarnessAuditEvent,
    HarnessAuditRun,
    HarnessAuditTrace,
    HarnessEvaluation,
)
from app.harness.contracts import HarnessPolicyViolation
from app.harness.market_research import (
    HarnessedMarketResearchService,
    MarketResearchWorkflow,
)
from app.harness.policy import MARKET_RESEARCH_POLICY
from app.harness.runtime import HarnessRuntime
from app.market.contracts import ContractSymbol
from app.reports.contracts import PersistedAnalysisReport

NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)
RUN_ID = UUID("00000000-0000-0000-0000-000000000903")


def _empty_audit_events() -> list[HarnessAuditEvent]:
    return []


@dataclass
class RecordingAuditRepository:
    events: list[HarnessAuditEvent] = field(default_factory=_empty_audit_events)

    async def create_requested_run(
        self,
        run: HarnessAuditRun,
        event: HarnessAuditEvent,
    ) -> None:
        del run
        self.events.append(event)

    async def append_policy_evaluation(
        self,
        evaluation: HarnessEvaluation,
        event: HarnessAuditEvent,
    ) -> None:
        del evaluation
        self.events.append(event)

    async def append_event(self, event: HarnessAuditEvent) -> None:
        self.events.append(event)

    async def get_trace(self, run_id: UUID) -> HarnessAuditTrace | None:
        del run_id
        return None


class RecordingAgentResearchService:
    def __init__(self) -> None:
        self.calls: list[tuple[ContractSymbol, UUID | None]] = []

    async def generate(
        self,
        symbol: ContractSymbol,
        *,
        analysis_id: UUID | None = None,
    ) -> PersistedAnalysisReport:
        self.calls.append((symbol, analysis_id))
        return cast(PersistedAnalysisReport, SimpleNamespace(analysis_id=analysis_id))


def _service(delegate: RecordingAgentResearchService) -> HarnessedMarketResearchService:
    runtime = HarnessRuntime(
        policies=(MARKET_RESEARCH_POLICY,),
        workflows=(MarketResearchWorkflow(delegate),),
        audit_repository=RecordingAuditRepository(),
    )
    return HarnessedMarketResearchService(
        runtime,
        clock=lambda: NOW,
        new_run_id=lambda: RUN_ID,
    )


@pytest.mark.asyncio
async def test_harnessed_service_passes_its_run_id_to_the_agent_report() -> None:
    delegate = RecordingAgentResearchService()

    report = await _service(delegate).generate(ContractSymbol.BTCUSDT)

    assert delegate.calls == [(ContractSymbol.BTCUSDT, RUN_ID)]
    assert report.analysis_id == RUN_ID


def test_market_research_workflow_declares_the_policy_capabilities() -> None:
    assert (
        MarketResearchWorkflow.required_capabilities
        == MARKET_RESEARCH_POLICY.allowed_capabilities
    )


@pytest.mark.asyncio
async def test_policy_rejection_does_not_call_the_agent_delegate() -> None:
    delegate = RecordingAgentResearchService()
    rejected_policy = MARKET_RESEARCH_POLICY.model_copy(
        update={"allowed_symbols": (ContractSymbol.ETHUSDT,)}
    )
    runtime = HarnessRuntime(
        policies=(rejected_policy,),
        workflows=(MarketResearchWorkflow(delegate),),
        audit_repository=RecordingAuditRepository(),
    )
    service = HarnessedMarketResearchService(
        runtime,
        clock=lambda: NOW,
        new_run_id=lambda: RUN_ID,
    )

    with pytest.raises(HarnessPolicyViolation, match="symbol_not_allowed"):
        await service.generate(ContractSymbol.BTCUSDT)

    assert delegate.calls == []
