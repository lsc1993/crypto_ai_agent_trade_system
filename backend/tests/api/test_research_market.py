from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI

from app.main import create_app
from app.market.contracts import (
    Candle,
    ContractSymbol,
    DataFreshness,
    FreshnessStatus,
    MarketDataUnavailableError,
    MarketSummary,
    MarketTimeframe,
)
from app.market.research import (
    MarketResearchQueryService,
    PersistedMarketReader,
    PersistedMarketSnapshot,
)

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


class FakePersistedMarketReader:
    async def load_latest_snapshot(
        self,
        symbol: ContractSymbol,
    ) -> PersistedMarketSnapshot | None:
        if symbol is ContractSymbol.BTCUSDT:
            return PersistedMarketSnapshot(summary=_summary(), captured_at=NOW)
        return None

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        assert symbol is ContractSymbol.BTCUSDT
        assert timeframe is MarketTimeframe.M15
        assert limit == 200
        return (_candle(),)


class UnavailablePersistedMarketReader:
    async def load_latest_snapshot(
        self,
        symbol: ContractSymbol,
    ) -> PersistedMarketSnapshot | None:
        del symbol
        raise MarketDataUnavailableError(
            "market_research_unavailable",
            "持久化市场研究数据不可用",
        )

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        del symbol, timeframe, limit
        raise MarketDataUnavailableError(
            "market_research_unavailable",
            "持久化市场研究数据不可用",
        )


async def get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_research_detail_keeps_the_existing_market_wire_contract() -> None:
    app = _research_app(FakePersistedMarketReader())

    response = await get(app, "/api/v1/research/market/BTCUSDT?timeframes=15m")

    assert response.status_code == 200
    assert response.json() == {
        "summary": {
            "symbol": "BTCUSDT",
            "price": "68000.30",
            "change24h": "1.25",
            "volume24h": "123456.789",
            "fundingRate": "0.00010000",
            "openInterest": "1234.5678",
            "freshness": {
                "status": "fresh",
                "source": "binance_usdm_public_rest",
                "observedAt": "2026-07-30T11:59:00Z",
                "fetchedAt": "2026-07-30T12:00:00Z",
            },
        },
        "series": [
            {
                "timeframe": "15m",
                "candles": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "15m",
                        "openTime": "2026-07-30T11:45:00Z",
                        "closeTime": "2026-07-30T12:00:00Z",
                        "open": "68000.10",
                        "high": "68001.20",
                        "low": "67999.90",
                        "close": "68000.30",
                        "volume": "12.34",
                    },
                ],
            },
        ],
        "news": [],
    }


@pytest.mark.asyncio
async def test_research_route_returns_stable_503_when_reader_is_unavailable() -> None:
    app = _research_app(UnavailablePersistedMarketReader())

    response = await get(app, "/api/v1/research/markets?symbols=BTCUSDT")

    assert response.status_code == 503
    assert response.json() == {
        "code": "market_research_unavailable",
        "message": "持久化市场研究数据不可用",
        "details": {},
    }


@pytest.mark.asyncio
async def test_research_route_rejects_duplicate_symbols_and_timeframes() -> None:
    app = _research_app(FakePersistedMarketReader())

    summary_response = await get(
        app,
        "/api/v1/research/markets?symbols=BTCUSDT&symbols=BTCUSDT",
    )
    detail_response = await get(
        app,
        "/api/v1/research/market/BTCUSDT?timeframes=15m&timeframes=15m",
    )

    assert summary_response.status_code == 422
    assert detail_response.status_code == 422


def _research_app(reader: PersistedMarketReader) -> FastAPI:
    app = create_app(market_research_reader=reader)
    app.state.market_research_service = MarketResearchQueryService(
        reader,
        clock=lambda: NOW,
    )
    return app


def _summary() -> MarketSummary:
    return MarketSummary(
        symbol=ContractSymbol.BTCUSDT,
        price=Decimal("68000.30"),
        change_24h=Decimal("1.25"),
        volume_24h=Decimal("123456.789"),
        funding_rate=Decimal("0.00010000"),
        open_interest=Decimal("1234.5678"),
        freshness=DataFreshness(
            status=FreshnessStatus.FRESH,
            source="binance_usdm_public_rest",
            observed_at=NOW - timedelta(minutes=1),
            fetched_at=NOW,
        ),
    )


def _candle() -> Candle:
    return Candle(
        symbol=ContractSymbol.BTCUSDT,
        timeframe=MarketTimeframe.M15,
        open_at=NOW - timedelta(minutes=15),
        close_at=NOW,
        open_price=Decimal("68000.10"),
        high_price=Decimal("68001.20"),
        low_price=Decimal("67999.90"),
        close_price=Decimal("68000.30"),
        volume=Decimal("12.34"),
        observed_at=NOW,
        fetched_at=NOW,
    )
