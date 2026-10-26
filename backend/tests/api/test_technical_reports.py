# 验证独立技术报告创建、分页、详情及手动队列接口。
# 生成器和分页仓储替身观察调用，入队返回后不应立即调用模型。
# 请求只能使用准入币种与固定方法，不能接受任意技能文件路径。
from uuid import uuid4

import httpx
import pytest

from app.agent.technical.service import TechnicalResearchService
from app.infrastructure.persistence.technical_run_repository import SqlAlchemyTechnicalRunRepository
from app.main import create_app
from app.reports.technical import TechnicalReport
from app.reports.technical_repository import TechnicalReportPage
from tests.agent.test_technical_service import Market, Model, Repository, technical_clock
from tests.conftest import MigratedDatabase


class Generator:
    def __init__(self, repository: Repository) -> None:
        self.service = TechnicalResearchService(
            market=Market(), repository=repository, model=Model(), clock=technical_clock
        )

    async def generate(self, symbol: str) -> TechnicalReport:
        return await self.service.generate(symbol, analysis_id=uuid4())


class PagedRepository(Repository):
    async def list(self, *, symbol: str | None, page: int, page_size: int) -> TechnicalReportPage:
        reports = tuple(
            report for report, _ in self.records if symbol is None or report.symbol == symbol
        )
        return TechnicalReportPage(
            items=reports[(page - 1) * page_size : page * page_size],
            page=page,
            page_size=page_size,
            total=len(reports),
        )


@pytest.mark.asyncio
async def test_enqueue_returns_202_without_model_call(migrated_database: MigratedDatabase) -> None:
    runs = SqlAlchemyTechnicalRunRepository(migrated_database.session_factory)
    repository = PagedRepository()
    app = create_app(
        market_gateway=Market(),
        technical_report_repository=repository,
        technical_research_service=Generator(repository),
        technical_run_repository=runs,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/technical-reports/runs", json={"symbol": "BTCUSDT", "requestId": str(uuid4())}
        )
        assert response.status_code == 202
        assert response.json()["status"] == "queued"
        assert not repository.records
        assert (
            await client.get(f"/api/v1/technical-reports/runs/{response.json()['id']}")
        ).json() == response.json()


@pytest.mark.asyncio
async def test_create_list_and_get_technical_report_use_separate_contract() -> None:
    repository = PagedRepository()
    app = create_app(
        market_gateway=Market(),
        technical_report_repository=repository,
        technical_research_service=Generator(repository),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/technical-reports", json={"symbol": "BTCUSDT"})
        assert response.status_code == 201
        body = response.json()
        assert body["analysis"]["facts"]["volumeRatio"] == "2"
        assert "market" not in body
        detail = await client.get(f"/api/v1/technical-reports/{body['id']}")
        assert detail.json() == body
        page = await client.get("/api/v1/technical-reports?symbol=BTCUSDT&pageSize=1")
        assert page.json()["total"] == 1
        assert page.json()["pageSize"] == 1
        assert (await client.get(f"/api/v1/technical-reports/{uuid4()}")).status_code == 404


@pytest.mark.asyncio
async def test_technical_request_rejects_unregistered_symbol_and_arbitrary_skill_path() -> None:
    repository = PagedRepository()
    app = create_app(
        market_gateway=Market(),
        technical_report_repository=repository,
        technical_research_service=Generator(repository),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post(
                "/api/v1/technical-reports", json={"symbol": "BTCUSDT", "skillPath": "/tmp/x"}
            )
        ).status_code == 422
        assert (
            await client.post("/api/v1/technical-reports", json={"symbol": "SOLUSDT"})
        ).status_code == 404
        assert repository.records == []
