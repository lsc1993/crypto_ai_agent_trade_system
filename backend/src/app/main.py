from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_exception_handlers
from app.api.router import API_NAME
from app.api.router import router as api_router
from app.api.routes.health import router as health_router
from app.market.binance_usdm import (
    BINANCE_USDM_BASE_URL,
    BinanceUsdmPublicMarketGateway,
)
from app.market.gateway import PublicMarketGateway
from app.market.service import MarketQueryService
from app.shared.config import AppSettings
from app.shared.logging import configure_logging


def create_app(market_gateway: PublicMarketGateway | None = None) -> FastAPI:
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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        yield
        if market_client is not None:
            await market_client.aclose()

    app = FastAPI(
        title=API_NAME,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.market_service = MarketQueryService(market_gateway)
    install_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type"],
    )
    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()
