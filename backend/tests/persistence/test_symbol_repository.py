# 验证目录登记、任务租约、归档与重新准入的事务行为。
# 并发调用检查同币种活动任务唯一与任务只能被领取一次。
# 过期所有者不能完成替代任务，终态不可变；刷新失败不抹除已有准入事实。
# ruff: noqa: E501

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.symbols import (
    ResearchSymbolEventRecord,
    ResearchSymbolSyncRunRecord,
)
from app.infrastructure.persistence.symbol_repository import SqlAlchemySymbolRepository
from app.symbols.contracts import Capability, CheckResult, MarketMetadata, SymbolError

NOW = datetime(2030, 1, 1, tzinfo=UTC)


class MigratedDatabase(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


def _repository(database: MigratedDatabase) -> SqlAlchemySymbolRepository:
    return SqlAlchemySymbolRepository(database.session_factory)


def _check() -> CheckResult:
    return CheckResult(
        symbol="SOLUSDT",
        supported=True,
        checks=(Capability(name="market", status="supported", message="ok"),),
        metadata=MarketMetadata(
            symbol="SOLUSDT",
            base_asset="SOL",
            quote_asset="USDT",
            margin_asset="USDT",
            contract_type="PERPETUAL",
            status="TRADING",
        ),
    )


async def _prepare(database: MigratedDatabase) -> SqlAlchemySymbolRepository:
    repository = _repository(database)
    await repository.archive("BTCUSDT", now=NOW)
    await repository.archive("ETHUSDT", now=NOW)
    return repository


# 同币种并发登记与重复入队应收敛到一个任务，同时保留操作审计。
@pytest.mark.asyncio
async def test_directory_add_is_atomic_idempotent_and_audited(migrated_database: MigratedDatabase):
    repository = await _prepare(migrated_database)
    await repository.record_check(_check(), now=NOW)
    first, second = await asyncio.gather(
        repository.add(_check(), keywords=("Solana",), now=NOW),
        repository.add(_check(), keywords=("Solana",), now=NOW),
    )
    assert first.last_sync is not None and second.last_sync is not None
    assert first.symbol == second.symbol == "SOLUSDT"
    assert first.last_sync.id == second.last_sync.id
    assert first.last_sync.status == "queued"
    assert not first.can_research
    assert first.keywords == ("Solana",)
    runs = await asyncio.gather(*(repository.enqueue("SOLUSDT", now=NOW) for _ in range(4)))
    assert {run.id for run in runs} == {first.last_sync.id}
    async with migrated_database.session_factory() as session:
        events = tuple((await session.scalars(select(ResearchSymbolEventRecord))).all())
    assert {event.kind for event in events} >= {"checked", "added", "queued"}


# 固定时钟推进到租约之后，旧领取记录不再拥有完成或续租权限。
@pytest.mark.asyncio
async def test_expired_lease_fails_and_cannot_finish_replacement(
    migrated_database: MigratedDatabase,
):
    repository = await _prepare(migrated_database)
    await repository.add(_check(), keywords=(), now=NOW)
    claimed = await repository.claim(now=NOW)
    assert claimed is not None and claimed.status == "running"
    assert claimed.lease_until == NOW + timedelta(seconds=30)
    assert await repository.claim(now=NOW) is None
    assert await repository.renew(claimed, now=NOW + timedelta(seconds=31)) is False
    assert await repository.claim(now=NOW + timedelta(seconds=31)) is None
    expired = await repository.get_run(claimed.id)
    assert expired is not None
    assert expired.status == "failed" and expired.error == "sync_lease_expired"
    replacement = await repository.enqueue("SOLUSDT", now=NOW + timedelta(seconds=32))
    assert replacement.id != claimed.id
    assert not await repository.finish(
        claimed,
        status="ready",
        sources=(),
        snapshot_id=None,
        error=None,
        now=NOW + timedelta(seconds=32),
    )
    entry = await repository.get("SOLUSDT")
    assert entry is not None and not entry.can_research


@pytest.mark.asyncio
async def test_archive_cancels_claim_and_reactivation_requires_new_sync(
    migrated_database: MigratedDatabase,
):
    repository = await _prepare(migrated_database)
    entry = await repository.add(_check(), keywords=(), now=NOW)
    claimed = await repository.claim(now=NOW)
    assert claimed is not None
    archived = await repository.archive("SOLUSDT", now=NOW)
    assert not archived.enabled and archived.version == entry.version + 1
    cancelled = await repository.get_run(claimed.id)
    assert cancelled is not None and cancelled.status == "cancelled"
    assert not await repository.renew(claimed, now=NOW)
    assert not await repository.finish(
        claimed, status="ready", sources=(), snapshot_id=None, error=None, now=NOW
    )
    revived = await repository.add(_check(), keywords=("Solana",), now=NOW)
    assert revived.enabled and not revived.can_research
    assert revived.version > archived.version
    assert revived.last_sync is not None
    assert revived.last_sync.id != claimed.id


@pytest.mark.asyncio
async def test_completed_sync_is_immutable_and_refresh_failure_preserves_admission(
    migrated_database: MigratedDatabase,
):
    repository = await _prepare(migrated_database)
    await repository.add(_check(), keywords=(), now=NOW)
    claimed = await repository.claim(now=NOW)
    assert claimed is not None
    assert await repository.renew(claimed, now=NOW + timedelta(seconds=10))
    assert await repository.finish(
        claimed,
        status="partial",
        sources=(),
        snapshot_id=None,
        error=None,
        now=NOW + timedelta(seconds=35),
    )
    admitted = await repository.get("SOLUSDT")
    assert admitted is not None and admitted.can_research
    assert not await repository.finish(
        claimed,
        status="failed",
        sources=(),
        snapshot_id=None,
        error="late",
        now=NOW + timedelta(seconds=36),
    )
    await repository.enqueue("SOLUSDT", now=NOW + timedelta(seconds=36))
    refresh = await repository.claim(now=NOW + timedelta(seconds=36))
    assert refresh is not None
    assert await repository.finish(
        refresh,
        status="failed",
        sources=(),
        snapshot_id=None,
        error="core_failed",
        now=NOW + timedelta(seconds=37),
    )
    preserved = await repository.get("SOLUSDT")
    assert preserved is not None and preserved.can_research
    async with migrated_database.session_factory() as session:
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(
                update(ResearchSymbolSyncRunRecord)
                .where(ResearchSymbolSyncRunRecord.id == claimed.id)
                .values(error="overwrite")
            )
            await session.commit()


# 并发领取而非顺序调用，以覆盖锁竞争下的重复领取风险。
@pytest.mark.asyncio
async def test_two_workers_cannot_claim_one_job(migrated_database: MigratedDatabase):
    repository = await _prepare(migrated_database)
    await repository.add(_check(), keywords=(), now=NOW)
    runs = await asyncio.gather(repository.claim(now=NOW), repository.claim(now=NOW))
    assert sum(run is not None for run in runs) == 1


@pytest.mark.asyncio
async def test_unknown_and_archived_symbols_have_safe_errors(migrated_database: MigratedDatabase):
    repository = await _prepare(migrated_database)
    with pytest.raises(SymbolError) as missing:
        await repository.enqueue("SOLUSDT", now=NOW)
    assert missing.value.code == "research_symbol_not_found"
    with pytest.raises(SymbolError) as archived:
        await repository.enqueue("BTCUSDT", now=NOW)
    assert archived.value.code == "research_symbol_archived"


# 不调用旧 worker 的 renew/finish，模拟进程退出后由新消费者主动回收过期任务。
@pytest.mark.asyncio
async def test_claim_recovers_crashed_sync_without_replaying(migrated_database: MigratedDatabase):
    repository = await _prepare(migrated_database)
    await repository.add(_check(), keywords=(), now=NOW)
    claimed = await repository.claim(now=NOW)
    assert claimed is not None
    restarted = _repository(migrated_database)
    assert await restarted.claim(now=NOW + timedelta(seconds=30)) is None
    expired = await restarted.get_run(claimed.id)
    assert expired is not None and expired.status == "failed"
    assert expired.error == "sync_lease_expired"
    assert not await repository.finish(
        claimed,
        status="ready",
        sources=(),
        snapshot_id=None,
        error=None,
        now=NOW + timedelta(seconds=30),
    )
    async with migrated_database.session_factory() as session:
        events = tuple((await session.scalars(select(ResearchSymbolEventRecord))).all())
    assert (
        sum(event.kind == "lease_expired" and event.run_id == claimed.id for event in events) == 1
    )


# 截止时刻不能被旧所有者续租或改写，避免与新消费者的过期回收边界不一致。
@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["renew", "finish"])
async def test_sync_lease_deadline_is_exclusive(
    migrated_database: MigratedDatabase,
    operation: str,
):
    repository = await _prepare(migrated_database)
    await repository.add(_check(), keywords=(), now=NOW)
    run = await repository.claim(now=NOW)
    assert run is not None
    deadline = NOW + timedelta(seconds=30)
    if operation == "renew":
        assert not await repository.renew(run, now=deadline)
    else:
        assert not await repository.finish(
            run,
            status="ready",
            sources=(),
            snapshot_id=None,
            error=None,
            now=deadline,
        )
    expired = await repository.get_run(run.id)
    assert expired is not None and expired.error == "sync_lease_expired"


# 显式失败 ID 绑定重试；并发请求合并，重试完成后迟到请求不得再排一轮。
@pytest.mark.asyncio
async def test_failed_sync_retry_is_concurrent_safe_and_rejects_late_requests(
    migrated_database: MigratedDatabase,
):
    repository = await _prepare(migrated_database)
    await repository.add(_check(), keywords=(), now=NOW)
    original = await repository.claim(now=NOW)
    assert original is not None
    assert await repository.finish(
        original,
        status="failed",
        sources=(),
        snapshot_id=None,
        error="market_sync_failed",
        now=NOW,
    )
    retries = await asyncio.gather(
        *(
            repository.retry("SOLUSDT", original.id, now=NOW + timedelta(seconds=1))
            for _ in range(4)
        )
    )
    assert len({run.id for run in retries}) == 1
    assert retries[0].id != original.id and retries[0].status == "queued"
    replacement = await repository.claim(now=NOW + timedelta(seconds=2))
    assert replacement is not None and replacement.id == retries[0].id
    assert await repository.finish(
        replacement,
        status="partial",
        sources=(),
        snapshot_id=None,
        error=None,
        now=NOW + timedelta(seconds=3),
    )
    with pytest.raises(SymbolError) as late:
        await repository.retry("SOLUSDT", original.id, now=NOW + timedelta(seconds=4))
    assert late.value.code == "research_symbol_sync_retry_conflict"
    old = await repository.get_run(original.id)
    assert old is not None and old.error == "market_sync_failed"
    assert await repository.claim(now=NOW + timedelta(seconds=4)) is None
    async with migrated_database.session_factory() as session:
        events = tuple((await session.scalars(select(ResearchSymbolEventRecord))).all())
    assert sum(event.kind == "retry_requested" for event in events) == 1


# 错标的、未知任务、非失败状态及归档不能借重试接口绕过目录约束。
@pytest.mark.asyncio
async def test_retry_validates_symbol_run_state_and_archive(migrated_database: MigratedDatabase):
    repository = await _prepare(migrated_database)
    entry = await repository.add(_check(), keywords=(), now=NOW)
    assert entry.last_sync is not None
    for symbol, run_id, code in (
        ("SOLUSDT", uuid4(), "research_symbol_sync_not_found"),
        ("XRPUSDT", entry.last_sync.id, "research_symbol_not_found"),
        ("BTCUSDT", entry.last_sync.id, "research_symbol_archived"),
        ("SOLUSDT", entry.last_sync.id, "research_symbol_sync_retry_conflict"),
    ):
        with pytest.raises(SymbolError) as error:
            await repository.retry(symbol, run_id, now=NOW)
        assert error.value.code == code
    failed = await repository.claim(now=NOW)
    assert failed is not None
    await repository.finish(
        failed,
        status="failed",
        sources=(),
        snapshot_id=None,
        error="market_sync_failed",
        now=NOW,
    )
    await repository.archive("SOLUSDT", now=NOW)
    await repository.add(_check(), keywords=(), now=NOW)
    with pytest.raises(SymbolError) as outdated:
        await repository.retry("SOLUSDT", failed.id, now=NOW)
    assert outdated.value.code == "research_symbol_sync_retry_conflict"
