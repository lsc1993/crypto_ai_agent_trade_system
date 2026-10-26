# 验证技术结构、突破确认与条件计划的确定性计算。
# 固定多周期 K 线覆盖未来数据、重复记录、零量、趋势冲突和缺失真实目标。
# 计划几何、时效及十进制线协议必须同时成立，不能延伸目标来凑盈亏比。
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest

from app.agent.technical import methods as technical_methods
from app.agent.technical.engine import calculate_technical_analysis
from app.market.binance_usdm import (
    _closed_candles_from_payload,  # pyright: ignore[reportPrivateUsage]
)
from app.market.contracts import (
    Candle,
    CandleSeries,
    DataFreshness,
    FreshnessStatus,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.reports.technical import (
    TechnicalClaim,
    TechnicalNarrative,
    TechnicalPlan,
    TechnicalQuality,
    TechnicalReport,
)

NOW = datetime(2026, 8, 10, tzinfo=UTC)
DURATIONS = {
    MarketTimeframe.H1: timedelta(hours=1),
    MarketTimeframe.H4: timedelta(hours=4),
    MarketTimeframe.D1: timedelta(days=1),
}


# 固定八十根多周期行情，末根放大成交量；指定历史转折点提供真实止损与目标结构。
def _series(timeframe: MarketTimeframe, *, falling: bool = False) -> CandleSeries:
    duration = DURATIONS[timeframe]
    candles: list[Candle] = []
    for index in range(80):
        close_at = NOW - duration * (79 - index)
        if timeframe is MarketTimeframe.H1:
            price = (
                Decimal("80") + Decimal(index) * Decimal("0.3") if index < 59 else Decimal("105")
            )
            if index == 79:
                price = Decimal("106.2")
        else:
            price = Decimal("80") + Decimal(index) * Decimal("0.3")
        if falling:
            price = Decimal("200") - price
        high = price + Decimal("1")
        low = price - Decimal("1")
        if timeframe is MarketTimeframe.H1 and index == 70:
            low = Decimal("98") if not falling else low
            high = Decimal("102") if falling else high
        if timeframe is MarketTimeframe.H4 and index == 64:
            high = Decimal("125") if not falling else high
            low = Decimal("75") if falling else low
        candles.append(
            Candle(
                symbol="BTCUSDT",
                timeframe=timeframe,
                open_at=close_at - duration,
                close_at=close_at,
                open_price=price,
                high_price=high,
                low_price=low,
                close_price=price,
                volume=Decimal("200") if index == 79 else Decimal("100"),
                observed_at=close_at,
                fetched_at=NOW,
            )
        )
    return CandleSeries(timeframe=timeframe, candles=tuple(candles))


# 将统一时刻的摘要和多周期样本组装为基线，反向模式复用同样结构检验空头路径。
def make_technical_detail(*, falling: bool = False) -> MarketDetail:
    return MarketDetail(
        summary=MarketSummary(
            symbol="BTCUSDT",
            price=Decimal("93.8") if falling else Decimal("106.2"),
            change_24h=Decimal("0"),
            volume_24h=Decimal("1000"),
            funding_rate=Decimal("0"),
            open_interest=Decimal("100"),
            freshness=DataFreshness(
                status=FreshnessStatus.FRESH,
                source="test-public-source",
                observed_at=NOW,
                fetched_at=NOW,
            ),
        ),
        series=tuple(_series(timeframe, falling=falling) for timeframe in DURATIONS),
    )


_detail = make_technical_detail


def _replace_series(
    detail: MarketDetail, timeframe: MarketTimeframe, candles: tuple[Candle, ...]
) -> MarketDetail:
    return detail.model_copy(
        update={
            "series": tuple(
                CandleSeries(timeframe=timeframe, candles=candles)
                if series.timeframe is timeframe
                else series
                for series in detail.series
            )
        }
    )


# 突破、量能与历史目标一起成立才生成候选，成本后的盈亏比仍必须由 Decimal 算得。
def test_confirmed_long_uses_prior_range_volume_and_real_target() -> None:
    analysis = calculate_technical_analysis(_detail(), captured_at=NOW)

    assert analysis.quality.status == "valid"
    assert analysis.facts is not None
    assert analysis.facts.volume_ratio == Decimal("2")
    assert analysis.facts.volume_signal == "high"
    assert analysis.facts.breakout == "long"
    assert len(analysis.plans) == 1
    plan = analysis.plans[0]
    assert plan.direction == "long"
    assert plan.state == "triggered"
    assert plan.target == Decimal("125")
    assert plan.entry_upper >= Decimal("106.2")
    assert plan.stop_loss < plan.entry_lower
    assert plan.reward_risk >= Decimal("1.5")
    # This fixed fixture gives about 1.99 before costs at the adverse entry.
    # Both sides' explicit fee and slippage assumptions lower it below 1.95.
    assert Decimal("1.9") < plan.reward_risk < Decimal("1.95")
    assert plan.fee_rate_per_side == Decimal("0.0005")
    assert plan.slippage_rate_per_side == Decimal("0.0005")
    assert plan.valid_until == NOW + timedelta(hours=4)


# 未来 K 线同时改极端价格和成交量，完整分析应与基线相同而不只是候选方向相同。
def test_future_candle_cannot_change_analysis() -> None:
    detail = _detail()
    original = calculate_technical_analysis(detail, captured_at=NOW)
    hourly = detail.series[0].candles
    future = hourly[-1].model_copy(
        update={
            "open_at": NOW,
            "close_at": NOW + timedelta(hours=1),
            "close_price": Decimal("1"),
            "low_price": Decimal("1"),
            "high_price": Decimal("200"),
            "volume": Decimal("99999"),
        }
    )
    changed = calculate_technical_analysis(
        _replace_series(detail, MarketTimeframe.H1, hourly + (future,)), captured_at=NOW
    )

    # 比较整个结果，覆盖事实、质量、证据身份与计划，而非仅判断方向。
    assert changed == original


@pytest.mark.parametrize("falling", [False, True])
@pytest.mark.parametrize("current_price", ["70", "100", "140"])
def test_latest_price_outside_triggered_entry_band_suppresses_plan(
    falling: bool, current_price: str
) -> None:
    detail = _detail(falling=falling)
    detail = detail.model_copy(
        update={"summary": detail.summary.model_copy(update={"price": Decimal(current_price)})}
    )
    analysis = calculate_technical_analysis(detail, captured_at=NOW)
    assert analysis.quality.status == "valid"
    assert analysis.plans == ()
    assert "current_price_invalidates_plan" in analysis.no_plan_reasons


# 分别注入重复、缺口、过期、错标的和样本不足，数据质量失败时连事实也不能伪装正常。
@pytest.mark.parametrize("defect", ["duplicate", "gap", "stale", "wrong_symbol", "short"])
def test_bad_candle_coverage_yields_no_plan(defect: str) -> None:
    detail = _detail()
    candles = detail.series[0].candles
    if defect == "duplicate":
        candles = candles[:30] + (candles[29],) + candles[30:]
    elif defect == "gap":
        candles = candles[:30] + candles[31:]
    elif defect == "stale":
        candles = candles[:-2]
    elif defect == "wrong_symbol":
        candles = candles[:-1] + (candles[-1].model_copy(update={"symbol": "ETHUSDT"}),)
    else:
        candles = candles[-59:]
    detail = _replace_series(detail, MarketTimeframe.H1, candles)

    analysis = calculate_technical_analysis(detail, captured_at=NOW)

    assert analysis.quality.status == "invalid"
    assert analysis.plans == ()
    assert analysis.facts is None
    assert analysis.no_plan_reasons


def test_trend_conflict_suppresses_plan() -> None:
    detail = _detail()
    daily = _series(MarketTimeframe.D1, falling=True)
    detail = _replace_series(detail, MarketTimeframe.D1, daily.candles)

    analysis = calculate_technical_analysis(detail, captured_at=NOW)

    assert analysis.quality.status == "valid"
    assert analysis.plans == ()
    assert "trend_conflict" in analysis.no_plan_reasons


def test_confirmed_short_uses_lower_structural_target() -> None:
    analysis = calculate_technical_analysis(_detail(falling=True), captured_at=NOW)

    assert analysis.quality.status == "valid"
    assert analysis.facts is not None
    assert analysis.facts.breakout == "short"
    assert len(analysis.plans) == 1
    plan = analysis.plans[0]
    assert plan.direction == "short"
    assert plan.state == "triggered"
    assert plan.target == Decimal("75")
    assert plan.stop_loss > plan.entry_upper
    assert plan.reward_risk >= Decimal("1.5")


def test_stale_summary_cannot_create_plan() -> None:
    detail = _detail()
    detail = detail.model_copy(
        update={
            "summary": detail.summary.model_copy(
                update={
                    "freshness": detail.summary.freshness.model_copy(
                        update={"status": FreshnessStatus.STALE}
                    )
                }
            )
        }
    )

    analysis = calculate_technical_analysis(detail, captured_at=NOW)

    assert analysis.quality.status == "invalid"
    assert analysis.plans == ()


def test_future_dated_source_observation_cannot_create_plan() -> None:
    detail = _detail()
    detail = detail.model_copy(
        update={
            "summary": detail.summary.model_copy(
                update={
                    "freshness": detail.summary.freshness.model_copy(
                        update={"observed_at": NOW + timedelta(minutes=1)}
                    )
                }
            )
        }
    )

    analysis = calculate_technical_analysis(detail, captured_at=NOW)

    assert analysis.quality.status == "invalid"
    assert analysis.plans == ()


# 来源时间与当前时刻直接比较，不能单凭上游自报新鲜标记放行旧数据。
def test_stale_source_observation_cannot_create_plan_despite_fresh_flag() -> None:
    detail = _detail()
    detail = detail.model_copy(
        update={
            "summary": detail.summary.model_copy(
                update={
                    "freshness": detail.summary.freshness.model_copy(
                        update={"observed_at": NOW - timedelta(hours=2)}
                    )
                }
            )
        }
    )

    analysis = calculate_technical_analysis(detail, captured_at=NOW)

    assert analysis.quality.status == "invalid"
    assert analysis.plans == ()


def test_zero_volume_baseline_cannot_confirm_breakout_or_plan() -> None:
    detail = _detail()
    hourly = detail.series[0].candles
    zeroed = tuple(candle.model_copy(update={"volume": Decimal("0")}) for candle in hourly[-21:-1])
    detail = _replace_series(detail, MarketTimeframe.H1, hourly[:-21] + zeroed + hourly[-1:])

    analysis = calculate_technical_analysis(detail, captured_at=NOW)

    assert analysis.quality.status == "invalid"
    assert analysis.facts is None
    assert analysis.plans == ()


# 重建交易所闭区间末毫秒格式，验证适配后的结束时间正好落在连续周期边界。
def test_binance_inclusive_close_time_normalizes_to_contiguous_closed_candles() -> None:
    detail = _detail()
    normalized: list[CandleSeries] = []
    for series in detail.series:
        raw = [
            [
                int(candle.open_at.timestamp() * 1000),
                str(candle.open_price),
                str(candle.high_price),
                str(candle.low_price),
                str(candle.close_price),
                str(candle.volume),
                int((candle.close_at - timedelta(milliseconds=1)).timestamp() * 1000),
            ]
            for candle in series.candles
        ]
        normalized.append(
            CandleSeries(
                timeframe=series.timeframe,
                candles=_closed_candles_from_payload(
                    raw,
                    symbol="BTCUSDT",
                    timeframe=series.timeframe,
                    fetched_at=NOW,
                ),
            )
        )
    detail = detail.model_copy(update={"series": tuple(normalized)})

    analysis = calculate_technical_analysis(detail, captured_at=NOW)

    assert analysis.quality.status == "valid"
    assert len(analysis.plans) == 1


# 将重复藏在指标窗口之前，避免只验证最近窗口而冻结证据仍包含坏行。
def test_duplicate_older_than_latest_sixty_is_rejected() -> None:
    detail = _detail()
    hourly = detail.series[0].candles
    detail = _replace_series(detail, MarketTimeframe.H1, hourly[:5] + (hourly[4],) + hourly[5:])

    analysis = calculate_technical_analysis(detail, captured_at=NOW)

    assert analysis.quality.status == "invalid"
    assert analysis.plans == ()


def test_low_volume_breakout_yields_no_plan() -> None:
    detail = _detail()
    hourly = detail.series[0].candles
    signal = hourly[-1].model_copy(update={"volume": Decimal("50")})
    detail = _replace_series(detail, MarketTimeframe.H1, hourly[:-1] + (signal,))

    analysis = calculate_technical_analysis(detail, captured_at=NOW)

    assert analysis.facts is not None
    assert analysis.facts.volume_signal == "low"
    assert analysis.facts.breakout == "none"
    assert analysis.plans == ()
    assert "unconfirmed_breakout" in analysis.no_plan_reasons


@pytest.mark.parametrize(
    ("falling", "current_price"),
    [(False, "106.1"), (False, "100"), (True, "93.9"), (True, "100")],
)
def test_waiting_plan_rejects_current_price_crossing_or_leaving_boundary(
    falling: bool, current_price: str
) -> None:
    detail = _detail(falling=falling)
    hourly = detail.series[0].candles
    close = Decimal("94.3") if falling else Decimal("105.7")
    signal = hourly[-1].model_copy(update={"close_price": close})
    detail = _replace_series(detail, MarketTimeframe.H1, hourly[:-1] + (signal,))
    detail = detail.model_copy(
        update={"summary": detail.summary.model_copy(update={"price": Decimal(current_price)})}
    )
    analysis = calculate_technical_analysis(detail, captured_at=NOW)
    assert analysis.plans == ()
    assert analysis.no_plan_reasons == ("current_price_invalidates_plan",)


# 当前价格接近边界只能产生待确认候选，必须等待后续已收盘量价突破。
def test_waiting_plan_requires_subsequent_closed_breakout() -> None:
    detail = _detail()
    detail = detail.model_copy(
        update={"summary": detail.summary.model_copy(update={"price": Decimal("105.7")})}
    )
    hourly = detail.series[0].candles
    signal = hourly[-1].model_copy(update={"close_price": Decimal("105.7")})
    detail = _replace_series(detail, MarketTimeframe.H1, hourly[:-1] + (signal,))

    analysis = calculate_technical_analysis(detail, captured_at=NOW)

    assert analysis.facts is not None
    assert analysis.facts.breakout == "none"
    assert len(analysis.plans) == 1
    assert analysis.plans[0].state == "awaiting_confirmation"
    assert analysis.plans[0].trigger_level == Decimal("106")
    assert analysis.plans[0].rationale == "awaiting_closed_volume_breakout_with_structural_target"


def test_missing_structural_target_suppresses_plan() -> None:
    detail = _detail()
    four_hour = detail.series[1].candles
    four_hour = (
        four_hour[:64]
        + (
            four_hour[64].model_copy(
                update={"high_price": four_hour[64].close_price + Decimal("1")}
            ),
        )
        + four_hour[65:]
    )
    detail = _replace_series(detail, MarketTimeframe.H4, four_hour)

    analysis = calculate_technical_analysis(detail, captured_at=NOW)

    assert analysis.plans == ()
    assert "no_structural_target" in analysis.no_plan_reasons


# 拉近真实目标后应取消低盈亏比候选，算法不能编造更远目标凑条件。
def test_near_structural_target_is_not_extended_to_meet_reward_risk() -> None:
    detail = _detail()
    four_hour = detail.series[1].candles
    changed = four_hour[64].model_copy(update={"high_price": Decimal("113")})
    detail = _replace_series(
        detail, MarketTimeframe.H4, four_hour[:64] + (changed,) + four_hour[65:]
    )

    analysis = calculate_technical_analysis(detail, captured_at=NOW)

    # 真实目标太近应不给计划，不能延伸目标来满足最低收益风险要求。
    assert analysis.plans == ()
    assert "reward_risk_below_minimum" in analysis.no_plan_reasons


def test_public_report_serializes_financial_values_as_strings_without_candles() -> None:
    analysis = calculate_technical_analysis(_detail(), captured_at=NOW)
    payload = analysis.model_dump(mode="json")

    assert isinstance(payload["facts"]["volumeRatio"], str)
    assert isinstance(payload["plans"][0]["entryUpper"], str)
    assert len(payload["plans"][0]["entryUpper"].partition(".")[2]) <= 18
    assert len(payload["plans"][0]["rewardRisk"].partition(".")[2]) <= 18
    assert len(payload["facts"]["atr14"].partition(".")[2]) <= 18
    assert "candles" not in str(payload).lower()
    assert len(payload["methods"]) >= 3


def test_plan_contract_rejects_binary_float_price() -> None:
    plan = calculate_technical_analysis(_detail(), captured_at=NOW).plans[0]
    payload = plan.model_dump(mode="python", by_alias=False)
    payload["entry_lower"] = 106.0

    with pytest.raises(ValueError):
        TechnicalPlan.model_validate(payload)


# 价格在内部 Decimal 可区分也不够，序列化精度不能把入场区间压成同价或放大溢出。
@pytest.mark.parametrize(
    ("stop", "lower", "upper", "target"),
    [
        (
            "0.0000000000000000001",
            "0.0000000000000000006",
            "0.0000000000000000007",
            "0.000000000000000002",
        ),
        (
            "0.0000000000000000006",
            "0.0000000000000000014",
            "0.00000000000000000149",
            "0.0000000000000000021",
        ),
        ("97", "106", "107", "1e38"),
    ],
)
def test_plan_rejects_prices_that_collapse_or_exceed_wire_precision(
    stop: str, lower: str, upper: str, target: str
) -> None:
    plan = calculate_technical_analysis(_detail(), captured_at=NOW).plans[0]
    payload = plan.model_dump(mode="python", by_alias=False)
    payload.update(
        stop_loss=Decimal(stop),
        entry_lower=Decimal(lower),
        trigger_level=Decimal(lower),
        entry_upper=Decimal(upper),
        target=Decimal(target),
    )

    with pytest.raises(ValueError):
        TechnicalPlan.model_validate(payload)


def test_tiny_valid_market_prices_yield_explicit_no_plan_reason() -> None:
    detail = _detail()
    factor = Decimal("1e-22")
    detail = detail.model_copy(
        update={
            "summary": detail.summary.model_copy(update={"price": detail.summary.price * factor}),
            "series": tuple(
                CandleSeries(
                    timeframe=series.timeframe,
                    candles=tuple(
                        candle.model_copy(
                            update={
                                name: getattr(candle, name) * factor
                                for name in ("open_price", "high_price", "low_price", "close_price")
                            }
                        )
                        for candle in series.candles
                    ),
                )
                for series in detail.series
            ),
        }
    )

    analysis = calculate_technical_analysis(detail, captured_at=NOW)

    assert analysis.plans == ()
    assert "unsupported_price_precision" in analysis.no_plan_reasons


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("direction", "none"),
        ("state", "unknown"),
        ("entry_lower", Decimal("0")),
        ("entry_lower", Decimal("200")),
        ("stop_loss", Decimal("120")),
        ("target", Decimal("100")),
        ("reward_risk", Decimal("-1")),
        ("fee_rate_per_side", Decimal("-0.001")),
        ("slippage_rate_per_side", Decimal("-0.001")),
        ("valid_until", NOW.replace(tzinfo=None)),
    ],
)
def test_public_plan_rejects_invalid_geometry_or_timestamp(field: str, value: object) -> None:
    plan = calculate_technical_analysis(_detail(), captured_at=NOW).plans[0]
    payload = plan.model_dump(mode="python", by_alias=False)
    payload[field] = value

    with pytest.raises(ValueError):
        TechnicalPlan.model_validate(payload)


def test_quality_rejects_naive_latest_close_timestamp() -> None:
    analysis = calculate_technical_analysis(_detail(), captured_at=NOW)
    payload = analysis.quality.model_dump(mode="python", by_alias=False)
    payload["latest_closed_at"] = {"1h": NOW.replace(tzinfo=None)}

    with pytest.raises(ValueError):
        TechnicalQuality.model_validate(payload)


def test_report_status_requires_matching_narrative_and_error() -> None:
    analysis = calculate_technical_analysis(_detail(), captured_at=NOW)
    claim = TechnicalClaim(
        text="量价结构可能延续但仍需后续确认。", evidence_ids=(analysis.evidence_id,)
    )
    narrative = TechnicalNarrative(thesis=claim, alternative=claim, risks=(claim,))
    base = {
        "id": uuid4(),
        "analysis_id": uuid4(),
        "symbol": "BTCUSDT",
        "created_at": NOW,
        "data_cutoff_at": NOW,
        "analysis": analysis,
    }

    with pytest.raises(ValueError):
        TechnicalReport.model_validate(
            {**base, "status": "degraded", "narrative": None, "error_code": None}
        )
    with pytest.raises(ValueError):
        TechnicalReport.model_validate(
            {
                **base,
                "status": "completed",
                "narrative": narrative,
                "error_code": "model_timeout",
            }
        )


def test_method_version_rejects_tampered_adapted_text(monkeypatch: pytest.MonkeyPatch) -> None:
    original = cast(Callable[[str], str], getattr(technical_methods, "_text"))

    def tampered(method_id: str) -> str:
        return original(method_id) + "\nunreviewed change"

    monkeypatch.setattr(
        technical_methods,
        "_text",
        tampered,
    )

    with pytest.raises(ValueError, match="指纹"):
        technical_methods.selected_methods()
