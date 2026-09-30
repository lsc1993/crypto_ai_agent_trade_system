from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.harness.contracts import (
    HarnessCapability,
    HarnessPolicy,
    HarnessRunKind,
    HarnessRunRequest,
)
from app.harness.runtime import HarnessRuntime
from app.market.symbols import ResearchSymbol
from app.reports.contracts import ReportStorageUnavailableError
from app.reports.technical import TechnicalReport

TECHNICAL_RESEARCH_POLICY = HarnessPolicy(
    version="technical_research_v1",
    run_kind=HarnessRunKind.TECHNICAL_RESEARCH,
    allowed_symbols=("BTCUSDT", "ETHUSDT"),
    symbol_admission="research_directory",
    allowed_capabilities=(
        HarnessCapability.READ_PUBLIC_MARKET,
        HarnessCapability.CALL_RESEARCH_MODEL,
        HarnessCapability.PERSIST_IMMUTABLE_REPORT,
    ),
)


class TechnicalGenerator(Protocol):
    async def generate(self, symbol: ResearchSymbol, *, analysis_id: UUID) -> TechnicalReport: ...


class TechnicalResearchWorkflow:
    kind = HarnessRunKind.TECHNICAL_RESEARCH
    required_capabilities = TECHNICAL_RESEARCH_POLICY.allowed_capabilities

    def __init__(self, service: TechnicalGenerator) -> None:
        self._service = service

    async def run(self, request: HarnessRunRequest) -> TechnicalReport:
        return await self._service.generate(request.symbol, analysis_id=request.run_id)


class TechnicalReportGenerator(Protocol):
    async def generate(self, symbol: ResearchSymbol) -> TechnicalReport: ...


class UnavailableTechnicalResearchService:
    async def generate(self, symbol: ResearchSymbol) -> TechnicalReport:
        raise ReportStorageUnavailableError("技术研究报告存储不可用")


class HarnessedTechnicalResearchService:
    def __init__(
        self, runtime: HarnessRuntime[TechnicalReport], *, clock: Callable[[], datetime]
    ) -> None:
        self._runtime, self._clock = runtime, clock

    async def generate(self, symbol: ResearchSymbol) -> TechnicalReport:
        return await self._runtime.run(
            HarnessRunRequest(
                run_id=uuid4(),
                kind=HarnessRunKind.TECHNICAL_RESEARCH,
                symbol=symbol,
                requested_at=self._clock(),
            )
        )
