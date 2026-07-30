from __future__ import annotations

from collections.abc import Sequence
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.market import (
    DerivativeObservationRecord,
    MarketCandleRecord,
    MarketSnapshotRecord,
)
from app.market.contracts import Candle
from app.market.repository import DerivativeObservation, MarketCaptureBatch, MarketRepository


class SqlAlchemyMarketRepository(MarketRepository):
    """以单个事务保存受限的公开市场采集批次。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def persist_batches(
        self,
        batches: tuple[MarketCaptureBatch, ...],
    ) -> tuple[UUID, ...]:
        if not batches:
            return ()

        snapshot_ids: list[UUID] = []
        async with self._session_factory() as session:
            async with session.begin():
                for batch in batches:
                    await session.execute(_upsert_candles(batch.candles))
                    await session.execute(_insert_observations(batch.observations))
                    snapshot_id = uuid4()
                    await session.execute(_insert_snapshot(batch, snapshot_id))
                    snapshot_ids.append(snapshot_id)
        return tuple(snapshot_ids)


def _upsert_candles(candles: Sequence[Candle]):
    statement = insert(MarketCandleRecord).values(
        [
            {
                "id": uuid4(),
                "symbol": candle.symbol.value,
                "timeframe": candle.timeframe.value,
                "open_at": candle.open_at,
                "close_at": candle.close_at,
                "open_price": candle.open_price,
                "high_price": candle.high_price,
                "low_price": candle.low_price,
                "close_price": candle.close_price,
                "volume": candle.volume,
                "source": "binance-usdm",
                "observed_at": candle.observed_at,
                "fetched_at": candle.fetched_at,
            }
            for candle in candles
        ],
    )
    return statement.on_conflict_do_update(
        constraint="uq_market_candles_scope",
        set_={
            "close_at": statement.excluded.close_at,
            "open_price": statement.excluded.open_price,
            "high_price": statement.excluded.high_price,
            "low_price": statement.excluded.low_price,
            "close_price": statement.excluded.close_price,
            "volume": statement.excluded.volume,
            "source": statement.excluded.source,
            "observed_at": statement.excluded.observed_at,
            "fetched_at": statement.excluded.fetched_at,
            "updated_at": func.now(),
        },
    )


def _insert_observations(observations: Sequence[DerivativeObservation]):
    statement = insert(DerivativeObservationRecord).values(
        [
            {
                "id": uuid4(),
                "symbol": observation.symbol.value,
                "metric_type": observation.metric_type.value,
                "value": observation.value,
                "source": observation.source,
                "observed_at": observation.observed_at,
                "fetched_at": observation.fetched_at,
            }
            for observation in observations
        ],
    )
    return statement.on_conflict_do_nothing(
        constraint="uq_derivative_observations_scope",
    )


def _insert_snapshot(batch: MarketCaptureBatch, snapshot_id: UUID):
    snapshot = batch.snapshot
    return insert(MarketSnapshotRecord).values(
        id=snapshot_id,
        symbol=snapshot.symbol.value,
        source=snapshot.source,
        captured_at=snapshot.captured_at,
        data_as_of=snapshot.data_as_of,
        data_version=snapshot.data_version,
        payload=cast(dict[str, object], snapshot.payload),
        payload_sha256=snapshot.payload_sha256,
    )
