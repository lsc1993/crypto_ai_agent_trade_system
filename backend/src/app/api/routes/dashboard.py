from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request

from app.api.routes.research_symbols import get_symbol_repository, require_research_symbol
from app.dashboard.service import DashboardService, DashboardSnapshot
from app.market.symbols import ResearchSymbol
from app.symbols.repository import SymbolRepository

router = APIRouter(tags=["dashboard"])


def get_dashboard_service(request: Request) -> DashboardService:
    return cast(DashboardService, request.app.state.dashboard_service)


@router.get("/dashboard", response_model=DashboardSnapshot)
async def get_dashboard(
    service: Annotated[DashboardService, Depends(get_dashboard_service)],
    repository: Annotated[SymbolRepository, Depends(get_symbol_repository)],
    symbol: Annotated[ResearchSymbol | None, Query()] = None,
) -> DashboardSnapshot:
    if symbol is not None:
        await require_research_symbol(repository, symbol)
    return await service.get_snapshot(symbol)
