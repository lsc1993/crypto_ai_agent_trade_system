from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.market.contracts import ContractSymbol


class TradeDirection(StrEnum):
    LONG = "long"
    SHORT = "short"


class TradeHorizon(StrEnum):
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"


class TradeLegAction(StrEnum):
    OPEN = "open"
    REDUCE = "reduce"
    CLOSE = "close"


class TradeStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    ARCHIVED = "archived"


class TradeAuditAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    ARCHIVED = "archived"


class TradeValidationError(ValueError):
    """手工交易事实不满足领域约束。"""


class _TradeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是 UTC 且带时区")
    return value.astimezone(UTC)


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("浮点数不能作为交易领域输入")
    return value


class TradeLegDraft(_TradeModel):
    id: UUID
    action: TradeLegAction
    executed_at: datetime
    sequence: Annotated[int, Field(ge=0)]
    price: Decimal
    quantity: Decimal
    fee: Decimal

    @field_validator("price", "quantity", "fee", mode="before")
    @classmethod
    def reject_float_values(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("executed_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("price", "quantity")
    @classmethod
    def validate_positive_decimal(cls, value: Decimal) -> Decimal:
        if value <= Decimal(0):
            raise ValueError("价格和数量必须大于零")
        return value

    @field_validator("fee")
    @classmethod
    def validate_nonnegative_fee(cls, value: Decimal) -> Decimal:
        if value < Decimal(0):
            raise ValueError("手续费不能为负数")
        return value


class TradeCashflowDraft(_TradeModel):
    id: UUID
    occurred_at: datetime
    amount: Decimal
    reason: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("amount", mode="before")
    @classmethod
    def reject_float_amount(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("occurred_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("资金现金流说明不能为空")
        return normalized


class TradeDraft(_TradeModel):
    symbol: ContractSymbol
    direction: TradeDirection
    horizon: TradeHorizon
    labels: tuple[Annotated[str, Field(min_length=1, max_length=100)], ...]
    linked_report_id: UUID | None
    leverage: Decimal
    legs: tuple[TradeLegDraft, ...]
    cashflows: tuple[TradeCashflowDraft, ...]
    thesis: Annotated[str, Field(max_length=5_000)]
    review: Annotated[str, Field(max_length=5_000)]

    @field_validator("leverage", mode="before")
    @classmethod
    def reject_float_leverage(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("leverage")
    @classmethod
    def validate_positive_leverage(cls, value: Decimal) -> Decimal:
        if value <= Decimal(0):
            raise ValueError("杠杆必须大于零")
        return value

    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(label.strip() for label in value)
        if any(not label for label in normalized):
            raise ValueError("标签不能为空")
        if len(set(normalized)) != len(normalized):
            raise ValueError("标签不能重复")
        return normalized

    @model_validator(mode="after")
    def validate_activity_identifiers(self) -> TradeDraft:
        if not self.legs:
            raise ValueError("交易至少需要一条交易腿")
        identifiers = tuple(leg.id for leg in self.legs) + tuple(
            cashflow.id for cashflow in self.cashflows
        )
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("交易腿 ID 必须唯一")
        return self
