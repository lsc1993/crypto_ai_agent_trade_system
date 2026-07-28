from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer, field_validator, model_validator


class ContractSymbol(StrEnum):
    BTCUSDT = "BTCUSDT"
    ETHUSDT = "ETHUSDT"


class MarketTimeframe(StrEnum):
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class FreshnessStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    FAILED = "failed"


def _serialize_decimal(value: Decimal) -> str:
    return format(value, "f")


def _serialize_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


DecimalValue = Annotated[
    Decimal,
    PlainSerializer(_serialize_decimal, return_type=str, when_used="json"),
]
UtcDateTime = Annotated[
    datetime,
    PlainSerializer(_serialize_utc, return_type=str, when_used="json"),
]


class MarketDataUnavailableError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _MarketModel(BaseModel):
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


class DataFreshness(_MarketModel):
    status: FreshnessStatus
    source: str
    observed_at: UtcDateTime
    fetched_at: UtcDateTime

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("数据来源不能为空")
        return normalized

    @field_validator("observed_at", "fetched_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("时间必须是 UTC 且带时区")
        return value


class Candle(_MarketModel):
    symbol: ContractSymbol
    timeframe: MarketTimeframe
    open_at: UtcDateTime
    close_at: UtcDateTime
    open_price: DecimalValue
    high_price: DecimalValue
    low_price: DecimalValue
    close_price: DecimalValue
    volume: DecimalValue
    observed_at: UtcDateTime
    fetched_at: UtcDateTime

    @field_validator(
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        mode="before",
    )
    @classmethod
    def parse_decimal_value(cls, value: object) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (Decimal, str)):
            raise ValueError("市场数值必须是 Decimal 或十进制字符串")
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError) as error:
            raise ValueError("市场数值必须是有效十进制数") from error
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("市场数值必须是有限非负十进制数")
        return parsed

    @field_validator("open_at", "close_at", "observed_at", "fetched_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("时间必须是 UTC 且带时区")
        return value

    @model_validator(mode="after")
    def validate_candle_range(self) -> Candle:
        if self.close_at <= self.open_at:
            raise ValueError("K 线结束时间必须晚于开始时间")
        if self.high_price < max(self.open_price, self.close_price):
            raise ValueError("最高价不能低于开盘价或收盘价")
        if self.low_price > min(self.open_price, self.close_price):
            raise ValueError("最低价不能高于开盘价或收盘价")
        return self


class CandleSeries(_MarketModel):
    timeframe: MarketTimeframe
    candles: tuple[Candle, ...]

    @model_validator(mode="after")
    def validate_series_scope_and_order(self) -> CandleSeries:
        if not self.candles:
            raise ValueError("K 线序列不能为空")
        if any(candle.timeframe != self.timeframe for candle in self.candles):
            raise ValueError("K 线周期必须与序列周期一致")
        open_times = tuple(candle.open_at for candle in self.candles)
        if open_times != tuple(sorted(open_times)):
            raise ValueError("K 线必须按开始时间升序排列")
        return self


class MarketSummary(_MarketModel):
    symbol: ContractSymbol
    price: DecimalValue
    change_24h: DecimalValue
    volume_24h: DecimalValue
    funding_rate: DecimalValue
    open_interest: DecimalValue
    freshness: DataFreshness

    @field_validator(
        "price",
        "change_24h",
        "volume_24h",
        "funding_rate",
        "open_interest",
        mode="before",
    )
    @classmethod
    def parse_decimal_value(cls, value: object) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (Decimal, str)):
            raise ValueError("市场数值必须是 Decimal 或十进制字符串")
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError) as error:
            raise ValueError("市场数值必须是有效十进制数") from error
        if not parsed.is_finite():
            raise ValueError("市场数值必须是有限十进制数")
        return parsed

    @model_validator(mode="after")
    def validate_summary_values(self) -> MarketSummary:
        if self.price <= 0:
            raise ValueError("价格必须为正数")
        if self.volume_24h < 0 or self.open_interest < 0:
            raise ValueError("成交量和未平仓量不能为负数")
        return self


class MarketDetail(_MarketModel):
    summary: MarketSummary
    series: tuple[CandleSeries, ...]
