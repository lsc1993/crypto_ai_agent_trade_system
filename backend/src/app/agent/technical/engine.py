"""Pure technical facts and conditional plans from frozen public candles."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

from app.agent.technical.methods import selected_methods
from app.market.contracts import Candle, FreshnessStatus, MarketDetail, MarketTimeframe
from app.reports.technical import (
    TechnicalAnalysis,
    TechnicalDirection,
    TechnicalFacts,
    TechnicalPlan,
    TechnicalQuality,
    wire_decimal_value,
    wire_plan_prices_valid,
)

_FRAMES = (MarketTimeframe.D1, MarketTimeframe.H4, MarketTimeframe.H1)
_DURATION = {
    MarketTimeframe.D1: timedelta(days=1),
    MarketTimeframe.H4: timedelta(hours=4),
    MarketTimeframe.H1: timedelta(hours=1),
}
_FEE = Decimal("0.0005")
_SLIPPAGE = Decimal("0.0005")
_MIN_REWARD_RISK = Decimal("1.5")


def calculate_technical_analysis(
    detail: MarketDetail, *, captured_at: datetime
) -> TechnicalAnalysis:
    """Analyze the latest closed, continuous 60+ candles for each required frame.

    The evidence ID fingerprints the summary and all closed rows checked for quality.
    The caller persists an immutable copy so both facts and rejections can be replayed.
    """
    if captured_at.tzinfo is None or captured_at.utcoffset() != timedelta(0):
        raise ValueError("采集时间必须是带时区的 UTC")
    frames: dict[MarketTimeframe, tuple[Candle, ...]] = {}
    counts: dict[str, int] = {}
    latest: dict[str, datetime] = {}
    reasons: list[str] = []
    if detail.summary.freshness.status is not FreshnessStatus.FRESH:
        reasons.append("market_summary_not_fresh")
    if (
        detail.summary.freshness.observed_at > captured_at
        or detail.summary.freshness.fetched_at > captured_at
    ):
        reasons.append("market_summary_future_timestamp")
    if captured_at - detail.summary.freshness.observed_at >= timedelta(hours=1):
        reasons.append("market_summary_stale_timestamp")
    for timeframe in _FRAMES:
        matching = [series for series in detail.series if series.timeframe is timeframe]
        if len(matching) != 1:
            reasons.append(f"{timeframe.value}_missing_or_duplicate_series")
            continue
        closed = tuple(candle for candle in matching[0].candles if candle.close_at <= captured_at)
        counts[timeframe.value] = len(closed)
        if closed:
            latest[timeframe.value] = closed[-1].close_at
        if len(closed) < 60:
            reasons.append(f"{timeframe.value}_insufficient_candles")
            continue
        used = closed[-60:]
        duration = _DURATION[timeframe]
        if any(candle.symbol != detail.summary.symbol for candle in closed):
            reasons.append(f"{timeframe.value}_wrong_symbol")
        if any(
            candle.observed_at > captured_at or candle.fetched_at > captured_at for candle in closed
        ):
            reasons.append(f"{timeframe.value}_future_timestamp")
        if any(candle.close_at - candle.open_at != duration for candle in closed):
            reasons.append(f"{timeframe.value}_invalid_duration")
        if any(left.close_at != right.open_at for left, right in zip(closed, closed[1:])):
            reasons.append(f"{timeframe.value}_gap_or_duplicate")
        if captured_at - used[-1].close_at >= duration:
            reasons.append(f"{timeframe.value}_stale")
        if timeframe is MarketTimeframe.H1 and not any(
            candle.volume > 0 for candle in used[-21:-1]
        ):
            reasons.append("1h_zero_volume_baseline")
        if any(
            not _wire_positive_price(price)
            for candle in used
            for price in (
                candle.open_price,
                candle.high_price,
                candle.low_price,
                candle.close_price,
            )
        ):
            reasons.append("unsupported_price_precision")
        frames[timeframe] = used
    if not _wire_positive_price(detail.summary.price):
        reasons.append("unsupported_price_precision")

    evidence_id = _evidence_id(detail, captured_at)
    quality = TechnicalQuality(
        status="invalid" if reasons else "valid",
        reasons=tuple(reasons),
        candle_counts=counts,
        latest_closed_at=latest,
    )
    if reasons:
        return TechnicalAnalysis(
            quality=quality,
            facts=None,
            plans=(),
            no_plan_reasons=tuple(reasons),
            methods=selected_methods(),
            evidence_id=evidence_id,
        )

    hourly = frames[MarketTimeframe.H1]
    signal = hourly[-1]
    prior = hourly[-21:-1]
    average_volume = sum((candle.volume for candle in prior), Decimal(0)) / Decimal(20)
    volume_ratio = signal.volume / average_volume if average_volume > 0 else Decimal(0)
    volume_signal = (
        "high"
        if volume_ratio >= Decimal("1.5")
        else ("low" if volume_ratio < Decimal("0.7") else "ordinary")
    )
    span = signal.high_price - signal.low_price
    body = abs(signal.close_price - signal.open_price)
    small_body = span > 0 and body / span <= Decimal("0.3")
    upper_wick = signal.high_price - max(signal.open_price, signal.close_price)
    lower_wick = min(signal.open_price, signal.close_price) - signal.low_price
    long_upper_wick = upper_wick > 0 and upper_wick >= body * 2
    long_lower_wick = lower_wick > 0 and lower_wick >= body * 2
    sma20 = {frame.value: _sma(candles, 20) for frame, candles in frames.items()}
    sma50 = {frame.value: _sma(candles, 50) for frame, candles in frames.items()}
    trends = {
        frame.value: "bullish"
        if sma20[frame.value] > sma50[frame.value]
        else ("bearish" if sma20[frame.value] < sma50[frame.value] else "neutral")
        for frame in _FRAMES
    }
    atr = _atr(hourly)
    range_high = max(candle.high_price for candle in prior)
    range_low = min(candle.low_price for candle in prior)
    breakout = TechnicalDirection.NONE
    if volume_signal == "high" and signal.close_price > range_high:
        breakout = TechnicalDirection.LONG
    elif volume_signal == "high" and signal.close_price < range_low:
        breakout = TechnicalDirection.SHORT
    supports = tuple(sorted({price for frame in _FRAMES for price in _pivots(frames[frame])[0]}))
    resistances = tuple(sorted({price for frame in _FRAMES for price in _pivots(frames[frame])[1]}))
    facts = TechnicalFacts(
        trend_alignment=trends,
        sma20=sma20,
        sma50=sma50,
        atr14=atr,
        range_high=range_high,
        range_low=range_low,
        volume_ratio=volume_ratio,
        volume_signal=volume_signal,
        small_body=small_body,
        long_upper_wick=long_upper_wick,
        long_lower_wick=long_lower_wick,
        breakout=breakout,
        support_levels=supports,
        resistance_levels=resistances,
    )
    plan, no_plan_reasons = _candidate_plan(facts, signal, detail.summary.price, captured_at)
    return TechnicalAnalysis(
        quality=quality,
        facts=facts,
        plans=(plan,) if plan is not None else (),
        no_plan_reasons=no_plan_reasons,
        methods=selected_methods(
            include_reversal=small_body and (long_upper_wick or long_lower_wick)
        ),
        evidence_id=evidence_id,
    )


def _candidate_plan(
    facts: TechnicalFacts, signal: Candle, current_price: Decimal, captured_at: datetime
) -> tuple[TechnicalPlan | None, tuple[str, ...]]:
    trends = set(facts.trend_alignment.values())
    if trends == {"bullish"}:
        direction = TechnicalDirection.LONG
        boundary = facts.range_high
    elif trends == {"bearish"}:
        direction = TechnicalDirection.SHORT
        boundary = facts.range_low
    else:
        return None, ("trend_conflict",)
    if facts.breakout not in {TechnicalDirection.NONE, direction}:
        return None, ("opposite_breakout",)
    if facts.atr14 <= 0:
        return None, ("insufficient_volatility",)
    if facts.breakout is TechnicalDirection.NONE and (
        (direction is TechnicalDirection.LONG and signal.close_price > boundary)
        or (direction is TechnicalDirection.SHORT and signal.close_price < boundary)
    ):
        return None, ("unconfirmed_breakout",)
    # A waiting plan is conditional on a future confirmed breakout; it is only
    # useful while price remains near the boundary and within the old range.
    triggered = facts.breakout is direction
    if not triggered and abs(signal.close_price - boundary) > facts.atr14 / 2:
        return None, ("awaiting_distant_trigger",)
    buffer = facts.atr14 / 4
    if direction is TechnicalDirection.LONG:
        entry_lower, entry_upper = boundary, boundary + buffer
        if triggered and signal.close_price > entry_upper:
            return None, ("entry_too_far_from_range",)
        supports = [price for price in facts.support_levels if price < entry_lower]
        targets = [price for price in facts.resistance_levels if price > entry_upper]
        if not supports:
            return None, ("no_structural_stop",)
        if not targets:
            return None, ("no_structural_target",)
        stop = max(supports) - buffer
        target = min(targets)
        adverse_entry = entry_upper
        gross_reward = target - adverse_entry
        gross_risk = adverse_entry - stop
    else:
        entry_lower, entry_upper = boundary - buffer, boundary
        if triggered and signal.close_price < entry_lower:
            return None, ("entry_too_far_from_range",)
        resistances = [price for price in facts.resistance_levels if price > entry_upper]
        targets = [price for price in facts.support_levels if price < entry_lower]
        if not resistances:
            return None, ("no_structural_stop",)
        if not targets:
            return None, ("no_structural_target",)
        stop = min(resistances) + buffer
        target = max(targets)
        adverse_entry = entry_lower
        gross_reward = adverse_entry - target
        gross_risk = stop - adverse_entry
    if triggered and not entry_lower <= current_price <= entry_upper:
        return None, ("current_price_invalidates_plan",)
    if not triggered and (
        abs(current_price - boundary) > facts.atr14 / 2
        or (direction is TechnicalDirection.LONG and current_price > boundary)
        or (direction is TechnicalDirection.SHORT and current_price < boundary)
    ):
        return None, ("current_price_invalidates_plan",)
    if gross_risk <= 0 or gross_reward <= 0:
        return None, ("invalid_structure",)
    # Both entry and exit carry fee and slippage assumptions; adverse entry
    # is the upper edge for longs and lower edge for shorts.
    round_trip_cost = (adverse_entry + target) * (_FEE + _SLIPPAGE)
    net_reward = gross_reward - round_trip_cost
    net_risk = gross_risk + (adverse_entry + stop) * (_FEE + _SLIPPAGE)
    reward_risk = net_reward / net_risk
    if reward_risk < _MIN_REWARD_RISK:
        return None, ("reward_risk_below_minimum",)
    if not wire_plan_prices_valid(
        direction,
        stop=stop,
        lower=entry_lower,
        trigger=boundary,
        upper=entry_upper,
        target=target,
    ) or any(wire_decimal_value(value) is None for value in (reward_risk, _FEE, _SLIPPAGE)):
        return None, ("unsupported_price_precision",)
    return TechnicalPlan(
        direction=direction,
        state="triggered" if triggered else "awaiting_confirmation",
        trigger_level=boundary,
        entry_lower=entry_lower,
        entry_upper=entry_upper,
        stop_loss=stop,
        target=target,
        reward_risk=reward_risk,
        fee_rate_per_side=_FEE,
        slippage_rate_per_side=_SLIPPAGE,
        valid_until=captured_at + timedelta(hours=4),
        rationale=(
            "closed_volume_breakout_with_structural_target"
            if triggered
            else "awaiting_closed_volume_breakout_with_structural_target"
        ),
    ), ()


def _wire_positive_price(value: Decimal) -> bool:
    rounded = wire_decimal_value(value)
    return rounded is not None and rounded > 0


def _sma(candles: tuple[Candle, ...], period: int) -> Decimal:
    return sum((candle.close_price for candle in candles[-period:]), Decimal(0)) / Decimal(period)


def _atr(candles: tuple[Candle, ...]) -> Decimal:
    true_ranges = [
        max(
            current.high_price - current.low_price,
            abs(current.high_price - previous.close_price),
            abs(current.low_price - previous.close_price),
        )
        for previous, current in zip(candles, candles[1:])
    ]
    return sum(true_ranges[-14:], Decimal(0)) / Decimal(14)


def _pivots(candles: tuple[Candle, ...]) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...]]:
    lows: list[Decimal] = []
    highs: list[Decimal] = []
    for previous, current, following in zip(candles, candles[1:], candles[2:]):
        if current.low_price < previous.low_price and current.low_price < following.low_price:
            lows.append(current.low_price)
        if current.high_price > previous.high_price and current.high_price > following.high_price:
            highs.append(current.high_price)
    return tuple(lows), tuple(highs)


def _evidence_id(detail: MarketDetail, captured_at: datetime) -> UUID:
    payload = {
        "summary": detail.summary.model_dump(mode="json"),
        "capturedAt": captured_at.astimezone(UTC).isoformat(),
        "series": [
            {
                "timeframe": series.timeframe.value,
                "candles": [
                    candle.model_dump(mode="json")
                    for candle in series.candles
                    if candle.close_at <= captured_at
                ],
            }
            for series in detail.series
            if series.timeframe in _FRAMES
        ],
    }
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return uuid5(NAMESPACE_URL, digest)
