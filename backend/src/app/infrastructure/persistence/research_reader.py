# 只读还原市场研究快照与最近 K 线。
# 先查询 ORM 记录，再核对载荷哈希、数量和币种并通过领域契约恢复。
# 最近 K 线来自可更新行情表；冻结输入必须按快照 ID 读取，校验失败统一视为不可用。
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
    MarketSnapshotInputRecord,
    MarketSnapshotRecord,
)
from app.market.contracts import (
    Candle,
    MarketDataUnavailableError,
    MarketSummary,
    MarketTimeframe,
)
from app.market.repository import snapshot_payload_sha256
from app.market.research import (
    PersistedMarketReader,
    PersistedMarketSnapshot,
    PersistedMarketSnapshotInput,
)
from app.market.symbols import ResearchSymbol

_MAX_CANDLES = 200
_UNAVAILABLE_CODE = "market_research_unavailable"
_UNAVAILABLE_MESSAGE = "持久化市场研究数据不可用"


# SqlAlchemyPersistedMarketReader 将已校验领域契约连接到异步会话；数据库操作范围由各方法决定。
class SqlAlchemyPersistedMarketReader(PersistedMarketReader):
    """从 PostgreSQL 只读查询已持久化的市场研究数据。"""

    # 仅保存注入的会话工厂供后续操作使用；构造实例时不连接数据库或开启事务。
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # 按传入标识/币种读取持久记录并映射领域契约；缺失返回 None，不隐式创建新数据。
    async def load_snapshot(self, snapshot_id: UUID) -> PersistedMarketSnapshot | None:
        statement = select(MarketSnapshotRecord).where(MarketSnapshotRecord.id == snapshot_id)
        record = await self._load_snapshot_record(statement)
        return None if record is None else _to_snapshot(record)

    # 按传入标识/币种读取持久记录并映射领域契约；缺失返回 None，不隐式创建新数据。
    async def load_latest_snapshot(
        self,
        symbol: ResearchSymbol,
    ) -> PersistedMarketSnapshot | None:
        statement = (
            select(MarketSnapshotRecord)
            .where(MarketSnapshotRecord.symbol == symbol)
            .order_by(MarketSnapshotRecord.captured_at.desc())
            .limit(1)
        )
        record = await self._load_snapshot_record(statement)
        return None if record is None else _to_snapshot(record)

    # 按传入标识/币种读取持久记录并映射领域契约；缺失返回 None，不隐式创建新数据。
    async def load_snapshot_input(
        self,
        snapshot_id: UUID,
    ) -> PersistedMarketSnapshotInput | None:
        statement = select(MarketSnapshotInputRecord).where(
            MarketSnapshotInputRecord.snapshot_id == snapshot_id
        )
        try:
            async with self._session_factory() as session:
                record = (await session.execute(statement)).scalar_one_or_none()
            return None if record is None else _to_snapshot_input(record)
        except (SQLAlchemyError, TypeError, ValidationError, ValueError) as error:
            raise _unavailable() from error

    # 读取最近一至二百根对应周期 K 线，倒序限量后转为时间升序；这条路径不读取冻结输入。
    async def load_recent_candles(
        self,
        symbol: ResearchSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        if not 1 <= limit <= _MAX_CANDLES:
            raise ValueError(f"K 线读取上限必须在 1 到 {_MAX_CANDLES} 之间")
        statement = (
            select(MarketCandleRecord)
            .where(
                MarketCandleRecord.symbol == symbol,
                MarketCandleRecord.timeframe == timeframe.value,
            )
            .order_by(MarketCandleRecord.open_at.desc())
            .limit(limit)
        )
        try:
            async with self._session_factory() as session:
                records = list((await session.execute(statement)).scalars())
            # 查询倒序取最近 N 根后反转为时间升序，供确定性指标按历史顺序处理。
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


# 按下面的显式字段映射还原 PersistedMarketSnapshot，保留可选值与已有顺序；不重新执行业务计算。
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
        if summary.symbol != record.symbol:
            raise ValueError("快照标的与摘要载荷不一致")
        return PersistedMarketSnapshot(
            summary=summary,
            captured_at=record.captured_at,
        )
    except (TypeError, ValidationError, ValueError) as error:
        raise _unavailable() from error


# 按下面的显式字段映射还原 Candle，保留可选值与已有顺序；不重新执行业务计算。
def _to_candle(record: MarketCandleRecord) -> Candle:
    return Candle(
        symbol=record.symbol,
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


# 按下面的显式字段映射还原 PersistedMarketSnapshotInput，保留可选值与已有顺序；不重新执行业务计算。
def _to_snapshot_input(
    record: MarketSnapshotInputRecord,
) -> PersistedMarketSnapshotInput:
    payload = cast(dict[str, JsonValue], record.payload)
    # 哈希通过后仍检查载荷形状、数量和标的；完整性摘要不代替领域契约验证。
    if snapshot_payload_sha256(payload) != record.payload_sha256:
        raise ValueError("冻结市场 K 线输入哈希不匹配")
    raw_candles = payload.get("candles")
    if not isinstance(raw_candles, list) or len(raw_candles) != record.candle_count:
        raise ValueError("冻结市场 K 线输入载荷无效")
    candles = tuple(Candle.model_validate(candle) for candle in raw_candles)
    if not candles or any(candle.symbol != record.symbol for candle in candles):
        raise ValueError("冻结市场 K 线输入标的不一致")
    return PersistedMarketSnapshotInput(
        candles=candles,
        payload_sha256=record.payload_sha256,
    )


def _unavailable() -> MarketDataUnavailableError:
    return MarketDataUnavailableError(_UNAVAILABLE_CODE, _UNAVAILABLE_MESSAGE)
