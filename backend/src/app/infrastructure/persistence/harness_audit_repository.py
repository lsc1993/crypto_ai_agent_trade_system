from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.harness.audit import (
    HarnessAuditEvent,
    HarnessAuditEventKind,
    HarnessAuditRepository,
    HarnessAuditRun,
    HarnessAuditStorageUnavailableError,
    HarnessAuditTrace,
    HarnessEvaluation,
    HarnessEvaluationDecision,
    HarnessEvaluationDetails,
    HarnessEventDetails,
    HarnessInitiatorKind,
)
from app.harness.contracts import HarnessRunKind
from app.infrastructure.persistence.models.harness import (
    HarnessAuditEventRecord,
    HarnessAuditRunRecord,
    HarnessEvaluationRecord,
)


class SqlAlchemyHarnessAuditRepository(HarnessAuditRepository):
    """Append and read immutable Harness audit traces in PostgreSQL."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_requested_run(
        self,
        run: HarnessAuditRun,
        event: HarnessAuditEvent,
    ) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add(_run_record(run))
                    await session.flush()
                    session.add(_event_record(event))
        except SQLAlchemyError:
            raise HarnessAuditStorageUnavailableError from None

    async def append_policy_evaluation(
        self,
        evaluation: HarnessEvaluation,
        event: HarnessAuditEvent,
    ) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add_all((_evaluation_record(evaluation), _event_record(event)))
        except SQLAlchemyError:
            raise HarnessAuditStorageUnavailableError from None

    async def append_event(self, event: HarnessAuditEvent) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add(_event_record(event))
        except SQLAlchemyError:
            raise HarnessAuditStorageUnavailableError from None

    async def get_trace(self, run_id: UUID) -> HarnessAuditTrace | None:
        try:
            async with self._session_factory() as session:
                run_record = (
                    await session.execute(
                        select(HarnessAuditRunRecord).where(
                            HarnessAuditRunRecord.run_id == run_id
                        )
                    )
                ).scalar_one_or_none()
                if run_record is None:
                    return None
                event_records = tuple(
                    (
                        await session.execute(
                            select(HarnessAuditEventRecord)
                            .where(HarnessAuditEventRecord.run_id == run_id)
                            .order_by(HarnessAuditEventRecord.sequence.asc())
                        )
                    ).scalars()
                )
                evaluation_records = tuple(
                    (
                        await session.execute(
                            select(HarnessEvaluationRecord)
                            .where(HarnessEvaluationRecord.run_id == run_id)
                            .order_by(HarnessEvaluationRecord.sequence.asc())
                        )
                    ).scalars()
                )
        except SQLAlchemyError:
            raise HarnessAuditStorageUnavailableError from None
        return HarnessAuditTrace(
            run=_to_run(run_record),
            events=tuple(_to_event(record) for record in event_records),
            evaluations=tuple(_to_evaluation(record) for record in evaluation_records),
        )


def _run_record(run: HarnessAuditRun) -> HarnessAuditRunRecord:
    return HarnessAuditRunRecord(
        run_id=run.run_id,
        run_kind=run.run_kind.value,
        policy_version=run.policy_version,
        policy_sha256=run.policy_sha256,
        symbol=run.symbol,
        requested_at=run.requested_at,
        initiator_kind=run.initiator_kind.value,
        request_sha256=run.request_sha256,
    )


def _event_record(event: HarnessAuditEvent) -> HarnessAuditEventRecord:
    return HarnessAuditEventRecord(
        run_id=event.run_id,
        sequence=event.sequence,
        event_kind=event.kind.value,
        occurred_at=event.occurred_at,
        duration_ms=event.duration_ms,
        error_code=event.error_code,
        details=event.details.model_dump(mode="json"),
    )


def _evaluation_record(evaluation: HarnessEvaluation) -> HarnessEvaluationRecord:
    return HarnessEvaluationRecord(
        run_id=evaluation.run_id,
        sequence=evaluation.sequence,
        evaluator_name=evaluation.evaluator_name,
        evaluator_version=evaluation.evaluator_version,
        decision=evaluation.decision.value,
        reason_code=evaluation.reason_code,
        evaluated_at=evaluation.evaluated_at,
        details=evaluation.details.model_dump(mode="json"),
    )


def _to_run(record: HarnessAuditRunRecord) -> HarnessAuditRun:
    return HarnessAuditRun(
        run_id=record.run_id,
        run_kind=HarnessRunKind(record.run_kind),
        policy_version=record.policy_version,
        policy_sha256=record.policy_sha256,
        symbol=record.symbol,
        requested_at=record.requested_at,
        initiator_kind=HarnessInitiatorKind(record.initiator_kind),
        request_sha256=record.request_sha256,
    )


def _to_event(record: HarnessAuditEventRecord) -> HarnessAuditEvent:
    return HarnessAuditEvent(
        run_id=record.run_id,
        sequence=record.sequence,
        kind=HarnessAuditEventKind(record.event_kind),
        occurred_at=record.occurred_at,
        duration_ms=record.duration_ms,
        error_code=record.error_code,
        details=HarnessEventDetails.model_validate(record.details),
    )


def _to_evaluation(record: HarnessEvaluationRecord) -> HarnessEvaluation:
    return HarnessEvaluation(
        run_id=record.run_id,
        sequence=record.sequence,
        evaluator_name=cast(Literal["policy_allowlist"], record.evaluator_name),
        evaluator_version=cast(Literal["1"], record.evaluator_version),
        decision=HarnessEvaluationDecision(record.decision),
        reason_code=record.reason_code,
        evaluated_at=record.evaluated_at,
        details=HarnessEvaluationDetails.model_validate(record.details),
    )
