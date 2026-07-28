from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.market.binance_usdm import (
    BINANCE_USDM_BASE_URL,
    BinanceUsdmPublicMarketGateway,
)
from app.market.contracts import (
    ContractSymbol,
    MarketDataUnavailableError,
    MarketTimeframe,
)

FIXED_NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


async def no_sleep(_: float) -> None:
    return None


def fixture_handler(requests: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    now_ms = int(FIXED_NOW.timestamp() * 1000)
    previous_open_ms = int((FIXED_NOW - timedelta(minutes=30)).timestamp() * 1000)
    previous_close_ms = int((FIXED_NOW - timedelta(minutes=15, milliseconds=1)).timestamp() * 1000)
    current_open_ms = int((FIXED_NOW - timedelta(minutes=15)).timestamp() * 1000)
    current_close_ms = int((FIXED_NOW + timedelta(minutes=1)).timestamp() * 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        symbol = request.url.params["symbol"]
        if request.url.path == "/fapi/v1/ticker/24hr":
            return httpx.Response(
                200,
                json={
                    "symbol": symbol,
                    "lastPrice": "68000.30",
                    "priceChangePercent": "1.25",
                    "quoteVolume": "123456.789",
                    "closeTime": now_ms,
                },
            )
        if request.url.path == "/fapi/v1/premiumIndex":
            return httpx.Response(
                200,
                json={
                    "symbol": symbol,
                    "lastFundingRate": "0.00010000",
                    "time": now_ms,
                },
            )
        if request.url.path == "/fapi/v1/openInterest":
            return httpx.Response(
                200,
                json={
                    "symbol": symbol,
                    "openInterest": "1234.5678",
                    "time": now_ms,
                },
            )
        if request.url.path == "/fapi/v1/klines":
            return httpx.Response(
                200,
                json=[
                    [
                        previous_open_ms,
                        "68000.10",
                        "68001.20",
                        "67999.90",
                        "68000.30",
                        "12.34",
                        previous_close_ms,
                    ],
                    [
                        current_open_ms,
                        "68000.30",
                        "68002.00",
                        "68000.00",
                        "68001.00",
                        "4.56",
                        current_close_ms,
                    ],
                ],
            )
        return httpx.Response(404, json={"message": "unexpected path"})

    return handler


@pytest.mark.asyncio
async def test_gateway_uses_only_allowlisted_public_paths_and_normalizes_decimals() -> None:
    requests: list[httpx.Request] = []
    async with httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        transport=httpx.MockTransport(fixture_handler(requests)),
    ) as client:
        gateway = BinanceUsdmPublicMarketGateway(
            client=client,
            clock=lambda: FIXED_NOW,
            sleep=no_sleep,
        )

        detail = await gateway.get_market(
            ContractSymbol.BTCUSDT,
            (MarketTimeframe.M15,),
        )

    assert detail.summary.price == Decimal("68000.30")
    assert detail.summary.funding_rate == Decimal("0.00010000")
    assert detail.series[0].candles[0].close_price == Decimal("68000.30")
    assert len(detail.series[0].candles) == 1
    assert {request.url.path for request in requests} == {
        "/fapi/v1/ticker/24hr",
        "/fapi/v1/premiumIndex",
        "/fapi/v1/openInterest",
        "/fapi/v1/klines",
    }
    assert all(request.headers.get("X-MBX-APIKEY") is None for request in requests)


@pytest.mark.asyncio
async def test_gateway_maps_rate_limits_to_a_stable_unavailable_error() -> None:
    async def no_wait(_: float) -> None:
        return None

    async with httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(429, headers={"Retry-After": "1"}),
        ),
    ) as client:
        gateway = BinanceUsdmPublicMarketGateway(
            client=client,
            clock=lambda: FIXED_NOW,
            sleep=no_wait,
        )

        with pytest.raises(MarketDataUnavailableError) as error:
            await gateway.get_summaries((ContractSymbol.BTCUSDT,))

    assert error.value.code == "market_data_rate_limited"
