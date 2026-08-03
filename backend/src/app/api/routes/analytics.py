from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, ValidationError

from app.market.contracts import ContractSymbol, DecimalValue, UtcDateTime
from app.trades.analytics import PerformanceAnalyticsService
from app.trades.contracts import (
    AnalyticsFilters,
    AnalyticsSnapshot,
    EquityPoint,
    TradeCalendarPoint,
    TradeDirection,
    TradeHorizon,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


class _ApiModel(BaseModel):
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


class EquityPointResponse(_ApiModel):
    at: UtcDateTime
    equity: DecimalValue
    net_pnl: DecimalValue


class TradeCalendarPointResponse(_ApiModel):
    at: UtcDateTime
    net_pnl: DecimalValue
    trade_count: int


class AnalyticsSnapshotResponse(_ApiModel):
    net_pnl: DecimalValue
    win_rate: DecimalValue
    profit_factor: DecimalValue | None
    expectancy: DecimalValue
    max_drawdown: DecimalValue
    equity_curve: tuple[EquityPointResponse, ...]
    trade_calendar: tuple[TradeCalendarPointResponse, ...]
    generated_at: UtcDateTime


def get_performance_analytics_service(request: Request) -> PerformanceAnalyticsService:
    return cast(PerformanceAnalyticsService, request.app.state.performance_analytics_service)


@router.get("", response_model=AnalyticsSnapshotResponse)
async def get_analytics_snapshot(
    service: Annotated[
        PerformanceAnalyticsService,
        Depends(get_performance_analytics_service),
    ],
    symbol: ContractSymbol | None = None,
    direction: TradeDirection | None = None,
    horizon: TradeHorizon | None = None,
    label: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    from_at: Annotated[UtcDateTime | None, Query(alias="from")] = None,
    to_at: Annotated[UtcDateTime | None, Query(alias="to")] = None,
) -> AnalyticsSnapshotResponse:
    filters = _validate_filters(
        symbol=symbol,
        direction=direction,
        horizon=horizon,
        label=label,
        from_at=from_at,
        to_at=to_at,
    )
    return _to_response(await service.get_snapshot(filters))


def _validate_filters(**values: object) -> AnalyticsFilters:
    try:
        return AnalyticsFilters.model_validate(values)
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error


def _to_response(snapshot: AnalyticsSnapshot) -> AnalyticsSnapshotResponse:
    return AnalyticsSnapshotResponse(
        net_pnl=snapshot.net_pnl,
        win_rate=snapshot.win_rate,
        profit_factor=snapshot.profit_factor,
        expectancy=snapshot.expectancy,
        max_drawdown=snapshot.max_drawdown,
        equity_curve=tuple(
            _to_equity_point_response(point) for point in snapshot.equity_curve
        ),
        trade_calendar=tuple(
            _to_calendar_point_response(point) for point in snapshot.trade_calendar
        ),
        generated_at=snapshot.generated_at,
    )


def _to_equity_point_response(point: EquityPoint) -> EquityPointResponse:
    return EquityPointResponse(
        at=point.at,
        equity=point.equity,
        net_pnl=point.net_pnl,
    )


def _to_calendar_point_response(
    point: TradeCalendarPoint,
) -> TradeCalendarPointResponse:
    return TradeCalendarPointResponse(
        at=point.at,
        net_pnl=point.net_pnl,
        trade_count=point.trade_count,
    )
