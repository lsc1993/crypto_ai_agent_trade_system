# 验证技术队列请求幂等、全局单任务执行和队列容量。
# 并发提交与固定租约时间复现竞争、超时所有权和进程中断。
# 已提交报告应恢复为成功终态而非再次入队，已开始的审计轨迹需闭合。
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.agent.technical.plan_service import TechnicalPlanResearchService
from app.harness.technical_research import HarnessedTechnicalPlanExecutor
from app.infrastructure.persistence.harness_audit_repository import SqlAlchemyHarnessAuditRepository
from app.infrastructure.persistence.models.technical_runs import TechnicalRunRecord
from app.infrastructure.persistence.technical_report_repository import (
    SqlAlchemyTechnicalReportRepository,
)
from app.infrastructure.persistence.technical_run_repository import SqlAlchemyTechnicalRunRepository
from app.reports.technical_runs import TechnicalRunError, TechnicalRunLease
from tests.agent.test_technical_engine import NOW
from tests.agent.test_technical_plan_service import Model, noop
from tests.agent.test_technical_service import Market, technical_clock
from tests.conftest import MigratedDatabase

# Reuse the existing audited lifecycle fixture without changing its public surface.
from tests.persistence.test_harness_audit_repository import (
    _admitted_run,  # pyright: ignore[reportPrivateUsage]
)


@pytest.mark.asyncio
async def test_request_id_replay_and_symbol_conflict(migrated_database: MigratedDatabase) -> None:
    repo = SqlAlchemyTechnicalRunRepository(migrated_database.session_factory)
    request = uuid4()
    first = await repo.enqueue("BTCUSDT", request_id=request, now=NOW)
    assert await repo.enqueue("BTCUSDT", request_id=request, now=NOW) == first
    alias = uuid4()
    assert (await repo.enqueue("BTCUSDT", request_id=alias, now=NOW)).id == first.id
    with pytest.raises(TechnicalRunError, match="request_conflict"):
        await repo.enqueue("ETHUSDT", request_id=alias, now=NOW)


@pytest.mark.asyncio
async def test_only_one_global_run_claimed_and_expired_owner_rejected(
    migrated_database: MigratedDatabase,
) -> None:
    repo = SqlAlchemyTechnicalRunRepository(migrated_database.session_factory)
    await repo.enqueue("BTCUSDT", request_id=uuid4(), now=NOW)
    await repo.enqueue("ETHUSDT", request_id=uuid4(), now=NOW)
    owners = (uuid4(), uuid4())
    claimed = await asyncio.gather(*(repo.claim(owner=owner, now=NOW) for owner in owners))
    assert sum(run is not None for run in claimed) == 1
    index = next(i for i, run in enumerate(claimed) if run is not None)
    run = claimed[index]
    assert run is not None
    assert await repo.heartbeat(run.id, owner=owners[index], now=NOW + timedelta(seconds=10))
    assert not await repo.advance(
        run.id, owner=owners[index], phase="analyzing", now=NOW + timedelta(seconds=41)
    )
    assert await repo.recover_expired(now=NOW + timedelta(seconds=41)) == 1
    recovered = await repo.get(run.id)
    assert recovered and recovered.status == "failed" and recovered.error_code == "interrupted"


# 同时提交超过容量的不同币种，验证容量检查由数据库协调而非先查后写。
@pytest.mark.asyncio
async def test_concurrent_queue_capacity_twenty(migrated_database: MigratedDatabase) -> None:
    repo = SqlAlchemyTechnicalRunRepository(migrated_database.session_factory)

    async def submit(index: int):
        try:
            return await repo.enqueue(f"COIN{index}USDT", request_id=uuid4(), now=NOW)
        except TechnicalRunError as error:
            return error

    results = await asyncio.gather(*(submit(i) for i in range(25)))
    assert sum(isinstance(result, TechnicalRunError) for result in results) == 5


# 模拟报告提交后任务收尾失败；恢复应读取已提交报告，避免再次执行模型。
@pytest.mark.asyncio
async def test_report_commit_recovery_does_not_reenqueue(
    migrated_database: MigratedDatabase,
) -> None:
    factory = migrated_database.session_factory
    repo, reports = (
        SqlAlchemyTechnicalRunRepository(factory),
        SqlAlchemyTechnicalReportRepository(factory),
    )
    run = await repo.enqueue("BTCUSDT", request_id=uuid4(), now=datetime.now(UTC))
    owner = uuid4()
    assert await repo.claim(owner=owner, now=datetime.now(UTC))

    async def allowed(symbol: str) -> bool:
        return True

    async def lease() -> TechnicalRunLease:
        return TechnicalRunLease(run.id, owner)

    service = TechnicalPlanResearchService(
        market=Market(), repository=reports, model=Model(), clock=technical_clock
    )
    executor = HarnessedTechnicalPlanExecutor(
        service,
        audit=SqlAlchemyHarnessAuditRepository(factory),
        authorizer=allowed,
        clock=technical_clock,
    )
    report = await executor.generate(
        "BTCUSDT", analysis_id=run.analysis_id, progress=noop, before_save=lease
    )
    assert report.version == "technical-v2"
    assert (await reports.get_by_analysis_id(run.analysis_id)) == report
    assert await repo.finish(
        run.id,
        owner=owner,
        status="failed",
        report_id=None,
        error_code="research_failed",
        now=datetime.now(UTC),
    )
    saved = await repo.get(run.id)
    assert saved and saved.report_id == report.id and saved.status == "completed"
    assert not await repo.claim(owner=uuid4(), now=datetime.now(UTC))


@pytest.mark.asyncio
@pytest.mark.parametrize("recover", [True, False])
async def test_crash_recovery_closes_started_harness_trace(
    migrated_database: MigratedDatabase,
    recover: bool,
) -> None:
    factory = migrated_database.session_factory
    repo = SqlAlchemyTechnicalRunRepository(factory)
    run = await repo.enqueue("BTCUSDT", request_id=uuid4(), now=NOW)
    recording = _admitted_run()
    audit = SqlAlchemyHarnessAuditRepository(factory)
    await audit.create_requested_run(recording.run, recording.requested)
    await audit.append_policy_evaluation(recording.evaluation, recording.authorized)
    await audit.append_event(recording.started)
    async with factory() as session, session.begin():
        await session.execute(
            update(TechnicalRunRecord)
            .where(TechnicalRunRecord.id == run.id)
            .values(analysis_id=recording.run.run_id)
        )
    owner = uuid4()
    assert await repo.claim(owner=owner, now=NOW)
    if recover:
        assert await repo.recover_expired(now=NOW + timedelta(seconds=31)) == 1
    else:
        assert await repo.finish(
            run.id,
            owner=owner,
            status="failed",
            report_id=None,
            error_code="interrupted",
            now=NOW + timedelta(seconds=1),
        )
    trace = await audit.get_trace(recording.run.run_id)
    assert trace and trace.events[-1].kind.value == "workflow_failed"
    assert trace.events[-1].error_code == "interrupted"
    assert await repo.recover_expired(now=NOW + timedelta(seconds=32)) == 0
