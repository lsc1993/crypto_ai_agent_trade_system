# 提供已持久化市场研究数据的只读查询。
# 查询前确认目录准入，随后读取快照及指定周期 K 线并映射响应。
# 读取历史持久化数据不会触发实时采集，不把缓存快照表述为本次新证据。
from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request

from app.api.routes.market_responses import (
    MarketCandleSeriesResponse,
    MarketDetailResponse,
    MarketSummaryListResponse,
    require_unique,
)
from app.api.routes.research_symbols import get_symbol_repository, require_research_symbol
from app.market.contracts import MarketTimeframe
from app.market.research import MarketResearchQueryService
from app.market.symbols import ResearchSymbol
from app.symbols.repository import SymbolRepository

router = APIRouter(prefix="/research", tags=["market-research"])


# 从应用 state 取得已装配的 market_research_service 依赖；cast 仅服务类型检查，不构造额外资源。
def get_market_research_service(request: Request) -> MarketResearchQueryService:
    return cast(MarketResearchQueryService, request.app.state.market_research_service)


# 接收路由声明的请求参数，委托 service.get_summaries，返回 MarketSummaryListResponse。
@router.get("/markets", response_model=MarketSummaryListResponse)
async def list_research_markets(
    symbols: Annotated[list[ResearchSymbol], Query(min_length=1, max_length=20)],
    service: Annotated[MarketResearchQueryService, Depends(get_market_research_service)],
    repository: Annotated[SymbolRepository, Depends(get_symbol_repository)],
) -> MarketSummaryListResponse:
    requested = require_unique(symbols, "symbols")
    for symbol in requested:
        await require_research_symbol(repository, symbol)
    summaries = await service.get_summaries(requested)
    return MarketSummaryListResponse(items=summaries)


# 接收路由声明的请求参数，委托 service.get_market，返回 MarketDetailResponse。
@router.get("/market/{symbol}", response_model=MarketDetailResponse)
async def get_research_market(
    symbol: ResearchSymbol,
    timeframes: Annotated[list[MarketTimeframe], Query(min_length=1, max_length=4)],
    service: Annotated[MarketResearchQueryService, Depends(get_market_research_service)],
    repository: Annotated[SymbolRepository, Depends(get_symbol_repository)],
) -> MarketDetailResponse:
    await require_research_symbol(repository, symbol)
    detail = await service.get_market(symbol, require_unique(timeframes, "timeframes"))
    return MarketDetailResponse(
        summary=detail.summary,
        series=tuple(
            MarketCandleSeriesResponse.from_series(series) for series in detail.series
        ),
    )
