from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.execution.contracts import ExecutionConfig, OrderStatus, SimulatedOrder
from app.execution.simulator import SimulatedExecutionService
from app.market.contracts import Candle, ContractSymbol, MarketTimeframe
from app.risk.contracts import RiskDecision
from app.strategy.contracts import IntentAction, TradeIntent

RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
ORDERED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def test_buy_fill_applies_adverse_slippage_fee_and_partial_ratio() -> None:
    order = _approved_order(IntentAction.OPEN_LONG, quantity="2")
    fill = SimulatedExecutionService(_config(fill_ratio="0.5")).submit_and_fill(
        order,
        _candle(open_price="100"),
    )

    assert fill.price == Decimal("100.0500")
    assert fill.quantity == Decimal("1.0")
    assert fill.fee == Decimal("0.10005000")
    assert fill.status is OrderStatus.PARTIALLY_FILLED
    assert fill.order_idempotency_key == order.idempotency_key
    assert fill.submitted_at == ORDERED_AT
    assert fill.filled_at == _candle().open_at
    assert fill.requested_quantity == Decimal("2")


def test_sell_fill_uses_downward_slippage() -> None:
    fill = SimulatedExecutionService(_config()).submit_and_fill(
        _approved_order(IntentAction.CLOSE_LONG, quantity="2"),
        _candle(open_price="100"),
    )

    assert fill.price == Decimal("99.9500")
    assert fill.quantity == Decimal("2")
    assert fill.status is OrderStatus.FILLED


def test_execution_rejects_invalid_config_and_non_positive_order_inputs() -> None:
    with pytest.raises(ValidationError, match="填充比例"):
        _config(fill_ratio="0")
    with pytest.raises(ValidationError, match="请求数量"):
        SimulatedOrder(
            run_id=RUN_ID,
            symbol=ContractSymbol.BTCUSDT,
            action=IntentAction.OPEN_LONG,
            idempotency_key="backtest:601:open",
            submitted_at=ORDERED_AT,
            requested_quantity=Decimal("0"),
        )


def test_execution_rejects_a_risk_rejected_intent() -> None:
    with pytest.raises(ValueError, match="风控拒绝"):
        SimulatedOrder.from_risk_decision(
            _intent(IntentAction.OPEN_LONG),
            RiskDecision(approved=False),
            submitted_at=ORDERED_AT,
        )


def test_execution_rejects_a_non_positive_next_open_price() -> None:
    with pytest.raises(ValueError, match="开盘价"):
        SimulatedExecutionService(_config()).submit_and_fill(
            _approved_order(IntentAction.OPEN_LONG, quantity="1"),
            _candle(open_price="0"),
        )


def _config(*, fill_ratio: str = "1") -> ExecutionConfig:
    return ExecutionConfig(
        fee_rate=Decimal("0.001"),
        slippage_rate=Decimal("0.0005"),
        fill_ratio=Decimal(fill_ratio),
    )


def _approved_order(action: IntentAction, *, quantity: str) -> SimulatedOrder:
    return SimulatedOrder.from_risk_decision(
        _intent(action),
        RiskDecision(approved=True, quantity=Decimal(quantity)),
        submitted_at=ORDERED_AT,
    )


def _intent(action: IntentAction) -> TradeIntent:
    return TradeIntent(
        run_id=RUN_ID,
        symbol=ContractSymbol.BTCUSDT,
        action=action,
        decision_at=ORDERED_AT - timedelta(hours=1),
        strategy_id="sma_crossover",
        strategy_version="v1",
        idempotency_key=f"backtest:601:{action.value}",
    )


def _candle(*, open_price: str = "100") -> Candle:
    return Candle(
        symbol=ContractSymbol.BTCUSDT,
        timeframe=MarketTimeframe.H1,
        open_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        close_at=datetime(2026, 7, 1, 13, 0, tzinfo=UTC),
        open_price=Decimal(open_price),
        high_price=Decimal(open_price),
        low_price=Decimal(open_price),
        close_price=Decimal(open_price),
        volume=Decimal("10"),
        observed_at=datetime(2026, 7, 1, 13, 0, tzinfo=UTC),
        fetched_at=datetime(2026, 7, 1, 13, 0, tzinfo=UTC),
    )
