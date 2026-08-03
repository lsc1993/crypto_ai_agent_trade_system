from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.market.contracts import ContractSymbol
from app.risk.contracts import RiskDecision
from app.strategy.contracts import IntentAction, TradeIntent


class OrderStatus(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fee_rate: Decimal
    slippage_rate: Decimal
    fill_ratio: Decimal

    @model_validator(mode="after")
    def validate_rates(self) -> ExecutionConfig:
        if not Decimal("0") <= self.fee_rate < Decimal("1"):
            raise ValueError("手续费率必须大于等于零且小于一")
        if not Decimal("0") <= self.slippage_rate < Decimal("1"):
            raise ValueError("滑点率必须大于等于零且小于一")
        if not Decimal("0") < self.fill_ratio <= Decimal("1"):
            raise ValueError("填充比例必须大于零且不超过一")
        return self


DEFAULT_EXECUTION_CONFIG = ExecutionConfig(
    fee_rate=Decimal("0.001"),
    slippage_rate=Decimal("0.0005"),
    fill_ratio=Decimal("1"),
)


class SimulatedOrder(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    symbol: ContractSymbol
    action: IntentAction
    idempotency_key: str
    submitted_at: datetime
    requested_quantity: Decimal
    status: OrderStatus = OrderStatus.PENDING

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("幂等键不能为空")
        return normalized

    @field_validator("submitted_at")
    @classmethod
    def validate_submitted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("下单时间必须是 UTC 且带时区")
        return value

    @field_validator("requested_quantity")
    @classmethod
    def validate_requested_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= Decimal("0"):
            raise ValueError("请求数量必须为正的有限十进制数")
        return value

    @property
    def is_buy(self) -> bool:
        return self.action is IntentAction.OPEN_LONG

    @classmethod
    def from_risk_decision(
        cls,
        intent: TradeIntent,
        decision: RiskDecision,
        *,
        submitted_at: datetime,
    ) -> SimulatedOrder:
        if not decision.approved or decision.quantity is None:
            raise ValueError("风控拒绝的意图不可生成模拟订单")
        return cls(
            run_id=intent.run_id,
            symbol=intent.symbol,
            action=intent.action,
            idempotency_key=intent.idempotency_key,
            submitted_at=submitted_at,
            requested_quantity=decision.quantity,
        )


class SimulatedFill(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    symbol: ContractSymbol
    action: IntentAction
    order_idempotency_key: str
    submitted_at: datetime
    filled_at: datetime
    requested_quantity: Decimal
    quantity: Decimal
    price: Decimal
    fee: Decimal
    status: OrderStatus

    @field_validator("submitted_at", "filled_at")
    @classmethod
    def validate_fill_times(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("成交时间必须是 UTC 且带时区")
        return value

    @field_validator("requested_quantity", "quantity", "price", "fee")
    @classmethod
    def validate_fill_values(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < Decimal("0"):
            raise ValueError("模拟成交数值必须是有限非负十进制数")
        return value

    @model_validator(mode="after")
    def validate_fill(self) -> SimulatedFill:
        if self.quantity <= Decimal("0"):
            raise ValueError("成交数量必须为正")
        if self.price <= Decimal("0"):
            raise ValueError("成交价格必须为正")
        if self.quantity > self.requested_quantity:
            raise ValueError("成交数量不能超过请求数量")
        if self.status is OrderStatus.FILLED and self.quantity != self.requested_quantity:
            raise ValueError("全额成交必须匹配请求数量")
        if self.status is OrderStatus.PARTIALLY_FILLED and (
            self.quantity >= self.requested_quantity
        ):
            raise ValueError("部分成交必须小于请求数量")
        return self
