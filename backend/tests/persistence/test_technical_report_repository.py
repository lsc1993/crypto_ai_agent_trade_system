from typing import Protocol
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.technical.service import TechnicalResearchService
from app.harness.runtime import HarnessRuntime
from app.harness.technical_research import (
    TECHNICAL_RESEARCH_POLICY,
    HarnessedTechnicalResearchService,
    TechnicalResearchWorkflow,
)
from app.infrastructure.persistence.harness_audit_repository import SqlAlchemyHarnessAuditRepository
from app.infrastructure.persistence.models.technical_reports import TechnicalReportRecord
from app.infrastructure.persistence.technical_report_repository import (
    SqlAlchemyTechnicalReportRepository,
)
from tests.agent.test_technical_service import Market, Model, technical_clock


class Database(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


@pytest.mark.asyncio
async def test_persists_frozen_report_and_atomic_terminal_audit(
    migrated_database: Database,
) -> None:
    factory = migrated_database.session_factory
    repository = SqlAlchemyTechnicalReportRepository(factory)
    audit = SqlAlchemyHarnessAuditRepository(factory)
    service = TechnicalResearchService(
        market=Market(), repository=repository, model=Model(), clock=technical_clock
    )
    runtime = HarnessRuntime(
        policies=(TECHNICAL_RESEARCH_POLICY,),
        workflows=(TechnicalResearchWorkflow(service),),
        audit_repository=audit,
    )
    report = await HarnessedTechnicalResearchService(runtime, clock=technical_clock).generate(
        "BTCUSDT"
    )
    assert await repository.get(report.id) == report
    trace = await audit.get_trace(report.analysis_id)
    assert trace is not None
    assert [event.kind.value for event in trace.events] == [
        "requested",
        "policy_authorized",
        "workflow_started",
        "workflow_completed",
    ]
    page = await repository.list(symbol="BTCUSDT", page=1, page_size=10)
    assert page.items == (report,)
    async with factory() as session:
        record = (await session.execute(select(TechnicalReportRecord))).scalar_one()
        assert record.frozen_evidence["market"]
        assert len(record.evidence_sha256) == 64
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(update(TechnicalReportRecord).values(symbol="ETHUSDT"))
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_missing_harness_run_rolls_back_report(migrated_database: Database) -> None:
    repository = SqlAlchemyTechnicalReportRepository(migrated_database.session_factory)
    service = TechnicalResearchService(
        market=Market(), repository=repository, model=Model(), clock=technical_clock
    )
    from app.reports.contracts import ReportStorageUnavailableError

    with pytest.raises(ReportStorageUnavailableError):
        await service.generate("BTCUSDT", analysis_id=uuid4())
    assert (await repository.list(symbol=None, page=1, page_size=10)).total == 0
