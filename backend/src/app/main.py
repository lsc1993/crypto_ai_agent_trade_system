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
from app.api.errors import install_exception_handlers
from app.api.router import API_NAME
from app.api.router import router as api_router
from app.api.routes.health import router as health_router
from app.dashboard.service import DashboardService
from app.infrastructure.persistence.backtest_repository import SqlAlchemyBacktestRepository
from app.infrastructure.persistence.news_repository import SqlAlchemyNewsRepository
from app.infrastructure.persistence.paper_trading_repository import (
    SqlAlchemyPaperTradingRepository,
)
from app.infrastructure.persistence.report_repository import (
    SqlAlchemyAnalysisReportRepository,
)
from app.infrastructure.persistence.repository import SqlAlchemyMarketRepository
from app.infrastructure.persistence.research_reader import SqlAlchemyPersistedMarketReader
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
from app.market.gateway import HistoricalCandleGateway, PublicMarketGateway
from app.market.research import (
    MarketResearchQueryService,
    PersistedMarketReader,
)
from app.market.service import MarketQueryService
from app.news.contracts import COINDESK_SOURCE, SEC_PRESS_RELEASES_SOURCE
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
    ReportStorageUnavailableError,
)
from app.reports.repository import AnalysisReportRepository
from app.reports.service import AnalysisReportService, DeterministicResearchReportService
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
        symbol: ContractSymbol,
    ) -> NoReturn:
        del symbol
        _raise_market_research_unavailable()

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
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
) -> FastAPI:
    settings = AppSettings()
    configure_logging(settings.log_level)

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

    news_client: httpx.AsyncClient | None = None
    model_client: httpx.AsyncClient | None = None
    checkpoint_connection: str | None = None
    agent_service_factory: Callable[[AsyncPostgresSaver], AgentResearchService] | None = None
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
        model_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.agent_request_timeout_seconds),
        )
        market_capture = PersistedAgentMarketCapture(
            capture_service=MarketCaptureService(
                market_gateway,
                SqlAlchemyMarketRepository(session_factory),
            ),
            reader=cast(AgentSnapshotInputReader, market_research_reader),
        )
        news_ingestion = NewsIngestionService(
            sources=(
                RssNewsSourceAdapter(
                    source=COINDESK_SOURCE,
                    client=news_client,
                    timeout_seconds=settings.news_http_timeout_seconds,
                ),
                RssNewsSourceAdapter(
                    source=SEC_PRESS_RELEASES_SOURCE,
                    client=news_client,
                    timeout_seconds=settings.news_http_timeout_seconds,
                ),
            ),
            repository=SqlAlchemyNewsRepository(session_factory),
        )
        model = DeepSeekResearchLanguageModel(
            client=model_client,
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
        )
        def create_agent_service(checkpointer: AsyncPostgresSaver) -> AgentResearchService:
            return AgentResearchService(
                dependencies=AgentResearchDependencies(
                    market=market_capture,
                    news=news_ingestion,
                    model=model,
                    repository=agent_report_repository,
                    clock=lambda: datetime.now(UTC),
                ),
                checkpointer=checkpointer,
            )

        agent_service_factory = create_agent_service
        checkpoint_connection = checkpoint_connection_string(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
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
            if model_client is not None:
                await model_client.aclose()
            if news_client is not None:
                await news_client.aclose()
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
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Accept", "Content-Type"],
    )
    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()


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
