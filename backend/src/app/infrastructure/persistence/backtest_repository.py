from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.execution.contracts import ExecutionConfig
from app.infrastructure.persistence.models.backtests import (
    BacktestCandleRecord,
    BacktestEventRecord,
    BacktestRunRecord,
)
from app.market.contracts import Candle, ContractSymbol, MarketTimeframe
from app.market.repository import snapshot_payload_sha256
from app.research.backtests.contracts import (
    BacktestAuditEvent,
    BacktestClosedTrade,
    BacktestEventKind,
    BacktestFilters,
    BacktestNotFoundError,
    BacktestPage,
    BacktestRequest,
    BacktestResult,
    BacktestRunStatus,
    BacktestStorageUnavailableError,
    BacktestSummary,
    PersistedBacktestRun,
    candle_snapshot_payload,
)
from app.research.backtests.repository import BacktestRepository
from app.risk.contracts import RiskConfig


class SqlAlchemyBacktestRepository(BacktestRepository):
    """在 PostgreSQL 中保存回测运行、冻结 K 线和追加式审计事件。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_pending(
        self,
        request: BacktestRequest,
        *,
        occurred_at: datetime,
    ) -> PersistedBacktestRun:
        record = BacktestRunRecord(
            id=uuid4(),
            status=BacktestRunStatus.PENDING.value,
            symbol=request.symbol.value,
            timeframe=request.timeframe.value,
            start_at=request.start_at,
            end_at=request.end_at,
            initial_cash=request.initial_cash,
            strategy_id=request.strategy_id,
            strategy_version=request.strategy_version,
            parameters=_parameters(request),
            risk_config=cast(dict[str, object], request.risk_config.model_dump(mode="json")),
            execution_config=cast(
                dict[str, object],
                request.execution_config.model_dump(mode="json"),
            ),
            snapshot_hash=None,
            metrics=None,
            failure_code=None,
            failure_message=None,
            created_at=occurred_at,
            finished_at=None,
        )
        try:
            async with self._session_factory.begin() as session:
                session.add(record)
        except SQLAlchemyError as error:
            raise BacktestStorageUnavailableError("回测运行创建不可用") from error
        return _to_persisted_run(record, events=())

    async def complete(
        self,
        run_id: UUID,
        result: BacktestResult,
        candles: tuple[Candle, ...],
        *,
        occurred_at: datetime,
    ) -> PersistedBacktestRun:
        snapshot_hash = snapshot_payload_sha256(candle_snapshot_payload(candles))
        if snapshot_hash != result.summary.snapshot_hash:
            raise ValueError("回测结果快照哈希与冻结 K 线不一致")
        try:
            async with self._session_factory.begin() as session:
                record = await _get_pending_run_for_update(session, run_id)
                record.status = BacktestRunStatus.COMPLETED.value
                record.snapshot_hash = snapshot_hash
                record.metrics = _metrics(result)
                record.finished_at = occurred_at
                session.add_all(
                    _candle_records(run_id, candles),
                )
                session.add_all(
                    _event_records(run_id, result.events),
                )
                await session.flush()
                return _to_persisted_run(record, events=result.events)
        except BacktestNotFoundError:
            raise
        except SQLAlchemyError as error:
            raise BacktestStorageUnavailableError("回测运行完成不可用") from error

    async def fail(
        self,
        run_id: UUID,
        *,
        code: str,
        message: str,
        occurred_at: datetime,
    ) -> PersistedBacktestRun:
        try:
            async with self._session_factory.begin() as session:
                record = await _get_pending_run_for_update(session, run_id)
                record.status = BacktestRunStatus.FAILED.value
                record.failure_code = code
                record.failure_message = message
                record.finished_at = occurred_at
                await session.flush()
                return _to_persisted_run(record, events=())
        except BacktestNotFoundError:
            raise
        except SQLAlchemyError as error:
            raise BacktestStorageUnavailableError("回测运行失败状态不可用") from error

    async def list(self, filters: BacktestFilters) -> BacktestPage:
        statement = (
            select(BacktestRunRecord)
            .order_by(BacktestRunRecord.created_at.desc(), BacktestRunRecord.id.desc())
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        )
        count_statement = select(func.count()).select_from(BacktestRunRecord)
        try:
            async with self._session_factory() as session:
                records = tuple((await session.execute(statement)).scalars())
                total = (await session.execute(count_statement)).scalar_one()
                items: list[PersistedBacktestRun] = []
                for record in records:
                    items.append(await _to_persisted_run_from_database(session, record))
        except SQLAlchemyError as error:
            raise BacktestStorageUnavailableError("回测运行读取不可用") from error
        return BacktestPage(
            items=tuple(items),
            page=filters.page,
            page_size=filters.page_size,
            total=total,
        )

    async def get_by_id(self, run_id: UUID) -> PersistedBacktestRun | None:
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(BacktestRunRecord).where(BacktestRunRecord.id == run_id)
                )
                record = result.scalar_one_or_none()
                if record is None:
                    return None
                return await _to_persisted_run_from_database(session, record)
        except SQLAlchemyError as error:
            raise BacktestStorageUnavailableError("回测运行读取不可用") from error


async def _get_pending_run_for_update(
    session: AsyncSession,
    run_id: UUID,
) -> BacktestRunRecord:
    result = await session.execute(
        select(BacktestRunRecord)
        .where(BacktestRunRecord.id == run_id)
        .with_for_update()
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise BacktestNotFoundError("未找到回测运行")
    if record.status != BacktestRunStatus.PENDING.value:
        raise ValueError("回测运行不是待处理状态")
    return record


async def _to_persisted_run_from_database(
    session: AsyncSession,
    record: BacktestRunRecord,
) -> PersistedBacktestRun:
    events: tuple[BacktestAuditEvent, ...] = ()
    if record.status == BacktestRunStatus.COMPLETED.value:
        event_records = tuple(
            (
                await session.execute(
                    select(BacktestEventRecord)
                    .where(BacktestEventRecord.run_id == record.id)
                    .order_by(BacktestEventRecord.sequence.asc())
                )
            ).scalars()
        )
        events = tuple(_to_event(event) for event in event_records)
    return _to_persisted_run(record, events=events)


def _to_persisted_run(
    record: BacktestRunRecord,
    *,
    events: tuple[BacktestAuditEvent, ...],
) -> PersistedBacktestRun:
    request = BacktestRequest(
        symbol=ContractSymbol(record.symbol),
        timeframe=MarketTimeframe(record.timeframe),
        start_at=record.start_at,
        end_at=record.end_at,
        initial_cash=record.initial_cash,
        strategy_id=record.strategy_id,
        strategy_version=record.strategy_version,
        risk_config=RiskConfig.model_validate(record.risk_config),
        execution_config=ExecutionConfig.model_validate(record.execution_config),
    )
    status = BacktestRunStatus(record.status)
    result = None if record.metrics is None else _to_result(record.metrics, events)
    return PersistedBacktestRun(
        id=record.id,
        status=status,
        request=request,
        created_at=record.created_at,
        finished_at=record.finished_at,
        result=result,
        failure_code=record.failure_code,
        failure_message=record.failure_message,
    )


def _parameters(request: BacktestRequest) -> dict[str, object]:
    return {
        "start_at": request.start_at.isoformat(),
        "end_at": request.end_at.isoformat(),
        "initial_cash": format(request.initial_cash, "f"),
    }


def _metrics(result: BacktestResult) -> dict[str, object]:
    return cast(
        dict[str, object],
        {
            "summary": result.summary.model_dump(mode="json"),
            "closed_trades": [
                trade.model_dump(mode="json") for trade in result.closed_trades
            ],
        },
    )


def _candle_records(
    run_id: UUID,
    candles: tuple[Candle, ...],
) -> tuple[BacktestCandleRecord, ...]:
    return tuple(
        BacktestCandleRecord(
            run_id=run_id,
            sequence=sequence,
            symbol=str(candle.symbol),
            timeframe=candle.timeframe.value,
            open_at=candle.open_at,
            close_at=candle.close_at,
            open_price=candle.open_price,
            high_price=candle.high_price,
            low_price=candle.low_price,
            close_price=candle.close_price,
            volume=candle.volume,
            observed_at=candle.observed_at,
            fetched_at=candle.fetched_at,
        )
        for sequence, candle in enumerate(candles)
    )


def _event_records(
    run_id: UUID,
    events: tuple[BacktestAuditEvent, ...],
) -> tuple[BacktestEventRecord, ...]:
    return tuple(
        BacktestEventRecord(
            run_id=run_id,
            sequence=event.sequence,
            kind=event.kind.value,
            occurred_at=event.occurred_at,
            candle_sequence=event.candle_sequence,
            idempotency_key=event.idempotency_key,
            payload=cast(dict[str, object], event.payload),
        )
        for event in events
    )


def _to_event(record: BacktestEventRecord) -> BacktestAuditEvent:
    return BacktestAuditEvent(
        sequence=record.sequence,
        kind=BacktestEventKind(record.kind),
        occurred_at=record.occurred_at,
        candle_sequence=record.candle_sequence,
        idempotency_key=record.idempotency_key,
        payload=cast(dict[str, JsonValue], record.payload),
    )


def _to_result(
    metrics: dict[str, object],
    events: tuple[BacktestAuditEvent, ...],
) -> BacktestResult:
    summary = BacktestSummary.model_validate(metrics["summary"])
    closed_trades = tuple(
        BacktestClosedTrade.model_validate(trade)
        for trade in cast(list[object], metrics["closed_trades"])
    )
    return BacktestResult(
        summary=summary,
        events=events,
        closed_trades=closed_trades,
    )
