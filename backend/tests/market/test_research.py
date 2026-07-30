from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.market.contracts import (
    Candle,
    ContractSymbol,
    DataFreshness,
    FreshnessStatus,
    MarketDataUnavailableError,
    MarketSummary,
    MarketTimeframe,
)
from app.market.research import (
    MarketResearchQueryService,
    PersistedMarketSnapshot,
)

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def _empty_snapshots() -> dict[ContractSymbol, PersistedMarketSnapshot]:
    return {}


def _empty_candles() -> dict[tuple[ContractSymbol, MarketTimeframe], tuple[Candle, ...]]:
    return {}


def _empty_limits() -> list[int]:
    return []


@dataclass
class FakePersistedMarketReader:
    snapshots: dict[ContractSymbol, PersistedMarketSnapshot] = field(
        default_factory=_empty_snapshots,
    )
    candles: dict[tuple[ContractSymbol, MarketTimeframe], tuple[Candle, ...]] = field(
        default_factory=_empty_candles,
    )
    limits: list[int] = field(default_factory=_empty_limits)

    async def load_latest_snapshot(
        self,
        symbol: ContractSymbol,
    ) -> PersistedMarketSnapshot | None:
        return self.snapshots.get(symbol)

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        self.limits.append(limit)
        return self.candles.get((symbol, timeframe), ())


@pytest.mark.asyncio
async def test_research_query_marks_latest_snapshot_fresh_within_two_minutes() -> None:
    reader = FakePersistedMarketReader(
        snapshots={
            ContractSymbol.BTCUSDT: _snapshot(captured_at=NOW - timedelta(minutes=2)),
        },
    )
    service = MarketResearchQueryService(reader, clock=lambda: NOW)

    summary = (await service.get_summaries((ContractSymbol.BTCUSDT,)))[0]

    assert summary.freshness.status is FreshnessStatus.FRESH
    assert summary.price == Decimal("68000.30")


@pytest.mark.asyncio
async def test_research_query_marks_last_success_stale_after_two_minutes() -> None:
    reader = FakePersistedMarketReader(
        snapshots={
            ContractSymbol.BTCUSDT: _snapshot(
                captured_at=NOW - timedelta(minutes=2, microseconds=1),
            ),
        },
    )
    service = MarketResearchQueryService(reader, clock=lambda: NOW)

    summary = (await service.get_summaries((ContractSymbol.BTCUSDT,)))[0]

    assert summary.freshness.status is FreshnessStatus.STALE
    assert summary.freshness.observed_at == NOW - timedelta(minutes=1)


@pytest.mark.asyncio
async def test_research_query_rejects_missing_snapshot() -> None:
    service = MarketResearchQueryService(FakePersistedMarketReader(), clock=lambda: NOW)

    with pytest.raises(MarketDataUnavailableError) as error:
        await service.get_summaries((ContractSymbol.BTCUSDT,))

    assert error.value.code == "market_research_unavailable"
    assert str(error.value) == "持久化市场研究数据不可用"


@pytest.mark.asyncio
async def test_research_detail_sorts_candles_and_rejects_missing_timeframes() -> None:
    latest = _candle(open_at=NOW - timedelta(minutes=30))
    earliest = _candle(open_at=NOW - timedelta(minutes=45))
    reader = FakePersistedMarketReader(
        snapshots={ContractSymbol.BTCUSDT: _snapshot(captured_at=NOW)},
        candles={(ContractSymbol.BTCUSDT, MarketTimeframe.M15): (latest, earliest)},
    )
    service = MarketResearchQueryService(reader, clock=lambda: NOW)

    detail = await service.get_market(ContractSymbol.BTCUSDT, (MarketTimeframe.M15,))

    assert reader.limits == [200]
    assert tuple(candle.open_at for candle in detail.series[0].candles) == (
        earliest.open_at,
        latest.open_at,
    )

    with pytest.raises(MarketDataUnavailableError) as error:
        await service.get_market(ContractSymbol.BTCUSDT, (MarketTimeframe.H1,))

    assert error.value.code == "market_research_unavailable"


def _snapshot(*, captured_at: datetime) -> PersistedMarketSnapshot:
    return PersistedMarketSnapshot(
        summary=MarketSummary(
            symbol=ContractSymbol.BTCUSDT,
            price=Decimal("68000.30"),
            change_24h=Decimal("1.25"),
            volume_24h=Decimal("123456.789"),
            funding_rate=Decimal("0.00010000"),
            open_interest=Decimal("1234.5678"),
            freshness=DataFreshness(
                status=FreshnessStatus.FRESH,
                source="binance_usdm_public_rest",
                observed_at=NOW - timedelta(minutes=1),
                fetched_at=NOW,
            ),
        ),
        captured_at=captured_at,
    )


def _candle(*, open_at: datetime) -> Candle:
    return Candle(
        symbol=ContractSymbol.BTCUSDT,
        timeframe=MarketTimeframe.M15,
        open_at=open_at,
        close_at=open_at + timedelta(minutes=15),
        open_price=Decimal("68000.10"),
        high_price=Decimal("68001.20"),
        low_price=Decimal("67999.90"),
        close_price=Decimal("68000.30"),
        volume=Decimal("12.34"),
        observed_at=open_at + timedelta(minutes=15),
        fetched_at=NOW,
    )
