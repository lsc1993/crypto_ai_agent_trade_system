# 以本次截止前已收盘的行情计算确定性趋势和支撑阻力，不读取外部资源。
# 区间与置信度来自数据覆盖和固定指标，模型只解释结果，不能改写计算值。
"""确定性市场结构计算模块。

数据流：冻结且已收盘的多周期 K 线 → SMA 趋势、ATR 容差和枢轴价格区间 → 结构化
趋势、支撑阻力与置信度。此模块不访问网络，也不调用语言模型。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.market.contracts import Candle, MarketDetail, MarketTimeframe
from app.reports.contracts import PriceZone, TrendDirection

# 短长均线比较的是固定窗口趋势，不对未来价格或收益作估计。
_SMA_SHORT_PERIOD = 20
_SMA_LONG_PERIOD = 50
_ATR_PERIOD = 14
_MAX_ZONES_PER_TIMEFRAME = 3


# 提供冻结的多周期趋势、有限价格区间及覆盖等级，作为模型提案的确定性约束。
class MarketStructure(BaseModel):
    """供报告和模型提案使用的确定性技术结构快照。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    trend_alignment: dict[MarketTimeframe, TrendDirection]
    support_zones: tuple[PriceZone, ...]
    resistance_zones: tuple[PriceZone, ...]
    confidence: Literal["low", "medium", "high"]


# 逐周期过滤未来收盘，再计算均线与枢轴；数据不足保留未知或空区间。
def calculate_market_structure(
    detail: MarketDetail,
    *,
    captured_at: datetime,
) -> MarketStructure:
    """从多周期市场详情计算趋势、支撑/阻力区间和数据覆盖置信度。

        每个周期独立过滤采集时刻后的 K 线；数据不足时输出 UNKNOWN/空区间，而不是
        用猜测值补全。
    """
    _require_utc(captured_at)
    # 先为所有契约周期保留未知值，缺少某周期时不从其他周期推断补齐。
    trend_alignment = {timeframe: TrendDirection.UNKNOWN for timeframe in MarketTimeframe}
    support_zones: list[PriceZone] = []
    resistance_zones: list[PriceZone] = []

    # 每个周期只使用采集时刻前已收盘的数据；这与回测的无未来数据泄漏约束一致。
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

    # 统一输出各周期区间，保留周期来源，不能把不同尺度的结构当同一信号。
    return MarketStructure(
        trend_alignment=trend_alignment,
        support_zones=tuple(support_zones),
        resistance_zones=tuple(resistance_zones),
        confidence=_confidence(trend_alignment),
    )


def _trend_from_sma_20_50(candles: tuple[Candle, ...]) -> TrendDirection:
    """比较 SMA20 与 SMA50，数据不足时明确返回 UNKNOWN。"""
    # 最长窗口不完整就不比较；只满足短窗口时也不能产生看似可靠的趋势。
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
    # 两个均值恰好相等属于中性，与数据不足的未知状态含义不同。
    return TrendDirection.NEUTRAL


def _pivot_zones(
    candles: tuple[Candle, ...],
    *,
    timeframe: MarketTimeframe,
    current_price: Decimal,
) -> tuple[tuple[PriceZone, ...], tuple[PriceZone, ...]]:
    """识别当前价格两侧的三点枢轴，并返回经波动率聚类后的区间。"""
    # ATR 用作聚类容差，让价格区间随标的近期波动自动调整，而不是使用固定金额。
    tolerance = _atr14(candles)
    if tolerance is None:
        return (), ()
    support_pivots: list[tuple[datetime, Decimal]] = []
    resistance_pivots: list[tuple[datetime, Decimal]] = []
    # 三点枢轴依赖左右邻居确认；调用方已过滤未来收盘，不能使用尚未收盘邻居。
    for previous, current, following in zip(candles, candles[1:], candles[2:]):
        if current.low_price <= previous.low_price and current.low_price <= following.low_price:
            if current.low_price < current_price:
                support_pivots.append((current.close_at, current.low_price))
        if current.high_price >= previous.high_price and current.high_price >= following.high_price:
            if current.high_price > current_price:
                resistance_pivots.append((current.close_at, current.high_price))
    # 四分之一波幅用于邻近价格聚类，两侧均保留自身周期和程序理由。
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
    """计算最近 14 个真实波幅的均值，作为价格区间的动态容差。"""
    # 每个真实波幅还需前一根收盘，因此十四个样本至少需要十五根 K 线。
    if len(candles) < _ATR_PERIOD + 1:
        return None
    # 同时覆盖日内波幅和跨收盘跳空，避免只看高低差低估波动。
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
    """合并相近枢轴并保留最近有限个价格区间，避免报告被历史噪声淹没。"""
    if not pivots:
        return ()
    clusters: list[list[tuple[datetime, Decimal]]] = []
    # 按相邻价格距离连接聚类；它不是每个成员都与首个价格比较的固定半径。
    for pivot in sorted(pivots, key=lambda item: item[1]):
        if clusters and pivot[1] - clusters[-1][-1][1] <= tolerance:
            clusters[-1].append(pivot)
        else:
            clusters.append([pivot])
    # 每组以最低和最高枢轴定义价格带，以最新触点时间决定保留优先级。
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
    # 相近枢轴先合并，再只保留最近的有限个区间，避免陈旧支撑阻力主导报告。
    most_recent = sorted(zones, key=lambda item: item[0], reverse=True)[:_MAX_ZONES_PER_TIMEFRAME]
    return tuple(zone for _, zone in sorted(most_recent, key=lambda item: item[0]))


# 这里衡量可计算的周期覆盖，不能解释为方向预测成功率或收益概率。
def _confidence(
    trends: dict[MarketTimeframe, TrendDirection],
) -> Literal["low", "medium", "high"]:
    """根据有足够 K 线的周期数量给出数据覆盖等级，而非预测准确率。"""
    known = sum(trend is not TrendDirection.UNKNOWN for trend in trends.values())
    if known == len(MarketTimeframe):
        return "high"
    # 至少两个周期能计算才为中等覆盖；不要求方向一致，也不是预测胜率。
    if known >= 2:
        return "medium"
    return "low"


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("采集时间必须是 UTC 且带时区")
