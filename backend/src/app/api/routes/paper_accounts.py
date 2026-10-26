# 提供手动模拟账户、意图、策略评估、绩效与归档接口。
# 外部请求转换成领域契约后交给 PaperTradingService，再映射账户及模拟成交历史。
# 路由不能替代服务中的确定性风控；金额保持十进制字符串，不连接真实账户。
from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, JsonValue, StrictStr, ValidationError

from app.execution.contracts import OrderStatus, SimulatedFill, SimulatedOrder
from app.market.contracts import ContractSymbol, DecimalValue, UtcDateTime
from app.paper_trading.contracts import (
    ManualPaperIntent,
    PaperAccount,
    PaperAccountCreate,
    PaperAccountDetail,
    PaperAccountFilters,
    PaperAccountPage,
    PaperAccountStatus,
    PaperAccountSummary,
    PaperActionOutcome,
    PaperAuditEvent,
    PaperDecisionStats,
    PaperEventKind,
    PaperHistoryStatus,
    PaperLedgerEntry,
    PaperMarketSnapshot,
    PaperPerformancePoint,
    PaperPerformanceSnapshot,
    PaperPosition,
)
from app.paper_trading.service import PaperTradingService
from app.strategy.contracts import IntentAction, IntentSource

router = APIRouter(prefix="/paper-accounts", tags=["paper-trading"])


# 共享当前模块的 HTTP 字段别名及冻结配置；具体字段限制由各请求/响应子类声明。
class _ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda value: "".join(
            [value.split("_")[0], *(part.capitalize() for part in value.split("_")[1:])]
        ),
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


# PaperAccountCreateRequest 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：initial_cash；完整契约以下方声明为准。
class PaperAccountCreateRequest(_ApiModel):
    initial_cash: StrictStr


# ManualPaperIntentRequest 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：client_request_id、action；完整契约以下方声明为准。
class ManualPaperIntentRequest(_ApiModel):
    client_request_id: UUID
    action: IntentAction


# PaperRiskConfigResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：max_exposure_fraction、stop_loss_fraction、daily_loss_fraction、
# max_drawdown_fraction、cooldown_candles、quantity_increment；完整契约以下方声明为准。
class PaperRiskConfigResponse(_ApiModel):
    max_exposure_fraction: DecimalValue
    stop_loss_fraction: DecimalValue
    daily_loss_fraction: DecimalValue
    max_drawdown_fraction: DecimalValue
    cooldown_candles: int
    quantity_increment: DecimalValue


# PaperExecutionConfigResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：fee_rate、slippage_rate、fill_ratio；完整契约以下方声明为准。
class PaperExecutionConfigResponse(_ApiModel):
    fee_rate: DecimalValue
    slippage_rate: DecimalValue
    fill_ratio: DecimalValue


# PaperAccountResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：id、status、symbol、initial_cash、cash、equity；完整契约以下方声明为准。
class PaperAccountResponse(_ApiModel):
    id: UUID
    status: PaperAccountStatus
    symbol: ContractSymbol
    initial_cash: DecimalValue
    cash: DecimalValue
    equity: DecimalValue
    peak_equity: DecimalValue
    daily_start_equity: DecimalValue
    daily_realized_loss: DecimalValue
    daily_day: str
    cooldown_remaining: int
    last_closed_candle_at: UtcDateTime | None
    risk_config: PaperRiskConfigResponse
    execution_config: PaperExecutionConfigResponse
    created_at: UtcDateTime
    archived_at: UtcDateTime | None


# PaperPositionResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：quantity、average_entry_price、remaining_entry_cost、opened_at、updated_at；
# 完整契约以下方声明为准。
class PaperPositionResponse(_ApiModel):
    quantity: DecimalValue
    average_entry_price: DecimalValue | None
    remaining_entry_cost: DecimalValue
    opened_at: UtcDateTime | None
    updated_at: UtcDateTime


# PaperMarketSnapshotResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：price、source、observed_at、fetched_at、payload_hash；完整契约以下方声明为准。
class PaperMarketSnapshotResponse(_ApiModel):
    price: DecimalValue
    source: str
    observed_at: UtcDateTime
    fetched_at: UtcDateTime
    payload_hash: str


# PaperOrderResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：action、idempotency_key、submitted_at、requested_quantity、status；
# 完整契约以下方声明为准。
class PaperOrderResponse(_ApiModel):
    action: IntentAction
    idempotency_key: str
    submitted_at: UtcDateTime
    requested_quantity: DecimalValue
    status: OrderStatus


# PaperFillResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：action、order_idempotency_key、submitted_at、filled_at、requested_quantity、quantity；
# 完整契约以下方声明为准。
class PaperFillResponse(_ApiModel):
    action: IntentAction
    order_idempotency_key: str
    submitted_at: UtcDateTime
    filled_at: UtcDateTime
    requested_quantity: DecimalValue
    quantity: DecimalValue
    price: DecimalValue
    fee: DecimalValue
    status: OrderStatus


# PaperLedgerEntryResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：occurred_at、kind、cash_delta、position_delta、realized_pnl、fee；
# 完整契约以下方声明为准。
class PaperLedgerEntryResponse(_ApiModel):
    occurred_at: UtcDateTime
    kind: IntentAction
    cash_delta: DecimalValue
    position_delta: DecimalValue
    realized_pnl: DecimalValue
    fee: DecimalValue
    cash_after: DecimalValue
    quantity_after: DecimalValue


# PaperAuditEventResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：sequence、kind、occurred_at、idempotency_key、payload；完整契约以下方声明为准。
class PaperAuditEventResponse(_ApiModel):
    sequence: int
    kind: PaperEventKind
    occurred_at: UtcDateTime
    idempotency_key: str | None
    payload: dict[str, JsonValue]


# PaperActionOutcomeResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：kind、source、idempotency_key、reason；完整契约以下方声明为准。
class PaperActionOutcomeResponse(_ApiModel):
    kind: str
    source: IntentSource | None
    idempotency_key: str | None
    reason: str | None


# PaperPerformancePointResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：at、cash、position_quantity、equity、net_pnl；完整契约以下方声明为准。
class PaperPerformancePointResponse(_ApiModel):
    at: UtcDateTime
    cash: DecimalValue
    position_quantity: DecimalValue
    equity: DecimalValue
    net_pnl: DecimalValue


# PaperDecisionStatsResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：manual_intent_count、strategy_evaluation_count、no_signal_count、risk_rejected_count、
# risk_exit_count、order_count；完整契约以下方声明为准。
class PaperDecisionStatsResponse(_ApiModel):
    manual_intent_count: int
    strategy_evaluation_count: int
    no_signal_count: int
    risk_rejected_count: int
    risk_exit_count: int
    order_count: int
    fill_count: int


# PaperPerformanceResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：account_id、initial_cash、current_equity、net_pnl、return_fraction、realized_pnl；
# 完整契约以下方声明为准。
class PaperPerformanceResponse(_ApiModel):
    account_id: UUID
    initial_cash: DecimalValue
    current_equity: DecimalValue
    net_pnl: DecimalValue
    return_fraction: DecimalValue
    realized_pnl: DecimalValue
    unrealized_pnl: DecimalValue
    total_fee: DecimalValue
    max_drawdown_amount: DecimalValue
    max_drawdown_fraction: DecimalValue
    open_fill_count: int
    close_fill_count: int
    profitable_close_count: int
    unprofitable_close_count: int
    break_even_close_count: int
    close_win_rate: DecimalValue
    decision_stats: PaperDecisionStatsResponse
    history_status: PaperHistoryStatus
    history_started_at: UtcDateTime
    history_ended_at: UtcDateTime
    equity_curve: tuple[PaperPerformancePointResponse, ...]
    generated_at: UtcDateTime


# PaperAccountDetailResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：position、latest_snapshot、orders、fills、ledger_entries、events；
# 完整契约以下方声明为准。
class PaperAccountDetailResponse(PaperAccountResponse):
    position: PaperPositionResponse
    latest_snapshot: PaperMarketSnapshotResponse | None
    orders: tuple[PaperOrderResponse, ...]
    fills: tuple[PaperFillResponse, ...]
    ledger_entries: tuple[PaperLedgerEntryResponse, ...]
    events: tuple[PaperAuditEventResponse, ...]
    action_outcome: PaperActionOutcomeResponse | None


# PaperAccountSummaryResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：id、status、symbol、cash、equity、position_quantity；完整契约以下方声明为准。
class PaperAccountSummaryResponse(_ApiModel):
    id: UUID
    status: PaperAccountStatus
    symbol: ContractSymbol
    cash: DecimalValue
    equity: DecimalValue
    position_quantity: DecimalValue
    created_at: UtcDateTime
    archived_at: UtcDateTime | None


# PaperAccountPageResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：items、page、page_size、total；完整契约以下方声明为准。
class PaperAccountPageResponse(_ApiModel):
    items: tuple[PaperAccountSummaryResponse, ...]
    page: int
    page_size: int
    total: int


# 从应用 state 取得已装配的 paper_trading_service 依赖；cast 仅服务类型检查，不构造额外资源。
def get_paper_trading_service(request: Request) -> PaperTradingService:
    return cast(PaperTradingService, request.app.state.paper_trading_service)


# 接收路由声明的请求参数，委托 service.create_account，返回 PaperAccountDetailResponse。
@router.post("", status_code=status.HTTP_201_CREATED, response_model=PaperAccountDetailResponse)
async def create_paper_account(
    request: PaperAccountCreateRequest,
    service: Annotated[PaperTradingService, Depends(get_paper_trading_service)],
) -> PaperAccountDetailResponse:
    return _to_detail_response(await service.create_account(_to_create_request(request)))


# 接收路由声明的请求参数，委托 service.list_accounts，返回 PaperAccountPageResponse。
@router.get("", response_model=PaperAccountPageResponse)
async def list_paper_accounts(
    service: Annotated[PaperTradingService, Depends(get_paper_trading_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, alias="pageSize")] = 20,
) -> PaperAccountPageResponse:
    return _to_page_response(
        await service.list_accounts(PaperAccountFilters(page=page, page_size=page_size))
    )


# 接收路由声明的请求参数，委托 service.get_performance，返回 PaperPerformanceResponse。
@router.get("/{account_id}/performance", response_model=PaperPerformanceResponse)
async def get_paper_performance(
    account_id: UUID,
    service: Annotated[PaperTradingService, Depends(get_paper_trading_service)],
) -> PaperPerformanceResponse:
    return _to_performance_response(await service.get_performance(account_id))


# 接收路由声明的请求参数，委托 service.get_account，返回 PaperAccountDetailResponse。
@router.get("/{account_id}", response_model=PaperAccountDetailResponse)
async def get_paper_account(
    account_id: UUID,
    service: Annotated[PaperTradingService, Depends(get_paper_trading_service)],
) -> PaperAccountDetailResponse:
    return _to_detail_response(await service.get_account(account_id))


# 接收路由声明的请求参数，委托 service.submit_manual_intent，返回 PaperAccountDetailResponse。
@router.post("/{account_id}/manual-intents", response_model=PaperAccountDetailResponse)
async def submit_manual_intent(
    account_id: UUID,
    request: ManualPaperIntentRequest,
    service: Annotated[PaperTradingService, Depends(get_paper_trading_service)],
) -> PaperAccountDetailResponse:
    return _to_detail_response(
        await service.submit_manual_intent(account_id, _to_manual_request(request))
    )


# 接收路由声明的请求参数，委托 service.evaluate_strategy，返回 PaperAccountDetailResponse。
@router.post("/{account_id}/strategy-evaluations", response_model=PaperAccountDetailResponse)
async def evaluate_strategy(
    account_id: UUID,
    service: Annotated[PaperTradingService, Depends(get_paper_trading_service)],
) -> PaperAccountDetailResponse:
    return _to_detail_response(await service.evaluate_strategy(account_id))


# 接收路由声明的请求参数，委托 service.archive_account，返回 PaperAccountDetailResponse。
@router.post("/{account_id}/archive", response_model=PaperAccountDetailResponse)
async def archive_paper_account(
    account_id: UUID,
    service: Annotated[PaperTradingService, Depends(get_paper_trading_service)],
) -> PaperAccountDetailResponse:
    return _to_detail_response(await service.archive_account(account_id))


# 按下面的显式字段映射还原 PaperAccountCreate，保留可选值与已有顺序；不重新执行业务计算。
def _to_create_request(request: PaperAccountCreateRequest) -> PaperAccountCreate:
    try:
        return PaperAccountCreate.model_validate({"initial_cash": request.initial_cash})
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error


# 按下面的显式字段映射还原 ManualPaperIntent，保留可选值与已有顺序；不重新执行业务计算。
def _to_manual_request(request: ManualPaperIntentRequest) -> ManualPaperIntent:
    try:
        return ManualPaperIntent.model_validate(
            {
                "client_request_id": request.client_request_id,
                "action": request.action,
            }
        )
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error


# 按下面的显式字段映射还原 PaperAccountPageResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_page_response(page: PaperAccountPage) -> PaperAccountPageResponse:
    return PaperAccountPageResponse(
        items=tuple(_to_summary_response(item) for item in page.items),
        page=page.page,
        page_size=page.page_size,
        total=page.total,
    )


# 按下面的显式字段映射还原 PaperAccountDetailResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_detail_response(detail: PaperAccountDetail) -> PaperAccountDetailResponse:
    account = _to_account_response(detail.account)
    return PaperAccountDetailResponse(
        **account.model_dump(by_alias=False),
        position=_to_position_response(detail.position),
        latest_snapshot=(
            None
            if detail.latest_snapshot is None
            else _to_snapshot_response(detail.latest_snapshot)
        ),
        orders=tuple(_to_order_response(order) for order in detail.orders),
        fills=tuple(_to_fill_response(fill) for fill in detail.fills),
        ledger_entries=tuple(_to_ledger_response(entry) for entry in detail.ledger_entries),
        events=tuple(_to_event_response(event) for event in detail.events),
        action_outcome=(
            None
            if detail.action_outcome is None
            else _to_outcome_response(detail.action_outcome)
        ),
    )


# 按下面的显式字段映射还原 PaperAccountResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_account_response(account: PaperAccount) -> PaperAccountResponse:
    return PaperAccountResponse(
        id=account.id,
        status=account.status,
        symbol=account.symbol,
        initial_cash=account.initial_cash,
        cash=account.cash,
        equity=account.equity,
        peak_equity=account.peak_equity,
        daily_start_equity=account.daily_start_equity,
        daily_realized_loss=account.daily_realized_loss,
        daily_day=account.daily_day.isoformat(),
        cooldown_remaining=account.cooldown_remaining,
        last_closed_candle_at=account.last_closed_candle_at,
        risk_config=PaperRiskConfigResponse(**account.risk_config.model_dump()),
        execution_config=PaperExecutionConfigResponse(
            **account.execution_config.model_dump()
        ),
        created_at=account.created_at,
        archived_at=account.archived_at,
    )


# 按下面的显式字段映射还原 PaperAccountSummaryResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_summary_response(summary: PaperAccountSummary) -> PaperAccountSummaryResponse:
    return PaperAccountSummaryResponse(
        id=summary.id,
        status=summary.status,
        symbol=summary.symbol,
        cash=summary.cash,
        equity=summary.equity,
        position_quantity=summary.position_quantity,
        created_at=summary.created_at,
        archived_at=summary.archived_at,
    )


# 按下面的显式字段映射还原 PaperPositionResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_position_response(position: PaperPosition) -> PaperPositionResponse:
    return PaperPositionResponse(
        quantity=position.quantity,
        average_entry_price=position.average_entry_price,
        remaining_entry_cost=position.remaining_entry_cost,
        opened_at=position.opened_at,
        updated_at=position.updated_at,
    )


# 按下面的显式字段映射还原 PaperMarketSnapshotResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_snapshot_response(snapshot: PaperMarketSnapshot) -> PaperMarketSnapshotResponse:
    return PaperMarketSnapshotResponse(
        price=snapshot.price,
        source=snapshot.source,
        observed_at=snapshot.observed_at,
        fetched_at=snapshot.fetched_at,
        payload_hash=snapshot.payload_hash,
    )


# 按下面的显式字段映射还原 PaperOrderResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_order_response(order: SimulatedOrder) -> PaperOrderResponse:
    return PaperOrderResponse(
        action=order.action,
        idempotency_key=order.idempotency_key,
        submitted_at=order.submitted_at,
        requested_quantity=order.requested_quantity,
        status=order.status,
    )


# 按下面的显式字段映射还原 PaperFillResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_fill_response(fill: SimulatedFill) -> PaperFillResponse:
    return PaperFillResponse(
        action=fill.action,
        order_idempotency_key=fill.order_idempotency_key,
        submitted_at=fill.submitted_at,
        filled_at=fill.filled_at,
        requested_quantity=fill.requested_quantity,
        quantity=fill.quantity,
        price=fill.price,
        fee=fill.fee,
        status=fill.status,
    )


# 按下面的显式字段映射还原 PaperLedgerEntryResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_ledger_response(entry: PaperLedgerEntry) -> PaperLedgerEntryResponse:
    return PaperLedgerEntryResponse(
        occurred_at=entry.occurred_at,
        kind=entry.kind,
        cash_delta=entry.cash_delta,
        position_delta=entry.position_delta,
        realized_pnl=entry.realized_pnl,
        fee=entry.fee,
        cash_after=entry.cash_after,
        quantity_after=entry.quantity_after,
    )


# 按下面的显式字段映射还原 PaperAuditEventResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_event_response(event: PaperAuditEvent) -> PaperAuditEventResponse:
    return PaperAuditEventResponse(
        sequence=event.sequence,
        kind=event.kind,
        occurred_at=event.occurred_at,
        idempotency_key=event.idempotency_key,
        payload=event.payload,
    )


# 按下面的显式字段映射还原 PaperActionOutcomeResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_outcome_response(outcome: PaperActionOutcome) -> PaperActionOutcomeResponse:
    return PaperActionOutcomeResponse(
        kind=outcome.kind.value,
        source=outcome.source,
        idempotency_key=outcome.idempotency_key,
        reason=outcome.reason,
    )


# 按下面的显式字段映射还原 PaperPerformanceResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_performance_response(
    snapshot: PaperPerformanceSnapshot,
) -> PaperPerformanceResponse:
    return PaperPerformanceResponse(
        account_id=snapshot.account_id,
        initial_cash=snapshot.initial_cash,
        current_equity=snapshot.current_equity,
        net_pnl=snapshot.net_pnl,
        return_fraction=snapshot.return_fraction,
        realized_pnl=snapshot.realized_pnl,
        unrealized_pnl=snapshot.unrealized_pnl,
        total_fee=snapshot.total_fee,
        max_drawdown_amount=snapshot.max_drawdown_amount,
        max_drawdown_fraction=snapshot.max_drawdown_fraction,
        open_fill_count=snapshot.open_fill_count,
        close_fill_count=snapshot.close_fill_count,
        profitable_close_count=snapshot.profitable_close_count,
        unprofitable_close_count=snapshot.unprofitable_close_count,
        break_even_close_count=snapshot.break_even_close_count,
        close_win_rate=snapshot.close_win_rate,
        decision_stats=_to_decision_stats_response(snapshot.decision_stats),
        history_status=snapshot.history_status,
        history_started_at=snapshot.history_started_at,
        history_ended_at=snapshot.history_ended_at,
        equity_curve=tuple(
            _to_performance_point_response(point) for point in snapshot.equity_curve
        ),
        generated_at=snapshot.generated_at,
    )


# 按下面的显式字段映射还原 PaperDecisionStatsResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_decision_stats_response(
    stats: PaperDecisionStats,
) -> PaperDecisionStatsResponse:
    return PaperDecisionStatsResponse(**stats.model_dump())


# 按下面的显式字段映射还原 PaperPerformancePointResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_performance_point_response(
    point: PaperPerformancePoint,
) -> PaperPerformancePointResponse:
    return PaperPerformancePointResponse(**point.model_dump())
