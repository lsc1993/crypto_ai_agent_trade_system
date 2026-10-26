# 模拟执行契约：有限 Decimal 费率、UTC 报价、风控批准订单和成交组成记录；
# 成交状态必须与请求和实际数量一致。
# 模拟执行领域：风控批准的模拟订单按冻结报价计算滑点、手续费和部分成交；不连接真实交易。
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.market.contracts import ContractSymbol
from app.risk.contracts import RiskDecision
from app.strategy.contracts import IntentAction, TradeIntent


# OrderStatus 固定可用枚举值：PENDING、FILLED、PARTIALLY_FILLED；外部数据不能自行增加状态或动作。
class OrderStatus(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"


# 模拟滑点、手续费与填充比例配置，以有限 Decimal 约束各比例范围。
class ExecutionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fee_rate: Decimal
    slippage_rate: Decimal
    fill_ratio: Decimal

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：手续费率必须大于等于零且小于一；滑点率必须大于等于零且小于一；
    # 填充比例必须大于零且不超过一。
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


# 静态交易标的的冻结报价，要求正有限价格、UTC 时刻和正确抓取时序。
class ExecutionQuote(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: ContractSymbol
    price: Decimal
    observed_at: datetime
    fetched_at: datetime
    source: str

    # 校验price 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：行情报价价格必须为正的有限十进制数。
    @field_validator("price")
    @classmethod
    def validate_price(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= Decimal("0"):
            raise ValueError("行情报价价格必须为正的有限十进制数")
        return value

    # 校验observed_at、fetched_at 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：行情报价时间必须是 UTC 且带时区。
    @field_validator("observed_at", "fetched_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("行情报价时间必须是 UTC 且带时区")
        return value

    # 校验source 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：行情报价来源不能为空。
    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("行情报价来源不能为空")
        return normalized

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：行情报价获取时间不能早于观察时间。
    @model_validator(mode="after")
    def validate_fetched_at(self) -> ExecutionQuote:
        if self.fetched_at < self.observed_at:
            raise ValueError("行情报价获取时间不能早于观察时间")
        return self


# 风控批准后形成的本地模拟订单，保留申请数量、提交时刻与幂等关联。
class SimulatedOrder(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    symbol: ContractSymbol
    action: IntentAction
    idempotency_key: str
    submitted_at: datetime
    requested_quantity: Decimal
    status: OrderStatus = OrderStatus.PENDING

    # 校验idempotency_key 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：幂等键不能为空。
    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("幂等键不能为空")
        return normalized

    # 校验submitted_at 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：下单时间必须是 UTC 且带时区。
    @field_validator("submitted_at")
    @classmethod
    def validate_submitted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("下单时间必须是 UTC 且带时区")
        return value

    # 校验requested_quantity 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：请求数量必须为正的有限十进制数。
    @field_validator("requested_quantity")
    @classmethod
    def validate_requested_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= Decimal("0"):
            raise ValueError("请求数量必须为正的有限十进制数")
        return value

    # 以开多动作识别买入方向，供模拟器选择对账户不利的滑点符号。
    @property
    def is_buy(self) -> bool:
        return self.action is IntentAction.OPEN_LONG

    # 仅在风控批准且具有数量时由意图构造模拟订单，沿用运行与幂等关联信息。
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


# 模拟成交结果，保存请求和实际数量、价格、费用及与数量一致的成交状态。
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

    # 校验submitted_at、filled_at 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：成交时间必须是 UTC 且带时区。
    @field_validator("submitted_at", "filled_at")
    @classmethod
    def validate_fill_times(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("成交时间必须是 UTC 且带时区")
        return value

    # 校验requested_quantity、quantity、price、fee 字段，返回规范化值或模型；
    # 不满足约束时抛出验证错误。
    # 拒绝条件包括：模拟成交数值必须是有限非负十进制数。
    @field_validator("requested_quantity", "quantity", "price", "fee")
    @classmethod
    def validate_fill_values(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < Decimal("0"):
            raise ValueError("模拟成交数值必须是有限非负十进制数")
        return value

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：成交数量必须为正；成交价格必须为正；成交数量不能超过请求数量；
    # 全额成交必须匹配请求数量；部分成交必须小于请求数量。
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
