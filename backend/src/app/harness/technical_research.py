from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.agent.technical.worker import TechnicalPlanRunExecutor
from app.harness.audit import HarnessAuditRepository
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
from app.reports.technical_plan import TechnicalPlanReport
from app.reports.technical_runs import TechnicalRunLease, TechnicalRunPhase

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


class TechnicalPlanWorkflow:
    kind = HarnessRunKind.TECHNICAL_RESEARCH
    required_capabilities = TECHNICAL_RESEARCH_POLICY.allowed_capabilities

    def __init__(
        self,
        service: TechnicalPlanRunExecutor,
        progress: Callable[[TechnicalRunPhase], Awaitable[None]],
        before_save: Callable[[], Awaitable[TechnicalRunLease | None]],
    ) -> None:
        self._service, self._progress, self._before_save = service, progress, before_save

    async def run(self, request: HarnessRunRequest) -> TechnicalPlanReport:
        return await self._service.generate(
            request.symbol,
            analysis_id=request.run_id,
            progress=self._progress,
            before_save=self._before_save,
        )


class HarnessedTechnicalPlanExecutor:
    def __init__(
        self,
        service: TechnicalPlanRunExecutor,
        *,
        audit: HarnessAuditRepository,
        authorizer: Callable[[ResearchSymbol], Awaitable[bool]],
        clock: Callable[[], datetime],
    ) -> None:
        self._service, self._audit, self._authorizer, self._clock = (
            service,
            audit,
            authorizer,
            clock,
        )

    async def generate(
        self,
        symbol: ResearchSymbol,
        *,
        analysis_id: UUID,
        progress: Callable[[TechnicalRunPhase], Awaitable[None]],
        before_save: Callable[[], Awaitable[TechnicalRunLease | None]],
    ) -> TechnicalPlanReport:
        # Recheck directory admission even for preset symbols; legacy Harness policy
        # admits presets directly, but queued work must respect later archiving.
        runtime = HarnessRuntime[TechnicalPlanReport](
            policies=(TECHNICAL_RESEARCH_POLICY,),
            workflows=(TechnicalPlanWorkflow(self._service, progress, before_save),),
            audit_repository=self._audit,
            symbol_authorizer=self._authorizer,
            require_all_symbols_authorized=True,
        )
        return await runtime.run(
            HarnessRunRequest(
                run_id=analysis_id,
                kind=HarnessRunKind.TECHNICAL_RESEARCH,
                symbol=symbol,
                requested_at=self._clock(),
            )
        )
