# 验证 K 线输入的研究币种、UTC 和精确十进制约束。
# 高低开收关系必须合理，浮点输入和无时区时间在模型构造时拒绝。
# 输出金额保留字符串形式，避免 HTTP 消费方引入二进制浮点误差。
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.market.contracts import (
    Candle,
    ContractSymbol,
    MarketTimeframe,
)


def valid_candle(**overrides: object) -> Candle:
    values: dict[str, object] = {
        "symbol": ContractSymbol.BTCUSDT,
        "timeframe": MarketTimeframe.M15,
        "open_at": datetime(2026, 7, 28, 0, 0, tzinfo=UTC),
        "close_at": datetime(2026, 7, 28, 0, 15, tzinfo=UTC),
        "open_price": "68000.10",
        "high_price": "68001.20",
        "low_price": "67999.90",
        "close_price": "68000.30",
        "volume": "12.34567890",
        "observed_at": datetime(2026, 7, 28, 0, 15, tzinfo=UTC),
        "fetched_at": datetime(2026, 7, 28, 0, 15, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return Candle.model_validate(values)


def test_candle_accepts_research_symbol_and_rejects_naive_time() -> None:
    candle = valid_candle(symbol="SOLUSDT")
    assert candle.symbol == "SOLUSDT"

    with pytest.raises(ValidationError):
        valid_candle(open_at=datetime(2026, 7, 28, 0, 0))


def test_candle_rejects_float_market_values() -> None:
    with pytest.raises(ValidationError):
        valid_candle(close_price=68000.3)


def test_candle_rejects_inconsistent_price_range() -> None:
    with pytest.raises(ValidationError):
        valid_candle(low_price="68000.20")


def test_candle_serializes_decimal_values_as_strings() -> None:
    candle = valid_candle()

    payload = candle.model_dump(mode="json", by_alias=True)

    assert candle.close_price == Decimal("68000.30")
    assert payload["closePrice"] == "68000.30"
    assert payload["openAt"] == "2026-07-28T00:00:00Z"
