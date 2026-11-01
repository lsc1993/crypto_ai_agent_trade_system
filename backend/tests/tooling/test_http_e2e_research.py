# 用真实数据库与 HTTP 路由验证验收装配，不以预制报告替代生产研究服务。
# 固定模型传输无外网；入队先返回 queued，worker 执行后才存在可重读的报告。
from uuid import uuid4

import httpx
import pytest

from scripts.http_e2e_research import research_runtime
from tests.conftest import MigratedDatabase


@pytest.mark.asyncio
async def test_research_http_uses_queue_worker_and_saved_reports(
    migrated_database: MigratedDatabase,
) -> None:
    async with research_runtime(migrated_database.session_factory, background=False) as runtime:
        # 本测试只需生产研究路由；不装配或访问交易日志测试 schema 管理端点。
        from fastapi import FastAPI

        app = FastAPI()
        runtime.install(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for symbol, status in (("BTCUSDT", "completed"), ("ETHUSDT", "degraded")):
                request = {"symbol": symbol, "requestId": str(uuid4())}
                response = await client.post("/api/v1/technical-reports/runs", json=request)
                assert response.status_code == 202
                run = response.json()
                assert run["status"] == "queued"
                replay = await client.post("/api/v1/technical-reports/runs", json=request)
                assert replay.json()["id"] == run["id"]
                assert await runtime.worker.run_once()
                finished = (await client.get(f"/api/v1/technical-reports/runs/{run['id']}")).json()
                assert finished["status"] == status
                report_id = finished["reportId"]
                report = (await client.get(f"/api/v1/technical-reports/{report_id}")).json()
                assert report["status"] == status
                assert report["version"] == "technical-v2"
                assert report["symbol"] == symbol
                assert report["generation"]["quality"] == (
                    "complete" if status == "completed" else "analysis_unavailable"
                )
                assert not await runtime.worker.run_once()
                assert "OFFLINE_PRIVATE" not in str(report)
        assert runtime.calls == [("BTCUSDT", "analysis"), ("BTCUSDT", "composition")]
