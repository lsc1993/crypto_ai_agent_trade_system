# 使用真实目录仓储及生产路由验证同步重试的 HTTP 契约；不装配公网客户端或后台采集。
# 失败任务来自测试 schema；无数据库模式必须明确拒绝，不能伪造排队成功。
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api.errors import install_exception_handlers
from app.api.routes.research_symbols import router
from app.infrastructure.persistence.symbol_repository import SqlAlchemySymbolRepository
from app.symbols.memory import StaticSymbolRepository
from tests.conftest import MigratedDatabase


@pytest.mark.asyncio
async def test_retry_route_queues_failed_sync_and_preserves_history(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemySymbolRepository(migrated_database.session_factory)
    now = datetime.now(UTC)
    original = await repository.claim(now=now)
    assert original is not None
    await repository.finish(
        original,
        status="failed",
        sources=(),
        snapshot_id=None,
        error="market_sync_failed",
        now=now,
    )
    app = FastAPI()
    app.state.symbol_repository = repository
    install_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    path = f"/api/v1/research-symbols/{original.symbol}/sync/retry"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(path, json={"runId": str(original.id)})
        assert response.status_code == 202
        queued = response.json()
        assert queued["status"] == "queued" and queued["id"] != str(original.id)
        assert queued["symbol"] == original.symbol
        assert (await client.post(path, json={"runId": str(original.id)})).json()["id"] == queued[
            "id"
        ]
        assert (await client.post(path, json={"runId": "not-uuid"})).status_code == 422
        assert (await client.post(path, json={})).status_code == 422
        missing = await client.post(path, json={"runId": str(uuid4())})
        assert missing.status_code == 404
        assert missing.json()["code"] == "research_symbol_sync_not_found"
    saved = await repository.get_run(original.id)
    assert saved is not None and saved.error == "market_sync_failed"


@pytest.mark.asyncio
async def test_retry_without_database_returns_safe_unavailable() -> None:
    app = FastAPI()
    app.state.symbol_repository = StaticSymbolRepository()
    install_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/research-symbols/BTCUSDT/sync/retry",
            json={"runId": str(uuid4())},
        )
    assert response.status_code == 503
    assert response.json()["code"] == "research_symbol_storage_unavailable"
