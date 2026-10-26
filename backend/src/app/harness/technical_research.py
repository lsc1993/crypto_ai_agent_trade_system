# 提供技术 v1 同步和 v2 队列执行的受控包装，技术策略不要求新闻读取能力。
# 队列执行重新核对全部标的的目录准入，尊重提交后归档；审计与报告共用运行标识。
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


# 技术 v1 固定服务端口，输入受控运行标识并返回冻结技术报告。
class TechnicalGenerator(Protocol):
    async def generate(self, symbol: ResearchSymbol, *, analysis_id: UUID) -> TechnicalReport: ...


# 同步技术工作流只委托技术服务，其能力与独立技术策略一致。
class TechnicalResearchWorkflow:
    kind = HarnessRunKind.TECHNICAL_RESEARCH
    required_capabilities = TECHNICAL_RESEARCH_POLICY.allowed_capabilities

    def __init__(self, service: TechnicalGenerator) -> None:
        self._service = service

    async def run(self, request: HarnessRunRequest) -> TechnicalReport:
        return await self._service.generate(request.symbol, analysis_id=request.run_id)


# 同步调用方的简化报告生成协议，内部标识由受控包装建立。
class TechnicalReportGenerator(Protocol):
    async def generate(self, symbol: ResearchSymbol) -> TechnicalReport: ...


# 未装配存储时明确抛安全错误，不返回伪成功报告。
class UnavailableTechnicalResearchService:
    async def generate(self, symbol: ResearchSymbol) -> TechnicalReport:
        raise ReportStorageUnavailableError("技术研究报告存储不可用")


# 为同步技术服务建立请求并执行策略准入和审计。
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


# 把队列进度与保存前租约回调传递给固定 v2 研究服务。
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


# 每次队列执行创建受限运行时，预置标的也必须通过当前目录授权。
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
