# 为隔离 HTTP 验收装配真实技术研究队列、worker、Harness 和 SQL 仓储。
# 仅行情与模型传输使用版本化合成数据；无公网请求、环境密钥或业务 lifespan。
# BTC 固定合法响应，ETH 固定缺配置降级；该分支只存在于开发验收装配中。
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.technical.plan_service import TechnicalPlanResearchService
from app.agent.technical.worker import TechnicalResearchWorker
from app.api.routes.research_symbols import router as symbols_router
from app.api.routes.technical_reports import router as reports_router
from app.harness.technical_research import HarnessedTechnicalPlanExecutor
from app.infrastructure.persistence.harness_audit_repository import SqlAlchemyHarnessAuditRepository
from app.infrastructure.persistence.models.symbols import ResearchSymbolSyncRunRecord
from app.infrastructure.persistence.symbol_repository import SqlAlchemySymbolRepository
from app.infrastructure.persistence.technical_report_repository import (
    SqlAlchemyTechnicalReportRepository,
)
from app.infrastructure.persistence.technical_run_repository import SqlAlchemyTechnicalRunRepository
from app.market.contracts import MarketDetail, MarketSummary, MarketTimeframe
from app.market.symbols import ResearchSymbol
from app.reports.technical_plan import TechnicalPlanReport
from app.reports.technical_runs import TechnicalRunLease, TechnicalRunPhase
from scripts.evaluate_research_flows import technical_model
from scripts.research_flow_fixtures import NOW, MarketRecipe, build_market

FIXTURES = Path(__file__).resolve().parents[1] / "evaluation" / "flows"


class SyntheticMarket:
    # 合成两币种使用同一价格路径，替换每层领域标识，不伪装为实时行情。
    def __init__(self) -> None:
        self.detail = build_market(
            MarketRecipe.model_validate_json((FIXTURES / "market.json").read_bytes())
        )

    async def get_market(
        self, symbol: ResearchSymbol, timeframes: tuple[MarketTimeframe, ...]
    ) -> MarketDetail:
        # 返回请求周期的冻结副本，摘要及每根 K 线同时换币种，防止合成 ETH 混入 BTC 标识。
        if symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported synthetic symbol")
        return self.detail.model_copy(
            update={
                "summary": self.detail.summary.model_copy(update={"symbol": symbol}),
                "series": tuple(
                    series.model_copy(
                        update={
                            "candles": tuple(
                                candle.model_copy(update={"symbol": symbol})
                                for candle in series.candles
                            )
                        }
                    )
                    for series in self.detail.series
                    if series.timeframe in timeframes
                ),
            }
        )

    async def get_summaries(self, symbols: tuple[ResearchSymbol, ...]) -> tuple[MarketSummary, ...]:
        # 摘要与完整行情使用同一构造路径，不另造时间或价格。
        return tuple([(await self.get_market(symbol, ())).summary for symbol in symbols])


class ResearchRuntime:
    # 生命周期由测试服务持有；停止 worker 后才能释放模型客户端或删除 schema。
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory
        self.runs = SqlAlchemyTechnicalRunRepository(factory)
        self.reports = SqlAlchemyTechnicalReportRepository(factory)
        self.symbols = SqlAlchemySymbolRepository(factory)
        self.calls: list[tuple[str, str]] = []
        self.client = httpx.AsyncClient(
            transport=httpx.MockTransport(self.respond), trust_env=False
        )
        self.worker = TechnicalResearchWorker(
            repository=self.runs, executor=self, clock=lambda: datetime.now(UTC)
        )
        self.task: asyncio.Task[None] | None = None
        self.closed = False

    def respond(self, request: httpx.Request) -> httpx.Response:
        # 只绑定本次证据 ID，研究正文取自已版本化语料；不保存或回传思考内容。
        payload = json.loads(request.content)
        if "tools" in payload or "tool_choice" in payload:
            raise ValueError("unexpected model tools")
        analysis = json.loads(payload["messages"][1]["content"])["frozenContext"]["analysis"]
        stage = "analysis" if payload["thinking"]["type"] == "enabled" else "composition"
        # 定性模型投影不包含币种字段；本装配只为 BTC 配置模型，ETH 零请求降级。
        self.calls.append(("BTCUSDT", stage))
        body = (FIXTURES / "technical-valid.json").read_text(encoding="utf-8")
        return httpx.Response(
            200, content=body.replace("__EVIDENCE_ID__", analysis["evidenceId"]).encode()
        )

    async def admitted(self, symbol: ResearchSymbol) -> bool:
        # Harness 实际查询 SQL 目录授权，不能用恒真替身绕过归档/就绪规则。
        entry = await self.symbols.get(symbol)
        return entry is not None and entry.can_research

    async def generate(
        self,
        symbol: ResearchSymbol,
        *,
        analysis_id: UUID,
        progress: Callable[[TechnicalRunPhase], Awaitable[None]],
        before_save: Callable[[], Awaitable[TechnicalRunLease | None]],
    ) -> TechnicalPlanReport:
        # 真实服务执行事实、引用校验和保存，Harness 仍复核目录授权及审计。
        service = TechnicalPlanResearchService(
            market=SyntheticMarket(),
            repository=self.reports,
            model=technical_model(self.client, configured=symbol == "BTCUSDT"),
            clock=lambda: NOW,
        )
        executor = HarnessedTechnicalPlanExecutor(
            service,
            audit=SqlAlchemyHarnessAuditRepository(self.factory),
            authorizer=self.admitted,
            clock=lambda: NOW,
        )
        return await executor.generate(
            symbol, analysis_id=analysis_id, progress=progress, before_save=before_save
        )

    async def seed(self) -> None:
        # 既有迁移已登记 BTC/ETH；仅在隔离 schema 追加合成 ready 同步历史满足真实准入。
        async with self.factory() as session, session.begin():
            for symbol in ("BTCUSDT", "ETHUSDT"):
                session.add(
                    ResearchSymbolSyncRunRecord(
                        id=uuid4(),
                        symbol=symbol,
                        version=1,
                        status="ready",
                        stage="completed",
                        created_at=NOW,
                        started_at=NOW,
                        completed_at=NOW,
                        sources=[],
                        error=None,
                    )
                )

    def install(self, app: FastAPI) -> None:
        # 向独立验收应用注入真实仓储和路由；不注册到生产 main.py，也不装配旧版同步服务。
        app.state.technical_run_repository = self.runs
        app.state.technical_report_repository = self.reports
        app.state.symbol_repository = self.symbols
        app.include_router(symbols_router, prefix="/api/v1")
        app.include_router(reports_router, prefix="/api/v1")

    async def close(self) -> None:
        # 幂等关闭，等待 worker 的取消/审计收尾后才关闭模型传输，供 schema 清理钩子调用。
        if self.closed:
            return
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.client.aclose()
        self.closed = True


@asynccontextmanager
async def research_runtime(
    factory: async_sessionmaker[AsyncSession], *, background: bool = True
) -> AsyncGenerator[ResearchRuntime]:
    # 合成准入初始化失败同样关闭客户端；background=False 仅供测试显式单步消费队列。
    runtime = ResearchRuntime(factory)
    try:
        await runtime.seed()
        if background:
            runtime.task = asyncio.create_task(runtime.worker.run_forever(asyncio.Event()))
        yield runtime
    finally:
        await runtime.close()
