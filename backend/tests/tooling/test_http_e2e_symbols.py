# 验证币种同步浏览器夹具确实使用生产 worker、快照仓储和 HTTP 重试路由。
# 事件门控制采集窗口而不依赖 sleep；合成故障不应泄漏原始异常或授予研究准入。
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.api.errors import install_exception_handlers
from app.infrastructure.persistence.models.market import MarketSnapshotRecord
from app.infrastructure.persistence.models.symbols import ResearchSymbolEventRecord
from scripts.http_e2e_symbols import symbol_sync_runtime
from tests.conftest import MigratedDatabase


@pytest.mark.asyncio
async def test_sync_fixture_retries_real_jobs_and_keeps_failed_history(
    migrated_database: MigratedDatabase,
) -> None:
    async with symbol_sync_runtime(migrated_database.session_factory, background=False) as runtime:
        app = FastAPI()
        install_exception_handlers(app)
        runtime.install(app, token="synthetic-run-token")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for symbol, terminal in (("SOLUSDT", "partial"), ("XRPUSDT", "failed")):
                original = await runtime.repository.get(symbol)
                assert original is not None and original.last_sync is not None
                assert original.last_sync.status == "failed" and not original.can_research
                path = f"/api/v1/research-symbols/{symbol}/sync/retry"
                request = {"runId": str(original.last_sync.id)}
                accepted = await client.post(path, json=request)
                assert accepted.status_code == 202
                run_id = UUID(accepted.json()["id"])
                assert run_id != original.last_sync.id
                work = asyncio.create_task(runtime.worker.run_once())
                try:
                    await asyncio.wait_for(runtime.market.started[symbol].wait(), timeout=3)
                    active = await runtime.repository.get(symbol)
                    assert active is not None and active.last_sync is not None
                    assert active.last_sync.id == run_id and active.last_sync.status == "running"
                    assert not active.can_research
                    replay = await client.post(path, json=request)
                    assert replay.status_code == 202 and replay.json()["id"] == str(run_id)
                    control = f"/__http_e2e__/symbol-sync/{symbol}/release"
                    assert (await client.post(control)).status_code == 403
                    assert not runtime.market.release[symbol].is_set()
                    assert (
                        await client.post(
                            control,
                            headers={
                                "x-http-e2e-token": "synthetic-run-token",
                            },
                        )
                    ).status_code == 204
                    assert await asyncio.wait_for(work, timeout=5)
                finally:
                    work.cancel()
                    await asyncio.gather(work, return_exceptions=True)

                saved = await runtime.repository.get(symbol)
                assert saved is not None and saved.last_sync is not None
                assert saved.last_sync.id == run_id and saved.last_sync.status == terminal
                assert saved.can_research == (terminal == "partial")
                assert "OFFLINE_PRIVATE" not in saved.model_dump_json()
                history = await runtime.repository.get_run(original.last_sync.id)
                assert history == original.last_sync
                conflict = await client.post(path, json=request)
                assert conflict.status_code == 409
                assert conflict.json()["code"] == "research_symbol_sync_retry_conflict"
                if terminal == "partial":
                    assert saved.last_sync.snapshot_id is not None
                    async with migrated_database.session_factory() as session:
                        snapshot = await session.get(
                            MarketSnapshotRecord, saved.last_sync.snapshot_id
                        )
                        assert snapshot is not None and snapshot.symbol == symbol
                    assert (
                        next(
                            source for source in saved.last_sync.sources if source.name == "funding"
                        ).status
                        == "missing"
                    )
                else:
                    assert saved.last_sync.snapshot_id is None
                    assert saved.last_sync.error == "market_sync_failed"
                async with migrated_database.session_factory() as session:
                    events = tuple(
                        (
                            await session.scalars(
                                select(ResearchSymbolEventRecord).where(
                                    ResearchSymbolEventRecord.run_id == run_id
                                )
                            )
                        ).all()
                    )
                assert {event.kind for event in events} >= {"queued", "claimed", terminal}


@pytest.mark.asyncio
async def test_sync_runtime_cancels_waiting_capture_before_closing(
    migrated_database: MigratedDatabase,
) -> None:
    async with symbol_sync_runtime(migrated_database.session_factory) as runtime:
        original = await runtime.repository.get("SOLUSDT")
        assert original is not None and original.last_sync is not None
        await runtime.repository.retry("SOLUSDT", original.last_sync.id, now=datetime.now(UTC))
        await asyncio.wait_for(runtime.market.started["SOLUSDT"].wait(), timeout=3)
        await runtime.close()
        assert runtime.task is not None and runtime.task.done()
        saved = await runtime.repository.get("SOLUSDT")
        assert saved is not None and saved.last_sync is not None
        assert saved.last_sync.status == "failed" and saved.last_sync.error == "sync_interrupted"
        await runtime.close()
