from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from pydantic import JsonValue, ValidationError

from app.market.contracts import Candle, ContractSymbol, MarketTimeframe
from app.market.repository import (
    DerivativeObservation,
    MarketCaptureBatch,
    MarketSnapshotDraft,
    MetricType,
    snapshot_payload_sha256,
)


def utc_at(hour: int = 12) -> datetime:
    return datetime(2026, 7, 29, hour, tzinfo=UTC)


def candle() -> Candle:
    return Candle(
        symbol=ContractSymbol.BTCUSDT,
        timeframe=MarketTimeframe.H1,
        open_at=utc_at(10),
        close_at=utc_at(11),
        open_price=Decimal("68000.00"),
        high_price=Decimal("68200.00"),
        low_price=Decimal("67900.00"),
        close_price=Decimal("68100.00"),
        volume=Decimal("12.50"),
        observed_at=utc_at(11),
        fetched_at=utc_at(12),
    )


def valid_payload() -> dict[str, JsonValue]:
    return {
        "symbol": "BTCUSDT",
        "capturedAt": "2026-07-29T12:00:00Z",
        "close": "68100.00",
    }


def test_snapshot_is_bounded_hashed_and_uses_utc_times() -> None:
    payload = valid_payload()
    payload_hash = snapshot_payload_sha256(payload)

    snapshot = MarketSnapshotDraft(
        symbol=ContractSymbol.BTCUSDT,
        source="binance_usdm_public_rest",
        captured_at=utc_at(),
        data_as_of=utc_at(11),
        data_version="market-v1",
        payload=payload,
        payload_sha256=payload_hash,
    )

    assert isinstance(snapshot.id, UUID)
    assert snapshot.payload_sha256 == payload_hash


def test_snapshot_generates_a_distinct_uuid_for_each_capture() -> None:
    payload = valid_payload()
    payload_hash = snapshot_payload_sha256(payload)
    first = MarketSnapshotDraft(
        symbol=ContractSymbol.BTCUSDT,
        source="binance_usdm_public_rest",
        captured_at=utc_at(),
        data_as_of=utc_at(11),
        data_version="market-v1",
        payload=payload,
        payload_sha256=payload_hash,
    )
    second = MarketSnapshotDraft(
        symbol=ContractSymbol.BTCUSDT,
        source="binance_usdm_public_rest",
        captured_at=utc_at(),
        data_as_of=utc_at(11),
        data_version="market-v1",
        payload=payload,
        payload_sha256=payload_hash,
    )

    assert first.id != second.id


def test_snapshot_rejects_a_payload_over_64_kib() -> None:
    payload: dict[str, JsonValue] = {"value": "x" * 65_537}

    with pytest.raises(ValidationError, match="64 KiB"):
        MarketSnapshotDraft(
            symbol=ContractSymbol.BTCUSDT,
            source="binance_usdm_public_rest",
            captured_at=utc_at(),
            data_as_of=utc_at(11),
            data_version="market-v1",
            payload=payload,
            payload_sha256="0" * 64,
        )


def test_observation_rejects_float_metric_values() -> None:
    with pytest.raises(ValidationError, match="Decimal"):
        DerivativeObservation(
            symbol=ContractSymbol.BTCUSDT,
            metric_type=MetricType.PRICE,
            value=cast(Decimal, 68100.5),
            source="binance_usdm_public_rest",
            observed_at=utc_at(11),
            fetched_at=utc_at(),
        )


def test_capture_batch_requires_all_five_metric_types_for_its_symbol() -> None:
    payload = valid_payload()
    snapshot = MarketSnapshotDraft(
        symbol=ContractSymbol.BTCUSDT,
        source="binance_usdm_public_rest",
        captured_at=utc_at(),
        data_as_of=utc_at(11),
        data_version="market-v1",
        payload=payload,
        payload_sha256=snapshot_payload_sha256(payload),
    )
    observations = tuple(
        DerivativeObservation(
            symbol=ContractSymbol.BTCUSDT,
            metric_type=metric_type,
            value=Decimal("1.00"),
            source="binance_usdm_public_rest",
            observed_at=utc_at(11),
            fetched_at=utc_at(),
        )
        for metric_type in MetricType
        if metric_type is not MetricType.VOLUME_24H
    )

    with pytest.raises(ValidationError, match="五类"):
        MarketCaptureBatch(
            symbol=ContractSymbol.BTCUSDT,
            candles=(candle(),),
            observations=observations,
            snapshot=snapshot,
        )


def test_capture_batch_rejects_candles_closed_after_the_snapshot_time() -> None:
    payload = valid_payload()
    snapshot = MarketSnapshotDraft(
        symbol=ContractSymbol.BTCUSDT,
        source="binance_usdm_public_rest",
        captured_at=utc_at(11),
        data_as_of=utc_at(11),
        data_version="market-v1",
        payload=payload,
        payload_sha256=snapshot_payload_sha256(payload),
    )
    observations = tuple(
        DerivativeObservation(
            symbol=ContractSymbol.BTCUSDT,
            metric_type=metric_type,
            value=Decimal("1.00"),
            source="binance_usdm_public_rest",
            observed_at=utc_at(11),
            fetched_at=utc_at(),
        )
        for metric_type in MetricType
    )
    late_candle = candle().model_copy(
        update={
            "close_at": utc_at(11) + timedelta(seconds=1),
            "observed_at": utc_at(11) + timedelta(seconds=1),
        },
    )

    with pytest.raises(ValidationError, match="快照时间"):
        MarketCaptureBatch(
            symbol=ContractSymbol.BTCUSDT,
            candles=(late_candle,),
            observations=observations,
            snapshot=snapshot,
        )
