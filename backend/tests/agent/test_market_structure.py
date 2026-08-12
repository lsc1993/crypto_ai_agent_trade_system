from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.agent.market_structure import calculate_market_structure
from app.market.contracts import (
    Candle,
    CandleSeries,
    ContractSymbol,
    DataFreshness,
    FreshnessStatus,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.reports.contracts import TrendDirection

CAPTURED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def test_market_structure_excludes_future_candles_from_trends_and_price_zones() -> None:
    structure = calculate_market_structure(
        _detail_with_a_future_bearish_candle(),
        captured_at=CAPTURED_AT,
    )

    assert structure.trend_alignment[MarketTimeframe.H1] is TrendDirection.BULLISH
    assert structure.trend_alignment[MarketTimeframe.H4] is TrendDirection.UNKNOWN
    assert structure.confidence == "low"
    assert any(zone.lower == Decimal("95") for zone in structure.support_zones)
    assert any(zone.lower == Decimal("105") for zone in structure.resistance_zones)
    assert all(zone.lower != Decimal("1") for zone in structure.resistance_zones)
    assert all(isinstance(zone.lower, Decimal) for zone in structure.support_zones)
    assert all(isinstance(zone.upper, Decimal) for zone in structure.resistance_zones)
    assert all(zone.upper < Decimal("100") for zone in structure.support_zones)
    assert all(zone.lower > Decimal("100") for zone in structure.resistance_zones)


def _detail_with_a_future_bearish_candle() -> MarketDetail:
    return MarketDetail(
        summary=MarketSummary(
            symbol=ContractSymbol.BTCUSDT,
            price=Decimal("100"),
            change_24h=Decimal("1"),
            volume_24h=Decimal("1000"),
            funding_rate=Decimal("0"),
            open_interest=Decimal("100"),
            freshness=DataFreshness(
                status=FreshnessStatus.FRESH,
                source="binance_usdm_public_rest",
                observed_at=CAPTURED_AT,
                fetched_at=CAPTURED_AT,
            ),
        ),
        series=(
            CandleSeries(
                timeframe=MarketTimeframe.H1,
                candles=tuple(
                    _candle(
                        MarketTimeframe.H1,
                        index,
                        close_price=Decimal("100") if index < 30 else Decimal("101"),
                    )
                    for index in range(50)
                )
                + (
                    _candle(
                        MarketTimeframe.H1,
                        50,
                        close_price=Decimal("1"),
                        close_at=CAPTURED_AT + timedelta(hours=1),
                    ),
                ),
            ),
            CandleSeries(
                timeframe=MarketTimeframe.H4,
                candles=tuple(
                    _candle(MarketTimeframe.H4, index, close_price=Decimal("100"))
                    for index in range(19)
                ),
            ),
            CandleSeries(
                timeframe=MarketTimeframe.M15,
                candles=tuple(_pivot_candle(index) for index in range(20)),
            ),
        ),
    )


def _candle(
    timeframe: MarketTimeframe,
    index: int,
    *,
    close_price: Decimal,
    close_at: datetime | None = None,
) -> Candle:
    duration = {
        MarketTimeframe.M15: timedelta(minutes=15),
        MarketTimeframe.H1: timedelta(hours=1),
        MarketTimeframe.H4: timedelta(hours=4),
        MarketTimeframe.D1: timedelta(days=1),
    }[timeframe]
    resolved_close_at = close_at or CAPTURED_AT - duration * (50 - index)
    return Candle(
        symbol=ContractSymbol.BTCUSDT,
        timeframe=timeframe,
        open_at=resolved_close_at - duration,
        close_at=resolved_close_at,
        open_price=close_price,
        high_price=close_price + Decimal("1"),
        low_price=max(Decimal("0"), close_price - Decimal("1")),
        close_price=close_price,
        volume=Decimal("10"),
        observed_at=resolved_close_at,
        fetched_at=CAPTURED_AT,
    )


def _pivot_candle(index: int) -> Candle:
    candle = _candle(MarketTimeframe.M15, index, close_price=Decimal("100"))
    if index % 4 == 1:
        return candle.model_copy(update={"high_price": Decimal("105")})
    if index % 4 == 3:
        return candle.model_copy(update={"low_price": Decimal("95")})
    return candle
