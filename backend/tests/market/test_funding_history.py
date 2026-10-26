# 验证公开已结算资金费率的时间窗口、记录限额与精度。
# HTTP 替身返回边界样本，无效行、超大响应和越界来源均需拒绝。
# 取消信号原样传播，错误内容不能包含上游原始响应。
import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.market.binance_usdm import BINANCE_USDM_BASE_URL, BinanceUsdmPublicMarketGateway
from app.market.contracts import ContractSymbol, MarketDataUnavailableError

NOW = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
SINCE = NOW - timedelta(days=7)


async def no_sleep(_: float) -> None:
    return None


def _gateway(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[httpx.AsyncClient, BinanceUsdmPublicMarketGateway]:
    client = httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    return client, BinanceUsdmPublicMarketGateway(
        client=client,
        clock=lambda: NOW,
        sleep=no_sleep,
    )


@pytest.mark.asyncio
async def test_get_funding_history_reads_the_public_boundary_with_exact_decimals() -> None:
    requests: list[httpx.Request] = []
    first_time = SINCE + timedelta(hours=8)
    latest_time = NOW - timedelta(hours=8)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "BTCUSDT",
                    "fundingTime": int(first_time.timestamp() * 1000),
                    "fundingRate": "0.00010000",
                    "markPrice": "64000.0",
                },
                {
                    "symbol": "BTCUSDT",
                    "fundingTime": int(latest_time.timestamp() * 1000),
                    "fundingRate": "-0.0002",
                    "markPrice": "63000.0",
                },
            ],
        )

    client, gateway = _gateway(handler)
    async with client:
        history = await gateway.get_funding_history(
            ContractSymbol.BTCUSDT,
            since=SINCE,
            until=NOW,
        )

    assert history.symbol is ContractSymbol.BTCUSDT
    assert history.since == SINCE
    assert history.until == NOW
    assert history.fetched_at == NOW
    assert [point.funding_time for point in history.points] == [first_time, latest_time]
    assert history.points[0].funding_rate == Decimal("0.00010000")
    assert history.points[-1].funding_rate == Decimal("-0.0002")
    assert requests[0].url.path == "/fapi/v1/fundingRate"
    assert requests[0].url.params["symbol"] == "BTCUSDT"
    assert requests[0].url.params["startTime"] == str(int(SINCE.timestamp() * 1000))
    assert requests[0].url.params["endTime"] == str(int(NOW.timestamp() * 1000))
    assert requests[0].url.params["limit"] == "1000"
    assert requests[0].headers.get("X-MBX-APIKEY") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        [
            {
                "symbol": "ETHUSDT",
                "fundingTime": int(SINCE.timestamp() * 1000),
                "fundingRate": "0.1",
            }
        ],
        [
            {
                "symbol": "BTCUSDT",
                "fundingTime": int(SINCE.timestamp() * 1000),
                "fundingRate": 0.1,
            }
        ],
        [
            {
                "symbol": "BTCUSDT",
                "fundingTime": int(SINCE.timestamp() * 1000),
                "fundingRate": "NaN",
            }
        ],
        [
            {
                "symbol": "BTCUSDT",
                "fundingTime": int((SINCE + timedelta(hours=1)).timestamp() * 1000),
                "fundingRate": "0.1",
            },
            {
                "symbol": "BTCUSDT",
                "fundingTime": int(SINCE.timestamp() * 1000),
                "fundingRate": "0.2",
            },
        ],
        [
            {
                "symbol": "BTCUSDT",
                "fundingTime": int(SINCE.timestamp() * 1000),
                "fundingRate": "0.1",
            },
            {
                "symbol": "BTCUSDT",
                "fundingTime": int(SINCE.timestamp() * 1000),
                "fundingRate": "0.2",
            },
        ],
        [
            {
                "symbol": "BTCUSDT",
                "fundingTime": int(
                    (SINCE - timedelta(milliseconds=1)).timestamp() * 1000
                ),
                "fundingRate": "0.1",
            }
        ],
        [
            {
                "symbol": "BTCUSDT",
                "fundingTime": int((NOW + timedelta(milliseconds=1)).timestamp() * 1000),
                "fundingRate": "0.1",
            }
        ],
        [{"symbol": "BTCUSDT", "fundingTime": 10**30, "fundingRate": "0.1"}],
    ],
    ids=[
        "mismatched-symbol",
        "non-string-rate",
        "non-finite-rate",
        "unsorted-times",
        "duplicate-times",
        "before-window",
        "after-window",
        "unrepresentable-time",
    ],
)
async def test_get_funding_history_rejects_invalid_public_rows(payload: object) -> None:
    client, gateway = _gateway(lambda _: httpx.Response(200, json=payload))
    async with client:
        with pytest.raises(MarketDataUnavailableError) as error:
            await gateway.get_funding_history(
                ContractSymbol.BTCUSDT,
                since=SINCE,
                until=NOW,
            )

    assert error.value.code == "market_data_invalid_response"


@pytest.mark.asyncio
async def test_get_funding_history_rejects_empty_or_invalid_windows() -> None:
    client, gateway = _gateway(lambda _: httpx.Response(200, json=[]))
    async with client:
        with pytest.raises(MarketDataUnavailableError) as empty_error:
            await gateway.get_funding_history(
                ContractSymbol.BTCUSDT,
                since=SINCE,
                until=NOW,
            )
        with pytest.raises(MarketDataUnavailableError):
            await gateway.get_funding_history(
                ContractSymbol.BTCUSDT,
                since=SINCE.replace(tzinfo=None),
                until=NOW,
            )
        with pytest.raises(MarketDataUnavailableError):
            await gateway.get_funding_history(
                ContractSymbol.BTCUSDT,
                since=NOW,
                until=SINCE,
            )

    assert empty_error.value.code == "market_data_missing"


@pytest.mark.asyncio
async def test_get_funding_history_rejects_more_than_the_public_record_limit() -> None:
    payload = [
        {
            "symbol": "BTCUSDT",
            "fundingTime": int((SINCE + timedelta(milliseconds=index)).timestamp() * 1000),
            "fundingRate": "0.0001",
        }
        for index in range(1001)
    ]
    client, gateway = _gateway(lambda _: httpx.Response(200, json=payload))
    async with client:
        with pytest.raises(MarketDataUnavailableError) as error:
            await gateway.get_funding_history(
                ContractSymbol.BTCUSDT,
                since=SINCE,
                until=NOW,
            )

    assert error.value.code == "market_data_invalid_response"


@pytest.mark.asyncio
async def test_get_funding_history_rejects_a_large_json_body_before_parsing() -> None:
    payload = [
        {
            "symbol": "BTCUSDT",
            "fundingTime": int(SINCE.timestamp() * 1000),
            "fundingRate": "0.0001",
            "ignoredPadding": "x" * 1_500_000,
        }
    ]
    client, gateway = _gateway(lambda _: httpx.Response(200, json=payload))
    async with client:
        with pytest.raises(MarketDataUnavailableError) as error:
            await gateway.get_funding_history(
                ContractSymbol.BTCUSDT,
                since=SINCE,
                until=NOW,
            )

    assert error.value.code == "market_data_response_too_large"


@pytest.mark.asyncio
async def test_funding_gateway_rejects_a_nondefault_binance_port() -> None:
    async with httpx.AsyncClient(
        base_url="https://fapi.binance.com:444",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[])),
    ) as client:
        with pytest.raises(ValueError, match="固定 Binance"):
            BinanceUsdmPublicMarketGateway(
                client=client,
                clock=lambda: NOW,
                sleep=no_sleep,
            )


@pytest.mark.asyncio
async def test_get_funding_history_never_follows_redirects_outside_binance() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "fapi.binance.com":
            return httpx.Response(
                302,
                headers={"Location": "https://example.com/funding"},
                content=b"x" * 1_000_001,
            )
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "BTCUSDT",
                    "fundingTime": int(SINCE.timestamp() * 1000),
                    "fundingRate": "0.0001",
                }
            ],
        )

    client = httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        follow_redirects=True,
        transport=httpx.MockTransport(handler),
    )
    gateway = BinanceUsdmPublicMarketGateway(
        client=client,
        clock=lambda: NOW,
        sleep=no_sleep,
    )
    async with client:
        with pytest.raises(MarketDataUnavailableError) as error:
            await gateway.get_funding_history(
                ContractSymbol.BTCUSDT,
                since=SINCE,
                until=NOW,
            )

    assert error.value.code == "market_data_upstream_rejected"
    assert [request.url.host for request in requests] == ["fapi.binance.com"]


@pytest.mark.asyncio
async def test_get_funding_history_propagates_cancellation() -> None:
    def cancelled(_: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    client, gateway = _gateway(cancelled)
    async with client:
        with pytest.raises(asyncio.CancelledError):
            await gateway.get_funding_history(
                ContractSymbol.BTCUSDT,
                since=SINCE,
                until=NOW,
            )
