# 将实时公开行情服务映射到市场摘要和 K 线 HTTP 接口。
# 先校验币种目录准入与查询去重，再调用公开行情服务并转换展示字段。
# ResearchSymbol 是研究范围；接口不会扩大静态交易合约或生成下单请求。
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
from app.market.contracts import MarketDetail, MarketTimeframe
from app.market.service import MarketQueryService
from app.market.symbols import ResearchSymbol
from app.symbols.repository import SymbolRepository

router = APIRouter(tags=["market"])


# 从应用 state 取得已装配的 market_service 依赖；cast 仅服务类型检查，不构造额外资源。
def get_market_service(request: Request) -> MarketQueryService:
    return cast(MarketQueryService, request.app.state.market_service)


# 接收路由声明的请求参数，委托 service.get_summaries，返回 MarketSummaryListResponse。
@router.get("/markets", response_model=MarketSummaryListResponse)
async def list_markets(
    symbols: Annotated[list[ResearchSymbol], Query(min_length=1, max_length=20)],
    service: Annotated[MarketQueryService, Depends(get_market_service)],
    repository: Annotated[SymbolRepository, Depends(get_symbol_repository)],
) -> MarketSummaryListResponse:
    requested = require_unique(symbols, "symbols")
    for symbol in requested:
        await require_research_symbol(repository, symbol)
    summaries = await service.get_summaries(requested)
    return MarketSummaryListResponse(items=summaries)


# 接收路由声明的请求参数，委托 service.get_market，返回 MarketDetailResponse。
@router.get("/market/{symbol}", response_model=MarketDetailResponse)
async def get_market(
    symbol: ResearchSymbol,
    timeframes: Annotated[list[MarketTimeframe], Query(min_length=1, max_length=4)],
    service: Annotated[MarketQueryService, Depends(get_market_service)],
    repository: Annotated[SymbolRepository, Depends(get_symbol_repository)],
) -> MarketDetailResponse:
    await require_research_symbol(repository, symbol)
    detail: MarketDetail = await service.get_market(
        symbol,
        require_unique(timeframes, "timeframes"),
    )
    return MarketDetailResponse(
        summary=detail.summary,
        series=tuple(
            MarketCandleSeriesResponse.from_series(series) for series in detail.series
        ),
    )
