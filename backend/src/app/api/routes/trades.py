# 提供交易日志录入、筛选、修改与归档的 HTTP 映射。
# 将外部请求转换为 TradeDraft，按输入顺序分配交易腿序号后交给日志服务。
# 日志记录描述交易事实，不执行订单；归档返回 204，金额字段遵循 DecimalValue。
from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from app.market.contracts import ContractSymbol, DecimalValue, UtcDateTime
from app.trades.contracts import (
    PersistedTrade,
    TradeDirection,
    TradeDraft,
    TradeFilters,
    TradeHorizon,
    TradeLegAction,
    TradePage,
    TradeStatus,
)
from app.trades.repository import TradeRepository
from app.trades.service import TradeService

router = APIRouter(prefix="/trades", tags=["trades"])


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


# TradeLegRequest 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：id、action、executed_at、price、quantity、fee；完整契约以下方声明为准。
class TradeLegRequest(_ApiModel):
    id: UUID
    action: TradeLegAction
    executed_at: UtcDateTime
    price: StrictStr
    quantity: StrictStr
    fee: StrictStr


# TradeCashflowRequest 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：id、occurred_at、amount、reason；完整契约以下方声明为准。
class TradeCashflowRequest(_ApiModel):
    id: UUID
    occurred_at: UtcDateTime
    amount: StrictStr
    reason: str


# TradeRequest 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：symbol、direction、horizon、labels、linked_report_id、leverage；完整契约以下方声明为准。
class TradeRequest(_ApiModel):
    symbol: ContractSymbol
    direction: TradeDirection
    horizon: TradeHorizon
    labels: tuple[str, ...]
    linked_report_id: UUID | None
    leverage: StrictStr
    legs: tuple[TradeLegRequest, ...]
    cashflows: tuple[TradeCashflowRequest, ...]
    thesis: str
    review: str


# TradeLegResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：id、action、executed_at、price、quantity、fee；完整契约以下方声明为准。
class TradeLegResponse(_ApiModel):
    id: UUID
    action: TradeLegAction
    executed_at: UtcDateTime
    price: DecimalValue
    quantity: DecimalValue
    fee: DecimalValue


# TradeCashflowResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：id、occurred_at、amount、reason；完整契约以下方声明为准。
class TradeCashflowResponse(_ApiModel):
    id: UUID
    occurred_at: UtcDateTime
    amount: DecimalValue
    reason: str


# TradeResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：id、symbol、direction、horizon、labels、linked_report_id；完整契约以下方声明为准。
class TradeResponse(_ApiModel):
    id: UUID
    symbol: ContractSymbol
    direction: TradeDirection
    horizon: TradeHorizon
    labels: tuple[str, ...]
    linked_report_id: UUID | None
    leverage: DecimalValue
    legs: tuple[TradeLegResponse, ...]
    cashflows: tuple[TradeCashflowResponse, ...]
    thesis: str
    review: str
    status: TradeStatus
    gross_realized_pnl: DecimalValue
    total_fees: DecimalValue
    total_funding_cashflow: DecimalValue
    net_pnl: DecimalValue
    opened_at: UtcDateTime
    closed_at: UtcDateTime | None
    archived_at: UtcDateTime | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


# TradePageResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：items、page、page_size、total；完整契约以下方声明为准。
class TradePageResponse(_ApiModel):
    items: tuple[TradeResponse, ...]
    page: int
    page_size: int = Field(serialization_alias="page_size")
    total: int


# 从应用 state 取得已装配的 trade_service 依赖；cast 仅服务类型检查，不构造额外资源。
def get_trade_service(request: Request) -> TradeService:
    return cast(TradeService, request.app.state.trade_service)


# 从应用 state 取得已装配的 trade_repository 依赖；cast 仅服务类型检查，不构造额外资源。
def get_trade_repository(request: Request) -> TradeRepository:
    return cast(TradeRepository, request.app.state.trade_repository)


# 接收路由声明的请求参数，委托 service.create_trade，返回 TradeResponse。
@router.post("", status_code=status.HTTP_201_CREATED, response_model=TradeResponse)
async def create_trade(
    request: TradeRequest,
    service: Annotated[TradeService, Depends(get_trade_service)],
) -> TradeResponse:
    return _to_response(await service.create_trade(_to_draft(request)))


# 接收路由声明的请求参数，委托 repository.list，返回 TradePageResponse。
@router.get("", response_model=TradePageResponse)
async def list_trades(
    repository: Annotated[TradeRepository, Depends(get_trade_repository)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    symbol: ContractSymbol | None = None,
    direction: TradeDirection | None = None,
    horizon: TradeHorizon | None = None,
    status_filter: Annotated[TradeStatus | None, Query(alias="status")] = None,
    label: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    from_at: Annotated[UtcDateTime | None, Query(alias="from")] = None,
    to_at: Annotated[UtcDateTime | None, Query(alias="to")] = None,
) -> TradePageResponse:
    filters = _validate_filters(
        page=page,
        page_size=page_size,
        symbol=symbol,
        direction=direction,
        horizon=horizon,
        status=status_filter,
        label=label,
        from_at=from_at,
        to_at=to_at,
    )
    return _to_page_response(await repository.list(filters))


# 接收路由声明的请求参数，委托 service.update_trade，返回 TradeResponse。
@router.put("/{trade_id}", response_model=TradeResponse)
async def update_trade(
    trade_id: UUID,
    request: TradeRequest,
    service: Annotated[TradeService, Depends(get_trade_service)],
) -> TradeResponse:
    return _to_response(await service.update_trade(trade_id, _to_draft(request)))


# 接收路由声明的请求参数，委托 service.archive_trade，返回 Response。
@router.post("/{trade_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_trade(
    trade_id: UUID,
    service: Annotated[TradeService, Depends(get_trade_service)],
) -> Response:
    await service.archive_trade(trade_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# 按下面的显式字段映射还原 TradeDraft，保留可选值与已有顺序；不重新执行业务计算。
def _to_draft(request: TradeRequest) -> TradeDraft:
    try:
        return TradeDraft.model_validate(
            {
                "symbol": request.symbol,
                "direction": request.direction,
                "horizon": request.horizon,
                "labels": request.labels,
                "linked_report_id": request.linked_report_id,
                "leverage": request.leverage,
                "legs": tuple(
                    {
                        "id": leg.id,
                        "action": leg.action,
                        "executed_at": leg.executed_at,
                        # 分腿顺序由请求数组确定，作为同一时刻成交的稳定排序依据。
                        "sequence": index,
                        "price": leg.price,
                        "quantity": leg.quantity,
                        "fee": leg.fee,
                    }
                    for index, leg in enumerate(request.legs)
                ),
                "cashflows": tuple(
                    {
                        "id": cashflow.id,
                        "occurred_at": cashflow.occurred_at,
                        "amount": cashflow.amount,
                        "reason": cashflow.reason,
                    }
                    for cashflow in request.cashflows
                ),
                "thesis": request.thesis,
                "review": request.review,
            }
        )
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error


def _validate_filters(**values: object) -> TradeFilters:
    try:
        return TradeFilters.model_validate(values)
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error


# 按下面的显式字段映射还原 TradePageResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_page_response(page: TradePage) -> TradePageResponse:
    return TradePageResponse(
        items=tuple(_to_response(trade) for trade in page.items),
        page=page.page,
        page_size=page.page_size,
        total=page.total,
    )


# 按下面的显式字段映射还原 TradeResponse，保留可选值与已有顺序；不重新执行业务计算。
def _to_response(trade: PersistedTrade) -> TradeResponse:
    return TradeResponse(
        id=trade.id,
        symbol=trade.symbol,
        direction=trade.direction,
        horizon=trade.horizon,
        labels=trade.labels,
        linked_report_id=trade.linked_report_id,
        leverage=trade.leverage,
        legs=tuple(
            TradeLegResponse(
                id=leg.id,
                action=leg.action,
                executed_at=leg.executed_at,
                price=leg.price,
                quantity=leg.quantity,
                fee=leg.fee,
            )
            for leg in trade.legs
        ),
        cashflows=tuple(
            TradeCashflowResponse(
                id=cashflow.id,
                occurred_at=cashflow.occurred_at,
                amount=cashflow.amount,
                reason=cashflow.reason,
            )
            for cashflow in trade.cashflows
        ),
        thesis=trade.thesis,
        review=trade.review,
        status=trade.status,
        gross_realized_pnl=trade.gross_realized_pnl,
        total_fees=trade.total_fees,
        total_funding_cashflow=trade.total_funding_cashflow,
        net_pnl=trade.net_pnl,
        opened_at=trade.opened_at,
        closed_at=trade.closed_at,
        archived_at=trade.archived_at,
        created_at=trade.created_at,
        updated_at=trade.updated_at,
    )
