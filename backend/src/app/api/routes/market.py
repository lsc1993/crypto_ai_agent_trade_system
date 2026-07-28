from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AnyHttpUrl, BaseModel, ConfigDict

from app.market.contracts import (
    CandleSeries,
    ContractSymbol,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
    UtcDateTime,
)
from app.market.service import MarketQueryService

router = APIRouter(tags=["market"])


class MarketSummaryListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[MarketSummary, ...]


class MarketNewsItem(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda value: "".join(
            [
                value.split("_")[0],
                *(part.capitalize() for part in value.split("_")[1:]),
            ]
        ),
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    id: str
    title: str
    summary: str
    source: str
    source_url: AnyHttpUrl
    published_at: UtcDateTime
    fetched_at: UtcDateTime
    symbols: tuple[ContractSymbol, ...]


class MarketDetailResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: MarketSummary
    series: tuple[CandleSeries, ...]
    news: tuple[MarketNewsItem, ...] = ()


def get_market_service(request: Request) -> MarketQueryService:
    return cast(MarketQueryService, request.app.state.market_service)


def _require_unique[T](values: list[T], label: str) -> tuple[T, ...]:
    result = tuple(values)
    if len(result) != len(set(result)):
        raise HTTPException(
            status_code=422,
            detail=f"{label} 不能重复",
        )
    return result


@router.get("/markets", response_model=MarketSummaryListResponse)
async def list_markets(
    symbols: Annotated[list[ContractSymbol], Query(min_length=1, max_length=2)],
    service: Annotated[MarketQueryService, Depends(get_market_service)],
) -> MarketSummaryListResponse:
    summaries = await service.get_summaries(_require_unique(symbols, "symbols"))
    return MarketSummaryListResponse(items=summaries)


@router.get("/market/{symbol}", response_model=MarketDetailResponse)
async def get_market(
    symbol: ContractSymbol,
    timeframes: Annotated[list[MarketTimeframe], Query(min_length=1, max_length=4)],
    service: Annotated[MarketQueryService, Depends(get_market_service)],
) -> MarketDetailResponse:
    detail: MarketDetail = await service.get_market(
        symbol,
        _require_unique(timeframes, "timeframes"),
    )
    return MarketDetailResponse(summary=detail.summary, series=detail.series)
