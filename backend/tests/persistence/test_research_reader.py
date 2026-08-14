from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol, cast
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.market import (
    MarketSnapshotInputRecord,
    MarketSnapshotRecord,
)
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
    older_snapshot_id = (await _persist_batch(migrated_database, older_batch))[0]
    await _persist_batch(
        migrated_database,
        _market_capture_batch(captured_at=NEWER_CAPTURED_AT, price=Decimal("69000.00")),
    )
    reader = SqlAlchemyPersistedMarketReader(migrated_database.session_factory)

    snapshot = await reader.load_snapshot(older_snapshot_id)

    assert snapshot is not None
    assert snapshot.captured_at == OLDER_CAPTURED_AT
    assert snapshot.summary.price == Decimal("68000.00")


@pytest.mark.asyncio
async def test_reader_limits_candles_to_200_and_returns_ascending_times(
    migrated_database: MigratedDatabase,
) -> None:
    start = datetime(2026, 7, 28, 0, 0, tzinfo=UTC)
    candles = tuple(_candle(open_at=start + timedelta(minutes=15 * index)) for index in range(201))
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
async def test_repository_persists_a_hash_verified_immutable_input_per_snapshot(
    migrated_database: MigratedDatabase,
) -> None:
    candles = tuple(
        _candle(open_at=NEWER_CAPTURED_AT - timedelta(minutes=15 * index)) for index in range(3)
    )
    batch = _market_capture_batch(
        captured_at=NEWER_CAPTURED_AT,
        price=Decimal("69000.00"),
        candles=candles,
    )
    snapshot_id = (await _persist_batch(migrated_database, batch))[0]
    reader = SqlAlchemyPersistedMarketReader(migrated_database.session_factory)
    expected_candles = tuple(sorted(candles, key=lambda candle: candle.open_at))

    snapshot_input = await reader.load_snapshot_input(snapshot_id)

    assert snapshot_input is not None
    assert snapshot_input.candles == expected_candles
    assert snapshot_input.payload_sha256 == snapshot_payload_sha256(
        {"candles": [candle.model_dump(mode="json") for candle in expected_candles]}
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


@pytest.mark.asyncio
async def test_reader_rejects_a_requested_snapshot_with_a_tampered_payload_hash(
    migrated_database: MigratedDatabase,
) -> None:
    batch = _market_capture_batch(
        captured_at=NEWER_CAPTURED_AT,
        price=Decimal("69000.00"),
    )
    summary = cast(dict[str, JsonValue], batch.snapshot.payload["summary"])
    tampered_payload: dict[str, JsonValue] = {
        "summary": {**summary, "price": "1.00"},
    }
    tampered_snapshot = batch.snapshot.model_copy(
        update={"payload": tampered_payload},
    )
    snapshot_id = (
        await _persist_batch(
            migrated_database,
            batch.model_copy(update={"snapshot": tampered_snapshot}),
        )
    )[0]
    reader = SqlAlchemyPersistedMarketReader(migrated_database.session_factory)

    with pytest.raises(MarketDataUnavailableError) as error:
        await reader.load_snapshot(snapshot_id)

    assert error.value.code == "market_research_unavailable"


@pytest.mark.asyncio
async def test_snapshot_conversion_rejects_a_valid_summary_with_a_tampered_payload_hash() -> None:
    batch = _market_capture_batch(
        captured_at=NEWER_CAPTURED_AT,
        price=Decimal("69000.00"),
    )
    summary = cast(dict[str, JsonValue], batch.snapshot.payload["summary"])
    record = MarketSnapshotRecord(
        id=uuid4(),
        symbol=ContractSymbol.BTCUSDT.value,
        source="binance_usdm_public_rest",
        captured_at=NEWER_CAPTURED_AT,
        data_as_of=NEWER_CAPTURED_AT,
        data_version="market-v1",
        payload={"summary": {**summary, "price": "1.00"}},
        payload_sha256=batch.snapshot.payload_sha256,
    )
    reader = SqlAlchemyPersistedMarketReader(
        cast(
            async_sessionmaker[AsyncSession],
            _SingleSnapshotSessionFactory(record),
        ),
    )

    with pytest.raises(MarketDataUnavailableError) as error:
        await reader.load_snapshot(record.id)

    assert error.value.code == "market_research_unavailable"


@pytest.mark.asyncio
async def test_reader_loads_the_hash_verified_immutable_snapshot_candle_input() -> None:
    candle = _candle(open_at=NEWER_CAPTURED_AT - timedelta(minutes=30))
    payload: dict[str, JsonValue] = {
        "candles": [candle.model_dump(mode="json")],
    }
    record = MarketSnapshotInputRecord(
        snapshot_id=uuid4(),
        symbol=ContractSymbol.BTCUSDT.value,
        payload=payload,
        payload_sha256=snapshot_payload_sha256(payload),
        candle_count=1,
    )
    reader = SqlAlchemyPersistedMarketReader(
        cast(
            async_sessionmaker[AsyncSession],
            _SingleSnapshotSessionFactory(record),
        ),
    )

    snapshot_input = await reader.load_snapshot_input(record.snapshot_id)

    assert snapshot_input is not None
    assert snapshot_input.candles == (candle,)
    assert snapshot_input.payload_sha256 == record.payload_sha256


@pytest.mark.asyncio
async def test_reader_rejects_a_tampered_immutable_snapshot_candle_input() -> None:
    candle = _candle(open_at=NEWER_CAPTURED_AT - timedelta(minutes=30))
    payload: dict[str, JsonValue] = {
        "candles": [candle.model_dump(mode="json")],
    }
    record = MarketSnapshotInputRecord(
        snapshot_id=uuid4(),
        symbol=ContractSymbol.BTCUSDT.value,
        payload=payload,
        payload_sha256="0" * 64,
        candle_count=1,
    )
    reader = SqlAlchemyPersistedMarketReader(
        cast(async_sessionmaker[AsyncSession], _SingleSnapshotSessionFactory(record)),
    )

    with pytest.raises(MarketDataUnavailableError) as error:
        await reader.load_snapshot_input(record.snapshot_id)

    assert error.value.code == "market_research_unavailable"


@pytest.mark.asyncio
async def test_reader_rejects_out_of_order_immutable_snapshot_candles() -> None:
    earlier = _candle(open_at=NEWER_CAPTURED_AT - timedelta(hours=1))
    later = _candle(open_at=NEWER_CAPTURED_AT - timedelta(minutes=30))
    payload: dict[str, JsonValue] = {
        "candles": [later.model_dump(mode="json"), earlier.model_dump(mode="json")],
    }
    record = MarketSnapshotInputRecord(
        snapshot_id=uuid4(),
        symbol=ContractSymbol.BTCUSDT.value,
        payload=payload,
        payload_sha256=snapshot_payload_sha256(payload),
        candle_count=2,
    )
    reader = SqlAlchemyPersistedMarketReader(
        cast(async_sessionmaker[AsyncSession], _SingleSnapshotSessionFactory(record)),
    )

    with pytest.raises(MarketDataUnavailableError) as error:
        await reader.load_snapshot_input(record.snapshot_id)

    assert error.value.code == "market_research_unavailable"


class _SingleSnapshotResult:
    def __init__(self, record: object) -> None:
        self._record = record

    def scalar_one_or_none(self) -> object:
        return self._record


class _SingleSnapshotSession:
    def __init__(self, record: object) -> None:
        self._record = record

    async def __aenter__(self) -> _SingleSnapshotSession:
        return self

    async def __aexit__(self, *arguments: object) -> None:
        del arguments

    async def execute(self, statement: object) -> _SingleSnapshotResult:
        del statement
        return _SingleSnapshotResult(self._record)


class _SingleSnapshotSessionFactory:
    def __init__(self, record: object) -> None:
        self._record = record

    def __call__(self) -> _SingleSnapshotSession:
        return _SingleSnapshotSession(self._record)


async def _persist_batch(
    migrated_database: MigratedDatabase,
    batch: MarketCaptureBatch,
) -> tuple[UUID, ...]:
    repository = SqlAlchemyMarketRepository(migrated_database.session_factory)
    return await repository.persist_batches((batch,))


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
