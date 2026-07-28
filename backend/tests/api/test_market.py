from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI

from app.main import create_app
from app.market.contracts import (
    Candle,
    CandleSeries,
    ContractSymbol,
    DataFreshness,
    FreshnessStatus,
    MarketDataUnavailableError,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)

FIXED_TIME = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def market_summary(symbol: ContractSymbol) -> MarketSummary:
    return MarketSummary(
        symbol=symbol,
        price=Decimal("68000.30"),
        change_24h=Decimal("1.25"),
        volume_24h=Decimal("123456.789"),
        funding_rate=Decimal("0.00010000"),
        open_interest=Decimal("1234.5678"),
        freshness=DataFreshness(
            status=FreshnessStatus.FRESH,
            source="binance_usdm_public_rest",
            observed_at=FIXED_TIME,
            fetched_at=FIXED_TIME,
        ),
    )


class FakeMarketGateway:
    async def get_summaries(
        self,
        symbols: tuple[ContractSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        return tuple(market_summary(symbol) for symbol in symbols)

    async def get_market(
        self,
        symbol: ContractSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        candle = Candle(
            symbol=symbol,
            timeframe=timeframes[0],
            open_at=datetime(2026, 7, 28, 11, 45, tzinfo=UTC),
            close_at=datetime(2026, 7, 28, 11, 59, 59, tzinfo=UTC),
            open_price=Decimal("68000.10"),
            high_price=Decimal("68001.20"),
            low_price=Decimal("67999.90"),
            close_price=Decimal("68000.30"),
            volume=Decimal("12.34"),
            observed_at=FIXED_TIME,
            fetched_at=FIXED_TIME,
        )
        return MarketDetail(
            summary=market_summary(symbol),
            series=tuple(
                CandleSeries(timeframe=timeframe, candles=(candle,))
                for timeframe in timeframes
            ),
        )


class RateLimitedGateway(FakeMarketGateway):
    async def get_summaries(
        self,
        symbols: tuple[ContractSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        del symbols
        raise MarketDataUnavailableError(
            "market_data_rate_limited",
            "公开行情请求受到限流",
        )


async def get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_market_summary_returns_decimal_strings_and_utc_freshness() -> None:
    response = await get(
        create_app(market_gateway=FakeMarketGateway()),
        "/api/v1/markets?symbols=BTCUSDT&symbols=ETHUSDT",
    )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "symbol": "BTCUSDT",
            "price": "68000.30",
            "change24h": "1.25",
            "volume24h": "123456.789",
            "fundingRate": "0.00010000",
            "openInterest": "1234.5678",
            "freshness": {
                "status": "fresh",
                "source": "binance_usdm_public_rest",
                "observedAt": "2026-07-28T12:00:00Z",
                "fetchedAt": "2026-07-28T12:00:00Z",
            },
        },
        {
            "symbol": "ETHUSDT",
            "price": "68000.30",
            "change24h": "1.25",
            "volume24h": "123456.789",
            "fundingRate": "0.00010000",
            "openInterest": "1234.5678",
            "freshness": {
                "status": "fresh",
                "source": "binance_usdm_public_rest",
                "observedAt": "2026-07-28T12:00:00Z",
                "fetchedAt": "2026-07-28T12:00:00Z",
            },
        },
    ]


@pytest.mark.asyncio
async def test_market_detail_rejects_unknown_symbol_with_validation_envelope() -> None:
    response = await get(
        create_app(market_gateway=FakeMarketGateway()),
        "/api/v1/market/SOLUSDT?timeframes=15m",
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


@pytest.mark.asyncio
async def test_market_rate_limit_becomes_a_stable_503_envelope() -> None:
    response = await get(
        create_app(market_gateway=RateLimitedGateway()),
        "/api/v1/markets?symbols=BTCUSDT",
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "market_data_rate_limited",
        "message": "公开行情请求受到限流",
        "details": {},
    }
