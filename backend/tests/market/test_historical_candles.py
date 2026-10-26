# 验证回测历史 K 线的时间范围和小时周期契约。
# 构造未收盘、重复或区间外行情，确保只返回指定窗口内闭合记录。
# 交易所包含式收盘时间需归一化为连续边界，避免误判缺失小时。
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

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

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
START = NOW - timedelta(hours=3)
END = NOW + timedelta(hours=1)


async def no_sleep(_: float) -> None:
    return None


def _handler(requests: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path != "/fapi/v1/klines":
            return httpx.Response(404, json={"message": "unexpected path"})
        return httpx.Response(
            200,
            json=tuple(_kline_row(NOW - timedelta(hours=offset)) for offset in (3, 2, 1, 0)),
        )

    return handler


@pytest.mark.asyncio
async def test_load_closed_candles_uses_range_and_excludes_open_candle() -> None:
    requests: list[httpx.Request] = []
    async with httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        transport=httpx.MockTransport(_handler(requests)),
    ) as client:
        gateway = BinanceUsdmPublicMarketGateway(
            client=client,
            clock=lambda: NOW,
            sleep=no_sleep,
        )

        candles = await gateway.load_closed_candles(
            ContractSymbol.BTCUSDT,
            MarketTimeframe.H1,
            start_at=START,
            end_at=END,
        )

    assert [candle.open_at for candle in candles] == [
        NOW - timedelta(hours=3),
        NOW - timedelta(hours=2),
        NOW - timedelta(hours=1),
    ]
    assert requests[0].url.params["symbol"] == "BTCUSDT"
    assert requests[0].url.params["interval"] == "1h"
    assert requests[0].url.params["startTime"] == str(int(START.timestamp() * 1000))
    assert requests[0].url.params["endTime"] == str(int(END.timestamp() * 1000))
    assert all(candle.close_at <= NOW for candle in candles)


@pytest.mark.asyncio
async def test_load_closed_candles_normalizes_binance_inclusive_close_time() -> None:
    async with httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        transport=httpx.MockTransport(_handler([])),
    ) as client:
        gateway = BinanceUsdmPublicMarketGateway(
            client=client,
            clock=lambda: NOW,
            sleep=no_sleep,
        )

        candles = await gateway.load_closed_candles(
            ContractSymbol.BTCUSDT,
            MarketTimeframe.H1,
            start_at=START,
            end_at=END,
        )

    assert candles[-1].close_at == NOW


@pytest.mark.asyncio
async def test_load_closed_candles_rejects_a_non_h1_timeframe() -> None:
    async with httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        transport=httpx.MockTransport(_handler([])),
    ) as client:
        gateway = BinanceUsdmPublicMarketGateway(
            client=client,
            clock=lambda: NOW,
            sleep=no_sleep,
        )

        with pytest.raises(ValueError, match="1h"):
            await gateway.load_closed_candles(
                ContractSymbol.BTCUSDT,
                MarketTimeframe.H4,
                start_at=START,
                end_at=END,
            )


@pytest.mark.asyncio
async def test_load_closed_candles_rejects_non_utc_or_reversed_ranges() -> None:
    async with httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        transport=httpx.MockTransport(_handler([])),
    ) as client:
        gateway = BinanceUsdmPublicMarketGateway(
            client=client,
            clock=lambda: NOW,
            sleep=no_sleep,
        )

        with pytest.raises(ValueError, match="UTC"):
            await gateway.load_closed_candles(
                ContractSymbol.BTCUSDT,
                MarketTimeframe.H1,
                start_at=START.replace(tzinfo=None),
                end_at=END,
            )
        with pytest.raises(ValueError, match="开始时间"):
            await gateway.load_closed_candles(
                ContractSymbol.BTCUSDT,
                MarketTimeframe.H1,
                start_at=END,
                end_at=START,
            )


@pytest.mark.asyncio
async def test_load_closed_candles_uses_the_bounded_backtest_limit() -> None:
    requests: list[httpx.Request] = []
    async with httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        transport=httpx.MockTransport(_handler(requests)),
    ) as client:
        gateway = BinanceUsdmPublicMarketGateway(
            client=client,
            clock=lambda: NOW,
            sleep=no_sleep,
        )

        await gateway.load_closed_candles(
            ContractSymbol.BTCUSDT,
            MarketTimeframe.H1,
            start_at=START,
            end_at=END,
        )

    assert requests[0].url.params["limit"] == "1049"


@pytest.mark.asyncio
async def test_load_closed_candles_rejects_duplicate_open_times() -> None:
    def duplicate_handler(_: httpx.Request) -> httpx.Response:
        row = _kline_row(NOW - timedelta(hours=1))
        return httpx.Response(200, json=[row, row])

    async with httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        transport=httpx.MockTransport(duplicate_handler),
    ) as client:
        gateway = BinanceUsdmPublicMarketGateway(
            client=client,
            clock=lambda: NOW,
            sleep=no_sleep,
        )

        with pytest.raises(MarketDataUnavailableError) as error:
            await gateway.load_closed_candles(
                ContractSymbol.BTCUSDT,
                MarketTimeframe.H1,
                start_at=START,
                end_at=END,
            )

    assert error.value.code == "market_data_invalid_response"


@pytest.mark.asyncio
async def test_load_closed_candles_filters_rows_outside_the_requested_range() -> None:
    range_end = NOW

    def out_of_range_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                _kline_row(START - timedelta(hours=1)),
                _kline_row(START),
                _kline_row(range_end - timedelta(hours=1)),
            ],
        )

    async with httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        transport=httpx.MockTransport(out_of_range_handler),
    ) as client:
        gateway = BinanceUsdmPublicMarketGateway(
            client=client,
            clock=lambda: NOW,
            sleep=no_sleep,
        )

        candles = await gateway.load_closed_candles(
            ContractSymbol.BTCUSDT,
            MarketTimeframe.H1,
            start_at=START,
            end_at=range_end,
        )

    assert [candle.open_at for candle in candles] == [START, range_end - timedelta(hours=1)]


@pytest.mark.asyncio
async def test_load_closed_candles_rejects_a_response_without_requested_rows() -> None:
    def out_of_range_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_kline_row(START - timedelta(hours=1))])

    async with httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        transport=httpx.MockTransport(out_of_range_handler),
    ) as client:
        gateway = BinanceUsdmPublicMarketGateway(
            client=client,
            clock=lambda: NOW,
            sleep=no_sleep,
        )

        with pytest.raises(MarketDataUnavailableError) as error:
            await gateway.load_closed_candles(
                ContractSymbol.BTCUSDT,
                MarketTimeframe.H1,
                start_at=START,
                end_at=NOW,
            )

    assert error.value.code == "market_data_missing"


def _kline_row(open_at: datetime) -> list[object]:
    close_at = open_at + timedelta(hours=1) - timedelta(milliseconds=1)
    return [
        int(open_at.timestamp() * 1000),
        "68000.10",
        "68001.20",
        "67999.90",
        "68000.30",
        "12.34",
        int(close_at.timestamp() * 1000),
    ]
