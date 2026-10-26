# 提供工作台看板聚合的 HTTP 入口。
# 显式指定币种时先检查研究准入，再由 DashboardService 组合快照。
# 返回领域聚合结果，不在路由层重新计算风控、执行交易或生成研究报告。
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request

from app.api.routes.research_symbols import get_symbol_repository, require_research_symbol
from app.dashboard.service import DashboardService, DashboardSnapshot
from app.market.symbols import ResearchSymbol
from app.symbols.repository import SymbolRepository

router = APIRouter(tags=["dashboard"])


# 从应用 state 取得已装配的 dashboard_service 依赖；cast 仅服务类型检查，不构造额外资源。
def get_dashboard_service(request: Request) -> DashboardService:
    return cast(DashboardService, request.app.state.dashboard_service)


# 接收路由声明的请求参数，委托 service.get_snapshot，返回 DashboardSnapshot。
@router.get("/dashboard", response_model=DashboardSnapshot)
async def get_dashboard(
    service: Annotated[DashboardService, Depends(get_dashboard_service)],
    repository: Annotated[SymbolRepository, Depends(get_symbol_repository)],
    symbol: Annotated[ResearchSymbol | None, Query()] = None,
) -> DashboardSnapshot:
    if symbol is not None:
        await require_research_symbol(repository, symbol)
    return await service.get_snapshot(symbol)
