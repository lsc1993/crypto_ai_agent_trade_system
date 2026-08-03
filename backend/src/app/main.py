from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.errors import install_exception_handlers
from app.api.router import API_NAME
from app.api.router import router as api_router
from app.api.routes.health import router as health_router
from app.infrastructure.persistence.report_repository import (
    SqlAlchemyAnalysisReportRepository,
)
from app.infrastructure.persistence.research_reader import SqlAlchemyPersistedMarketReader
from app.infrastructure.persistence.trade_repository import SqlAlchemyTradeRepository
from app.market.binance_usdm import (
    BINANCE_USDM_BASE_URL,
    BinanceUsdmPublicMarketGateway,
)
from app.market.contracts import (
    ContractSymbol,
    MarketDataUnavailableError,
    MarketTimeframe,
)
from app.market.gateway import PublicMarketGateway
from app.market.research import (
    MarketResearchQueryService,
    PersistedMarketReader,
)
from app.market.service import MarketQueryService
from app.reports.contracts import (
    AnalysisReportCreation,
    AnalysisReportStatus,
    ReportStorageUnavailableError,
)
from app.reports.repository import AnalysisReportRepository
from app.reports.service import DeterministicResearchReportService
from app.shared.config import AppSettings
from app.shared.database import create_database_engine, create_session_factory
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


def create_app(
    market_gateway: PublicMarketGateway | None = None,
    market_research_reader: PersistedMarketReader | None = None,
    analysis_report_repository: AnalysisReportRepository | None = None,
    trade_repository: TradeRepository | None = None,
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

    research_engine: AsyncEngine | None = None
    session_factory = None
    if (
        market_research_reader is None
        or analysis_report_repository is None
        or trade_repository is None
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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        yield
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
    app.state.market_research_service = MarketResearchQueryService(
        market_research_reader,
        clock=lambda: datetime.now(UTC),
    )
    app.state.analysis_report_repository = analysis_report_repository
    app.state.analysis_report_service = DeterministicResearchReportService(
        market_research_reader,
        analysis_report_repository,
        clock=lambda: datetime.now(UTC),
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
