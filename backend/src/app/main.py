import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import NoReturn, cast
from uuid import UUID

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.model import DeepSeekResearchLanguageModel
from app.agent.service import (
    AgentResearchDependencies,
    AgentResearchService,
    AgentSnapshotInputReader,
    PersistedAgentMarketCapture,
)
from app.agent.technical.model import DeepSeekTechnicalLanguageModel
from app.agent.technical.plan_model import DeepSeekTechnicalPlanLanguageModel
from app.agent.technical.plan_service import TechnicalPlanResearchService
from app.agent.technical.service import TechnicalResearchService
from app.agent.technical.worker import TechnicalResearchWorker
from app.api.errors import install_exception_handlers
from app.api.router import API_NAME
from app.api.router import router as api_router
from app.api.routes.health import router as health_router
from app.dashboard.service import DashboardService
from app.harness.market_research import (
    HarnessedMarketResearchService,
    MarketResearchWorkflow,
)
from app.harness.policy import MARKET_RESEARCH_POLICY
from app.harness.runtime import HarnessRuntime
from app.harness.technical_research import (
    TECHNICAL_RESEARCH_POLICY,
    HarnessedTechnicalPlanExecutor,
    HarnessedTechnicalResearchService,
    TechnicalReportGenerator,
    TechnicalResearchWorkflow,
    UnavailableTechnicalResearchService,
)
from app.infrastructure.persistence.backtest_repository import SqlAlchemyBacktestRepository
from app.infrastructure.persistence.harness_audit_repository import (
    SqlAlchemyHarnessAuditRepository,
)
from app.infrastructure.persistence.news_repository import SqlAlchemyNewsRepository
from app.infrastructure.persistence.paper_trading_repository import (
    SqlAlchemyPaperTradingRepository,
)
from app.infrastructure.persistence.report_repository import (
    SqlAlchemyAnalysisReportRepository,
)
from app.infrastructure.persistence.repository import SqlAlchemyMarketRepository
from app.infrastructure.persistence.research_reader import SqlAlchemyPersistedMarketReader
from app.infrastructure.persistence.symbol_repository import SqlAlchemySymbolRepository
from app.infrastructure.persistence.technical_report_repository import (
    SqlAlchemyTechnicalReportRepository,
)
from app.infrastructure.persistence.technical_run_repository import SqlAlchemyTechnicalRunRepository
from app.infrastructure.persistence.trade_repository import SqlAlchemyTradeRepository
from app.market.binance_usdm import (
    BINANCE_USDM_BASE_URL,
    BinanceUsdmPublicMarketGateway,
)
from app.market.capture import MarketCaptureService
from app.market.contracts import (
    Candle,
    ContractSymbol,
    MarketDataUnavailableError,
    MarketTimeframe,
)
from app.market.etf_flows import FARSIDE_BASE_URL, FarsideEtfFlowGateway
from app.market.gateway import HistoricalCandleGateway, PublicMarketGateway
from app.market.research import (
    MarketResearchQueryService,
    PersistedMarketReader,
)
from app.market.research_context import (
    ALTERNATIVE_ME_BASE_URL,
    AlternativeMeFearGreedGateway,
    PublicResearchContextCollector,
)
from app.market.service import MarketQueryService
from app.market.symbols import ResearchSymbol
from app.news.contracts import ALLOWED_NEWS_SOURCES
from app.news.rss import RssNewsSourceAdapter
from app.news.service import NewsIngestionService
from app.paper_trading.contracts import (
    PaperAccountCreate,
    PaperAccountFilters,
    PaperStorageUnavailableError,
    PaperTransition,
)
from app.paper_trading.repository import PaperTradingRepository
from app.paper_trading.service import PaperTradingService
from app.reports.contracts import (
    AnalysisReportCreation,
    AnalysisReportStatus,
    PersistedAnalysisReport,
    ReportStorageUnavailableError,
)
from app.reports.repository import AnalysisReportRepository
from app.reports.service import AnalysisReportService, DeterministicResearchReportService
from app.reports.technical import TechnicalReport
from app.reports.technical_repository import (
    TechnicalReportRepository,
    UnavailableTechnicalReportRepository,
)
from app.reports.technical_run_repository import TechnicalRunRepository
from app.research.backtests.contracts import (
    BacktestFilters,
    BacktestRequest,
    BacktestResult,
    BacktestStorageUnavailableError,
)
from app.research.backtests.engine import DeterministicBacktestEngine
from app.research.backtests.repository import BacktestRepository
from app.research.backtests.service import BacktestService
from app.shared.config import AppSettings
from app.shared.database import (
    checkpoint_connection_string,
    create_database_engine,
    create_session_factory,
)
from app.shared.logging import configure_logging
from app.symbols.memory import StaticSymbolRepository
from app.symbols.repository import SymbolRepository
from app.symbols.service import SymbolProbeGateway, SymbolService
from app.symbols.sync import ResearchSymbolSyncWorker
from app.trades.analytics import PerformanceAnalyticsService
from app.trades.calculator import TradePnl
from app.trades.contracts import (
    TradeDraft,
    TradeFilters,
    TradeStorageUnavailableError,
)
from app.trades.repository import TradeRepository
from app.trades.service import TradeService


class _UnavailablePersistedMarketReader(PersistedMarketReader):
    async def load_snapshot(self, snapshot_id: UUID) -> NoReturn:
        del snapshot_id
        _raise_market_research_unavailable()

    async def load_latest_snapshot(
        self,
        symbol: ResearchSymbol,
    ) -> NoReturn:
        del symbol
        _raise_market_research_unavailable()

    async def load_recent_candles(
        self,
        symbol: ResearchSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> NoReturn:
        del symbol, timeframe, limit
        _raise_market_research_unavailable()


class _UnavailableAnalysisReportRepository(AnalysisReportRepository):
    async def persist(
        self,
        creation: AnalysisReportCreation,
    ) -> NoReturn:
        del creation
        _raise_analysis_report_storage_unavailable()

    async def get_by_id(self, report_id: UUID) -> NoReturn:
        del report_id
        _raise_analysis_report_storage_unavailable()

    async def get_by_analysis_id(self, analysis_id: UUID) -> NoReturn:
        del analysis_id
        _raise_analysis_report_storage_unavailable()

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        symbol: ContractSymbol | None,
        status: AnalysisReportStatus | None,
    ) -> NoReturn:
        del page, page_size, symbol, status
        _raise_analysis_report_storage_unavailable()


class _UnavailableTradeRepository(TradeRepository):
    async def create(
        self,
        *,
        draft: TradeDraft,
        pnl: TradePnl,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> NoReturn:
        del draft, pnl, occurred_at, correlation_id
        _raise_trade_storage_unavailable()

    async def replace(
        self,
        *,
        trade_id: UUID,
        draft: TradeDraft,
        pnl: TradePnl,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> NoReturn:
        del trade_id, draft, pnl, occurred_at, correlation_id
        _raise_trade_storage_unavailable()

    async def archive(
        self,
        trade_id: UUID,
        *,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> NoReturn:
        del trade_id, occurred_at, correlation_id
        _raise_trade_storage_unavailable()

    async def get_by_id(self, trade_id: UUID) -> NoReturn:
        del trade_id
        _raise_trade_storage_unavailable()

    async def list(self, filters: TradeFilters) -> NoReturn:
        del filters
        _raise_trade_storage_unavailable()

    async def list_closed(self, filters: TradeFilters) -> NoReturn:
        del filters
        _raise_trade_storage_unavailable()


class _UnavailableHistoricalCandleGateway(HistoricalCandleGateway):
    async def load_closed_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> NoReturn:
        del symbol, timeframe, start_at, end_at
        _raise_backtest_history_unavailable()


class _UnavailableBacktestRepository(BacktestRepository):
    async def create_pending(
        self,
        request: BacktestRequest,
        *,
        occurred_at: datetime,
    ) -> NoReturn:
        del request, occurred_at
        _raise_backtest_storage_unavailable()

    async def complete(
        self,
        run_id: UUID,
        result: BacktestResult,
        candles: tuple[Candle, ...],
        *,
        occurred_at: datetime,
    ) -> NoReturn:
        del run_id, result, candles, occurred_at
        _raise_backtest_storage_unavailable()

    async def fail(
        self,
        run_id: UUID,
        *,
        code: str,
        message: str,
        occurred_at: datetime,
    ) -> NoReturn:
        del run_id, code, message, occurred_at
        _raise_backtest_storage_unavailable()

    async def list(self, filters: BacktestFilters) -> NoReturn:
        del filters
        _raise_backtest_storage_unavailable()

    async def get_by_id(self, run_id: UUID) -> NoReturn:
        del run_id
        _raise_backtest_storage_unavailable()


class _UnavailablePaperTradingRepository(PaperTradingRepository):
    async def create_account(
        self,
        request: PaperAccountCreate,
        *,
        occurred_at: datetime,
    ) -> NoReturn:
        del request, occurred_at
        _raise_paper_storage_unavailable()

    async def list(self, filters: PaperAccountFilters) -> NoReturn:
        del filters
        _raise_paper_storage_unavailable()

    async def get_by_id(self, account_id: UUID) -> NoReturn:
        del account_id
        _raise_paper_storage_unavailable()

    async def get_performance_data(self, account_id: UUID) -> NoReturn:
        del account_id
        _raise_paper_storage_unavailable()

    async def find_outcome(
        self,
        account_id: UUID,
        idempotency_key: str,
    ) -> NoReturn:
        del account_id, idempotency_key
        _raise_paper_storage_unavailable()

    async def apply_transition(
        self,
        account_id: UUID,
        idempotency_key: str,
        transition: PaperTransition,
        *,
        occurred_at: datetime,
    ) -> NoReturn:
        del account_id, idempotency_key, transition, occurred_at
        _raise_paper_storage_unavailable()

    async def record_market_failure(
        self,
        account_id: UUID,
        idempotency_key: str,
        *,
        code: str,
        occurred_at: datetime,
    ) -> NoReturn:
        del account_id, idempotency_key, code, occurred_at
        _raise_paper_storage_unavailable()

    async def archive(self, account_id: UUID, *, occurred_at: datetime) -> NoReturn:
        del account_id, occurred_at
        _raise_paper_storage_unavailable()


def build_public_research_context_collector(
    *,
    market_gateway: PublicMarketGateway,
    alternative_client: httpx.AsyncClient,
    clock: Callable[[], datetime],
) -> PublicResearchContextCollector | None:
    """Build the public-only context collector without replacing injected gateways."""

    if not isinstance(market_gateway, BinanceUsdmPublicMarketGateway):
        return None
    return PublicResearchContextCollector(
        derivatives=market_gateway,
        fear_greed=AlternativeMeFearGreedGateway(
            client=alternative_client,
            clock=clock,
        ),
    )


def build_news_sources(
    *,
    client: httpx.AsyncClient,
    timeout_seconds: int,
) -> tuple[RssNewsSourceAdapter, ...]:
    """Construct the complete, registered RSS source set in registry order."""

    return tuple(
        RssNewsSourceAdapter(
            source=source,
            client=client,
            timeout_seconds=timeout_seconds,
        )
        for source in ALLOWED_NEWS_SOURCES.values()
    )


def create_app(
    market_gateway: PublicMarketGateway | None = None,
    market_research_reader: PersistedMarketReader | None = None,
    analysis_report_repository: AnalysisReportRepository | None = None,
    agent_research_service: AnalysisReportService | None = None,
    trade_repository: TradeRepository | None = None,
    historical_candle_gateway: HistoricalCandleGateway | None = None,
    backtest_repository: BacktestRepository | None = None,
    backtest_clock: Callable[[], datetime] | None = None,
    paper_repository: PaperTradingRepository | None = None,
    paper_clock: Callable[[], datetime] | None = None,
    dashboard_clock: Callable[[], datetime] | None = None,
    symbol_repository: SymbolRepository | None = None,
    symbol_service: SymbolService | None = None,
    technical_report_repository: TechnicalReportRepository | None = None,
    technical_research_service: TechnicalReportGenerator | None = None,
    technical_run_repository: TechnicalRunRepository | None = None,
) -> FastAPI:
    settings = AppSettings()
    configure_logging(settings.log_level)
    # Dependency-injected apps are used for tests and local component wiring;
    # they deliberately keep the legacy BTC/ETH read-only directory in memory.
    # The default production composition uses the durable PostgreSQL directory.
    use_durable_symbol_directory = all(
        dependency is None
        for dependency in (
            market_gateway,
            market_research_reader,
            analysis_report_repository,
            agent_research_service,
            trade_repository,
            historical_candle_gateway,
            backtest_repository,
            paper_repository,
            technical_report_repository,
            technical_research_service,
            technical_run_repository,
        )
    )

    market_client: httpx.AsyncClient | None = None
    if market_gateway is None:
        market_client = httpx.AsyncClient(
            base_url=BINANCE_USDM_BASE_URL,
            headers={"Accept": "application/json"},
        )
        market_gateway = BinanceUsdmPublicMarketGateway(
            client=market_client,
            clock=lambda: datetime.now(UTC),
        )

    if historical_candle_gateway is None:
        historical_candle_gateway = (
            market_gateway
            if isinstance(market_gateway, BinanceUsdmPublicMarketGateway)
            else _UnavailableHistoricalCandleGateway()
        )

    research_engine: AsyncEngine | None = None
    session_factory = None
    if (
        market_research_reader is None
        or analysis_report_repository is None
        or trade_repository is None
        or backtest_repository is None
        or paper_repository is None
        or symbol_repository is None
    ):
        if settings.database_url is not None:
            research_engine = create_database_engine(settings.database_url)
            session_factory = create_session_factory(research_engine)

    if market_research_reader is None:
        if session_factory is None:
            market_research_reader = _UnavailablePersistedMarketReader()
        else:
            market_research_reader = SqlAlchemyPersistedMarketReader(
                session_factory,
            )

    if analysis_report_repository is None:
        analysis_report_repository = (
            _UnavailableAnalysisReportRepository()
            if session_factory is None
            else SqlAlchemyAnalysisReportRepository(session_factory)
        )

    if technical_report_repository is None:
        technical_report_repository = (
            UnavailableTechnicalReportRepository()
            if session_factory is None
            else SqlAlchemyTechnicalReportRepository(session_factory)
        )

    if trade_repository is None:
        trade_repository = (
            _UnavailableTradeRepository()
            if session_factory is None
            else SqlAlchemyTradeRepository(session_factory)
        )

    if backtest_repository is None:
        backtest_repository = (
            _UnavailableBacktestRepository()
            if session_factory is None
            else SqlAlchemyBacktestRepository(session_factory)
        )

    if paper_repository is None:
        paper_repository = (
            _UnavailablePaperTradingRepository()
            if session_factory is None
            else SqlAlchemyPaperTradingRepository(session_factory)
        )

    if symbol_repository is None:
        symbol_repository = (
            StaticSymbolRepository()
            if session_factory is None or not use_durable_symbol_directory
            else SqlAlchemySymbolRepository(session_factory)
        )
    if symbol_service is None:
        symbol_service = SymbolService(
            symbol_repository,
            cast(SymbolProbeGateway, market_gateway),
            clock=lambda: datetime.now(UTC),
        )

    market_capture_service: MarketCaptureService | None = None
    symbol_sync_worker: ResearchSymbolSyncWorker | None = None
    if session_factory is not None:
        market_capture_service = MarketCaptureService(
            market_gateway,
            SqlAlchemyMarketRepository(session_factory),
            admission=(
                (lambda symbol: _is_enabled_research_symbol(symbol_repository, symbol))
                if isinstance(symbol_repository, SqlAlchemySymbolRepository)
                else None
            ),
        )
    if market_capture_service is not None and isinstance(
        symbol_repository, SqlAlchemySymbolRepository
    ):
        symbol_sync_worker = ResearchSymbolSyncWorker(
            repository=symbol_repository,
            capture=market_capture_service,
            funding=(
                market_gateway
                if isinstance(market_gateway, BinanceUsdmPublicMarketGateway)
                else None
            ),
            clock=lambda: datetime.now(UTC),
        )

    news_client: httpx.AsyncClient | None = None
    alternative_client: httpx.AsyncClient | None = None
    etf_client: httpx.AsyncClient | None = None
    model_client: httpx.AsyncClient | None = None
    checkpoint_connection: str | None = None
    agent_service_factory: Callable[[AsyncPostgresSaver], AnalysisReportService] | None = None
    agent_report_repository = (
        analysis_report_repository
        if isinstance(analysis_report_repository, SqlAlchemyAnalysisReportRepository)
        else None
    )
    if (
        agent_research_service is None
        and session_factory is not None
        and settings.database_url is not None
        and agent_report_repository is not None
    ):
        news_client = httpx.AsyncClient(headers={"Accept": "application/xml"})
        etf_client = httpx.AsyncClient(
            base_url=FARSIDE_BASE_URL,
            headers={"Accept": "text/html"},
            timeout=5.0,
            follow_redirects=False,
        )
        etf_gateway = FarsideEtfFlowGateway(client=etf_client, clock=lambda: datetime.now(UTC))
        if isinstance(market_gateway, BinanceUsdmPublicMarketGateway):
            alternative_client = httpx.AsyncClient(
                base_url=ALTERNATIVE_ME_BASE_URL,
                headers={"Accept": "application/json"},
                timeout=httpx.Timeout(settings.news_http_timeout_seconds),
            )
        model_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.agent_request_timeout_seconds),
        )
        if market_capture_service is None:
            raise RuntimeError("研究币对同步服务未初始化")
        market_capture = PersistedAgentMarketCapture(
            capture_service=market_capture_service,
            reader=cast(AgentSnapshotInputReader, market_research_reader),
            research_context=(
                None
                if alternative_client is None
                else build_public_research_context_collector(
                    market_gateway=market_gateway,
                    alternative_client=alternative_client,
                    clock=lambda: datetime.now(UTC),
                )
            ),
        )
        news_ingestion = NewsIngestionService(
            sources=build_news_sources(
                client=news_client,
                timeout_seconds=settings.news_http_timeout_seconds,
            ),
            repository=SqlAlchemyNewsRepository(session_factory),
            symbol_repository=symbol_repository,
        )
        model = DeepSeekResearchLanguageModel(
            client=model_client,
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
        )
        harness_audit_repository = SqlAlchemyHarnessAuditRepository(session_factory)

        def create_agent_service(checkpointer: AsyncPostgresSaver) -> AnalysisReportService:
            agent_service = AgentResearchService(
                dependencies=AgentResearchDependencies(
                    market=market_capture,
                    news=news_ingestion,
                    model=model,
                    repository=agent_report_repository,
                    clock=lambda: datetime.now(UTC),
                    funding=(
                        market_gateway
                        if isinstance(
                            market_gateway,
                            BinanceUsdmPublicMarketGateway,
                        )
                        else None
                    ),
                    etf=etf_gateway,
                ),
                checkpointer=checkpointer,
            )
            runtime = HarnessRuntime[PersistedAnalysisReport](
                policies=(MARKET_RESEARCH_POLICY,),
                workflows=(MarketResearchWorkflow(agent_service),),
                audit_repository=harness_audit_repository,
                symbol_authorizer=lambda symbol: _is_research_ready_symbol(
                    symbol_repository,
                    symbol,
                ),
            )
            return HarnessedMarketResearchService(
                runtime,
                clock=lambda: datetime.now(UTC),
            )

        agent_service_factory = create_agent_service
        checkpoint_connection = checkpoint_connection_string(settings.database_url)

    technical_model_client: httpx.AsyncClient | None = None
    if technical_research_service is None:
        if session_factory is None:
            technical_research_service = UnavailableTechnicalResearchService()
        else:
            technical_model_client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.agent_request_timeout_seconds),
            )
            technical_service = TechnicalResearchService(
                market=market_gateway,
                repository=technical_report_repository,
                model=DeepSeekTechnicalLanguageModel(
                    client=technical_model_client,
                    api_key=settings.deepseek_api_key,
                    model=settings.deepseek_model,
                ),
                clock=lambda: datetime.now(UTC),
            )
            technical_runtime = HarnessRuntime[TechnicalReport](
                policies=(TECHNICAL_RESEARCH_POLICY,),
                workflows=(TechnicalResearchWorkflow(technical_service),),
                audit_repository=SqlAlchemyHarnessAuditRepository(session_factory),
                symbol_authorizer=lambda symbol: _is_research_ready_symbol(
                    symbol_repository, symbol
                ),
            )
            technical_research_service = HarnessedTechnicalResearchService(
                technical_runtime,
                clock=lambda: datetime.now(UTC),
            )

    technical_plan_client: httpx.AsyncClient | None = None
    technical_plan_worker: TechnicalResearchWorker | None = None
    if technical_run_repository is None and session_factory is not None:
        technical_run_repository = SqlAlchemyTechnicalRunRepository(session_factory)
        technical_plan_client = httpx.AsyncClient(
            timeout=settings.technical_analysis_timeout_seconds
        )
        plan_service = TechnicalPlanResearchService(
            market=market_gateway,
            repository=technical_report_repository,
            model=DeepSeekTechnicalPlanLanguageModel(
                client=technical_plan_client,
                api_key=settings.deepseek_api_key,
                model=settings.deepseek_model,
                settings=settings,
            ),
            clock=lambda: datetime.now(UTC),
            timeout_seconds=settings.technical_run_timeout_seconds,
        )
        executor = HarnessedTechnicalPlanExecutor(
            plan_service,
            audit=SqlAlchemyHarnessAuditRepository(session_factory),
            authorizer=lambda symbol: _is_research_ready_symbol(symbol_repository, symbol),
            clock=lambda: datetime.now(UTC),
        )
        technical_plan_worker = TechnicalResearchWorker(
            repository=technical_run_repository, executor=executor, clock=lambda: datetime.now(UTC)
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        stop_sync = asyncio.Event()
        stop_plan = asyncio.Event()
        plan_task = (
            None
            if technical_plan_worker is None
            else asyncio.create_task(technical_plan_worker.run_forever(stop_plan))
        )
        sync_task = (
            None
            if symbol_sync_worker is None
            else asyncio.create_task(symbol_sync_worker.run_forever(stop_sync))
        )
        try:
            if agent_service_factory is not None and checkpoint_connection is not None:
                async with AsyncPostgresSaver.from_conn_string(
                    checkpoint_connection,
                ) as checkpointer:
                    await checkpointer.setup()
                    app.state.analysis_report_service = agent_service_factory(checkpointer)
                    yield
            else:
                yield
        finally:
            stop_plan.set()
            if plan_task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(plan_task), timeout=5)
                except TimeoutError:
                    plan_task.cancel()
                    await asyncio.gather(plan_task, return_exceptions=True)
            if technical_plan_client is not None:
                await technical_plan_client.aclose()
            if technical_model_client is not None:
                await technical_model_client.aclose()
            stop_sync.set()
            if sync_task is not None:
                await sync_task
            if model_client is not None:
                await model_client.aclose()
            if news_client is not None:
                await news_client.aclose()
            if alternative_client is not None:
                await alternative_client.aclose()
            if etf_client is not None:
                await etf_client.aclose()
            if market_client is not None:
                await market_client.aclose()
            if research_engine is not None:
                await research_engine.dispose()

    app = FastAPI(
        title=API_NAME,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.market_service = MarketQueryService(market_gateway)
    app.state.symbol_repository = symbol_repository
    app.state.symbol_service = symbol_service
    app.state.dashboard_service = DashboardService(
        app.state.market_service,
        analysis_report_repository,
        clock=dashboard_clock or (lambda: datetime.now(UTC)),
    )
    app.state.market_research_service = MarketResearchQueryService(
        market_research_reader,
        clock=lambda: datetime.now(UTC),
    )
    app.state.analysis_report_repository = analysis_report_repository
    app.state.technical_report_repository = technical_report_repository
    app.state.technical_research_service = technical_research_service
    app.state.technical_run_repository = technical_run_repository
    app.state.analysis_report_service = (
        agent_research_service
        if agent_research_service is not None
        else DeterministicResearchReportService(
            market_research_reader,
            analysis_report_repository,
            clock=lambda: datetime.now(UTC),
        )
    )
    app.state.trade_repository = trade_repository
    app.state.trade_service = TradeService(
        repository=trade_repository,
        clock=lambda: datetime.now(UTC),
    )
    app.state.performance_analytics_service = PerformanceAnalyticsService(
        repository=trade_repository,
        clock=lambda: datetime.now(UTC),
    )
    app.state.backtest_repository = backtest_repository
    app.state.backtest_service = BacktestService(
        history=historical_candle_gateway,
        repository=backtest_repository,
        engine=DeterministicBacktestEngine(),
        clock=backtest_clock or (lambda: datetime.now(UTC)),
    )
    app.state.paper_trading_repository = paper_repository
    app.state.paper_trading_service = PaperTradingService(
        market=market_gateway,
        history=historical_candle_gateway,
        repository=paper_repository,
        clock=paper_clock or (lambda: datetime.now(UTC)),
    )
    install_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Accept", "Content-Type"],
    )
    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()


async def _is_enabled_research_symbol(
    repository: SymbolRepository,
    symbol: ResearchSymbol,
) -> bool:
    entry = await repository.get(symbol)
    return entry is not None and entry.enabled


async def _is_research_ready_symbol(
    repository: SymbolRepository,
    symbol: ResearchSymbol,
) -> bool:
    entry = await repository.get(symbol)
    return entry is not None and entry.enabled and entry.can_research


def _raise_market_research_unavailable() -> NoReturn:
    raise MarketDataUnavailableError(
        "market_research_unavailable",
        "持久化市场研究数据不可用",
    )


def _raise_analysis_report_storage_unavailable() -> NoReturn:
    raise ReportStorageUnavailableError("研究报告存储不可用")


def _raise_trade_storage_unavailable() -> NoReturn:
    raise TradeStorageUnavailableError("交易日志存储不可用")


def _raise_backtest_history_unavailable() -> NoReturn:
    raise MarketDataUnavailableError(
        "backtest_history_unavailable",
        "历史回测行情不可用",
    )


def _raise_backtest_storage_unavailable() -> NoReturn:
    raise BacktestStorageUnavailableError("回测存储不可用")


def _raise_paper_storage_unavailable() -> NoReturn:
    raise PaperStorageUnavailableError("模拟盘存储不可用")
