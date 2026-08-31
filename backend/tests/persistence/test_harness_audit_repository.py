from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.harness.audit import (
    HarnessAuditEvent,
    HarnessAuditEventKind,
    HarnessAuditRun,
    HarnessAuditStorageUnavailableError,
    HarnessEvaluation,
    HarnessEvaluationDecision,
    HarnessEvaluationDetails,
    HarnessEventDetails,
    HarnessInitiatorKind,
)
from app.harness.contracts import HarnessRunKind
from app.infrastructure.persistence.harness_audit_repository import (
    SqlAlchemyHarnessAuditRepository,
)
from app.infrastructure.persistence.models.harness import (
    HarnessAuditEventRecord,
    HarnessAuditRunRecord,
    HarnessEvaluationRecord,
)
from app.market.contracts import ContractSymbol

NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)


class MigratedDatabase(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class Recording:
    run: HarnessAuditRun
    requested: HarnessAuditEvent
    evaluation: HarnessEvaluation
    authorized: HarnessAuditEvent
    started: HarnessAuditEvent


@pytest.mark.asyncio
async def test_repository_appends_and_reads_an_ordered_trace(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyHarnessAuditRepository(migrated_database.session_factory)
    recording = _admitted_run()

    await repository.create_requested_run(recording.run, recording.requested)
    await repository.append_policy_evaluation(recording.evaluation, recording.authorized)
    await repository.append_event(recording.started)

    trace = await repository.get_trace(recording.run.run_id)

    assert trace is not None
    assert trace.run == recording.run
    assert [event.kind for event in trace.events] == [
        HarnessAuditEventKind.REQUESTED,
        HarnessAuditEventKind.POLICY_AUTHORIZED,
        HarnessAuditEventKind.WORKFLOW_STARTED,
    ]
    assert trace.evaluations == (recording.evaluation,)


@pytest.mark.asyncio
async def test_repository_returns_none_when_the_run_is_absent(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyHarnessAuditRepository(migrated_database.session_factory)

    assert await repository.get_trace(uuid4()) is None


@pytest.mark.asyncio
async def test_repository_translates_a_duplicate_append_to_the_safe_storage_error(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyHarnessAuditRepository(migrated_database.session_factory)
    recording = _admitted_run()
    await repository.create_requested_run(recording.run, recording.requested)

    with pytest.raises(
        HarnessAuditStorageUnavailableError,
        match="Harness 审计存储不可用",
    ) as raised:
        await repository.append_event(recording.requested)

    assert raised.value.__cause__ is None
    assert "harness_run_events" not in str(raised.value)


@pytest.mark.asyncio
async def test_database_rejects_update_and_delete_of_every_harness_record(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyHarnessAuditRepository(migrated_database.session_factory)
    recording = _admitted_run()
    await repository.create_requested_run(recording.run, recording.requested)
    await repository.append_policy_evaluation(recording.evaluation, recording.authorized)

    mutations = (
        update(HarnessAuditRunRecord)
        .where(HarnessAuditRunRecord.run_id == recording.run.run_id)
        .values(symbol=ContractSymbol.ETHUSDT.value),
        delete(HarnessAuditRunRecord).where(
            HarnessAuditRunRecord.run_id == recording.run.run_id
        ),
        update(HarnessAuditEventRecord)
        .where(HarnessAuditEventRecord.run_id == recording.run.run_id)
        .values(duration_ms=1),
        delete(HarnessAuditEventRecord).where(
            HarnessAuditEventRecord.run_id == recording.run.run_id
        ),
        update(HarnessEvaluationRecord)
        .where(HarnessEvaluationRecord.run_id == recording.run.run_id)
        .values(decision=HarnessEvaluationDecision.REJECTED.value),
        delete(HarnessEvaluationRecord).where(
            HarnessEvaluationRecord.run_id == recording.run.run_id
        ),
    )

    async with migrated_database.session_factory() as session:
        for mutation in mutations:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(mutation)
                await session.commit()
            await session.rollback()


@pytest.mark.asyncio
async def test_repository_never_stores_raw_context_in_details(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyHarnessAuditRepository(migrated_database.session_factory)
    recording = _admitted_run()
    await repository.create_requested_run(recording.run, recording.requested)
    await repository.append_policy_evaluation(recording.evaluation, recording.authorized)
    await repository.append_event(recording.started)

    async with migrated_database.session_factory() as session:
        event_details = tuple(
            (
                await session.execute(
                    select(HarnessAuditEventRecord.details).where(
                        HarnessAuditEventRecord.run_id == recording.run.run_id
                    )
                )
            ).scalars()
        )
        evaluation_details = tuple(
            (
                await session.execute(
                    select(HarnessEvaluationRecord.details).where(
                        HarnessEvaluationRecord.run_id == recording.run.run_id
                    )
                )
            ).scalars()
        )

    assert all("raw_context" not in details for details in event_details)
    assert all("raw_context" not in details for details in evaluation_details)


def _admitted_run() -> Recording:
    run_id = uuid4()
    run = HarnessAuditRun(
        run_id=run_id,
        run_kind=HarnessRunKind.MARKET_RESEARCH,
        policy_version="market_research_v1",
        policy_sha256="a" * 64,
        symbol=ContractSymbol.BTCUSDT,
        requested_at=NOW,
        initiator_kind=HarnessInitiatorKind.MANUAL_API,
        request_sha256="b" * 64,
    )
    requested = HarnessAuditEvent(
        run_id=run_id,
        sequence=0,
        kind=HarnessAuditEventKind.REQUESTED,
        occurred_at=NOW,
        duration_ms=0,
        error_code=None,
        details=HarnessEventDetails(declared_capability_count=4),
    )
    evaluation = HarnessEvaluation(
        run_id=run_id,
        sequence=0,
        evaluator_name="policy_allowlist",
        evaluator_version="1",
        decision=HarnessEvaluationDecision.PASSED,
        reason_code=None,
        evaluated_at=NOW + timedelta(milliseconds=1),
        details=HarnessEvaluationDetails(
            declared_capability_count=4,
            allowed_capability_count=4,
        ),
    )
    authorized = HarnessAuditEvent(
        run_id=run_id,
        sequence=1,
        kind=HarnessAuditEventKind.POLICY_AUTHORIZED,
        occurred_at=NOW + timedelta(milliseconds=1),
        duration_ms=1,
        error_code=None,
        details=HarnessEventDetails(allowed_capability_count=4),
    )
    started = HarnessAuditEvent(
        run_id=run_id,
        sequence=2,
        kind=HarnessAuditEventKind.WORKFLOW_STARTED,
        occurred_at=NOW + timedelta(milliseconds=2),
        duration_ms=2,
        error_code=None,
        details=HarnessEventDetails(workflow_kind=HarnessRunKind.MARKET_RESEARCH),
    )
    return Recording(
        run=run,
        requested=requested,
        evaluation=evaluation,
        authorized=authorized,
        started=started,
    )
