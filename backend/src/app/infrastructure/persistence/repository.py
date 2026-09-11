"""公开市场快照的 SQLAlchemy 仓储实现。

数据流：MarketCaptureBatch → K 线上传、指标插入、展示快照及完整输入快照 → 单一
数据库事务。K 线可幂等更新，快照及输入哈希保留一次采集的可复放证据。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.market import (
    DerivativeObservationRecord,
    MarketCandleRecord,
    MarketSnapshotInputRecord,
    MarketSnapshotRecord,
)
from app.market.contracts import Candle, MarketTimeframe
from app.market.repository import (
    DerivativeObservation,
    MarketCaptureBatch,
    MarketRepository,
    snapshot_payload_sha256,
)


class SqlAlchemyMarketRepository(MarketRepository):
    """以单个事务保存受限的公开市场采集批次。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def persist_batches(
        self,
        batches: tuple[MarketCaptureBatch, ...],
    ) -> tuple[UUID, ...]:
        """在同一事务中保存一批市场采集并按输入顺序返回生成的快照 ID。"""
        if not batches:
            return ()

        snapshot_ids: list[UUID] = []
        async with self._session_factory() as session:
            async with session.begin():
                # K 线、派生指标、展示快照与完整输入必须同一事务提交，防止报告引用半成品证据。
                for batch in batches:
                    await session.execute(_upsert_candles(batch.candles))
                    await session.execute(_insert_observations(batch.observations))
                    snapshot_id = uuid4()
                    await session.execute(_insert_snapshot(batch, snapshot_id))
                    await session.execute(_insert_snapshot_input(batch, snapshot_id))
                    snapshot_ids.append(snapshot_id)
        return tuple(snapshot_ids)


def _upsert_candles(candles: Sequence[Candle]):
    """构造按标的、周期和开盘时刻幂等更新的 K 线 UPSERT 语句。"""
    # 相同标的/周期/开盘时刻的 K 线可被后续更完整的公开数据修正，但不会产生重复记录。
    statement = insert(MarketCandleRecord).values(
        [
            {
                "id": uuid4(),
                "symbol": candle.symbol,
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
    """构造忽略重复指标观测的 INSERT 语句，保留最先记录的原始观察。"""
    statement = insert(DerivativeObservationRecord).values(
        [
            {
                "id": uuid4(),
                "symbol": observation.symbol,
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
    """构造展示用市场摘要快照的 INSERT 语句，并保留载荷哈希。"""
    snapshot = batch.snapshot
    return insert(MarketSnapshotRecord).values(
        id=snapshot_id,
        symbol=snapshot.symbol,
        source=snapshot.source,
        captured_at=snapshot.captured_at,
        data_as_of=snapshot.data_as_of,
        data_version=snapshot.data_version,
        payload=cast(dict[str, object], snapshot.payload),
        payload_sha256=snapshot.payload_sha256,
    )


def _insert_snapshot_input(batch: MarketCaptureBatch, snapshot_id: UUID):
    """构造完整 K 线输入快照的 INSERT 语句，用于研究和回测复放。"""
    # 快照输入保存可复放的完整 K 线集合，并与展示用摘要分开哈希、独立校验。
    candles = _snapshot_input_candles(batch)
    payload = cast(
        dict[str, JsonValue],
        {"candles": [candle.model_dump(mode="json") for candle in candles]},
    )
    return insert(MarketSnapshotInputRecord).values(
        snapshot_id=snapshot_id,
        symbol=batch.symbol,
        payload=cast(dict[str, object], payload),
        payload_sha256=snapshot_payload_sha256(payload),
        candle_count=len(candles),
    )


def _snapshot_input_candles(batch: MarketCaptureBatch) -> tuple[Candle, ...]:
    """按枚举周期和开盘时间稳定排序，每周期截取最近 200 根作为冻结输入。"""
    # 每个周期最多保留最近 200 根，并固定按周期和开盘时间排序，使哈希在重复采集时稳定。
    return tuple(
        candle
        for timeframe in MarketTimeframe
        for candle in sorted(
            (item for item in batch.candles if item.timeframe is timeframe),
            key=lambda item: item.open_at,
        )[-200:]
    )
