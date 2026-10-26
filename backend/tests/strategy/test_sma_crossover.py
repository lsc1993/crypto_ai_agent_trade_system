# 验证均线交叉只使用已可观察的收盘数据。
# 固定 K 线覆盖预热、无交叉和持仓退出，策略仅输出结构化意图。
# UTC 决策时间与意图来源元数据有独立契约，手动意图不伪装为策略意图。
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.market.contracts import Candle, ContractSymbol, MarketTimeframe
from app.strategy import contracts as strategy_contracts
from app.strategy.contracts import IntentAction, TradeIntent
from app.strategy.sma_crossover import SmaCrossoverStrategy

RUN_ID = UUID("00000000-0000-0000-0000-000000000401")
START = datetime(2026, 7, 1, tzinfo=UTC)


def test_sma_crossover_emits_open_after_an_observable_upward_cross() -> None:
    candles = tuple(
        _candle(index, price) for index, price in enumerate(("100", "100", "100", "102"))
    )

    intent = SmaCrossoverStrategy(fast_window=2, slow_window=3).decide(
        run_id=RUN_ID,
        candles=candles,
        position_is_open=False,
    )

    assert intent is not None
    assert intent.action is IntentAction.OPEN_LONG
    assert intent.symbol is ContractSymbol.BTCUSDT
    assert intent.decision_at == START + timedelta(hours=4)
    assert intent.strategy_id == "sma_crossover"
    assert intent.strategy_version == "v1"
    assert intent.source is strategy_contracts.IntentSource.STRATEGY
    assert intent.idempotency_key == (
        "00000000-0000-0000-0000-000000000401:sma_crossover:v1:"
        "2026-07-01T04:00:00+00:00:open_long"
    )
    assert "quantity" not in type(intent).model_fields


def test_sma_crossover_emits_close_only_for_an_open_position_after_downward_cross() -> None:
    candles = tuple(
        _candle(index, price) for index, price in enumerate(("100", "100", "100", "98"))
    )
    strategy = SmaCrossoverStrategy(fast_window=2, slow_window=3)

    close_intent = strategy.decide(
        run_id=RUN_ID,
        candles=candles,
        position_is_open=True,
    )
    flat_intent = strategy.decide(
        run_id=RUN_ID,
        candles=candles,
        position_is_open=False,
    )

    assert close_intent is not None
    assert close_intent.action is IntentAction.CLOSE_LONG
    assert close_intent.idempotency_key.endswith(":close_long")
    assert flat_intent is None


def test_sma_crossover_does_not_emit_from_warmup_or_without_a_cross() -> None:
    strategy = SmaCrossoverStrategy(fast_window=2, slow_window=3)
    warmup = tuple(_candle(index, "100") for index in range(3))
    flat = tuple(_candle(index, "100") for index in range(4))

    assert strategy.decide(run_id=RUN_ID, candles=warmup, position_is_open=False) is None
    assert strategy.decide(run_id=RUN_ID, candles=flat, position_is_open=False) is None


def test_sma_crossover_rejects_invalid_window_order() -> None:
    with pytest.raises(ValueError, match="fast_window"):
        SmaCrossoverStrategy(fast_window=3, slow_window=3)
    with pytest.raises(ValueError, match="正整数"):
        SmaCrossoverStrategy(fast_window=0, slow_window=3)


def test_trade_intent_requires_a_utc_decision_time() -> None:
    with pytest.raises(ValueError, match="UTC"):
        TradeIntent(
            run_id=RUN_ID,
            symbol=ContractSymbol.BTCUSDT,
            action=IntentAction.OPEN_LONG,
            decision_at=datetime(2026, 7, 1),
            strategy_id="sma_crossover",
            strategy_version="v1",
            idempotency_key="intent-key",
        )


def test_manual_trade_intent_is_valid_without_strategy_metadata() -> None:
    intent = TradeIntent(
        run_id=RUN_ID,
        symbol=ContractSymbol.BTCUSDT,
        action=IntentAction.OPEN_LONG,
        decision_at=START,
        source=strategy_contracts.IntentSource.MANUAL,
        idempotency_key="paper:manual:request-1",
    )

    assert intent.source is strategy_contracts.IntentSource.MANUAL
    assert intent.strategy_id is None
    assert intent.strategy_version is None


def test_strategy_trade_intent_requires_strategy_metadata() -> None:
    with pytest.raises(ValueError, match="策略意图"):
        TradeIntent(
            run_id=RUN_ID,
            symbol=ContractSymbol.BTCUSDT,
            action=IntentAction.OPEN_LONG,
            decision_at=START,
            source=strategy_contracts.IntentSource.STRATEGY,
            idempotency_key="strategy:missing-metadata",
        )


def _candle(index: int, close_price: str) -> Candle:
    open_at = START + timedelta(hours=index)
    close_at = open_at + timedelta(hours=1)
    price = Decimal(close_price)
    return Candle(
        symbol=ContractSymbol.BTCUSDT,
        timeframe=MarketTimeframe.H1,
        open_at=open_at,
        close_at=close_at,
        open_price=price,
        high_price=price,
        low_price=price,
        close_price=price,
        volume=Decimal("1"),
        observed_at=close_at,
        fetched_at=close_at,
    )
