# 使用真实 worker、Harness 与 SQL 仓储验收中断、恢复和幂等，不连接真实模型。
# 新建仓储/worker 模拟进程对象重建；UTC 时钟推进复现租约到期，不等待三十秒。
# 不模拟完整操作系统崩溃；测试只接触 migrated_database 的随机 schema。
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.technical.worker import TechnicalResearchWorker
from app.infrastructure.persistence.harness_audit_repository import SqlAlchemyHarnessAuditRepository
from app.infrastructure.persistence.technical_report_repository import (
    SqlAlchemyTechnicalReportRepository,
)
from app.infrastructure.persistence.technical_run_repository import SqlAlchemyTechnicalRunRepository
from app.reports.contracts import ReportStorageUnavailableError
from app.reports.technical_plan import TechnicalPlanReport
from app.reports.technical_runs import TechnicalRunError, TechnicalRunLease
from scripts.http_e2e_research import research_runtime
from tests.conftest import MigratedDatabase


@pytest.mark.asyncio
async def test_killed_worker_process_is_recovered_without_replay(
    migrated_database: MigratedDatabase,
    tmp_path: Path,
) -> None:
    # 子进程实际运行生产 worker 并提交领取/阶段变更后被强制终止；没有机会执行 finally。
    # 仅以安全 PID 文件同步，不打印连接串、异常、模型内容，不接触其他测试 schema。
    factory = migrated_database.session_factory
    engine = cast(AsyncEngine, factory.kw["bind"])
    mapping = cast(dict[object, str], engine.get_execution_options()["schema_translate_map"])
    schema = mapping[None]
    now = datetime.now(UTC)
    run = await SqlAlchemyTechnicalRunRepository(factory).enqueue(
        "BTCUSDT", request_id=uuid4(), now=now
    )
    ready = tmp_path / "worker-ready.json"
    child = """
import asyncio, json, os, re
from datetime import UTC, datetime
from pathlib import Path
from app.agent.technical.worker import TechnicalResearchWorker
from app.infrastructure.persistence.technical_run_repository import SqlAlchemyTechnicalRunRepository
from app.shared.database import create_async_engine_from_secret, create_session_factory
from scripts.check_test_database import check_test_database
async def main():
    url = await check_test_database()
    schema = os.environ['RUNTIME_TEST_SCHEMA']
    assert re.fullmatch(r'market_test_[0-9a-f]{16}', schema)
    engine = create_async_engine_from_secret(url).execution_options(
        schema_translate_map={None:schema})
    class Blocked:
        async def generate(self, symbol, *, analysis_id, progress, before_save):
            await progress('analyzing')
            ready = Path(os.environ['RUNTIME_TEST_READY'])
            ready.with_suffix('.pending').write_text(json.dumps({'pid':os.getpid()}))
            ready.with_suffix('.pending').replace(ready)
            await asyncio.Event().wait()
    repository = SqlAlchemyTechnicalRunRepository(create_session_factory(engine))
    worker = TechnicalResearchWorker(repository=repository,
        executor=Blocked(), clock=lambda:datetime.now(UTC))
    await worker.run_once()
asyncio.run(main())
"""
    environment = dict(os.environ)
    environment.update(
        RUNTIME_TEST_SCHEMA=schema,
        RUNTIME_TEST_READY=str(ready),
        PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"),
    )
    process = subprocess.Popen(
        [sys.executable, "-c", child],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(15):
            while not ready.is_file():
                assert process.poll() is None, "worker process exited before claiming"
                await asyncio.sleep(0.05)
        pid = json.loads(ready.read_text())["pid"]
        saved = await SqlAlchemyTechnicalRunRepository(factory).get(run.id)
        assert saved and saved.status == "running" and saved.phase == "analyzing"
        os.kill(pid, signal.SIGTERM)
        await asyncio.to_thread(process.wait, 10)
        assert process.returncode != 0
        executor = NeverExecute()
        fresh = SqlAlchemyTechnicalRunRepository(factory)
        restart = TechnicalResearchWorker(
            repository=fresh,
            executor=executor,
            clock=lambda: datetime.now(UTC) + timedelta(seconds=31),
        )
        assert not await restart.run_once()
        recovered = await fresh.get(run.id)
        assert recovered and recovered.error_code == "interrupted"
        assert recovered.status == "failed" and executor.calls == 0
    finally:
        if process.poll() is None:
            if ready.is_file():
                try:
                    os.kill(json.loads(ready.read_text())["pid"], signal.SIGTERM)
                except ProcessLookupError:
                    pass
            process.kill()
        await asyncio.to_thread(process.wait, 10)


class NeverExecute:
    # 恢复/重复领取若错误地重放模型，立刻失败并留下实际调用计数。
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, *args: Any, **kwargs: Any) -> TechnicalPlanReport:
        self.calls += 1
        raise AssertionError("unexpected research replay")


@pytest.mark.asyncio
async def test_cancel_after_report_commit_preserves_completed_run(
    migrated_database: MigratedDatabase,
) -> None:
    # 在真实服务/Harness 已保存报告与终态审计后阻塞返回，精确取消 worker 收尾窗口。
    committed = asyncio.Event()
    async with research_runtime(migrated_database.session_factory, background=False) as runtime:

        class AfterCommit:
            async def generate(self, symbol: str, **kwargs: Any) -> TechnicalPlanReport:
                report = await runtime.generate(symbol, **kwargs)
                committed.set()
                await asyncio.Event().wait()
                return report

        request_id = uuid4()
        run = await runtime.runs.enqueue("BTCUSDT", request_id=request_id, now=datetime.now(UTC))
        worker = TechnicalResearchWorker(
            repository=runtime.runs, executor=AfterCommit(), clock=lambda: datetime.now(UTC)
        )
        task = asyncio.create_task(worker.run_once())
        try:
            await asyncio.wait_for(committed.wait(), timeout=10)
            report = await runtime.reports.get_by_analysis_id(run.analysis_id)
            assert report and report.status == "completed"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
            saved = await runtime.runs.get(run.id)
            assert saved and saved.status == "completed" and saved.report_id == report.id
            assert saved.error_code is None
            assert (
                await runtime.runs.enqueue("BTCUSDT", request_id=request_id, now=datetime.now(UTC))
            ).id == run.id
            no_calls = NeverExecute()
            restart = TechnicalResearchWorker(
                repository=SqlAlchemyTechnicalRunRepository(runtime.factory),
                executor=no_calls,
                clock=lambda: datetime.now(UTC),
            )
            assert not await restart.run_once()
            assert no_calls.calls == 0
            trace = await SqlAlchemyHarnessAuditRepository(runtime.factory).get_trace(
                run.analysis_id
            )
            assert trace and len(trace.events) == 4
            assert trace.events[-1].kind.value == "workflow_completed"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_new_worker_expires_unsaved_run_without_replay(
    migrated_database: MigratedDatabase,
) -> None:
    now = datetime.now(UTC)
    factory = migrated_database.session_factory
    original = SqlAlchemyTechnicalRunRepository(factory)
    request_id, owner = uuid4(), uuid4()
    run = await original.enqueue("BTCUSDT", request_id=request_id, now=now)
    assert await original.claim(owner=owner, now=now)
    fresh, executor = SqlAlchemyTechnicalRunRepository(factory), NeverExecute()
    future = now + timedelta(seconds=31)
    worker = TechnicalResearchWorker(repository=fresh, executor=executor, clock=lambda: future)
    assert not await worker.run_once()
    saved = await fresh.get(run.id)
    assert saved and saved.status == "failed" and saved.error_code == "interrupted"
    assert not await original.advance(run.id, owner=owner, phase="saving", now=future)
    assert not await original.heartbeat(run.id, owner=owner, now=future)
    assert (await fresh.enqueue("BTCUSDT", request_id=request_id, now=future)).id == run.id
    assert not await worker.run_once()
    assert executor.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol,status", [("BTCUSDT", "completed"), ("ETHUSDT", "degraded")])
async def test_committed_report_survives_finish_failure_and_restart(
    migrated_database: MigratedDatabase,
    symbol: str,
    status: str,
) -> None:
    # 仅故障注入 worker 最后一次可变状态写入；报告与审计事务仍为真实实现。
    class FinishUnavailable(SqlAlchemyTechnicalRunRepository):
        async def finish(self, *args: Any, **kwargs: Any) -> bool:
            raise TechnicalRunError("storage_unavailable")

    factory, now = migrated_database.session_factory, datetime.now(UTC)
    async with research_runtime(factory, background=False) as runtime:
        run = await runtime.runs.enqueue(symbol, request_id=uuid4(), now=now)
        worker = TechnicalResearchWorker(
            repository=FinishUnavailable(factory), executor=runtime, clock=lambda: now
        )
        assert await worker.run_once()
        committed = await SqlAlchemyTechnicalReportRepository(factory).get_by_analysis_id(
            run.analysis_id
        )
        assert committed and committed.status == status
        pending = await runtime.runs.get(run.id)
        assert pending and pending.status == "running"
        executor = NeverExecute()
        fresh = SqlAlchemyTechnicalRunRepository(factory)
        restart = TechnicalResearchWorker(
            repository=fresh, executor=executor, clock=lambda: now + timedelta(seconds=31)
        )
        assert not await restart.run_once()
        recovered = await fresh.get(run.id)
        assert recovered and recovered.status == status and recovered.report_id == committed.id
        assert (
            await SqlAlchemyTechnicalReportRepository(factory).list(
                symbol=symbol, page=1, page_size=20
            )
        ).total == 1
        trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(run.analysis_id)
        assert trace and len(trace.events) == 4
        assert trace.events[-1].kind.value == (
            "workflow_completed" if status == "completed" else "workflow_degraded"
        )
        assert executor.calls == 0


@pytest.mark.asyncio
async def test_concurrent_replays_produce_one_report(migrated_database: MigratedDatabase) -> None:
    async with research_runtime(migrated_database.session_factory, background=False) as runtime:
        now, request = datetime.now(UTC), uuid4()
        runs = await asyncio.gather(
            *[
                runtime.runs.enqueue("BTCUSDT", request_id=request if i < 3 else uuid4(), now=now)
                for i in range(6)
            ]
        )
        assert len({run.id for run in runs}) == 1
        assert await runtime.worker.run_once()
        assert not await runtime.worker.run_once()
        assert runtime.calls == [("BTCUSDT", "analysis"), ("BTCUSDT", "composition")]
        assert (await runtime.reports.list(symbol="BTCUSDT", page=1, page_size=20)).total == 1


@pytest.mark.asyncio
async def test_cancellation_stops_model_and_restart_does_not_replay(
    migrated_database: MigratedDatabase,
) -> None:
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def blocked(request: httpx.Request) -> httpx.Response:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        raise AssertionError("unreachable")

    async with research_runtime(migrated_database.session_factory, background=False) as runtime:
        await runtime.client.aclose()
        runtime.client = httpx.AsyncClient(transport=httpx.MockTransport(blocked), trust_env=False)
        run = await runtime.runs.enqueue("BTCUSDT", request_id=uuid4(), now=datetime.now(UTC))
        task = asyncio.create_task(runtime.worker.run_once())
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
            assert cancelled.is_set()
            saved = await runtime.runs.get(run.id)
            assert saved and saved.status == "failed" and saved.error_code == "interrupted"
            assert await runtime.reports.get_by_analysis_id(run.analysis_id) is None
            no_calls = NeverExecute()
            restart = TechnicalResearchWorker(
                repository=SqlAlchemyTechnicalRunRepository(runtime.factory),
                executor=no_calls,
                clock=lambda: datetime.now(UTC),
            )
            assert not await restart.run_once()
            assert no_calls.calls == 0
            trace = await SqlAlchemyHarnessAuditRepository(runtime.factory).get_trace(
                run.analysis_id
            )
            assert trace and len(trace.events) == 4
            terminal = trace.events[-1]
            assert terminal.kind.value == "workflow_failed"
            # Harness 与 worker 关闭并发发生，保留先提交的不可变失败审计，不能覆写。
            assert (terminal.error_code, terminal.details.error_type) in {
                ("workflow_exception", "CancelledError"),
                ("interrupted", "InterruptedRun"),
            }
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_stale_owner_cannot_append_report_after_recovery(
    migrated_database: MigratedDatabase,
) -> None:
    now = datetime.now(UTC)
    async with research_runtime(migrated_database.session_factory, background=False) as runtime:
        # 先生成合法报告作为结构样本，再模拟另一项尚未提交任务的旧 worker 迟到写入。
        await runtime.runs.enqueue("BTCUSDT", request_id=uuid4(), now=now)
        assert await runtime.worker.run_once()
        template = (await runtime.reports.list(symbol="BTCUSDT", page=1, page_size=20)).items[0]
        stale = await runtime.runs.enqueue("BTCUSDT", request_id=uuid4(), now=now)
        owner = uuid4()
        assert await runtime.runs.claim(owner=owner, now=now)
        assert await runtime.runs.recover_expired(now=now + timedelta(seconds=31)) == 1
        candidate = template.model_copy(update={"id": uuid4(), "analysis_id": stale.analysis_id})
        with pytest.raises(ReportStorageUnavailableError):
            await runtime.reports.persist(candidate, {}, lease=TechnicalRunLease(stale.id, owner))
        assert await runtime.reports.get_by_analysis_id(stale.analysis_id) is None
        assert (await runtime.reports.list(symbol="BTCUSDT", page=1, page_size=20)).total == 1
