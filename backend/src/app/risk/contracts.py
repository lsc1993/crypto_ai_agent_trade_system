# 风控契约：冻结安全比例、数量精度、账户快照和放行结果；配置初始化时校验范围，
# 不允许无效限制进入引擎。
# 确定性风控领域：依据账户快照、行情价格和固定配置审核意图；模型结论不能作为放行依据。
from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


# RiskRejectionCode 固定可用枚举值：DAILY_LOSS_LIMIT、CIRCUIT_BREAKER、POSITION_ALREADY_OPEN、
# COOLDOWN、INVALID_MARK_PRICE、NO_OPEN_POSITION；外部数据不能自行增加状态或动作。
class RiskRejectionCode(StrEnum):
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    CIRCUIT_BREAKER = "circuit_breaker"
    POSITION_ALREADY_OPEN = "position_already_open"
    COOLDOWN = "cooldown"
    INVALID_MARK_PRICE = "invalid_mark_price"
    NO_OPEN_POSITION = "no_open_position"


# 冻结敞口、止损、日损失、回撤、冷却与数量精度，初始化时验证安全范围。
class RiskConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_exposure_fraction: Decimal
    stop_loss_fraction: Decimal
    daily_loss_fraction: Decimal
    max_drawdown_fraction: Decimal
    cooldown_candles: int
    quantity_increment: Decimal

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：最大敞口必须大于零且不超过权益；止损比例必须大于零且小于一；
    # 日亏损比例必须大于零且小于一；最大回撤比例必须大于零且小于一；冷却 K 线数不能为负数；
    # 数量步长必须为正数。
    @model_validator(mode="after")
    def validate_safety_limits(self) -> RiskConfig:
        if not Decimal("0") < self.max_exposure_fraction <= Decimal("1"):
            raise ValueError("最大敞口必须大于零且不超过权益")
        if not Decimal("0") < self.stop_loss_fraction < Decimal("1"):
            raise ValueError("止损比例必须大于零且小于一")
        if not Decimal("0") < self.daily_loss_fraction < Decimal("1"):
            raise ValueError("日亏损比例必须大于零且小于一")
        if not Decimal("0") < self.max_drawdown_fraction < Decimal("1"):
            raise ValueError("最大回撤比例必须大于零且小于一")
        if self.cooldown_candles < 0:
            raise ValueError("冷却 K 线数不能为负数")
        if self.quantity_increment <= Decimal("0"):
            raise ValueError("数量步长必须为正数")
        return self


DEFAULT_RISK_CONFIG = RiskConfig(
    max_exposure_fraction=Decimal("0.95"),
    stop_loss_fraction=Decimal("0.05"),
    daily_loss_fraction=Decimal("0.03"),
    max_drawdown_fraction=Decimal("0.15"),
    cooldown_candles=3,
    quantity_increment=Decimal("0.000001"),
)


# 确定性审核所需现金、权益高点、日损失、持仓入场价与冷却状态快照。
class PortfolioSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cash: Decimal
    equity: Decimal
    peak_equity: Decimal
    daily_start_equity: Decimal
    daily_realized_loss: Decimal
    position_quantity: Decimal
    entry_price: Decimal | None
    cooldown_remaining: int


# 确定性审核结果，提供放行数量或拒绝原因，不创建或执行订单。
class RiskDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    approved: bool
    reason: RiskRejectionCode | None = None
    quantity: Decimal | None = None
    risk_exit: bool = False
