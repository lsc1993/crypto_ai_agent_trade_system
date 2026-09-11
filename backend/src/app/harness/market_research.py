from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.harness.contracts import (
    HarnessCapability,
    HarnessRunKind,
    HarnessRunRequest,
    HarnessWorkflow,
)
from app.harness.policy import MARKET_RESEARCH_POLICY
from app.harness.runtime import HarnessRuntime
from app.market.symbols import ResearchSymbol
from app.reports.contracts import PersistedAnalysisReport


class AgentResearchGenerator(Protocol):
    async def generate(
        self,
        symbol: Any,
        *,
        analysis_id: UUID | None = None,
    ) -> PersistedAnalysisReport: ...


class MarketResearchWorkflow(HarnessWorkflow[PersistedAnalysisReport]):
    kind = HarnessRunKind.MARKET_RESEARCH
    required_capabilities: tuple[HarnessCapability, ...] = (
        MARKET_RESEARCH_POLICY.allowed_capabilities
    )

    def __init__(self, service: AgentResearchGenerator) -> None:
        self._service = service

    async def run(self, request: HarnessRunRequest) -> PersistedAnalysisReport:
        return await self._service.generate(
            request.symbol,
            analysis_id=request.run_id,
        )


class HarnessedMarketResearchService:
    def __init__(
        self,
        runtime: HarnessRuntime[PersistedAnalysisReport],
        *,
        clock: Callable[[], datetime],
        new_run_id: Callable[[], UUID] = uuid4,
    ) -> None:
        self._runtime = runtime
        self._clock = clock
        self._new_run_id = new_run_id

    async def generate(self, symbol: ResearchSymbol) -> PersistedAnalysisReport:
        request = HarnessRunRequest(
            run_id=self._new_run_id(),
            kind=HarnessRunKind.MARKET_RESEARCH,
            symbol=symbol,
            requested_at=_require_utc(self._clock()),
        )
        return await self._runtime.run(request)


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("Harness 运行时间必须是 UTC 且带时区")
    return value.astimezone(UTC)
