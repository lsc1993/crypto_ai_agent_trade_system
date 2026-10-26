# 手工日志契约：交易腿、现金流、方向、标签与复盘组成草稿，保存派生盈亏和时间；
# 筛选与统计使用独立响应模型。
# 手工交易日志领域：记录用户录入的历史成交与复盘，按先进先出核算盈亏；不生成交易请求。
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.market.contracts import ContractSymbol


# TradeDirection 固定可用枚举值：LONG、SHORT；外部数据不能自行增加状态或动作。
class TradeDirection(StrEnum):
    LONG = "long"
    SHORT = "short"


# TradeHorizon 固定可用枚举值：SHORT_TERM、MEDIUM_TERM；外部数据不能自行增加状态或动作。
class TradeHorizon(StrEnum):
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"


# TradeLegAction 固定可用枚举值：OPEN、REDUCE、CLOSE；外部数据不能自行增加状态或动作。
class TradeLegAction(StrEnum):
    OPEN = "open"
    REDUCE = "reduce"
    CLOSE = "close"


# TradeStatus 固定可用枚举值：OPEN、CLOSED；外部数据不能自行增加状态或动作。
class TradeStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


# TradeAuditAction 固定可用枚举值：CREATED、UPDATED、ARCHIVED；外部数据不能自行增加状态或动作。
class TradeAuditAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    ARCHIVED = "archived"


# 手工交易事实不满足领域约束。
class TradeValidationError(ValueError):
    """手工交易事实不满足领域约束。"""


# 交易日志无法安全持久化或读取。
class TradeStorageUnavailableError(RuntimeError):
    """交易日志无法安全持久化或读取。"""


# 手工交易日志契约的冻结公共基类，拒绝额外字段。
class _TradeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是 UTC 且带时区")
    return value.astimezone(UTC)


# 在类型转换之前拒绝浮点领域输入，避免金融数值被二进制误差污染。
def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("浮点数不能作为交易领域输入")
    return value


# 用户录入的历史成交腿，保存稳定标识、UTC 时间、动作、价格、数量和费用供先进先出匹配。
class TradeLegDraft(_TradeModel):
    id: UUID
    action: TradeLegAction
    executed_at: datetime
    sequence: Annotated[int, Field(ge=0)]
    price: Decimal
    quantity: Decimal
    fee: Decimal

    # 校验price、quantity、fee 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 先拒绝浮点输入，避免二进制小数误差被转换为金融领域数值。
    @field_validator("price", "quantity", "fee", mode="before")
    @classmethod
    def reject_float_values(cls, value: Any) -> Any:
        return _reject_float(value)

    # 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
    @field_validator("executed_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    # 校验price、quantity 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：价格和数量必须大于零。
    @field_validator("price", "quantity")
    @classmethod
    def validate_positive_decimal(cls, value: Decimal) -> Decimal:
        if value <= Decimal(0):
            raise ValueError("价格和数量必须大于零")
        return value

    # 校验fee 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：手续费不能为负数。
    @field_validator("fee")
    @classmethod
    def validate_nonnegative_fee(cls, value: Decimal) -> Decimal:
        if value < Decimal(0):
            raise ValueError("手续费不能为负数")
        return value


# 不参与价格差匹配的现金流事实，保存金额、UTC 时间与说明。
class TradeCashflowDraft(_TradeModel):
    id: UUID
    occurred_at: datetime
    amount: Decimal
    reason: Annotated[str, Field(min_length=1, max_length=500)]

    # 校验amount 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 先拒绝浮点输入，避免二进制小数误差被转换为金融领域数值。
    @field_validator("amount", mode="before")
    @classmethod
    def reject_float_amount(cls, value: Any) -> Any:
        return _reject_float(value)

    # 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
    @field_validator("occurred_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    # 校验reason 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：资金现金流说明不能为空。
    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("资金现金流说明不能为空")
        return normalized


# 用户手工录入的历史交易与复盘，关联静态标的、成交腿、现金流和可选研究报告。
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

    # 校验leverage 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 先拒绝浮点输入，避免二进制小数误差被转换为金融领域数值。
    @field_validator("leverage", mode="before")
    @classmethod
    def reject_float_leverage(cls, value: Any) -> Any:
        return _reject_float(value)

    # 校验leverage 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：杠杆必须大于零。
    @field_validator("leverage")
    @classmethod
    def validate_positive_leverage(cls, value: Decimal) -> Decimal:
        if value <= Decimal(0):
            raise ValueError("杠杆必须大于零")
        return value

    # 校验labels 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：标签不能为空；标签不能重复。
    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(label.strip() for label in value)
        if any(not label for label in normalized):
            raise ValueError("标签不能为空")
        if len(set(normalized)) != len(normalized):
            raise ValueError("标签不能重复")
        return normalized

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：交易至少需要一条交易腿；交易腿 ID 必须唯一。
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


# 保存后的交易日志，在草稿之上增加派生盈亏、生命周期与归档时刻。
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

    # 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
    @field_validator("opened_at", "closed_at", "archived_at", "created_at", "updated_at")
    @classmethod
    def validate_persisted_utc_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)


# 日志分页筛选，支持标的、方向、周期、状态、标签和 UTC 时间范围。
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

    # 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
    @field_validator("from_at", "to_at")
    @classmethod
    def validate_filter_utc_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：交易筛选开始时间不能晚于结束时间。
    @model_validator(mode="after")
    def validate_time_range(self) -> TradeFilters:
        if self.from_at is not None and self.to_at is not None and self.from_at > self.to_at:
            raise ValueError("交易筛选开始时间不能晚于结束时间")
        return self


# 交易日志分页结果，包含记录元组、页码、页长与总数。
class TradePage(_TradeModel):
    items: tuple[PersistedTrade, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: Annotated[int, Field(ge=0)]


# 已实现绩效的筛选范围，不包含列表分页参数。
class AnalyticsFilters(_TradeModel):
    symbol: ContractSymbol | None = None
    direction: TradeDirection | None = None
    horizon: TradeHorizon | None = None
    label: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    from_at: datetime | None = None
    to_at: datetime | None = None

    # 校验label 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：标签不能为空。
    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("标签不能为空")
        return normalized

    # 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
    @field_validator("from_at", "to_at")
    @classmethod
    def validate_filter_utc_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：统计筛选开始时间不能晚于结束时间。
    @model_validator(mode="after")
    def validate_time_range(self) -> AnalyticsFilters:
        if self.from_at is not None and self.to_at is not None and self.from_at > self.to_at:
            raise ValueError("统计筛选开始时间不能晚于结束时间")
        return self


# 平仓时刻的累积已实现净盈亏点，统计曲线以零为基线。
class EquityPoint(_TradeModel):
    at: datetime
    equity: Decimal
    net_pnl: Decimal

    # 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
    @field_validator("at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)


# UTC 自然日的已实现净盈亏与交易数量。
class TradeCalendarPoint(_TradeModel):
    at: datetime
    net_pnl: Decimal
    trade_count: Annotated[int, Field(ge=0)]

    # 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
    @field_validator("at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)


# 已平仓日志绩效快照，汇集胜率、盈亏比、期望、金额回撤和权益及日历曲线。
class AnalyticsSnapshot(_TradeModel):
    net_pnl: Decimal
    win_rate: Decimal
    profit_factor: Decimal | None
    expectancy: Decimal
    max_drawdown: Decimal
    equity_curve: tuple[EquityPoint, ...]
    trade_calendar: tuple[TradeCalendarPoint, ...]
    generated_at: datetime

    # 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
    @field_validator("generated_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)
