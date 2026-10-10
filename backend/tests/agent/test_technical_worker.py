import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.agent.technical.worker import TechnicalResearchWorker
from app.infrastructure.persistence.technical_run_repository import SqlAlchemyTechnicalRunRepository
from app.reports.technical_plan import TechnicalPlanReport
from tests.conftest import MigratedDatabase


class ExplodingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, *args: Any, **kwargs: Any) -> TechnicalPlanReport:
        self.calls += 1
        raise RuntimeError("private-error")


@pytest.mark.asyncio
async def test_worker_failure_is_safe_and_not_replayed(migrated_database: MigratedDatabase) -> None:
    repo = SqlAlchemyTechnicalRunRepository(migrated_database.session_factory)
    run = await repo.enqueue("BTCUSDT", request_id=uuid4(), now=datetime.now(UTC))
    executor = ExplodingExecutor()
    worker = TechnicalResearchWorker(
        repository=repo, executor=executor, clock=lambda: datetime.now(UTC)
    )
    assert await worker.run_once()
    saved = await repo.get(run.id)
    assert saved and saved.status == "failed" and saved.error_code == "research_failed"
    assert "private-error" not in saved.model_dump_json()
    assert not await worker.run_once()
    assert executor.calls == 1


@pytest.mark.asyncio
async def test_stopped_worker_does_not_claim(migrated_database: MigratedDatabase) -> None:
    repo = SqlAlchemyTechnicalRunRepository(migrated_database.session_factory)
    executor = ExplodingExecutor()
    worker = TechnicalResearchWorker(
        repository=repo, executor=executor, clock=lambda: datetime.now(UTC)
    )
    stop = asyncio.Event()
    stop.set()
    await worker.run_forever(stop)
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_cancel_stops_model_before_blocked_failure_write(
    migrated_database: MigratedDatabase,
) -> None:
    started, cancelled, writing = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class BlockedRepository(SqlAlchemyTechnicalRunRepository):
        async def finish(self, *args: Any, **kwargs: Any) -> bool:
            writing.set()
            await asyncio.Event().wait()
            return False

    class SlowExecutor:
        async def generate(self, *args: Any, **kwargs: Any) -> TechnicalPlanReport:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            raise AssertionError("unreachable")

    repo = BlockedRepository(migrated_database.session_factory)
    await repo.enqueue("BTCUSDT", request_id=uuid4(), now=datetime.now(UTC))
    worker = TechnicalResearchWorker(
        repository=repo, executor=SlowExecutor(), clock=lambda: datetime.now(UTC)
    )
    task = asyncio.create_task(worker.run_once())
    try:
        await started.wait()
        task.cancel()
        await writing.wait()
        await asyncio.wait_for(cancelled.wait(), timeout=0.2)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
