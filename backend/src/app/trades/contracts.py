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


class TradeAuditAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    ARCHIVED = "archived"


class TradeValidationError(ValueError):
    """手工交易事实不满足领域约束。"""


class TradeStorageUnavailableError(RuntimeError):
    """交易日志无法安全持久化或读取。"""


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


class PersistedTrade(TradeDraft):
    id: UUID
    status: TradeStatus
    gross_realized_pnl: Decimal
    total_fees: Decimal
    total_funding_cashflow: Decimal
    net_pnl: Decimal
    opened_at: datetime
    closed_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_validator("opened_at", "closed_at", "archived_at", "created_at", "updated_at")
    @classmethod
    def validate_persisted_utc_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)


class TradeFilters(_TradeModel):
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    symbol: ContractSymbol | None = None
    direction: TradeDirection | None = None
    horizon: TradeHorizon | None = None
    status: TradeStatus | None = None
    label: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    from_at: datetime | None = None
    to_at: datetime | None = None

    @field_validator("from_at", "to_at")
    @classmethod
    def validate_filter_utc_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)

    @model_validator(mode="after")
    def validate_time_range(self) -> TradeFilters:
        if self.from_at is not None and self.to_at is not None and self.from_at > self.to_at:
            raise ValueError("交易筛选开始时间不能晚于结束时间")
        return self


class TradePage(_TradeModel):
    items: tuple[PersistedTrade, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: Annotated[int, Field(ge=0)]


class AnalyticsFilters(_TradeModel):
    symbol: ContractSymbol | None = None
    direction: TradeDirection | None = None
    horizon: TradeHorizon | None = None
    label: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    from_at: datetime | None = None
    to_at: datetime | None = None

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("标签不能为空")
        return normalized

    @field_validator("from_at", "to_at")
    @classmethod
    def validate_filter_utc_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)

    @model_validator(mode="after")
    def validate_time_range(self) -> AnalyticsFilters:
        if self.from_at is not None and self.to_at is not None and self.from_at > self.to_at:
            raise ValueError("统计筛选开始时间不能晚于结束时间")
        return self


class EquityPoint(_TradeModel):
    at: datetime
    equity: Decimal
    net_pnl: Decimal

    @field_validator("at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)


class TradeCalendarPoint(_TradeModel):
    at: datetime
    net_pnl: Decimal
    trade_count: Annotated[int, Field(ge=0)]

    @field_validator("at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)


class AnalyticsSnapshot(_TradeModel):
    net_pnl: Decimal
    win_rate: Decimal
    profit_factor: Decimal | None
    expectancy: Decimal
    max_drawdown: Decimal
    equity_curve: tuple[EquityPoint, ...]
    trade_calendar: tuple[TradeCalendarPoint, ...]
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)
