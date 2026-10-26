# 行情契约：声明静态交易标的、研究行情及新鲜度；字段校验约束 Decimal、UTC、K 线范围和周期顺序。
# 公开行情领域：统一研究行情模型、固定公开来源适配器与冻结快照读取；不访问私有账户。
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer, field_validator, model_validator

from app.market.symbols import ResearchSymbol


# ContractSymbol 固定可用枚举值：BTCUSDT、ETHUSDT；外部数据不能自行增加状态或动作。
class ContractSymbol(StrEnum):
    BTCUSDT = "BTCUSDT"
    ETHUSDT = "ETHUSDT"


# MarketTimeframe 固定可用枚举值：M15、H1、H4、D1；外部数据不能自行增加状态或动作。
class MarketTimeframe(StrEnum):
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


# FreshnessStatus 固定可用枚举值：FRESH、STALE、MISSING、FAILED；外部数据不能自行增加状态或动作。
class FreshnessStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    FAILED = "failed"


# 以不使用科学计数法的十进制字符串输出，避免 JSON 数值丢失金额精度。
def _serialize_decimal(value: Decimal) -> str:
    return format(value, "f")


# 将带时区时间转为 UTC 的标准字符串，使用末尾 Z 表明零时区。
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


# 公开行情安全错误，携带稳定错误码和可显示提示。
class MarketDataUnavailableError(RuntimeError):
    # 初始化本实例依赖和配置；输入 code、message。
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# 行情契约公共基类：冻结值、拒绝额外字段并以驼峰字段名序列化。
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


# 行情来源、新鲜度状态及观测和抓取时间的组合，区分新鲜、过期、缺失与失败。
class DataFreshness(_MarketModel):
    status: FreshnessStatus
    source: str
    observed_at: UtcDateTime
    fetched_at: UtcDateTime

    # 校验source 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：数据来源不能为空。
    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("数据来源不能为空")
        return normalized

    # 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
    @field_validator("observed_at", "fetched_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("时间必须是 UTC 且带时区")
        return value


# 单根研究 K 线，保留周期、十进制价格与成交量以及来源时刻，验证范围与 UTC 时间。
class Candle(_MarketModel):
    symbol: ResearchSymbol
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

    # 校验open_price、high_price、low_price、close_price、volume 字段，返回规范化值或模型；
    # 不满足约束时抛出验证错误。
    # 拒绝条件包括：市场数值必须是 Decimal 或十进制字符串；市场数值必须是有限非负十进制数；
    # 市场数值必须是有效十进制数。
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

    # 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
    @field_validator("open_at", "close_at", "observed_at", "fetched_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("时间必须是 UTC 且带时区")
        return value

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：K 线结束时间必须晚于开始时间；最高价不能低于开盘价或收盘价；
    # 最低价不能高于开盘价或收盘价。
    @model_validator(mode="after")
    def validate_candle_range(self) -> Candle:
        if self.close_at <= self.open_at:
            raise ValueError("K 线结束时间必须晚于开始时间")
        if self.high_price < max(self.open_price, self.close_price):
            raise ValueError("最高价不能低于开盘价或收盘价")
        if self.low_price > min(self.open_price, self.close_price):
            raise ValueError("最低价不能高于开盘价或收盘价")
        return self


# 一个周期的非空升序 K 线序列，不接纳周期不一致或无序行情。
class CandleSeries(_MarketModel):
    timeframe: MarketTimeframe
    candles: tuple[Candle, ...]

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：K 线序列不能为空；K 线周期必须与序列周期一致；K 线必须按开始时间升序排列。
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


# 研究标的的价格、涨跌幅、成交量、费率与未平仓量摘要，同时保留来源新鲜度。
class MarketSummary(_MarketModel):
    symbol: ResearchSymbol
    price: DecimalValue
    change_24h: DecimalValue
    volume_24h: DecimalValue
    funding_rate: DecimalValue
    open_interest: DecimalValue
    freshness: DataFreshness

    # 校验price、change_24h、volume_24h、funding_rate、open_interest 字段，返回规范化值或模型；
    # 不满足约束时抛出验证错误。
    # 拒绝条件包括：市场数值必须是 Decimal 或十进制字符串；市场数值必须是有限十进制数；
    # 市场数值必须是有效十进制数。
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

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：价格必须为正数；成交量和未平仓量不能为负数。
    @model_validator(mode="after")
    def validate_summary_values(self) -> MarketSummary:
        if self.price <= 0:
            raise ValueError("价格必须为正数")
        if self.volume_24h < 0 or self.open_interest < 0:
            raise ValueError("成交量和未平仓量不能为负数")
        return self


# 把一个研究标的的摘要和多周期 K 线序列组合为行情详情。
class MarketDetail(_MarketModel):
    summary: MarketSummary
    series: tuple[CandleSeries, ...]
