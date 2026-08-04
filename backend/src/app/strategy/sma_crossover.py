from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.market.contracts import Candle
from app.strategy.contracts import IntentAction, IntentSource, TradeIntent


class SmaCrossoverStrategy:
    def __init__(self, *, fast_window: int = 20, slow_window: int = 50) -> None:
        if fast_window <= 0 or slow_window <= 0:
            raise ValueError("均线窗口必须是正整数")
        if fast_window >= slow_window:
            raise ValueError("fast_window 必须小于 slow_window")
        self._fast_window = fast_window
        self._slow_window = slow_window

    def decide(
        self,
        *,
        run_id: UUID,
        candles: tuple[Candle, ...],
        position_is_open: bool,
    ) -> TradeIntent | None:
        if len(candles) < self._slow_window + 1:
            return None

        previous_fast = _sma(candles[-self._fast_window - 1 : -1])
        previous_slow = _sma(candles[-self._slow_window - 1 : -1])
        current_fast = _sma(candles[-self._fast_window :])
        current_slow = _sma(candles[-self._slow_window :])
        action = _action_for_cross(
            previous_fast=previous_fast,
            previous_slow=previous_slow,
            current_fast=current_fast,
            current_slow=current_slow,
            position_is_open=position_is_open,
        )
        if action is None:
            return None

        decision_at = candles[-1].close_at
        return TradeIntent(
            run_id=run_id,
            symbol=candles[-1].symbol,
            action=action,
            decision_at=decision_at,
            source=IntentSource.STRATEGY,
            strategy_id="sma_crossover",
            strategy_version="v1",
            idempotency_key=(
                f"{run_id}:sma_crossover:v1:{decision_at.isoformat()}:{action.value}"
            ),
        )


def _sma(candles: tuple[Candle, ...]) -> Decimal:
    return sum((candle.close_price for candle in candles), start=Decimal("0")) / len(candles)


def _action_for_cross(
    *,
    previous_fast: Decimal,
    previous_slow: Decimal,
    current_fast: Decimal,
    current_slow: Decimal,
    position_is_open: bool,
) -> IntentAction | None:
    if not position_is_open and previous_fast <= previous_slow and current_fast > current_slow:
        return IntentAction.OPEN_LONG
    if position_is_open and previous_fast >= previous_slow and current_fast < current_slow:
        return IntentAction.CLOSE_LONG
    return None
