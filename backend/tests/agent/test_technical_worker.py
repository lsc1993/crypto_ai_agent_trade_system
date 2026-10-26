# 验证技术 worker 的失败、停止及取消生命周期。
# 抛错与阻塞替身复现执行失败和写入挂起，检查失败安全且不自动重放。
# 取消时先结束模型任务，停止后的 worker 不再领取队列工作。
import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.agent.technical.worker import TechnicalResearchWorker
from app.infrastructure.persistence.technical_run_repository import SqlAlchemyTechnicalRunRepository
from app.reports.technical_plan import TechnicalPlanReport
from tests.conftest import MigratedDatabase


# 每次执行都抛敏感异常并计数，验证 worker 保存安全终态且不重放失败任务。
class ExplodingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, *args: Any, **kwargs: Any) -> TechnicalPlanReport:
        self.calls += 1
        raise RuntimeError("private-error")


# 第一次消费保存失败，第二次队列应为空；错误正文不会进入持久化运行状态。
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


# 提前置位停止事件，持续循环不应领取或执行任何任务。
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


# 用阻塞失败写入复现关闭竞争，确保模型先取消而不是继续运行等待仓储。
# 三组事件分别观察模型开始、模型取消与失败写入开始，隔离关闭过程的先后竞争。
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
            # 无论断言结果如何都取消并回收任务，避免阻塞替身泄留后台协程。
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
        # 确认失败写入已经挂起后观察模型取消，排除只是任务尚未运行的假阳性。
        await writing.wait()
        await asyncio.wait_for(cancelled.wait(), timeout=0.2)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
