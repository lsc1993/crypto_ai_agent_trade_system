# 真实 SQL 租约与 worker 联验：用事件推进 UTC 时钟，不等待三十秒或访问公网。
# 成功路径使用生产采集/行情仓储与固定合成市场；取消、超时和归档不能授予研究资格。
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.infrastructure.persistence.models.market import MarketSnapshotRecord
from app.infrastructure.persistence.models.symbols import ResearchSymbolEventRecord
from app.infrastructure.persistence.repository import SqlAlchemyMarketRepository
from app.infrastructure.persistence.symbol_repository import SqlAlchemySymbolRepository
from app.market.capture import MarketCaptureService
from app.market.funding_history import FundingHistory
from app.market.symbols import ResearchSymbol
from app.symbols.contracts import SyncRun
from app.symbols.sync import ResearchSymbolSyncWorker
from scripts.http_e2e_research import SyntheticMarket
from scripts.research_flow_fixtures import NOW
from tests.conftest import MigratedDatabase


class BlockingCapture(MarketCaptureService):
    # 只阻塞真实采集入口；释放后仍经生产快照持久化，不构造无外键关联的假快照。
    def __init__(self, database: MigratedDatabase) -> None:
        super().__init__(SyntheticMarket(), SqlAlchemyMarketRepository(database.session_factory))
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = asyncio.Event()

    async def capture_symbol(
        self,
        symbol: ResearchSymbol,
        *,
        captured_at: datetime,
    ) -> UUID:
        self.started.set()
        try:
            await self.release.wait()
            return await super().capture_symbol(symbol, captured_at=captured_at)
        finally:
            self.closed.set()


@pytest.mark.asyncio
async def test_worker_heartbeat_extends_real_lease_and_saves_snapshot(
    migrated_database: MigratedDatabase,
) -> None:
    renewed = asyncio.Event()

    class ObservedRepository(SqlAlchemySymbolRepository):
        async def renew(self, run: SyncRun, *, now: datetime) -> bool:
            accepted = await super().renew(run, now=now)
            if accepted:
                renewed.set()
            return accepted

    repository = ObservedRepository(migrated_database.session_factory)
    await repository.archive("ETHUSDT", now=NOW)
    capture = BlockingCapture(migrated_database)
    clock = NOW
    worker = ResearchSymbolSyncWorker(
        repository=repository,
        capture=capture,
        funding=None,
        clock=lambda: clock,
        heartbeat_seconds=0.01,
    )
    task = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(capture.started.wait(), timeout=2)
        clock = NOW + timedelta(seconds=10)
        await asyncio.wait_for(renewed.wait(), timeout=2)
        # 超过原三十秒租约，但在续租后的四十秒截止内，必须能成功关联真实快照。
        clock = NOW + timedelta(seconds=35)
        capture.release.set()
        assert await asyncio.wait_for(task, timeout=3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    saved = await repository.get("BTCUSDT")
    assert saved is not None and saved.can_research and saved.last_sync is not None
    assert saved.last_sync.status == "partial" and saved.last_sync.snapshot_id is not None
    async with migrated_database.session_factory() as session:
        events = tuple((await session.scalars(select(ResearchSymbolEventRecord))).all())
    assert any(event.kind == "lease_renewed" for event in events)


# 归档取消数据库租约，后台心跳看到 False 后停止采集，不把取消改写成失败或成功。
@pytest.mark.asyncio
async def test_archiving_symbol_stops_worker_and_preserves_cancelled_run(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemySymbolRepository(migrated_database.session_factory)
    await repository.archive("ETHUSDT", now=NOW)
    capture = BlockingCapture(migrated_database)
    worker = ResearchSymbolSyncWorker(
        repository=repository,
        capture=capture,
        funding=None,
        clock=lambda: NOW,
        heartbeat_seconds=0.01,
    )
    task = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(capture.started.wait(), timeout=2)
        archived = await repository.archive("BTCUSDT", now=NOW)
        assert archived.last_sync is not None and archived.last_sync.status == "cancelled"
        assert await asyncio.wait_for(task, timeout=3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert capture.closed.is_set()
    saved = await repository.get("BTCUSDT")
    assert saved is not None and not saved.can_research and saved.last_sync is not None
    assert saved.last_sync.status == "cancelled" and saved.last_sync.snapshot_id is None


# 两种退出均经真实 finish，确认安全失败可重读且旧 run 不会被自动重放。
@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_sync_timeout_and_cancel_are_durable_and_manually_retryable(
    migrated_database: MigratedDatabase,
    cancel: bool,
) -> None:
    repository = SqlAlchemySymbolRepository(migrated_database.session_factory)
    await repository.archive("ETHUSDT", now=NOW)
    capture = BlockingCapture(migrated_database)
    worker = ResearchSymbolSyncWorker(
        repository=repository,
        capture=capture,
        funding=None,
        clock=lambda: NOW,
        heartbeat_seconds=0.01,
        timeout_seconds=0.1 if not cancel else 120,
    )
    task = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(capture.started.wait(), timeout=2)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await asyncio.wait_for(task, timeout=3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert capture.closed.is_set()
    saved = await repository.get("BTCUSDT")
    assert saved is not None and not saved.can_research and saved.last_sync is not None
    assert saved.last_sync.status == "failed"
    assert saved.last_sync.error == ("sync_interrupted" if cancel else "sync_timeout")
    restarted = SqlAlchemySymbolRepository(migrated_database.session_factory)
    assert await restarted.claim(now=NOW + timedelta(seconds=31)) is None
    retry = await restarted.retry("BTCUSDT", saved.last_sync.id, now=NOW + timedelta(seconds=32))
    assert retry.id != saved.last_sync.id and retry.status == "queued"


# 快照独立提交后资金费率仍可阻塞；取消只终结同步任务，不伪称撤销不可变行情事务。
@pytest.mark.asyncio
async def test_cancel_after_snapshot_commit_keeps_data_without_admitting_symbol(
    migrated_database: MigratedDatabase,
) -> None:
    funding_started = asyncio.Event()
    funding_closed = asyncio.Event()

    class BlockedFunding:
        async def get_funding_history(
            self,
            symbol: ResearchSymbol,
            *,
            since: datetime,
            until: datetime,
        ) -> FundingHistory:
            funding_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                funding_closed.set()
            raise AssertionError("unreachable")

    repository = SqlAlchemySymbolRepository(migrated_database.session_factory)
    await repository.archive("ETHUSDT", now=NOW)
    capture = MarketCaptureService(
        SyntheticMarket(),
        SqlAlchemyMarketRepository(migrated_database.session_factory),
    )
    worker = ResearchSymbolSyncWorker(
        repository=repository,
        capture=capture,
        funding=BlockedFunding(),
        clock=lambda: NOW,
    )
    task = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(funding_started.wait(), timeout=3)
        async with migrated_database.session_factory() as session:
            snapshots = tuple((await session.scalars(select(MarketSnapshotRecord))).all())
        assert len(snapshots) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert funding_closed.is_set()
    saved = await repository.get("BTCUSDT")
    assert saved is not None and not saved.can_research and saved.last_sync is not None
    assert saved.last_sync.status == "failed" and saved.last_sync.error == "sync_interrupted"
    assert saved.last_sync.snapshot_id is None
    async with migrated_database.session_factory() as session:
        after = tuple((await session.scalars(select(MarketSnapshotRecord))).all())
    assert [snapshot.id for snapshot in after] == [snapshots[0].id]
