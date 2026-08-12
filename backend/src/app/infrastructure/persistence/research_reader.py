from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy import Select, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.market import (
    MarketCandleRecord,
    MarketSnapshotRecord,
)
from app.market.contracts import (
    Candle,
    ContractSymbol,
    MarketDataUnavailableError,
    MarketSummary,
    MarketTimeframe,
)
from app.market.repository import snapshot_payload_sha256
from app.market.research import PersistedMarketReader, PersistedMarketSnapshot

_MAX_CANDLES = 200
_UNAVAILABLE_CODE = "market_research_unavailable"
_UNAVAILABLE_MESSAGE = "持久化市场研究数据不可用"


class SqlAlchemyPersistedMarketReader(PersistedMarketReader):
    """从 PostgreSQL 只读查询已持久化的市场研究数据。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_snapshot(self, snapshot_id: UUID) -> PersistedMarketSnapshot | None:
        statement = select(MarketSnapshotRecord).where(MarketSnapshotRecord.id == snapshot_id)
        record = await self._load_snapshot_record(statement)
        return None if record is None else _to_snapshot(record)

    async def load_latest_snapshot(
        self,
        symbol: ContractSymbol,
    ) -> PersistedMarketSnapshot | None:
        statement = (
            select(MarketSnapshotRecord)
            .where(MarketSnapshotRecord.symbol == symbol.value)
            .order_by(MarketSnapshotRecord.captured_at.desc())
            .limit(1)
        )
        record = await self._load_snapshot_record(statement)
        return None if record is None else _to_snapshot(record)

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        if not 1 <= limit <= _MAX_CANDLES:
            raise ValueError(f"K 线读取上限必须在 1 到 {_MAX_CANDLES} 之间")
        statement = (
            select(MarketCandleRecord)
            .where(
                MarketCandleRecord.symbol == symbol.value,
                MarketCandleRecord.timeframe == timeframe.value,
            )
            .order_by(MarketCandleRecord.open_at.desc())
            .limit(limit)
        )
        try:
            async with self._session_factory() as session:
                records = list((await session.execute(statement)).scalars())
            return tuple(
                _to_candle(record)
                for record in reversed(records)
            )
        except (SQLAlchemyError, TypeError, ValueError) as error:
            raise _unavailable() from error

    async def _load_snapshot_record(
        self,
        statement: Select[tuple[MarketSnapshotRecord]],
    ) -> MarketSnapshotRecord | None:
        try:
            async with self._session_factory() as session:
                return (await session.execute(statement)).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise _unavailable() from error


def _to_snapshot(record: MarketSnapshotRecord) -> PersistedMarketSnapshot:
    try:
        payload = cast(dict[str, JsonValue], record.payload)
        if snapshot_payload_sha256(payload) != record.payload_sha256:
            raise ValueError("快照载荷哈希不匹配")
        payload_summary = record.payload.get("summary")
        if not isinstance(payload_summary, Mapping):
            raise ValueError("快照摘要载荷无效")
        summary = MarketSummary.model_validate(
            dict(cast(Mapping[str, object], payload_summary)),
        )
        if summary.symbol.value != record.symbol:
            raise ValueError("快照标的与摘要载荷不一致")
        return PersistedMarketSnapshot(
            summary=summary,
            captured_at=record.captured_at,
        )
    except (TypeError, ValidationError, ValueError) as error:
        raise _unavailable() from error


def _to_candle(record: MarketCandleRecord) -> Candle:
    return Candle(
        symbol=ContractSymbol(record.symbol),
        timeframe=MarketTimeframe(record.timeframe),
        open_at=record.open_at,
        close_at=record.close_at,
        open_price=record.open_price,
        high_price=record.high_price,
        low_price=record.low_price,
        close_price=record.close_price,
        volume=record.volume,
        observed_at=record.observed_at,
        fetched_at=record.fetched_at,
    )


def _unavailable() -> MarketDataUnavailableError:
    return MarketDataUnavailableError(_UNAVAILABLE_CODE, _UNAVAILABLE_MESSAGE)
