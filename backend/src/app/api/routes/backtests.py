# 把确定性回测请求与结果映射为 HTTP 契约。
# 字符串资金输入经 BacktestRequest 二次校验，服务运行后映射指标和审计事件。
# 响应金额按十八位小数量化并输出字符串；API 不调用真实执行接口。
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PlainSerializer,
    StrictStr,
    ValidationError,
)

from app.market.contracts import ContractSymbol, MarketTimeframe, UtcDateTime
from app.research.backtests.contracts import (
    BacktestAuditEvent,
    BacktestClosedTrade,
    BacktestFilters,
    BacktestPage,
    BacktestRequest,
    BacktestRunStatus,
    BacktestSummary,
    PersistedBacktestRun,
)
from app.research.backtests.service import BacktestService

router = APIRouter(prefix="/backtests", tags=["backtests"])

_RESPONSE_DECIMAL_QUANTUM = Decimal("0.000000000000000001")


# 在局部 Decimal 上下文扩大精度，再按十八位和 HALF_EVEN 量化，零规范化为字符串 0。
def _serialize_backtest_decimal(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = max(
            context.prec,
            len(value.as_tuple().digits),
            value.adjusted() + 19,
        )
        normalized = value.quantize(
            _RESPONSE_DECIMAL_QUANTUM,
            rounding=ROUND_HALF_EVEN,
        )
    if normalized.is_zero():
        return "0"
    return format(normalized.normalize(), "f")


BacktestDecimalValue = Annotated[
    Decimal,
    PlainSerializer(_serialize_backtest_decimal, return_type=str, when_used="json"),
]


# 共享当前模块的 HTTP 字段别名及冻结配置；具体字段限制由各请求/响应子类声明。
class _ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda value: "".join(
            [
                value.split("_")[0],
                *(part.capitalize() for part in value.split("_")[1:]),
            ]
        ),
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


# BacktestCreateRequest 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：symbol、timeframe、start_at、end_at、initial_cash；完整契约以下方声明为准。
class BacktestCreateRequest(_ApiModel):
    symbol: ContractSymbol
    timeframe: MarketTimeframe
    start_at: UtcDateTime
    end_at: UtcDateTime
    initial_cash: StrictStr


# BacktestRiskConfigResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：max_exposure_fraction、stop_loss_fraction、daily_loss_fraction、
# max_drawdown_fraction、cooldown_candles、quantity_increment；完整契约以下方声明为准。
class BacktestRiskConfigResponse(_ApiModel):
    max_exposure_fraction: BacktestDecimalValue
    stop_loss_fraction: BacktestDecimalValue
    daily_loss_fraction: BacktestDecimalValue
    max_drawdown_fraction: BacktestDecimalValue
    cooldown_candles: int
    quantity_increment: BacktestDecimalValue


# BacktestExecutionConfigResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：fee_rate、slippage_rate、fill_ratio；完整契约以下方声明为准。
class BacktestExecutionConfigResponse(_ApiModel):
    fee_rate: BacktestDecimalValue
    slippage_rate: BacktestDecimalValue
    fill_ratio: BacktestDecimalValue


# BacktestSummaryResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：initial_cash、final_equity、net_pnl、realized_pnl、unrealized_pnl、return_fraction；
# 完整契约以下方声明为准。
class BacktestSummaryResponse(_ApiModel):
    initial_cash: BacktestDecimalValue
    final_equity: BacktestDecimalValue
    net_pnl: BacktestDecimalValue
    realized_pnl: BacktestDecimalValue
    unrealized_pnl: BacktestDecimalValue
    return_fraction: BacktestDecimalValue
    max_drawdown_fraction: BacktestDecimalValue
    win_rate: BacktestDecimalValue
    profit_factor: BacktestDecimalValue | None
    closed_trade_count: int
    fill_count: int
    rejection_count: int
    open_position_quantity: BacktestDecimalValue
    candle_count: int
    snapshot_hash: str


# BacktestClosedTradeResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：opened_at、closed_at、quantity、net_pnl；完整契约以下方声明为准。
class BacktestClosedTradeResponse(_ApiModel):
    opened_at: UtcDateTime
    closed_at: UtcDateTime
    quantity: BacktestDecimalValue
    net_pnl: BacktestDecimalValue


# BacktestAuditEventResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：sequence、kind、occurred_at、candle_sequence、idempotency_key、payload；
# 完整契约以下方声明为准。
class BacktestAuditEventResponse(_ApiModel):
    sequence: int
    kind: str
    occurred_at: UtcDateTime
    candle_sequence: int | None
    idempotency_key: str | None
    payload: dict[str, JsonValue]


# BacktestRunSummaryResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：id、status、symbol、timeframe、start_at、end_at；完整契约以下方声明为准。
class BacktestRunSummaryResponse(_ApiModel):
    id: UUID
    status: BacktestRunStatus
    symbol: ContractSymbol
    timeframe: MarketTimeframe
    start_at: UtcDateTime
    end_at: UtcDateTime
    initial_cash: BacktestDecimalValue
    strategy_id: str
    strategy_version: str
    risk_config: BacktestRiskConfigResponse
    execution_config: BacktestExecutionConfigResponse
    created_at: UtcDateTime
    finished_at: UtcDateTime | None
    summary: BacktestSummaryResponse | None
    failure_code: str | None
    failure_message: str | None


# BacktestRunDetailResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：closed_trades、events；完整契约以下方声明为准。
class BacktestRunDetailResponse(BacktestRunSummaryResponse):
    closed_trades: tuple[BacktestClosedTradeResponse, ...]
    events: tuple[BacktestAuditEventResponse, ...]


# BacktestPageResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：items、page、page_size、total；完整契约以下方声明为准。
class BacktestPageResponse(_ApiModel):
    items: tuple[BacktestRunSummaryResponse, ...]
    page: int
    page_size: int = Field(serialization_alias="page_size")
    total: int


# 从应用 state 取得已装配的 backtest_service 依赖；cast 仅服务类型检查，不构造额外资源。
def get_backtest_service(request: Request) -> BacktestService:
    return cast(BacktestService, request.app.state.backtest_service)


# 接收路由声明的请求参数，委托 service.start，返回 BacktestRunDetailResponse。
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=BacktestRunDetailResponse,
)
async def start_backtest(
    request: BacktestCreateRequest,
    service: Annotated[BacktestService, Depends(get_backtest_service)],
) -> BacktestRunDetailResponse:
    return _to_detail_response(await service.start(_to_backtest_request(request)))


# 接收路由声明的请求参数，委托 service.list，返回 BacktestPageResponse。
@router.get("", response_model=BacktestPageResponse)
async def list_backtests(
    service: Annotated[BacktestService, Depends(get_backtest_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BacktestPageResponse:
    return _to_page_response(await service.list(BacktestFilters(page=page, page_size=page_size)))


# 接收路由声明的请求参数，委托 service.get，返回 BacktestRunDetailResponse。
@router.get("/{run_id}", response_model=BacktestRunDetailResponse)
async def get_backtest(
    run_id: UUID,
    service: Annotated[BacktestService, Depends(get_backtest_service)],
) -> BacktestRunDetailResponse:
    return _to_detail_response(await service.get(run_id))


# 按下面的显式字段映射还原 BacktestRequest，保留可选值与已有顺序；不重新执行业务计算。
def _to_backtest_request(request: BacktestCreateRequest) -> BacktestRequest:
    try:
        return BacktestRequest.model_validate(
            {
                "symbol": request.symbol,
                "timeframe": request.timeframe,
                "start_at": request.start_at,
                "end_at": request.end_at,
                "initial_cash": request.initial_cash,
            }
        )
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error


# 按下面的显式字段映射还原 BacktestPageResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_page_response(page: BacktestPage) -> BacktestPageResponse:
    return BacktestPageResponse(
        items=tuple(_to_summary_response(run) for run in page.items),
        page=page.page,
        page_size=page.page_size,
        total=page.total,
    )


# 按下面的显式字段映射还原 BacktestRunDetailResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_detail_response(run: PersistedBacktestRun) -> BacktestRunDetailResponse:
    response = _to_summary_response(run)
    result = run.result
    return BacktestRunDetailResponse(
        **response.model_dump(),
        closed_trades=()
        if result is None
        else tuple(_to_closed_trade_response(trade) for trade in result.closed_trades),
        events=()
        if result is None
        else tuple(_to_event_response(event) for event in result.events),
    )


# 按下面的显式字段映射还原 BacktestRunSummaryResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_summary_response(run: PersistedBacktestRun) -> BacktestRunSummaryResponse:
    request = run.request
    return BacktestRunSummaryResponse(
        id=run.id,
        status=run.status,
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_at=request.start_at,
        end_at=request.end_at,
        initial_cash=request.initial_cash,
        strategy_id=request.strategy_id,
        strategy_version=request.strategy_version,
        risk_config=BacktestRiskConfigResponse(
            **request.risk_config.model_dump(),
        ),
        execution_config=BacktestExecutionConfigResponse(
            **request.execution_config.model_dump(),
        ),
        created_at=run.created_at,
        finished_at=run.finished_at,
        summary=None if run.result is None else _to_summary(run.result.summary),
        failure_code=run.failure_code,
        failure_message=run.failure_message,
    )


# 按下面的显式字段映射还原 BacktestSummaryResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_summary(summary: BacktestSummary) -> BacktestSummaryResponse:
    return BacktestSummaryResponse(**summary.model_dump())


# 按下面的显式字段映射还原 BacktestClosedTradeResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_closed_trade_response(
    trade: BacktestClosedTrade,
) -> BacktestClosedTradeResponse:
    return BacktestClosedTradeResponse(**trade.model_dump())


# 按下面的显式字段映射还原 BacktestAuditEventResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_event_response(event: BacktestAuditEvent) -> BacktestAuditEventResponse:
    return BacktestAuditEventResponse(
        sequence=event.sequence,
        kind=event.kind.value,
        occurred_at=event.occurred_at,
        candle_sequence=event.candle_sequence,
        idempotency_key=event.idempotency_key,
        payload=event.payload,
    )
