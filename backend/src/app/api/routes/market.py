from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request

from app.api.routes.market_responses import (
    MarketCandleSeriesResponse,
    MarketDetailResponse,
    MarketSummaryListResponse,
    require_unique,
)
from app.market.contracts import (
    ContractSymbol,
    MarketDetail,
    MarketTimeframe,
)
from app.market.service import MarketQueryService

router = APIRouter(tags=["market"])


def get_market_service(request: Request) -> MarketQueryService:
    return cast(MarketQueryService, request.app.state.market_service)


@router.get("/markets", response_model=MarketSummaryListResponse)
async def list_markets(
    symbols: Annotated[list[ContractSymbol], Query(min_length=1, max_length=2)],
    service: Annotated[MarketQueryService, Depends(get_market_service)],
) -> MarketSummaryListResponse:
    summaries = await service.get_summaries(require_unique(symbols, "symbols"))
    return MarketSummaryListResponse(items=summaries)


@router.get("/market/{symbol}", response_model=MarketDetailResponse)
async def get_market(
    symbol: ContractSymbol,
    timeframes: Annotated[list[MarketTimeframe], Query(min_length=1, max_length=4)],
    service: Annotated[MarketQueryService, Depends(get_market_service)],
) -> MarketDetailResponse:
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
