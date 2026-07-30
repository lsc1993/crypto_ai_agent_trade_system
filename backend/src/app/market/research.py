from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NoReturn, Protocol

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


class PersistedMarketReader(Protocol):
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
