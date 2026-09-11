"""持久化市场研究读取模块。

数据流：已保存的快照与 K 线输入 → 新鲜度重算和范围校验 → 只读 MarketSummary/
MarketDetail 响应；该模块绝不在用户查询时回源获取实时行情。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NoReturn, Protocol
from uuid import UUID

from app.market.contracts import (
    Candle,
    CandleSeries,
    FreshnessStatus,
    MarketDataUnavailableError,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.symbols import ResearchSymbol

_FRESHNESS_THRESHOLD = timedelta(minutes=2)
_CANDLE_LIMIT = 200
_UNAVAILABLE_CODE = "market_research_unavailable"
_UNAVAILABLE_MESSAGE = "持久化市场研究数据不可用"


@dataclass(frozen=True)
class PersistedMarketSnapshot:
    """已持久化市场摘要及其冻结时刻的轻量读取模型。"""
    summary: MarketSummary
    captured_at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.captured_at)


@dataclass(frozen=True)
class PersistedMarketSnapshotInput:
    """生成研究结论时使用的、带哈希的冻结 K 线输入。"""

    candles: tuple[Candle, ...]
    payload_sha256: str

    def __post_init__(self) -> None:
        """校验哈希格式、标的一致性和每周期 K 线数量上限。"""
        if not self.candles:
            raise ValueError("冻结市场快照输入不能为空")
        if len(self.candles) > len(MarketTimeframe) * _CANDLE_LIMIT:
            raise ValueError("冻结市场快照输入超过 K 线限制")
        if len(self.payload_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.payload_sha256
        ):
            raise ValueError("冻结市场快照输入哈希无效")
        symbol = self.candles[0].symbol
        if any(candle.symbol != symbol for candle in self.candles):
            raise ValueError("冻结市场快照输入标的必须一致")
        for timeframe in MarketTimeframe:
            series_candles = tuple(
                candle for candle in self.candles if candle.timeframe is timeframe
            )
            if len(series_candles) > _CANDLE_LIMIT:
                raise ValueError("冻结市场快照输入单周期超过 K 线限制")
            if series_candles:
                CandleSeries(timeframe=timeframe, candles=series_candles)


class PersistedMarketReader(Protocol):
    async def load_snapshot(self, snapshot_id: UUID) -> PersistedMarketSnapshot | None: ...

    async def load_latest_snapshot(
        self,
        symbol: Any,
    ) -> PersistedMarketSnapshot | None: ...

    async def load_recent_candles(
        self,
        symbol: Any,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]: ...


class MarketResearchQueryService:
    """从已持久化的公开研究数据构造只读市场响应。"""

    def __init__(
        self,
        reader: PersistedMarketReader,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._reader = reader
        self._clock = clock

    async def get_summaries(
        self,
        symbols: tuple[ResearchSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        """按请求顺序读取多个标的的最新已保存摘要，并统一以当前 UTC 时钟标注新鲜度。"""
        now = self._now()
        summaries: list[MarketSummary] = []
        for symbol in symbols:
            summaries.append(await self._summary_for(symbol, now=now))
        return tuple(summaries)

    async def get_market(
        self,
        symbol: ResearchSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        """读取一个标的指定周期的排序 K 线序列及其最新冻结摘要。"""
        summary = await self._summary_for(symbol, now=self._now())
        series: list[CandleSeries] = []
        # 读取路径只访问已持久化的快照，不回源请求实时行情，确保页面可复现。
        for timeframe in timeframes:
            candles = await self._reader.load_recent_candles(
                symbol,
                timeframe,
                _CANDLE_LIMIT,
            )
            if not candles or any(
                candle.symbol != symbol or candle.timeframe is not timeframe
                for candle in candles
            ):
                _raise_unavailable()
            series.append(
                CandleSeries(
                    timeframe=timeframe,
                    candles=tuple(sorted(candles, key=lambda candle: candle.open_at)),
                ),
            )
        return MarketDetail(summary=summary, series=tuple(series))

    async def _summary_for(
        self,
        symbol: ResearchSymbol,
        *,
        now: datetime,
    ) -> MarketSummary:
        """读取最近快照并仅更新 freshness 状态，不改变已冻结的行情数值。"""
        snapshot = await self._reader.load_latest_snapshot(symbol)
        if snapshot is None or snapshot.summary.symbol != symbol:
            _raise_unavailable()
        # 新鲜度在读取时计算：同一快照本身不变，但其对当前用户是否仍可用会随时间改变。
        freshness = snapshot.summary.freshness.model_copy(
            update={
                "status": (
                    FreshnessStatus.FRESH
                    if now - snapshot.captured_at <= _FRESHNESS_THRESHOLD
                    else FreshnessStatus.STALE
                ),
            },
        )
        return snapshot.summary.model_copy(update={"freshness": freshness})

    def _now(self) -> datetime:
        """取得并验证服务时钟，保证过期判断始终使用带时区的 UTC 时间。"""
        now = self._clock()
        _require_utc(now)
        return now


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是 UTC 且带时区")


def _raise_unavailable() -> NoReturn:
    raise MarketDataUnavailableError(_UNAVAILABLE_CODE, _UNAVAILABLE_MESSAGE)
