from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from importlib.util import find_spec
from typing import Protocol, cast
from uuid import UUID

import pytest
from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.market import (
    DerivativeObservationRecord,
    MarketCandleRecord,
    MarketSnapshotRecord,
)
from app.market.contracts import Candle, ContractSymbol, MarketTimeframe
from app.market.repository import (
    DerivativeObservation,
    MarketCaptureBatch,
    MarketSnapshotDraft,
    MetricType,
    snapshot_payload_sha256,
)


class MigratedDatabase(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


@pytest.mark.asyncio
async def test_repository_upserts_candles_deduplicates_metrics_and_inserts_snapshots(
    migrated_database: MigratedDatabase,
) -> None:
    assert find_spec("app.infrastructure.persistence.repository") is not None
    repository_module = import_module("app.infrastructure.persistence.repository")
    repository = repository_module.SqlAlchemyMarketRepository(
        migrated_database.session_factory,
    )
    batch = _market_capture_batch(ContractSymbol.BTCUSDT)

    first_snapshot_ids = await repository.persist_batches((batch,))
    second_snapshot_ids = await repository.persist_batches((batch,))

    assert len(first_snapshot_ids) == 1
    assert len(second_snapshot_ids) == 1
    assert first_snapshot_ids[0] != second_snapshot_ids[0]
    assert await _row_count(migrated_database, MarketCandleRecord) == 1
    assert await _row_count(migrated_database, DerivativeObservationRecord) == 5
    assert await _row_count(migrated_database, MarketSnapshotRecord) == 2


@pytest.mark.asyncio
async def test_repository_rolls_back_all_symbols_when_one_batch_is_invalid(
    migrated_database: MigratedDatabase,
) -> None:
    assert find_spec("app.infrastructure.persistence.repository") is not None
    repository_module = import_module("app.infrastructure.persistence.repository")
    repository = repository_module.SqlAlchemyMarketRepository(
        migrated_database.session_factory,
    )
    batch = _market_capture_batch(ContractSymbol.BTCUSDT)
    eth_batch = _market_capture_batch(ContractSymbol.ETHUSDT)
    database_rejected_batch = eth_batch.model_copy(
        update={"snapshot": eth_batch.snapshot.model_copy(update={"source": "x" * 101})},
    )

    with pytest.raises(DBAPIError):
        await repository.persist_batches((batch, database_rejected_batch))

    assert await _row_count(migrated_database, MarketCandleRecord) == 0
    assert await _row_count(migrated_database, DerivativeObservationRecord) == 0
    assert await _row_count(migrated_database, MarketSnapshotRecord) == 0


@pytest.mark.asyncio
async def test_snapshot_payload_contains_only_normalized_strings_and_utc_times(
    migrated_database: MigratedDatabase,
) -> None:
    repository_module = import_module("app.infrastructure.persistence.repository")
    repository = repository_module.SqlAlchemyMarketRepository(
        migrated_database.session_factory,
    )
    batch = _market_capture_batch(ContractSymbol.BTCUSDT)

    snapshot_id = (await repository.persist_batches((batch,)))[0]
    payload = await _load_snapshot_payload(migrated_database, snapshot_id)

    assert "apiKey" not in payload
    assert "secret" not in payload
    assert payload["price"] == "100000.00"
    assert payload["observedAt"] == "2026-07-30T00:00:00Z"


async def _row_count(
    migrated_database: MigratedDatabase,
    record_type: type[
        MarketCandleRecord | DerivativeObservationRecord | MarketSnapshotRecord
    ],
) -> int:
    async with migrated_database.session_factory() as session:
        result = await session.execute(select(func.count()).select_from(record_type))
        return result.scalar_one()


async def _load_snapshot_payload(
    migrated_database: MigratedDatabase,
    snapshot_id: UUID,
) -> dict[str, JsonValue]:
    async with migrated_database.session_factory() as session:
        result = await session.execute(
            select(MarketSnapshotRecord.payload).where(MarketSnapshotRecord.id == snapshot_id),
        )
        return cast(dict[str, JsonValue], result.scalar_one())


def _market_capture_batch(symbol: ContractSymbol) -> MarketCaptureBatch:
    observed_at = datetime(2026, 7, 30, 0, 0, tzinfo=UTC)
    captured_at = observed_at + timedelta(minutes=5)
    payload: dict[str, JsonValue] = {
        "symbol": symbol.value,
        "price": "100000.00",
        "observedAt": "2026-07-30T00:00:00Z",
    }
    return MarketCaptureBatch(
        symbol=symbol,
        candles=(
            Candle(
                symbol=symbol,
                timeframe=MarketTimeframe.M15,
                open_at=observed_at - timedelta(minutes=15),
                close_at=observed_at,
                open_price=Decimal("99000.00"),
                high_price=Decimal("101000.00"),
                low_price=Decimal("98000.00"),
                close_price=Decimal("100000.00"),
                volume=Decimal("12.5"),
                observed_at=observed_at,
                fetched_at=captured_at,
            ),
        ),
        observations=(
            DerivativeObservation(
                symbol=symbol,
                metric_type=MetricType.PRICE,
                value=Decimal("100000.00"),
                source="binance-usdm",
                observed_at=observed_at,
                fetched_at=captured_at,
            ),
            DerivativeObservation(
                symbol=symbol,
                metric_type=MetricType.FUNDING_RATE,
                value=Decimal("-0.0001"),
                source="binance-usdm",
                observed_at=observed_at,
                fetched_at=captured_at,
            ),
            DerivativeObservation(
                symbol=symbol,
                metric_type=MetricType.OPEN_INTEREST,
                value=Decimal("500000.00"),
                source="binance-usdm",
                observed_at=observed_at,
                fetched_at=captured_at,
            ),
            DerivativeObservation(
                symbol=symbol,
                metric_type=MetricType.CHANGE_24H,
                value=Decimal("1.25"),
                source="binance-usdm",
                observed_at=observed_at,
                fetched_at=captured_at,
            ),
            DerivativeObservation(
                symbol=symbol,
                metric_type=MetricType.VOLUME_24H,
                value=Decimal("1000000.00"),
                source="binance-usdm",
                observed_at=observed_at,
                fetched_at=captured_at,
            ),
        ),
        snapshot=MarketSnapshotDraft(
            symbol=symbol,
            source="binance-usdm",
            captured_at=captured_at,
            data_as_of=observed_at,
            data_version="market-v1",
            payload=payload,
            payload_sha256=snapshot_payload_sha256(payload),
        ),
    )
