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


class BacktestCreateRequest(_ApiModel):
    symbol: ContractSymbol
    timeframe: MarketTimeframe
    start_at: UtcDateTime
    end_at: UtcDateTime
    initial_cash: StrictStr


class BacktestRiskConfigResponse(_ApiModel):
    max_exposure_fraction: BacktestDecimalValue
    stop_loss_fraction: BacktestDecimalValue
    daily_loss_fraction: BacktestDecimalValue
    max_drawdown_fraction: BacktestDecimalValue
    cooldown_candles: int
    quantity_increment: BacktestDecimalValue


class BacktestExecutionConfigResponse(_ApiModel):
    fee_rate: BacktestDecimalValue
    slippage_rate: BacktestDecimalValue
    fill_ratio: BacktestDecimalValue


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


class BacktestClosedTradeResponse(_ApiModel):
    opened_at: UtcDateTime
    closed_at: UtcDateTime
    quantity: BacktestDecimalValue
    net_pnl: BacktestDecimalValue


class BacktestAuditEventResponse(_ApiModel):
    sequence: int
    kind: str
    occurred_at: UtcDateTime
    candle_sequence: int | None
    idempotency_key: str | None
    payload: dict[str, JsonValue]


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


class BacktestRunDetailResponse(BacktestRunSummaryResponse):
    closed_trades: tuple[BacktestClosedTradeResponse, ...]
    events: tuple[BacktestAuditEventResponse, ...]


class BacktestPageResponse(_ApiModel):
    items: tuple[BacktestRunSummaryResponse, ...]
    page: int
    page_size: int = Field(serialization_alias="page_size")
    total: int


def get_backtest_service(request: Request) -> BacktestService:
    return cast(BacktestService, request.app.state.backtest_service)


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


@router.get("", response_model=BacktestPageResponse)
async def list_backtests(
    service: Annotated[BacktestService, Depends(get_backtest_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BacktestPageResponse:
    return _to_page_response(await service.list(BacktestFilters(page=page, page_size=page_size)))


@router.get("/{run_id}", response_model=BacktestRunDetailResponse)
async def get_backtest(
    run_id: UUID,
    service: Annotated[BacktestService, Depends(get_backtest_service)],
) -> BacktestRunDetailResponse:
    return _to_detail_response(await service.get(run_id))


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


def _to_page_response(page: BacktestPage) -> BacktestPageResponse:
    return BacktestPageResponse(
        items=tuple(_to_summary_response(run) for run in page.items),
        page=page.page,
        page_size=page.page_size,
        total=page.total,
    )


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


def _to_summary(summary: BacktestSummary) -> BacktestSummaryResponse:
    return BacktestSummaryResponse(**summary.model_dump())


def _to_closed_trade_response(
    trade: BacktestClosedTrade,
) -> BacktestClosedTradeResponse:
    return BacktestClosedTradeResponse(**trade.model_dump())


def _to_event_response(event: BacktestAuditEvent) -> BacktestAuditEventResponse:
    return BacktestAuditEventResponse(
        sequence=event.sequence,
        kind=event.kind.value,
        occurred_at=event.occurred_at,
        candle_sequence=event.candle_sequence,
        idempotency_key=event.idempotency_key,
        payload=event.payload,
    )
