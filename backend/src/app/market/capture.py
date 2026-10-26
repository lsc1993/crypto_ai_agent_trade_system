# 公开行情采集：按获准范围读取多周期数据，过滤未收盘行，形成指标与哈希快照，交由仓储保存。
# 公开行情领域：统一研究行情模型、固定公开来源适配器与冻结快照读取；不访问私有账户。
"""公开行情快照采集模块。

数据流：白名单标的的公开行情 → 过滤未收盘 K 线 → 构造观察值与规范化快照载荷 →
单事务持久化。快照是报告、研究和回测可复核的输入边界。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from pydantic import JsonValue

from app.market.contracts import (
    Candle,
    ContractSymbol,
    MarketDataUnavailableError,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.gateway import PublicMarketGateway
from app.market.repository import (
    DerivativeObservation,
    MarketCaptureBatch,
    MarketRepository,
    MarketSnapshotDraft,
    MetricType,
    snapshot_payload_sha256,
)
from app.market.symbols import ResearchSymbol

CAPTURE_SYMBOLS = (ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT)
# 采集范围是显式白名单，而不是由调用方任意指定，保证快照输入可预期、可审计。
CAPTURE_TIMEFRAMES = (
    MarketTimeframe.M15,
    MarketTimeframe.H1,
    MarketTimeframe.H4,
    MarketTimeframe.D1,
)


# 将固定范围的公开行情转换为可审计的研究快照。
class MarketCaptureService:
    """将固定范围的公开行情转换为可审计的研究快照。"""

    # 初始化本实例依赖和配置；输入 gateway、repository、admission。
    def __init__(
        self,
        gateway: PublicMarketGateway,
        repository: MarketRepository,
        admission: Callable[[ResearchSymbol], Awaitable[bool]] | None = None,
    ) -> None:
        self._gateway = gateway
        self._repository = repository
        self._admission = admission

    # 并发采集全部白名单标的，并在所有读取成功后返回其快照 ID。
    async def capture(self, captured_at: datetime) -> tuple[UUID, ...]:
        """并发采集全部白名单标的，并在所有读取成功后返回其快照 ID。"""
        _require_utc(captured_at)
        # 各标的可并发读取；持久化在全部读取成功后统一执行，避免产生半批次快照。
        batches = await asyncio.gather(
            *(
                self._capture_symbol_batch(symbol, captured_at=captured_at)
                for symbol in CAPTURE_SYMBOLS
            ),
        )
        return await self._repository.persist_batches(tuple(batches))

    # 采集一个获准标的并持久化恰好一个可审计快照。
    async def capture_symbol(
        self,
        symbol: ResearchSymbol,
        *,
        captured_at: datetime,
    ) -> UUID:
        """采集一个获准标的并持久化恰好一个可审计快照。"""
        _require_utc(captured_at)
        if self._admission is None and symbol not in CAPTURE_SYMBOLS:
            raise ValueError("标的未获准进行公开行情采集")
        if self._admission is not None and not await self._admission(symbol):
            raise ValueError("标的未获准进行公开行情采集")
        snapshot_ids = await self._repository.persist_batches(
            (await self._capture_symbol_batch(symbol, captured_at=captured_at),),
        )
        if len(snapshot_ids) != 1:
            raise RuntimeError("单标的采集必须恰好持久化一个快照")
        return snapshot_ids[0]

    # 从网关读取一个标的的多周期详情，并验证上游返回的标的一致。
    async def _capture_symbol_batch(
        self,
        symbol: ResearchSymbol,
        *,
        captured_at: datetime,
    ) -> MarketCaptureBatch:
        """从网关读取一个标的的多周期详情，并验证上游返回的标的一致。"""
        detail = await self._gateway.get_market(symbol, CAPTURE_TIMEFRAMES)
        if detail.summary.symbol != symbol:
            raise MarketDataUnavailableError(
                "market_data_invalid",
                "公开行情返回的标的不一致",
            )
        return _capture_batch(detail, captured_at)


# 把网关模型转换成仓储一次提交所需的 K 线、指标和快照草稿。
def _capture_batch(detail: MarketDetail, captured_at: datetime) -> MarketCaptureBatch:
    """把网关模型转换成仓储一次提交所需的 K 线、指标和快照草稿。"""
    # 仅冻结已经收盘的 K 线；未收盘 K 线会随着时间变化，不能作为研究或回测证据。
    candles = tuple(
        candle
        for series in detail.series
        for candle in series.candles
        if candle.close_at <= captured_at
    )
    if not candles:
        raise MarketDataUnavailableError(
            "market_data_missing",
            "公开行情未提供采集时刻前已收盘的 K 线",
        )

    observations = _observations(detail.summary)
    # 数据截止时刻取所有证据中最早的观测时间，防止报告误称拥有更新的数据。
    data_as_of = min(
        *(candle.observed_at for candle in candles),
        *(observation.observed_at for observation in observations),
    )
    payload = _snapshot_payload(detail, candles)
    snapshot = MarketSnapshotDraft(
        symbol=detail.summary.symbol,
        source=detail.summary.freshness.source,
        captured_at=captured_at,
        data_as_of=data_as_of,
        data_version="market-v1",
        payload=payload,
        payload_sha256=snapshot_payload_sha256(payload),
    )
    return MarketCaptureBatch(
        symbol=detail.summary.symbol,
        candles=candles,
        observations=observations,
        snapshot=snapshot,
    )


# 将行情摘要拆分为可按指标类型查询的派生品观察记录。
def _observations(summary: MarketSummary) -> tuple[DerivativeObservation, ...]:
    """将行情摘要拆分为可按指标类型查询的派生品观察记录。"""
    freshness = summary.freshness
    metric_values = (
        (MetricType.PRICE, summary.price),
        (MetricType.FUNDING_RATE, summary.funding_rate),
        (MetricType.OPEN_INTEREST, summary.open_interest),
        (MetricType.CHANGE_24H, summary.change_24h),
        (MetricType.VOLUME_24H, summary.volume_24h),
    )
    return tuple(
        DerivativeObservation(
            symbol=summary.symbol,
            metric_type=metric_type,
            value=value,
            source=freshness.source,
            observed_at=freshness.observed_at,
            fetched_at=freshness.fetched_at,
        )
        for metric_type, value in metric_values
    )


# 生成字段排序稳定、禁止 NaN 的摘要载荷，供哈希和后续证据展示使用。
def _snapshot_payload(
    detail: MarketDetail,
    candles: tuple[Candle, ...],
) -> dict[str, JsonValue]:
    """生成字段排序稳定、禁止 NaN 的摘要载荷，供哈希和后续证据展示使用。"""
    # 审计载荷只保留每个周期最新的已收盘 K 线，完整序列由独立快照输入表保存。
    latest_closed_candles = tuple(
        max(
            (candle for candle in candles if candle.timeframe is series.timeframe),
            key=lambda candle: candle.close_at,
        )
        for series in detail.series
    )
    raw_payload = {
        "summary": detail.summary.model_dump(mode="json"),
        "latestClosedCandles": [
            candle.model_dump(mode="json") for candle in latest_closed_candles
        ],
    }
    serialized = json.dumps(
        raw_payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return cast(dict[str, JsonValue], json.loads(serialized))


# 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("采集时间必须是 UTC 且带时区")
