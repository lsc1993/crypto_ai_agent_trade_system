from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class RiskRejectionCode(StrEnum):
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    CIRCUIT_BREAKER = "circuit_breaker"
    POSITION_ALREADY_OPEN = "position_already_open"
    COOLDOWN = "cooldown"
    INVALID_MARK_PRICE = "invalid_mark_price"
    NO_OPEN_POSITION = "no_open_position"


class RiskConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_exposure_fraction: Decimal
    stop_loss_fraction: Decimal
    daily_loss_fraction: Decimal
    max_drawdown_fraction: Decimal
    cooldown_candles: int
    quantity_increment: Decimal

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


class RiskDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    approved: bool
    reason: RiskRejectionCode | None = None
    quantity: Decimal | None = None
    risk_exit: bool = False
