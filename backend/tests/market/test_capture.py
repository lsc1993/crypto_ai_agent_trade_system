from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.market.contracts import (
    Candle,
    CandleSeries,
    ContractSymbol,
    DataFreshness,
    FreshnessStatus,
    MarketDataUnavailableError,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.gateway import PublicMarketGateway
from app.market.repository import MarketCaptureBatch, MarketRepository

CAPTURED_AT = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


@dataclass
class RecordingRepository(MarketRepository):
    persisted_batches: tuple[MarketCaptureBatch, ...] = ()

    async def persist_batches(
        self,
        batches: tuple[MarketCaptureBatch, ...],
    ) -> tuple[UUID, ...]:
        self.persisted_batches = batches
        return tuple(uuid4() for _ in batches)


class FakeMarketGateway(PublicMarketGateway):
    def __init__(self) -> None:
        self.requests: list[tuple[ContractSymbol, tuple[MarketTimeframe, ...]]] = []

    async def get_summaries(
        self,
        symbols: tuple[ContractSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        return tuple(_summary(symbol) for symbol in symbols)

    async def get_market(
        self,
        symbol: ContractSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        self.requests.append((symbol, timeframes))
        await asyncio.sleep(0)
        return _market_detail(symbol, timeframes)


class FailingMarketGateway(FakeMarketGateway):
    async def get_market(
        self,
        symbol: ContractSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        self.requests.append((symbol, timeframes))
        if symbol is ContractSymbol.ETHUSDT:
            raise MarketDataUnavailableError(
                "market_data_unavailable",
                "公开行情服务不可用",
            )
        return _market_detail(symbol, timeframes)


@pytest.mark.asyncio
async def test_capture_persists_two_symbol_batches_only_after_all_reads_succeed() -> None:
    from app.market.capture import (
        CAPTURE_SYMBOLS,
        CAPTURE_TIMEFRAMES,
        MarketCaptureService,
    )

    gateway = FakeMarketGateway()
    repository = RecordingRepository()
    service = MarketCaptureService(gateway, repository)

    snapshot_ids = await service.capture(captured_at=CAPTURED_AT)

    assert len(snapshot_ids) == 2
    assert tuple(batch.symbol for batch in repository.persisted_batches) == CAPTURE_SYMBOLS
    assert gateway.requests == [
        (ContractSymbol.BTCUSDT, CAPTURE_TIMEFRAMES),
        (ContractSymbol.ETHUSDT, CAPTURE_TIMEFRAMES),
    ]


@pytest.mark.asyncio
async def test_capture_does_not_write_when_one_gateway_read_fails() -> None:
    from app.market.capture import MarketCaptureService

    gateway = FailingMarketGateway()
    repository = RecordingRepository()
    service = MarketCaptureService(gateway, repository)

    with pytest.raises(MarketDataUnavailableError):
        await service.capture(captured_at=CAPTURED_AT)

    assert repository.persisted_batches == ()


@pytest.mark.asyncio
async def test_capture_excludes_current_candles_before_persistence() -> None:
    from app.market.capture import MarketCaptureService

    repository = RecordingRepository()
    service = MarketCaptureService(FakeMarketGateway(), repository)

    await service.capture(captured_at=CAPTURED_AT)

    assert all(
        candle.close_at <= CAPTURED_AT
        for batch in repository.persisted_batches
        for candle in batch.candles
    )
    assert [len(batch.candles) for batch in repository.persisted_batches] == [4, 4]


def _market_detail(
    symbol: ContractSymbol,
    timeframes: tuple[MarketTimeframe, ...],
) -> MarketDetail:
    return MarketDetail(
        summary=_summary(symbol),
        series=tuple(
            CandleSeries(
                timeframe=timeframe,
                candles=(
                    _candle(symbol, timeframe, close_at=CAPTURED_AT - timedelta(minutes=1)),
                    _candle(symbol, timeframe, close_at=CAPTURED_AT + timedelta(minutes=1)),
                ),
            )
            for timeframe in timeframes
        ),
    )


def _candle(
    symbol: ContractSymbol,
    timeframe: MarketTimeframe,
    *,
    close_at: datetime,
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_at=close_at - timedelta(minutes=15),
        close_at=close_at,
        open_price=Decimal("99000.00"),
        high_price=Decimal("101000.00"),
        low_price=Decimal("98000.00"),
        close_price=Decimal("100000.00"),
        volume=Decimal("12.5"),
        observed_at=close_at,
        fetched_at=CAPTURED_AT,
    )


def _summary(symbol: ContractSymbol) -> MarketSummary:
    return MarketSummary(
        symbol=symbol,
        price=Decimal("100000.00"),
        change_24h=Decimal("1.25"),
        volume_24h=Decimal("1000000.00"),
        funding_rate=Decimal("-0.0001"),
        open_interest=Decimal("500000.00"),
        freshness=DataFreshness(
            status=FreshnessStatus.FRESH,
            source="binance_usdm_public_rest",
            observed_at=CAPTURED_AT - timedelta(minutes=2),
            fetched_at=CAPTURED_AT,
        ),
    )
