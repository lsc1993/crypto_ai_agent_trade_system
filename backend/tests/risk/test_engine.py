from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.market.contracts import ContractSymbol
from app.risk.contracts import (
    DEFAULT_RISK_CONFIG,
    PortfolioSnapshot,
    RiskConfig,
    RiskRejectionCode,
)
from app.risk.engine import RiskEngine
from app.strategy.contracts import IntentAction, TradeIntent

RUN_ID = UUID("00000000-0000-0000-0000-000000000501")
DECISION_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def test_risk_rejects_a_new_long_after_the_daily_loss_limit() -> None:
    decision = RiskEngine(DEFAULT_RISK_CONFIG).evaluate(
        _intent(IntentAction.OPEN_LONG),
        _portfolio(
            cash="9700",
            equity="9700",
            daily_start_equity="10000",
            daily_realized_loss="300",
        ),
        close_price=Decimal("100"),
    )

    assert decision.approved is False
    assert decision.reason is RiskRejectionCode.DAILY_LOSS_LIMIT
    assert decision.quantity is None


def test_circuit_breaker_rejects_open_but_allows_close() -> None:
    engine = RiskEngine(DEFAULT_RISK_CONFIG)
    halted = _portfolio(
        cash="8500",
        equity="8500",
        peak_equity="10000",
        position_quantity="1",
        entry_price="100",
    )

    open_decision = engine.evaluate(
        _intent(IntentAction.OPEN_LONG),
        halted,
        close_price=Decimal("100"),
    )
    close_decision = engine.evaluate(
        _intent(IntentAction.CLOSE_LONG),
        halted,
        close_price=Decimal("100"),
    )

    assert open_decision.approved is False
    assert open_decision.reason is RiskRejectionCode.CIRCUIT_BREAKER
    assert close_decision.approved is True
    assert close_decision.quantity == Decimal("1")


def test_risk_caps_open_quantity_by_available_cash_and_max_exposure() -> None:
    decision = RiskEngine(DEFAULT_RISK_CONFIG).evaluate(
        _intent(IntentAction.OPEN_LONG),
        _portfolio(cash="120", equity="10000"),
        close_price=Decimal("100"),
    )

    assert decision.approved is True
    assert decision.quantity == Decimal("1.200000")


def test_risk_rejects_a_second_position_and_cooldown_open() -> None:
    engine = RiskEngine(DEFAULT_RISK_CONFIG)
    existing_position = engine.evaluate(
        _intent(IntentAction.OPEN_LONG),
        _portfolio(cash="9000", equity="10000", position_quantity="1", entry_price="100"),
        close_price=Decimal("100"),
    )
    cooling_down = engine.evaluate(
        _intent(IntentAction.OPEN_LONG),
        _portfolio(cash="10000", equity="10000", cooldown_remaining=1),
        close_price=Decimal("100"),
    )

    assert existing_position.reason is RiskRejectionCode.POSITION_ALREADY_OPEN
    assert cooling_down.reason is RiskRejectionCode.COOLDOWN


def test_risk_triggers_stop_loss_only_at_the_configured_close_threshold() -> None:
    engine = RiskEngine(DEFAULT_RISK_CONFIG)
    position = _portfolio(
        cash="9000",
        equity="9900",
        position_quantity="1",
        entry_price="100",
    )

    assert engine.stop_loss_triggered(position, close_price=Decimal("95")) is True
    assert engine.stop_loss_triggered(position, close_price=Decimal("95.01")) is False


def test_risk_config_rejects_leverage_or_an_invalid_quantity_increment() -> None:
    with pytest.raises(ValueError, match="最大敞口"):
        RiskConfig.model_validate(
            _risk_config_values(max_exposure_fraction=Decimal("1.01"))
        )
    with pytest.raises(ValueError, match="数量步长"):
        RiskConfig.model_validate(_risk_config_values(quantity_increment=Decimal("0")))
    with pytest.raises(ValueError, match="止损"):
        RiskConfig.model_validate(_risk_config_values(stop_loss_fraction=Decimal("0")))
    with pytest.raises(ValueError, match="冷却"):
        RiskConfig.model_validate(_risk_config_values(cooldown_candles=Decimal("-1")))


def test_risk_rejects_a_non_positive_mark_price() -> None:
    decision = RiskEngine(DEFAULT_RISK_CONFIG).evaluate(
        _intent(IntentAction.OPEN_LONG),
        _portfolio(cash="10000", equity="10000"),
        close_price=Decimal("0"),
    )

    assert decision.approved is False
    assert decision.reason is RiskRejectionCode.INVALID_MARK_PRICE


def test_risk_rejects_a_close_without_an_open_position() -> None:
    decision = RiskEngine(DEFAULT_RISK_CONFIG).evaluate(
        _intent(IntentAction.CLOSE_LONG),
        _portfolio(cash="10000", equity="10000"),
        close_price=Decimal("100"),
    )

    assert decision.approved is False
    assert decision.reason is RiskRejectionCode.NO_OPEN_POSITION


def _intent(action: IntentAction) -> TradeIntent:
    return TradeIntent(
        run_id=RUN_ID,
        symbol=ContractSymbol.BTCUSDT,
        action=action,
        decision_at=DECISION_AT,
        strategy_id="sma_crossover",
        strategy_version="v1",
        idempotency_key=f"risk-test:{action.value}",
    )


def _portfolio(
    *,
    cash: str,
    equity: str,
    daily_start_equity: str = "10000",
    daily_realized_loss: str = "0",
    peak_equity: str = "10000",
    position_quantity: str = "0",
    entry_price: str | None = None,
    cooldown_remaining: int = 0,
) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        cash=Decimal(cash),
        equity=Decimal(equity),
        peak_equity=Decimal(peak_equity),
        daily_start_equity=Decimal(daily_start_equity),
        daily_realized_loss=Decimal(daily_realized_loss),
        position_quantity=Decimal(position_quantity),
        entry_price=None if entry_price is None else Decimal(entry_price),
        cooldown_remaining=cooldown_remaining,
    )


def _risk_config_values(**updates: Decimal) -> dict[str, object]:
    return {**DEFAULT_RISK_CONFIG.model_dump(), **updates}
