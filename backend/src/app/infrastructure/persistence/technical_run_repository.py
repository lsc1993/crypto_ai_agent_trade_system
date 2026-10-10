"""Atomic durable queue with bounded global concurrency and expiring ownership."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.harness import HarnessAuditEventRecord
from app.infrastructure.persistence.models.technical_reports import TechnicalReportRecord
from app.infrastructure.persistence.models.technical_runs import (
    TechnicalQueueRecord,
    TechnicalRequestRecord,
    TechnicalRunRecord,
)
from app.market.symbols import ResearchSymbol
from app.reports.technical import require_utc
from app.reports.technical_runs import (
    PHASES,
    TechnicalRun,
    TechnicalRunError,
    TechnicalRunPhase,
    TechnicalRunStatus,
)


def public_run(record: TechnicalRunRecord) -> TechnicalRun:
    return TechnicalRun.model_validate(
        {key: getattr(record, key) for key in TechnicalRun.model_fields}
    )


class SqlAlchemyTechnicalRunRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def _lock(self, session: AsyncSession) -> None:
        await session.scalar(
            select(TechnicalQueueRecord).where(TechnicalQueueRecord.id == 1).with_for_update()
        )

    async def enqueue(
        self, symbol: ResearchSymbol, *, request_id: UUID, now: datetime
    ) -> TechnicalRun:
        now = require_utc(now)
        try:
            async with self._factory() as session, session.begin():
                await self._lock(session)
                old = await session.get(TechnicalRequestRecord, request_id)
                if old:
                    record = await session.get(TechnicalRunRecord, old.run_id)
                    assert record is not None
                    if record.symbol != symbol:
                        raise TechnicalRunError("request_conflict")
                    return public_run(record)
                record = await session.scalar(
                    select(TechnicalRunRecord).where(
                        TechnicalRunRecord.symbol == symbol,
                        TechnicalRunRecord.status.in_(("queued", "running")),
                    )
                )
                if record is None:
                    count = await session.scalar(
                        select(func.count())
                        .select_from(TechnicalRunRecord)
                        .where(TechnicalRunRecord.status.in_(("queued", "running")))
                    )
                    if count is not None and count >= 20:
                        raise TechnicalRunError("queue_full")
                    record = TechnicalRunRecord(
                        id=uuid4(),
                        analysis_id=uuid4(),
                        symbol=symbol,
                        status="queued",
                        phase="queued",
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(record)
                    await session.flush()
                session.add(TechnicalRequestRecord(request_id=request_id, run_id=record.id))
                return public_run(record)
        except SQLAlchemyError:
            raise TechnicalRunError("storage_unavailable") from None

    async def get(self, run_id: UUID) -> TechnicalRun | None:
        try:
            async with self._factory() as session:
                record = await session.get(TechnicalRunRecord, run_id)
                return public_run(record) if record else None
        except SQLAlchemyError:
            raise TechnicalRunError("storage_unavailable") from None

    async def claim(self, *, owner: UUID, now: datetime) -> TechnicalRun | None:
        now = require_utc(now)
        try:
            async with self._factory() as session, session.begin():
                await self._lock(session)
                running = await session.scalar(
                    select(TechnicalRunRecord.id)
                    .where(TechnicalRunRecord.status == "running")
                    .limit(1)
                )
                if running:
                    return None
                record = await session.scalar(
                    select(TechnicalRunRecord)
                    .where(TechnicalRunRecord.status == "queued")
                    .order_by(TechnicalRunRecord.created_at, TechnicalRunRecord.id)
                    .limit(1)
                    .with_for_update()
                )
                if record is None:
                    return None
                record.status, record.phase = "running", "collecting"
                record.owner, record.lease_expires_at = owner, now + timedelta(seconds=30)
                record.started_at, record.updated_at = now, now
                return public_run(record)
        except SQLAlchemyError:
            raise TechnicalRunError("storage_unavailable") from None

    async def _owned(
        self, session: AsyncSession, run_id: UUID, owner: UUID, now: datetime
    ) -> TechnicalRunRecord | None:
        return await session.scalar(
            select(TechnicalRunRecord)
            .where(
                TechnicalRunRecord.id == run_id,
                TechnicalRunRecord.owner == owner,
                TechnicalRunRecord.status == "running",
                TechnicalRunRecord.lease_expires_at > now,
            )
            .with_for_update()
        )

    async def heartbeat(self, run_id: UUID, *, owner: UUID, now: datetime) -> bool:
        return await self._change(run_id, owner=owner, now=now)

    async def advance(
        self, run_id: UUID, *, owner: UUID, phase: TechnicalRunPhase, now: datetime
    ) -> bool:
        return await self._change(run_id, owner=owner, now=now, phase=phase)

    async def finish(
        self,
        run_id: UUID,
        *,
        owner: UUID,
        status: TechnicalRunStatus,
        report_id: UUID | None,
        error_code: str | None,
        now: datetime,
    ) -> bool:
        return await self._change(
            run_id, owner=owner, now=now, status=status, report_id=report_id, error_code=error_code
        )

    async def _change(
        self,
        run_id: UUID,
        *,
        owner: UUID,
        now: datetime,
        phase: TechnicalRunPhase | None = None,
        status: TechnicalRunStatus | None = None,
        report_id: UUID | None = None,
        error_code: str | None = None,
    ) -> bool:
        now = require_utc(now)
        try:
            async with self._factory() as session, session.begin():
                record = await self._owned(session, run_id, owner, now)
                if record is None:
                    return False
                if phase:
                    if phase in {"queued", "finished"} or PHASES.index(phase) < PHASES.index(
                        record.phase
                    ):
                        raise ValueError("phase_regression")
                    record.phase = phase
                elif status:
                    if status not in {"completed", "degraded", "failed"}:
                        raise ValueError("terminal_status")
                    if status == "failed":
                        committed = await session.scalar(
                            select(TechnicalReportRecord).where(
                                TechnicalReportRecord.analysis_id == record.analysis_id
                            )
                        )
                        if committed:
                            status = "completed" if committed.status == "completed" else "degraded"
                            report_id, error_code = committed.id, None
                    if report_id:
                        report = await session.get(TechnicalReportRecord, report_id)
                        if (
                            not report
                            or report.analysis_id != record.analysis_id
                            or report.status != status
                        ):
                            raise ValueError("report_association")
                    record.status, record.phase = status, "finished"
                    record.report_id, record.error_code, record.finished_at = (
                        report_id,
                        error_code,
                        now,
                    )
                    record.owner, record.lease_expires_at = None, None
                    if status == "failed":
                        await self._close_failed_audit(
                            session, record.analysis_id, now, error_code or "research_failed"
                        )
                else:
                    record.lease_expires_at = now + timedelta(seconds=30)
                record.updated_at = now
                public_run(record)
                return True
        except SQLAlchemyError:
            raise TechnicalRunError("storage_unavailable") from None

    async def recover_expired(self, *, now: datetime) -> int:
        now = require_utc(now)
        try:
            async with self._factory() as session, session.begin():
                await self._lock(session)
                records = (
                    await session.scalars(
                        select(TechnicalRunRecord)
                        .where(
                            TechnicalRunRecord.status == "running",
                            TechnicalRunRecord.lease_expires_at <= now,
                        )
                        .with_for_update()
                    )
                ).all()
                for record in records:
                    report = await session.scalar(
                        select(TechnicalReportRecord).where(
                            TechnicalReportRecord.analysis_id == record.analysis_id
                        )
                    )
                    record.status = report.status if report else "failed"
                    record.report_id = report.id if report else None
                    record.error_code = None if report else "interrupted"
                    record.phase, record.finished_at, record.updated_at = "finished", now, now
                    record.owner, record.lease_expires_at = None, None
                    if report is None:
                        await self._close_failed_audit(
                            session, record.analysis_id, now, "interrupted"
                        )
                return len(records)
        except SQLAlchemyError:
            raise TechnicalRunError("storage_unavailable") from None

    async def _close_failed_audit(
        self,
        session: AsyncSession,
        analysis_id: UUID,
        now: datetime,
        code: str,
    ) -> None:
        started = await session.get(HarnessAuditEventRecord, (analysis_id, 2))
        terminal = await session.get(HarnessAuditEventRecord, (analysis_id, 3))
        if started is not None and terminal is None:
            await session.execute(
                insert(HarnessAuditEventRecord)
                .values(
                    run_id=analysis_id,
                    sequence=3,
                    event_kind="workflow_failed",
                    occurred_at=now,
                    duration_ms=max(0, int((now - started.occurred_at).total_seconds() * 1000)),
                    error_code=code,
                    details={"error_type": "InterruptedRun"},
                )
                .on_conflict_do_nothing(index_elements=["run_id", "sequence"])
            )
