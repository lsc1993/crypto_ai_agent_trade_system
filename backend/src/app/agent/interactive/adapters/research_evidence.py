# 将现有受治理公开行情网关适配为 T08 证据端口，并把冻结行情投影为有界公开事实。
# 本适配器只读取固定公开行情详情，不接受模型传入 URL/路径，不访问私有账户或订单接口。
# 聚合证据的 observed/available/fetched 是集合参考时刻；原始 MarketDetail 保留逐项真实时点。
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast

from pydantic import ValidationError

from app.agent_runs.evidence import EvidenceCollection, EvidenceDraft
from app.market.contracts import (
    Candle,
    CandleSeries,
    FreshnessStatus,
    MarketDetail,
    MarketTimeframe,
)
from app.market.gateway import PublicMarketGateway
from app.market.symbols import ResearchSymbol
from app.research.evidence import (
    MARKET_EVIDENCE_KIND,
    EvidenceItem,
    EvidenceQuality,
    EvidenceUnavailableError,
)
from app.shared.agent_types import JsonObject, ProductKey

MARKET_DETAIL_CALCULATION_VERSION = "market_detail_v1"


# 固定公开行情证据端口：一次读取一个标的的摘要与请求周期已收盘 K 线。
class MarketResearchEvidencePort:
    def __init__(self, market: PublicMarketGateway) -> None:
        self._market = market

    # 摘要一次 + 每个周期一次公开请求；缓存命中仍按上限保守计数，绝不低估传输预算。
    def planned_transport_calls(self, timeframes: tuple[MarketTimeframe, ...]) -> int:
        return 1 + len(timeframes)

    async def collect(
        self,
        *,
        product: ProductKey,
        timeframes: tuple[MarketTimeframe, ...],
        analysis_as_of: datetime,
    ) -> EvidenceCollection:
        detail = await self._market.get_market(product.symbol, timeframes)
        _validate_detail(detail, product.symbol, timeframes, analysis_as_of)

        observed_times = [detail.summary.freshness.observed_at]
        fetched_times = [detail.summary.freshness.fetched_at]
        for series in detail.series:
            observed_times.extend(candle.observed_at for candle in series.candles)
            fetched_times.extend(candle.fetched_at for candle in series.candles)
        observed_at = min(observed_times)
        available_at = max(observed_times)
        fetched_at = max(fetched_times)
        if fetched_at < available_at:
            raise EvidenceUnavailableError(
                "market_time_inconsistent",
                "公开行情抓取时刻早于观测时刻",
            )

        content = cast(JsonObject, detail.model_dump(mode="json"))
        return EvidenceCollection(
            items=(
                EvidenceDraft(
                    kind=MARKET_EVIDENCE_KIND,
                    source=detail.summary.freshness.source,
                    observed_at=observed_at,
                    available_at=available_at,
                    fetched_at=fetched_at,
                    quality=_quality_for(detail.summary.freshness.status),
                    calculation_version=MARKET_DETAIL_CALCULATION_VERSION,
                    content=content,
                ),
            )
        )


# 校验网关返回的详情确实覆盖请求的标的/周期，并且所有 K 线在截止时刻前已收盘。
def _validate_detail(
    detail: MarketDetail,
    symbol: ResearchSymbol,
    timeframes: tuple[MarketTimeframe, ...],
    analysis_as_of: datetime,
) -> None:
    if detail.summary.symbol != symbol:
        raise EvidenceUnavailableError("market_symbol_mismatch", "公开行情标的不一致")
    returned = tuple(series.timeframe for series in detail.series)
    if len(set(returned)) != len(returned) or set(returned) != set(timeframes):
        raise EvidenceUnavailableError("market_series_incomplete", "公开行情周期覆盖不完整")
    for series in detail.series:
        if not series.candles:
            raise EvidenceUnavailableError("market_series_empty", "公开行情周期没有 K 线")
        if series.candles[-1].close_at > analysis_as_of:
            raise EvidenceUnavailableError(
                "market_data_not_closed",
                "公开行情包含分析截止时刻之后才收盘的 K 线",
            )


# 来源新鲜度映射：只有 fresh 才是 valid；stale/missing/failed 保持真实降级。
def _quality_for(status: FreshnessStatus) -> EvidenceQuality:
    if status is FreshnessStatus.FRESH:
        return EvidenceQuality.VALID
    if status is FreshnessStatus.STALE:
        return EvidenceQuality.STALE
    if status is FreshnessStatus.MISSING:
        return EvidenceQuality.MISSING
    return EvidenceQuality.INVALID


# 将冻结 MarketDetail 投影为模型可见的公开事实文本；不读取任何本地财务资料。
# 只保留摘要与每个周期最近两根已收盘 K 线，避免把完整长序列塞进模型上下文。
class MarketEvidenceFactProjector:
    def project(self, item: EvidenceItem) -> str | None:
        if item.kind != MARKET_EVIDENCE_KIND or item.content is None:
            return None
        try:
            detail = MarketDetail.model_validate(item.content)
        except ValidationError:
            return None
        summary = detail.summary
        lines = [
            "公开行情摘要（公开数据）：",
            (
                f"symbol={summary.symbol} price={_decimal(summary.price)} "
                f"change24h={_decimal(summary.change_24h)} "
                f"volume24h={_decimal(summary.volume_24h)} "
                f"fundingRate={_decimal(summary.funding_rate)} "
                f"openInterest={_decimal(summary.open_interest)} "
                f"freshness={summary.freshness.status.value} "
                f"source={summary.freshness.source} "
                f"observedAt={summary.freshness.observed_at.isoformat()} "
                f"fetchedAt={summary.freshness.fetched_at.isoformat()}"
            ),
            "最近已收盘 K 线（每周期最多两根）：",
        ]
        for series in detail.series:
            for candle in _tail(series, limit=2):
                lines.append(
                    f"timeframe={series.timeframe.value} "
                    f"openAt={candle.open_at.isoformat()} "
                    f"closeAt={candle.close_at.isoformat()} "
                    f"open={_decimal(candle.open_price)} "
                    f"high={_decimal(candle.high_price)} "
                    f"low={_decimal(candle.low_price)} "
                    f"close={_decimal(candle.close_price)} "
                    f"volume={_decimal(candle.volume)}"
                )
        lines.append(
            "限制：摘要观测时刻是多个公开分量的最早参考时刻，不能代表每个字段都在该时刻观测；"
            "K 线仅使用已收盘数据，止损触发不保证按该价格成交。"
        )
        return "\n".join(lines)


# 返回序列末尾有界 K 线；MarketDetail 已保证按开始时间升序。
def _tail(series: CandleSeries, *, limit: int) -> tuple[Candle, ...]:
    return series.candles[-limit:]


# 十进制按非指数形式渲染；不做额外舍入，展示值仍来自冻结证据。
def _decimal(value: Decimal) -> str:
    return format(value, "f")


__all__ = [
    "MARKET_DETAIL_CALCULATION_VERSION",
    "MarketEvidenceFactProjector",
    "MarketResearchEvidencePort",
]
