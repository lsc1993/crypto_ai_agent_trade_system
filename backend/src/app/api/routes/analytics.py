# 提供已记录交易的筛选绩效与权益曲线接口。
# 查询条件经 AnalyticsFilters 校验，服务计算后映射为十进制响应字段。
# 这里只读取日志统计，不查询真实资金余额，也不对未来表现作推断。
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


# 共享当前模块的 HTTP 字段别名及冻结配置；具体字段限制由各请求/响应子类声明。
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


# EquityPointResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：at、equity、net_pnl；完整契约以下方声明为准。
class EquityPointResponse(_ApiModel):
    at: UtcDateTime
    equity: DecimalValue
    net_pnl: DecimalValue


# TradeCalendarPointResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：at、net_pnl、trade_count；完整契约以下方声明为准。
class TradeCalendarPointResponse(_ApiModel):
    at: UtcDateTime
    net_pnl: DecimalValue
    trade_count: int


# AnalyticsSnapshotResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：net_pnl、win_rate、profit_factor、expectancy、max_drawdown、equity_curve；
# 完整契约以下方声明为准。
class AnalyticsSnapshotResponse(_ApiModel):
    net_pnl: DecimalValue
    win_rate: DecimalValue
    profit_factor: DecimalValue | None
    expectancy: DecimalValue
    max_drawdown: DecimalValue
    equity_curve: tuple[EquityPointResponse, ...]
    trade_calendar: tuple[TradeCalendarPointResponse, ...]
    generated_at: UtcDateTime


# 从应用 state 取得已装配的 performance_analytics_service 依赖；cast 仅服务类型检查，
# 不构造额外资源。
def get_performance_analytics_service(request: Request) -> PerformanceAnalyticsService:
    return cast(PerformanceAnalyticsService, request.app.state.performance_analytics_service)


# 接收路由声明的请求参数，委托 service.get_snapshot，返回 AnalyticsSnapshotResponse。
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


# 按下面的显式字段映射还原 AnalyticsSnapshotResponse，保留可选值与已有顺序；不重新执行业务计算。
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


# 按下面的显式字段映射还原 EquityPointResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_equity_point_response(point: EquityPoint) -> EquityPointResponse:
    return EquityPointResponse(
        at=point.at,
        equity=point.equity,
        net_pnl=point.net_pnl,
    )


# 按下面的显式字段映射还原 TradeCalendarPointResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_calendar_point_response(
    point: TradeCalendarPoint,
) -> TradeCalendarPointResponse:
    return TradeCalendarPointResponse(
        at=point.at,
        net_pnl=point.net_pnl,
        trade_count=point.trade_count,
    )
