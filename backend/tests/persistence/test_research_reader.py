from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol, cast

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.repository import SqlAlchemyMarketRepository
from app.infrastructure.persistence.research_reader import SqlAlchemyPersistedMarketReader
from app.market.contracts import (
    Candle,
    ContractSymbol,
    DataFreshness,
    FreshnessStatus,
    MarketDataUnavailableError,
    MarketSummary,
    MarketTimeframe,
)
from app.market.repository import (
    DerivativeObservation,
    MarketCaptureBatch,
    MarketSnapshotDraft,
    MetricType,
    snapshot_payload_sha256,
)

OLDER_CAPTURED_AT = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)
NEWER_CAPTURED_AT = datetime(2026, 7, 30, 9, 0, tzinfo=UTC)


class MigratedDatabase(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


@pytest.mark.asyncio
async def test_reader_uses_the_latest_snapshot_and_revalidates_its_summary(
    migrated_database: MigratedDatabase,
) -> None:
    await _persist_batch(
        migrated_database,
        _market_capture_batch(captured_at=OLDER_CAPTURED_AT, price=Decimal("68000.00")),
    )
    await _persist_batch(
        migrated_database,
        _market_capture_batch(captured_at=NEWER_CAPTURED_AT, price=Decimal("69000.00")),
    )
    reader = SqlAlchemyPersistedMarketReader(migrated_database.session_factory)

    snapshot = await reader.load_latest_snapshot(ContractSymbol.BTCUSDT)

    assert snapshot is not None
    assert snapshot.captured_at == NEWER_CAPTURED_AT
    assert snapshot.summary.price == Decimal("69000.00")


@pytest.mark.asyncio
async def test_reader_loads_the_requested_snapshot_instead_of_the_latest_one(
    migrated_database: MigratedDatabase,
) -> None:
    older_batch = _market_capture_batch(
        captured_at=OLDER_CAPTURED_AT,
        price=Decimal("68000.00"),
    )
    await _persist_batch(migrated_database, older_batch)
    await _persist_batch(
        migrated_database,
        _market_capture_batch(captured_at=NEWER_CAPTURED_AT, price=Decimal("69000.00")),
    )
    reader = SqlAlchemyPersistedMarketReader(migrated_database.session_factory)

    snapshot = await reader.load_snapshot(older_batch.snapshot.id)

    assert snapshot is not None
    assert snapshot.captured_at == OLDER_CAPTURED_AT
    assert snapshot.summary.price == Decimal("68000.00")


@pytest.mark.asyncio
async def test_reader_limits_candles_to_200_and_returns_ascending_times(
    migrated_database: MigratedDatabase,
) -> None:
    start = datetime(2026, 7, 28, 0, 0, tzinfo=UTC)
    candles = tuple(
        _candle(open_at=start + timedelta(minutes=15 * index))
        for index in range(201)
    )
    await _persist_batch(
        migrated_database,
        _market_capture_batch(
            captured_at=NEWER_CAPTURED_AT,
            price=Decimal("69000.00"),
            candles=candles,
        ),
    )
    reader = SqlAlchemyPersistedMarketReader(migrated_database.session_factory)

    result = await reader.load_recent_candles(
        ContractSymbol.BTCUSDT,
        MarketTimeframe.M15,
        limit=200,
    )

    assert len(result) == 200
    assert result[0].open_at == candles[1].open_at
    assert result[-1].open_at == candles[-1].open_at
    assert tuple(candle.open_at for candle in result) == tuple(
        sorted(candle.open_at for candle in result),
    )


@pytest.mark.asyncio
async def test_reader_rejects_a_snapshot_without_a_valid_summary_payload(
    migrated_database: MigratedDatabase,
) -> None:
    batch = _market_capture_batch(
        captured_at=NEWER_CAPTURED_AT,
        price=Decimal("69000.00"),
    )
    invalid_payload: dict[str, JsonValue] = {
        "summary": {"symbol": "BTCUSDT"},
    }
    invalid_snapshot = batch.snapshot.model_copy(
        update={
            "payload": invalid_payload,
            "payload_sha256": snapshot_payload_sha256(invalid_payload),
        },
    )
    await _persist_batch(
        migrated_database,
        batch.model_copy(update={"snapshot": invalid_snapshot}),
    )
    reader = SqlAlchemyPersistedMarketReader(migrated_database.session_factory)

    with pytest.raises(MarketDataUnavailableError) as error:
        await reader.load_latest_snapshot(ContractSymbol.BTCUSDT)

    assert error.value.code == "market_research_unavailable"


async def _persist_batch(
    migrated_database: MigratedDatabase,
    batch: MarketCaptureBatch,
) -> None:
    repository = SqlAlchemyMarketRepository(migrated_database.session_factory)
    await repository.persist_batches((batch,))


def _market_capture_batch(
    *,
    captured_at: datetime,
    price: Decimal,
    candles: Sequence[Candle] | None = None,
) -> MarketCaptureBatch:
    persisted_candles = tuple(candles or (_candle(open_at=captured_at - timedelta(minutes=30)),))
    observed_at = min(candle.observed_at for candle in persisted_candles)
    summary = MarketSummary(
        symbol=ContractSymbol.BTCUSDT,
        price=price,
        change_24h=Decimal("1.25"),
        volume_24h=Decimal("123456.789"),
        funding_rate=Decimal("0.00010000"),
        open_interest=Decimal("1234.5678"),
        freshness=DataFreshness(
            status=FreshnessStatus.FRESH,
            source="binance_usdm_public_rest",
            observed_at=observed_at,
            fetched_at=captured_at,
        ),
    )
    payload = cast(dict[str, JsonValue], {"summary": summary.model_dump(mode="json")})
    observations = tuple(
        DerivativeObservation(
            symbol=ContractSymbol.BTCUSDT,
            metric_type=metric_type,
            value=value,
            source="binance_usdm_public_rest",
            observed_at=observed_at,
            fetched_at=captured_at,
        )
        for metric_type, value in (
            (MetricType.PRICE, price),
            (MetricType.FUNDING_RATE, Decimal("0.00010000")),
            (MetricType.OPEN_INTEREST, Decimal("1234.5678")),
            (MetricType.CHANGE_24H, Decimal("1.25")),
            (MetricType.VOLUME_24H, Decimal("123456.789")),
        )
    )
    return MarketCaptureBatch(
        symbol=ContractSymbol.BTCUSDT,
        candles=persisted_candles,
        observations=observations,
        snapshot=MarketSnapshotDraft(
            symbol=ContractSymbol.BTCUSDT,
            source="binance_usdm_public_rest",
            captured_at=captured_at,
            data_as_of=observed_at,
            data_version="market-v1",
            payload=payload,
            payload_sha256=snapshot_payload_sha256(payload),
        ),
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
        fetched_at=NEWER_CAPTURED_AT,
    )
