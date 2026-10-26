# 提供公开研究币种的检查、登记、列举与归档接口。
# 登记交给 SymbolService，研究查询共用 require_research_symbol 检查启用与同步状态。
# 归档修改目录状态并保留历史；研究准入与 ContractSymbol 交易契约相互独立。
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


# 从应用 state 取得已装配的 symbol_repository 依赖；cast 仅服务类型检查，不构造额外资源。
def get_symbol_repository(request: Request) -> SymbolRepository:
    return cast(SymbolRepository, request.app.state.symbol_repository)


# 从应用 state 取得已装配的 symbol_service 依赖；cast 仅服务类型检查，不构造额外资源。
def get_symbol_service(request: Request) -> SymbolService:
    return cast(SymbolService, request.app.state.symbol_service)


# 接收路由声明的请求参数，委托 repository.list，返回 SymbolList。
@router.get("", response_model=SymbolList)
async def list_research_symbols(
    repository: Annotated[SymbolRepository, Depends(get_symbol_repository)],
) -> SymbolList:
    return SymbolList(items=await repository.list())


# 接收路由声明的请求参数，委托 service.check，返回 CheckResult。
@router.post("/check", response_model=CheckResult)
async def check_research_symbol(
    request: SymbolInput,
    service: Annotated[SymbolService, Depends(get_symbol_service)],
) -> CheckResult:
    return await service.check(request.symbol)


# 接收路由声明的请求参数，委托 service.add，返回 ResearchSymbolEntry。
@router.post("", status_code=status.HTTP_201_CREATED, response_model=ResearchSymbolEntry)
async def add_research_symbol(
    request: SymbolInput,
    service: Annotated[SymbolService, Depends(get_symbol_service)],
) -> ResearchSymbolEntry:
    return await service.add(request)


# 接收路由声明的请求参数，委托 repository.archive，返回 ResearchSymbolEntry。
@router.delete("/{symbol}", response_model=ResearchSymbolEntry)
async def archive_research_symbol(
    symbol: ResearchSymbol,
    repository: Annotated[SymbolRepository, Depends(get_symbol_repository)],
) -> ResearchSymbolEntry:
    return await repository.archive(symbol, now=datetime.now(UTC))


# 读取目录项并分别拒绝未登记、归档、尚未就绪状态；require_ready 控制同步门槛。
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
