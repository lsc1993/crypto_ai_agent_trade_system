from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NoReturn, Protocol
from uuid import UUID

from app.market.contracts import (
    Candle,
    CandleSeries,
    ContractSymbol,
    FreshnessStatus,
    MarketDataUnavailableError,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)

_FRESHNESS_THRESHOLD = timedelta(minutes=2)
_CANDLE_LIMIT = 200
_UNAVAILABLE_CODE = "market_research_unavailable"
_UNAVAILABLE_MESSAGE = "持久化市场研究数据不可用"


@dataclass(frozen=True)
class PersistedMarketSnapshot:
    summary: MarketSummary
    captured_at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.captured_at)


@dataclass(frozen=True)
class PersistedMarketSnapshotInput:
    candles: tuple[Candle, ...]
    payload_sha256: str

    def __post_init__(self) -> None:
        if not self.candles:
            raise ValueError("冻结市场快照输入不能为空")
        if len(self.candles) > len(MarketTimeframe) * _CANDLE_LIMIT:
            raise ValueError("冻结市场快照输入超过 K 线限制")
        if len(self.payload_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.payload_sha256
        ):
            raise ValueError("冻结市场快照输入哈希无效")
        symbol = self.candles[0].symbol
        if any(candle.symbol is not symbol for candle in self.candles):
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
        symbol: ContractSymbol,
    ) -> PersistedMarketSnapshot | None: ...

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
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
        symbols: tuple[ContractSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        now = self._now()
        summaries: list[MarketSummary] = []
        for symbol in symbols:
            summaries.append(await self._summary_for(symbol, now=now))
        return tuple(summaries)

    async def get_market(
        self,
        symbol: ContractSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        summary = await self._summary_for(symbol, now=self._now())
        series: list[CandleSeries] = []
        for timeframe in timeframes:
            candles = await self._reader.load_recent_candles(
                symbol,
                timeframe,
                _CANDLE_LIMIT,
            )
            if not candles or any(
                candle.symbol is not symbol or candle.timeframe is not timeframe
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
        symbol: ContractSymbol,
        *,
        now: datetime,
    ) -> MarketSummary:
        snapshot = await self._reader.load_latest_snapshot(symbol)
        if snapshot is None or snapshot.summary.symbol is not symbol:
            _raise_unavailable()
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
        now = self._clock()
        _require_utc(now)
        return now


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是 UTC 且带时区")


def _raise_unavailable() -> NoReturn:
    raise MarketDataUnavailableError(_UNAVAILABLE_CODE, _UNAVAILABLE_MESSAGE)
