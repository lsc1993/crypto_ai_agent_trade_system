"""HTTP routes for public research-symbol admission and status."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status

from app.market.symbols import ResearchSymbol
from app.symbols.contracts import CheckResult, ResearchSymbolEntry, SymbolInput, SymbolList
from app.symbols.repository import SymbolRepository
from app.symbols.service import SymbolService

router = APIRouter(prefix="/research-symbols", tags=["research-symbols"])


def get_symbol_repository(request: Request) -> SymbolRepository:
    return cast(SymbolRepository, request.app.state.symbol_repository)


def get_symbol_service(request: Request) -> SymbolService:
    return cast(SymbolService, request.app.state.symbol_service)


@router.get("", response_model=SymbolList)
async def list_research_symbols(
    repository: Annotated[SymbolRepository, Depends(get_symbol_repository)],
) -> SymbolList:
    return SymbolList(items=await repository.list())


@router.post("/check", response_model=CheckResult)
async def check_research_symbol(
    request: SymbolInput,
    service: Annotated[SymbolService, Depends(get_symbol_service)],
) -> CheckResult:
    return await service.check(request.symbol)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ResearchSymbolEntry)
async def add_research_symbol(
    request: SymbolInput,
    service: Annotated[SymbolService, Depends(get_symbol_service)],
) -> ResearchSymbolEntry:
    return await service.add(request)


@router.delete("/{symbol}", response_model=ResearchSymbolEntry)
async def archive_research_symbol(
    symbol: ResearchSymbol,
    repository: Annotated[SymbolRepository, Depends(get_symbol_repository)],
) -> ResearchSymbolEntry:
    return await repository.archive(symbol, now=datetime.now(UTC))


async def require_research_symbol(
    repository: SymbolRepository,
    symbol: ResearchSymbol,
    *,
    require_ready: bool = True,
) -> ResearchSymbolEntry:
    entry = await repository.get(symbol)
    if entry is None:
        from app.symbols.contracts import SymbolError

        raise SymbolError("research_symbol_not_found", "研究币对未登记。", 404)
    if not entry.enabled:
        from app.symbols.contracts import SymbolError

        raise SymbolError("research_symbol_archived", "研究币对已删除。", 409)
    if require_ready and not entry.can_research:
        from app.symbols.contracts import SymbolError

        raise SymbolError("research_symbol_sync_pending", "研究币对数据正在同步，请稍后重试。", 409)
    return entry
