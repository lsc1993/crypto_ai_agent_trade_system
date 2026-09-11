# ruff: noqa: E501

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol

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
        symbol="SOLUSDT", supported=True,
        checks=(Capability(name="market", status="supported", message="ok"),),
        metadata=MarketMetadata(
            symbol="SOLUSDT", base_asset="SOL", quote_asset="USDT", margin_asset="USDT",
            contract_type="PERPETUAL", status="TRADING",
        ),
    )


async def _prepare(database: MigratedDatabase) -> SqlAlchemySymbolRepository:
    repository = _repository(database)
    await repository.archive("BTCUSDT", now=NOW)
    await repository.archive("ETHUSDT", now=NOW)
    return repository


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


@pytest.mark.asyncio
async def test_expired_lease_fails_and_cannot_finish_replacement(migrated_database: MigratedDatabase):
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
        claimed, status="ready", sources=(), snapshot_id=None, error=None,
        now=NOW + timedelta(seconds=32),
    )
    entry = await repository.get("SOLUSDT")
    assert entry is not None and not entry.can_research


@pytest.mark.asyncio
async def test_archive_cancels_claim_and_reactivation_requires_new_sync(migrated_database: MigratedDatabase):
    repository = await _prepare(migrated_database)
    entry = await repository.add(_check(), keywords=(), now=NOW)
    claimed = await repository.claim(now=NOW)
    assert claimed is not None
    archived = await repository.archive("SOLUSDT", now=NOW)
    assert not archived.enabled and archived.version == entry.version + 1
    cancelled = await repository.get_run(claimed.id)
    assert cancelled is not None and cancelled.status == "cancelled"
    assert not await repository.renew(claimed, now=NOW)
    assert not await repository.finish(claimed, status="ready", sources=(), snapshot_id=None, error=None, now=NOW)
    revived = await repository.add(_check(), keywords=("Solana",), now=NOW)
    assert revived.enabled and not revived.can_research
    assert revived.version > archived.version
    assert revived.last_sync is not None
    assert revived.last_sync.id != claimed.id


@pytest.mark.asyncio
async def test_completed_sync_is_immutable_and_refresh_failure_preserves_admission(migrated_database: MigratedDatabase):
    repository = await _prepare(migrated_database)
    await repository.add(_check(), keywords=(), now=NOW)
    claimed = await repository.claim(now=NOW)
    assert claimed is not None
    assert await repository.renew(claimed, now=NOW + timedelta(seconds=10))
    assert await repository.finish(claimed, status="partial", sources=(), snapshot_id=None, error=None, now=NOW + timedelta(seconds=35))
    admitted = await repository.get("SOLUSDT")
    assert admitted is not None and admitted.can_research
    assert not await repository.finish(claimed, status="failed", sources=(), snapshot_id=None, error="late", now=NOW + timedelta(seconds=36))
    await repository.enqueue("SOLUSDT", now=NOW + timedelta(seconds=36))
    refresh = await repository.claim(now=NOW + timedelta(seconds=36))
    assert refresh is not None
    assert await repository.finish(refresh, status="failed", sources=(), snapshot_id=None, error="core_failed", now=NOW + timedelta(seconds=37))
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
