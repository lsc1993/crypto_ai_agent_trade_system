# 验证单次初始同步记录行情能力及安全失败。
# 记录仓储与采集替身保留结束状态，不使用真实公开源。
# 行情成功与 ETF 不支持分别表达，核心采集失败不能伪装为可研究状态。
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TypedDict, cast
from uuid import UUID, uuid4

import pytest

from app.market.capture import MarketCaptureService
from app.market.contracts import MarketDataUnavailableError
from app.symbols.contracts import SymbolError, SyncRun, SyncSource
from app.symbols.repository import SymbolRepository
from app.symbols.sync import ResearchSymbolSyncWorker

NOW = datetime(2030, 1, 1, tzinfo=UTC)


class FinishedRun(TypedDict):
    status: str
    sources: tuple[SyncSource, ...]
    snapshot_id: UUID | None
    error: str | None
    now: datetime


class RecordingRepository:
    def __init__(self, run: SyncRun | None) -> None:
        self.run = run
        self.finished: list[FinishedRun] = []
        self.renewed = asyncio.Event()
        self.renew_count = 0
        self.owns_lease = True
        self.renew_error = False

    async def claim(self, *, now: datetime) -> SyncRun | None:
        assert now == NOW
        return self.run

    # 仅模拟所有权反馈，用事件协调采集，不依赖实际十秒等待或数据库。
    async def renew(self, run: SyncRun, *, now: datetime) -> bool:
        self.renew_count += 1
        self.renewed.set()
        if self.renew_error:
            raise RuntimeError("upstream-private-error")
        return self.owns_lease

    async def finish(
        self,
        run: SyncRun,
        *,
        status: str,
        sources: tuple[SyncSource, ...],
        snapshot_id: UUID | None,
        error: str | None,
        now: datetime,
    ) -> bool:
        assert run == self.run
        self.finished.append(
            {
                "status": status,
                "sources": sources,
                "snapshot_id": snapshot_id,
                "error": error,
                "now": now,
            }
        )
        return True


class Capture:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    async def capture_symbol(self, symbol: str, *, captured_at: datetime) -> UUID:
        assert symbol == "SOLUSDT"
        assert captured_at == NOW
        if self.unavailable:
            raise MarketDataUnavailableError("market_data_unavailable", "safe")
        return uuid4()


def _run() -> SyncRun:
    return SyncRun(
        id=uuid4(),
        symbol="SOLUSDT",
        version=1,
        status="running",
        stage="capturing",
        created_at=NOW,
        started_at=NOW,
        lease_token=uuid4(),
        lease_until=NOW + timedelta(seconds=30),
    )


@pytest.mark.asyncio
async def test_sync_marks_market_inputs_ready_and_etf_unsupported() -> None:
    repository = RecordingRepository(_run())
    worker = ResearchSymbolSyncWorker(
        repository=repository,  # type: ignore[arg-type]
        capture=Capture(),  # type: ignore[arg-type]
        funding=None,
        clock=lambda: NOW,
    )

    assert await worker.run_once()
    finished = repository.finished[0]
    assert finished["status"] == "partial"
    sources = finished["sources"]
    assert isinstance(sources, tuple)
    assert {source.name for source in sources} == {
        "market",
        "candles",
        "derivatives",
        "funding",
        "news",
        "sentiment",
        "etf",
    }
    etf = next(source for source in sources if source.name == "etf")
    assert etf.status == "unsupported"
    assert etf.message == "当前数据源不支持"


@pytest.mark.asyncio
async def test_sync_records_safe_core_failure() -> None:
    repository = RecordingRepository(_run())
    worker = ResearchSymbolSyncWorker(
        repository=repository,  # type: ignore[arg-type]
        capture=Capture(unavailable=True),  # type: ignore[arg-type]
        funding=None,
        clock=lambda: NOW,
    )

    assert await worker.run_once()
    finished = repository.finished[0]
    assert finished["status"] == "failed"
    assert finished["error"] == "market_sync_failed"
    sources = finished["sources"]
    assert isinstance(sources, tuple)
    assert sources[0].status == "failed"
    assert sources[0].message == "公开行情同步失败，请稍后重试。"


# 慢采集等待 worker 续租事件；终态必须在至少一次续租后保存。
@pytest.mark.asyncio
async def test_sync_heartbeats_while_capture_is_running() -> None:
    repository = RecordingRepository(_run())

    class SlowCapture:
        async def capture_symbol(self, symbol: str, *, captured_at: datetime) -> UUID:
            await repository.renewed.wait()
            return uuid4()

    worker = ResearchSymbolSyncWorker(
        repository=cast(SymbolRepository, repository),
        capture=cast(MarketCaptureService, SlowCapture()),
        funding=None,
        clock=lambda: NOW,
        heartbeat_seconds=0.01,
        timeout_seconds=1,
    )
    assert await asyncio.wait_for(worker.run_once(), timeout=2)
    assert repository.renew_count >= 1
    assert repository.finished[0]["status"] == "partial"


class BlockingCapture:
    # finally 事件证明 worker 已等待采集取消完成，而非只发送 cancel 信号。
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = asyncio.Event()

    async def capture_symbol(self, symbol: str, *, captured_at: datetime) -> UUID:
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.closed.set()
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_sync_total_timeout_cancels_capture_and_records_safe_failure() -> None:
    repository = RecordingRepository(_run())
    capture = BlockingCapture()
    worker = ResearchSymbolSyncWorker(
        repository=cast(SymbolRepository, repository),
        capture=cast(MarketCaptureService, capture),
        funding=None,
        clock=lambda: NOW,
        heartbeat_seconds=0.01,
        timeout_seconds=0.05,
    )
    assert await asyncio.wait_for(worker.run_once(), timeout=2)
    assert capture.closed.is_set()
    assert repository.finished[0]["error"] == "sync_timeout"
    assert repository.finished[0]["snapshot_id"] is None


# 失去所有权和续租异常均停止采集，不试图用失败覆盖其他所有者/归档后的终态。
@pytest.mark.asyncio
@pytest.mark.parametrize("renew_error", [False, True])
async def test_sync_lease_loss_cancels_capture_without_finishing(renew_error: bool) -> None:
    repository = RecordingRepository(_run())
    repository.owns_lease = False
    repository.renew_error = renew_error
    capture = BlockingCapture()
    worker = ResearchSymbolSyncWorker(
        repository=cast(SymbolRepository, repository),
        capture=cast(MarketCaptureService, capture),
        funding=None,
        clock=lambda: NOW,
        heartbeat_seconds=0.01,
        timeout_seconds=1,
    )
    assert await asyncio.wait_for(worker.run_once(), timeout=2)
    assert capture.closed.is_set()
    assert repository.finished == []


# 停机取消必须传播给调用方，采集已回收，且不会在后台继续续租。
@pytest.mark.asyncio
async def test_sync_cancellation_marks_interrupted_and_reaps_children() -> None:
    repository = RecordingRepository(_run())
    capture = BlockingCapture()
    worker = ResearchSymbolSyncWorker(
        repository=cast(SymbolRepository, repository),
        capture=cast(MarketCaptureService, capture),
        funding=None,
        clock=lambda: NOW,
        heartbeat_seconds=0.01,
        timeout_seconds=1,
    )
    task = asyncio.create_task(worker.run_once())
    await asyncio.wait_for(capture.started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert capture.closed.is_set()
    assert repository.finished[0]["error"] == "sync_interrupted"
    count = repository.renew_count
    await asyncio.sleep(0.03)
    assert repository.renew_count == count


@pytest.mark.parametrize("timeout, heartbeat", [(0, 10), (120, 0), (120, 30), (10, -1)])
def test_sync_rejects_unsafe_timer_configuration(timeout: int, heartbeat: int) -> None:
    with pytest.raises(ValueError):
        ResearchSymbolSyncWorker(
            repository=cast(SymbolRepository, RecordingRepository(_run())),
            capture=cast(MarketCaptureService, Capture()),
            funding=None,
            clock=lambda: NOW,
            timeout_seconds=timeout,
            heartbeat_seconds=heartbeat,
        )


# 心跳还必须覆盖采集结束后的提交等待；续租异常不能被 finally 中 gather 静默吞掉。
@pytest.mark.asyncio
async def test_heartbeat_failure_cancels_pending_terminal_commit() -> None:
    commit_started = asyncio.Event()
    commit_cancelled = asyncio.Event()

    class SlowCommitRepository(RecordingRepository):
        async def finish(
            self,
            run: SyncRun,
            *,
            status: str,
            sources: tuple[SyncSource, ...],
            snapshot_id: UUID | None,
            error: str | None,
            now: datetime,
        ) -> bool:
            commit_started.set()
            self.renew_error = True
            try:
                # 等待心跳完成后模拟还未提交的事务；旧实现会等到一秒后超时才取消。
                await asyncio.Event().wait()
            finally:
                commit_cancelled.set()
            return True

    repository = SlowCommitRepository(_run())
    worker = ResearchSymbolSyncWorker(
        repository=cast(SymbolRepository, repository),
        capture=cast(MarketCaptureService, Capture()),
        funding=None,
        clock=lambda: NOW,
        heartbeat_seconds=0.01,
        timeout_seconds=1,
    )
    task = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(commit_started.wait(), timeout=1)
        assert await asyncio.wait_for(task, timeout=0.3)
        assert commit_cancelled.is_set()
        assert repository.finished == []
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# 临时仓储错误不能让 API lifespan 中的消费任务永久退出；下一次轮询仍有机会恢复。
@pytest.mark.asyncio
async def test_sync_loop_survives_temporary_queue_storage_failure() -> None:
    stop = asyncio.Event()

    class RecoveringRepository(RecordingRepository):
        calls = 0

        async def claim(self, *, now: datetime) -> SyncRun | None:
            self.calls += 1
            if self.calls == 1:
                raise SymbolError("research_symbol_storage_unavailable", "存储暂时不可用。", 503)
            stop.set()
            return None

    repository = RecoveringRepository(None)
    worker = ResearchSymbolSyncWorker(
        repository=cast(SymbolRepository, repository),
        capture=cast(MarketCaptureService, Capture()),
        funding=None,
        clock=lambda: NOW,
    )
    await asyncio.wait_for(worker.run_forever(stop), timeout=3)
    assert repository.calls == 2 and repository.finished == []
