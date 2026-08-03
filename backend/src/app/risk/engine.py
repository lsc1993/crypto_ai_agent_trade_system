from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from app.risk.contracts import (
    PortfolioSnapshot,
    RiskConfig,
    RiskDecision,
    RiskRejectionCode,
)
from app.strategy.contracts import IntentAction, TradeIntent


class RiskEngine:
    def __init__(self, config: RiskConfig) -> None:
        self._config = config

    def evaluate(
        self,
        intent: TradeIntent,
        portfolio: PortfolioSnapshot,
        close_price: Decimal,
    ) -> RiskDecision:
        if close_price <= Decimal("0"):
            return RiskDecision(
                approved=False,
                reason=RiskRejectionCode.INVALID_MARK_PRICE,
            )
        if intent.action is IntentAction.CLOSE_LONG:
            if portfolio.position_quantity <= Decimal("0"):
                return RiskDecision(
                    approved=False,
                    reason=RiskRejectionCode.NO_OPEN_POSITION,
                )
            return RiskDecision(approved=True, quantity=portfolio.position_quantity)

        if self._circuit_breaker_triggered(portfolio):
            return RiskDecision(
                approved=False,
                reason=RiskRejectionCode.CIRCUIT_BREAKER,
            )
        if portfolio.position_quantity > Decimal("0"):
            return RiskDecision(
                approved=False,
                reason=RiskRejectionCode.POSITION_ALREADY_OPEN,
            )
        if portfolio.cooldown_remaining > 0:
            return RiskDecision(
                approved=False,
                reason=RiskRejectionCode.COOLDOWN,
            )
        if portfolio.daily_realized_loss >= (
            portfolio.daily_start_equity * self._config.daily_loss_fraction
        ):
            return RiskDecision(
                approved=False,
                reason=RiskRejectionCode.DAILY_LOSS_LIMIT,
            )

        budget = min(
            portfolio.cash,
            portfolio.equity * self._config.max_exposure_fraction,
        )
        quantity = (budget / close_price).quantize(
            self._config.quantity_increment,
            rounding=ROUND_DOWN,
        )
        return RiskDecision(approved=True, quantity=quantity)

    def stop_loss_triggered(
        self,
        portfolio: PortfolioSnapshot,
        *,
        close_price: Decimal,
    ) -> bool:
        if portfolio.position_quantity <= Decimal("0") or portfolio.entry_price is None:
            return False
        threshold = portfolio.entry_price * (Decimal("1") - self._config.stop_loss_fraction)
        return close_price <= threshold

    def _circuit_breaker_triggered(self, portfolio: PortfolioSnapshot) -> bool:
        if portfolio.peak_equity <= Decimal("0"):
            return False
        drawdown = (portfolio.peak_equity - portfolio.equity) / portfolio.peak_equity
        return drawdown >= self._config.max_drawdown_fraction
