from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.market.contracts import Candle, MarketDetail, MarketTimeframe
from app.reports.contracts import PriceZone, TrendDirection

_SMA_SHORT_PERIOD = 20
_SMA_LONG_PERIOD = 50
_ATR_PERIOD = 14
_MAX_ZONES_PER_TIMEFRAME = 3


class MarketStructure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trend_alignment: dict[MarketTimeframe, TrendDirection]
    support_zones: tuple[PriceZone, ...]
    resistance_zones: tuple[PriceZone, ...]
    confidence: Literal["low", "medium", "high"]


def calculate_market_structure(
    detail: MarketDetail,
    *,
    captured_at: datetime,
) -> MarketStructure:
    _require_utc(captured_at)
    trend_alignment = {timeframe: TrendDirection.UNKNOWN for timeframe in MarketTimeframe}
    support_zones: list[PriceZone] = []
    resistance_zones: list[PriceZone] = []

    for series in detail.series:
        closed = tuple(candle for candle in series.candles if candle.close_at <= captured_at)
        trend_alignment[series.timeframe] = _trend_from_sma_20_50(closed)
        support, resistance = _pivot_zones(
            closed,
            timeframe=series.timeframe,
            current_price=detail.summary.price,
        )
        support_zones.extend(support)
        resistance_zones.extend(resistance)

    return MarketStructure(
        trend_alignment=trend_alignment,
        support_zones=tuple(support_zones),
        resistance_zones=tuple(resistance_zones),
        confidence=_confidence(trend_alignment),
    )


def _trend_from_sma_20_50(candles: tuple[Candle, ...]) -> TrendDirection:
    if len(candles) < _SMA_LONG_PERIOD:
        return TrendDirection.UNKNOWN
    short_sma = sum(candle.close_price for candle in candles[-_SMA_SHORT_PERIOD:]) / Decimal(
        _SMA_SHORT_PERIOD
    )
    long_sma = sum(candle.close_price for candle in candles[-_SMA_LONG_PERIOD:]) / Decimal(
        _SMA_LONG_PERIOD
    )
    if short_sma > long_sma:
        return TrendDirection.BULLISH
    if short_sma < long_sma:
        return TrendDirection.BEARISH
    return TrendDirection.NEUTRAL


def _pivot_zones(
    candles: tuple[Candle, ...],
    *,
    timeframe: MarketTimeframe,
    current_price: Decimal,
) -> tuple[tuple[PriceZone, ...], tuple[PriceZone, ...]]:
    tolerance = _atr14(candles)
    if tolerance is None:
        return (), ()
    support_pivots: list[tuple[datetime, Decimal]] = []
    resistance_pivots: list[tuple[datetime, Decimal]] = []
    for previous, current, following in zip(candles, candles[1:], candles[2:]):
        if current.low_price <= previous.low_price and current.low_price <= following.low_price:
            if current.low_price < current_price:
                support_pivots.append((current.close_at, current.low_price))
        if current.high_price >= previous.high_price and current.high_price >= following.high_price:
            if current.high_price > current_price:
                resistance_pivots.append((current.close_at, current.high_price))
    return (
        _cluster_pivot_zones(
            support_pivots,
            tolerance=tolerance / Decimal("4"),
            timeframe=timeframe,
            rationale="closed-candle support pivot cluster",
        ),
        _cluster_pivot_zones(
            resistance_pivots,
            tolerance=tolerance / Decimal("4"),
            timeframe=timeframe,
            rationale="closed-candle resistance pivot cluster",
        ),
    )


def _atr14(candles: tuple[Candle, ...]) -> Decimal | None:
    if len(candles) < _ATR_PERIOD + 1:
        return None
    true_ranges = tuple(
        max(
            current.high_price - current.low_price,
            abs(current.high_price - previous.close_price),
            abs(current.low_price - previous.close_price),
        )
        for previous, current in zip(candles, candles[1:])
    )
    return sum(true_ranges[-_ATR_PERIOD:]) / Decimal(_ATR_PERIOD)


def _cluster_pivot_zones(
    pivots: list[tuple[datetime, Decimal]],
    *,
    tolerance: Decimal,
    timeframe: MarketTimeframe,
    rationale: str,
) -> tuple[PriceZone, ...]:
    if not pivots:
        return ()
    clusters: list[list[tuple[datetime, Decimal]]] = []
    for pivot in sorted(pivots, key=lambda item: item[1]):
        if clusters and pivot[1] - clusters[-1][-1][1] <= tolerance:
            clusters[-1].append(pivot)
        else:
            clusters.append([pivot])
    zones = tuple(
        (
            max(timestamp for timestamp, _ in cluster),
            PriceZone(
                lower=min(price for _, price in cluster),
                upper=max(price for _, price in cluster),
                timeframe=timeframe,
                rationale=rationale,
            ),
        )
        for cluster in clusters
    )
    most_recent = sorted(zones, key=lambda item: item[0], reverse=True)[:_MAX_ZONES_PER_TIMEFRAME]
    return tuple(zone for _, zone in sorted(most_recent, key=lambda item: item[0]))


def _confidence(
    trends: dict[MarketTimeframe, TrendDirection],
) -> Literal["low", "medium", "high"]:
    known = sum(trend is not TrendDirection.UNKNOWN for trend in trends.values())
    if known == len(MarketTimeframe):
        return "high"
    if known >= 2:
        return "medium"
    return "low"


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("采集时间必须是 UTC 且带时区")
