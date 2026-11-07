# 将手动综合研究包装成带 UTC 时间和独立运行标识的受治理请求。
# 工作流只委托固定研究服务，权限和审计由治理内核的统一运行时执行，结果仍是冻结报告。
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.governance.contracts import (
    GovernanceCapability,
    GovernanceRunKind,
    GovernanceRunRequest,
    GovernedWorkflow,
)
from app.governance.policy import MARKET_RESEARCH_POLICY
from app.governance.runtime import GovernanceRuntime
from app.market.symbols import ResearchSymbol
from app.reports.contracts import PersistedAnalysisReport


# 被协调的研究服务端口；关联标识传入报告链路，避免新建不相干审计运行。
class AgentResearchGenerator(Protocol):
    # 构造请求并交给运行时，准入拒绝时不会先调用底层研究服务。
    async def generate(
        self,
        symbol: Any,
        *,
        analysis_id: UUID | None = None,
    ) -> PersistedAnalysisReport: ...


# 声明综合研究所需能力，并沿用受控运行标识生成报告。
class MarketResearchWorkflow(GovernedWorkflow[PersistedAnalysisReport]):
    kind = GovernanceRunKind.MARKET_RESEARCH
    required_capabilities: tuple[GovernanceCapability, ...] = (
        MARKET_RESEARCH_POLICY.allowed_capabilities
    )

    def __init__(self, service: AgentResearchGenerator) -> None:
        self._service = service

    async def run(self, request: GovernanceRunRequest) -> PersistedAnalysisReport:
        return await self._service.generate(
            request.symbol,
            analysis_id=request.run_id,
        )


# 对外手动入口注入时钟与标识生成器，使准入与审计可确定性测试。
class GovernedMarketResearchService:
    def __init__(
        self,
        runtime: GovernanceRuntime[PersistedAnalysisReport],
        *,
        clock: Callable[[], datetime],
        new_run_id: Callable[[], UUID] = uuid4,
    ) -> None:
        self._runtime = runtime
        self._clock = clock
        self._new_run_id = new_run_id

    # 构造请求并交给运行时，准入拒绝时不会先调用底层研究服务。
    async def generate(self, symbol: ResearchSymbol) -> PersistedAnalysisReport:
        request = GovernanceRunRequest(
            run_id=self._new_run_id(),
            kind=GovernanceRunKind.MARKET_RESEARCH,
            symbol=symbol,
            requested_at=_require_utc(self._clock()),
        )
        return await self._runtime.run(request)


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("治理运行时间必须是 UTC 且带时区")
    return value.astimezone(UTC)
