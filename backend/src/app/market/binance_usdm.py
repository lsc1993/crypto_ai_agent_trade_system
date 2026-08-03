from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast

import httpx

from app.market.cache import AsyncTtlCache
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

BINANCE_USDM_BASE_URL = "https://fapi.binance.com"
SOURCE_NAME = "binance_usdm_public_rest"
ALLOWED_PATHS = frozenset(
    {
        "/fapi/v1/ticker/24hr",
        "/fapi/v1/klines",
        "/fapi/v1/openInterest",
        "/fapi/v1/premiumIndex",
    },
)
SUMMARY_TTL = timedelta(seconds=10)
CANDLE_TTL = timedelta(seconds=60)
MAX_ATTEMPTS = 2
MAX_BACKTEST_CANDLES = 1049

Sleep = Callable[[float], Awaitable[None]]


class BinanceUsdmPublicMarketGateway:
    """Binance USDⓈ-M 公共 REST 的唯一只读边界。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        clock: Callable[[], datetime],
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        base_url = client.base_url
        if (
            base_url.scheme != "https"
            or base_url.host != "fapi.binance.com"
            or base_url.path not in {"", "/"}
        ):
            raise ValueError("公共市场数据客户端必须使用固定 Binance USDⓈ-M 地址")
        self._client = client
        self._clock = clock
        self._sleep = sleep
        self._summary_cache: AsyncTtlCache[MarketSummary] = AsyncTtlCache(clock)
        self._candle_cache: AsyncTtlCache[CandleSeries] = AsyncTtlCache(clock)

    async def get_summaries(
        self,
        symbols: tuple[ContractSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        summaries = await asyncio.gather(
            *(self._get_summary(symbol) for symbol in symbols),
        )
        return tuple(summaries)

    async def get_market(
        self,
        symbol: ContractSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        summary = await self._get_summary(symbol)
        series = await asyncio.gather(
            *(self._get_candles(symbol, timeframe) for timeframe in timeframes),
        )
        return MarketDetail(summary=summary, series=tuple(series))

    async def load_closed_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[Candle, ...]:
        if timeframe is not MarketTimeframe.H1:
            raise ValueError("历史回测仅支持 1h K 线")
        _validate_utc_range(start_at, end_at)
        payload = await self._get_public_json(
            "/fapi/v1/klines",
            {
                "symbol": symbol.value,
                "interval": timeframe.value,
                "startTime": str(int(start_at.timestamp() * 1000)),
                "endTime": str(int(end_at.timestamp() * 1000)),
                "limit": str(MAX_BACKTEST_CANDLES),
            },
        )
        candles = _closed_candles_from_payload(
            payload,
            symbol=symbol,
            timeframe=timeframe,
            fetched_at=self._now(),
        )
        open_times = tuple(candle.open_at for candle in candles)
        if len(open_times) != len(set(open_times)):
            raise MarketDataUnavailableError(
                "market_data_invalid_response",
                "公开 K 线响应包含重复时间",
            )
        requested_candles = tuple(
            candle for candle in candles if start_at <= candle.open_at < end_at
        )
        if not requested_candles:
            raise MarketDataUnavailableError(
                "market_data_missing",
                "公开行情未提供请求范围内的已收盘 K 线",
            )
        return requested_candles

    async def _get_summary(self, symbol: ContractSymbol) -> MarketSummary:
        return await self._summary_cache.get_or_load(
            f"summary:{symbol.value}",
            lambda: self._fetch_summary(symbol),
            SUMMARY_TTL,
        )

    async def _fetch_summary(self, symbol: ContractSymbol) -> MarketSummary:
        ticker, premium, open_interest = await asyncio.gather(
            self._get_public_json("/fapi/v1/ticker/24hr", {"symbol": symbol.value}),
            self._get_public_json("/fapi/v1/premiumIndex", {"symbol": symbol.value}),
            self._get_public_json("/fapi/v1/openInterest", {"symbol": symbol.value}),
        )
        ticker_payload = _mapping_payload(ticker)
        premium_payload = _mapping_payload(premium)
        interest_payload = _mapping_payload(open_interest)
        fetched_at = self._now()
        observed_at = min(
            _timestamp(ticker_payload, "closeTime"),
            _timestamp(premium_payload, "time"),
            _timestamp(interest_payload, "time"),
        )
        return MarketSummary(
            symbol=symbol,
            price=_decimal(ticker_payload, "lastPrice"),
            change_24h=_decimal(ticker_payload, "priceChangePercent"),
            volume_24h=_decimal(ticker_payload, "quoteVolume"),
            funding_rate=_decimal(premium_payload, "lastFundingRate"),
            open_interest=_decimal(interest_payload, "openInterest"),
            freshness=DataFreshness(
                status=FreshnessStatus.FRESH,
                source=SOURCE_NAME,
                observed_at=observed_at,
                fetched_at=fetched_at,
            ),
        )

    async def _get_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
    ) -> CandleSeries:
        return await self._candle_cache.get_or_load(
            f"candles:{symbol.value}:{timeframe.value}",
            lambda: self._fetch_candles(symbol, timeframe),
            CANDLE_TTL,
        )

    async def _fetch_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
    ) -> CandleSeries:
        payload = await self._get_public_json(
            "/fapi/v1/klines",
            {"symbol": symbol.value, "interval": timeframe.value, "limit": "200"},
        )
        candles = _closed_candles_from_payload(
            payload,
            symbol=symbol,
            timeframe=timeframe,
            fetched_at=self._now(),
        )
        return CandleSeries(
            timeframe=timeframe,
            candles=candles,
        )

    async def _get_public_json(self, path: str, params: dict[str, str]) -> object:
        if path not in ALLOWED_PATHS:
            raise ValueError("公开市场数据路径不在允许列表中")

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await self._client.get(path, params=params, timeout=5.0)
            except httpx.TimeoutException as error:
                if attempt + 1 == MAX_ATTEMPTS:
                    raise MarketDataUnavailableError(
                        "market_data_timeout",
                        "公开行情请求超时",
                    ) from error
                await self._sleep(0)
                continue
            except httpx.HTTPError as error:
                if attempt + 1 == MAX_ATTEMPTS:
                    raise MarketDataUnavailableError(
                        "market_data_unavailable",
                        "公开行情服务不可用",
                    ) from error
                await self._sleep(0)
                continue

            if response.status_code == 429:
                if attempt + 1 == MAX_ATTEMPTS:
                    raise MarketDataUnavailableError(
                        "market_data_rate_limited",
                        "公开行情请求受到限流",
                    )
                await self._sleep(_retry_after(response))
                continue
            if response.status_code >= 500:
                if attempt + 1 == MAX_ATTEMPTS:
                    raise MarketDataUnavailableError(
                        "market_data_unavailable",
                        "公开行情服务不可用",
                    )
                await self._sleep(0)
                continue
            if response.status_code >= 400:
                raise MarketDataUnavailableError(
                    "market_data_upstream_rejected",
                    "公开行情请求被上游拒绝",
                )
            try:
                return cast(object, response.json())
            except ValueError as error:
                raise MarketDataUnavailableError(
                    "market_data_invalid_response",
                    "公开行情响应不是有效 JSON",
                ) from error

        raise AssertionError("公开市场数据重试流程未返回结果")

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("市场数据时钟必须返回 UTC 带时区时间")
        return now


def _validate_utc_range(start_at: datetime, end_at: datetime) -> None:
    for value in (start_at, end_at):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("历史 K 线范围必须使用 UTC 带时区时间")
    if start_at >= end_at:
        raise ValueError("历史 K 线开始时间必须早于结束时间")


def _closed_candles_from_payload(
    payload: object,
    *,
    symbol: ContractSymbol,
    timeframe: MarketTimeframe,
    fetched_at: datetime,
) -> tuple[Candle, ...]:
    rows = _list_payload(payload)
    candles: list[Candle] = []
    for row in rows:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
            raise MarketDataUnavailableError(
                "market_data_invalid_response",
                "公开 K 线响应包含无效记录",
            )
        values = cast(Sequence[object], row)
        if len(values) < 7:
            raise MarketDataUnavailableError(
                "market_data_invalid_response",
                "公开 K 线响应包含无效记录",
            )
        open_at = _timestamp_value(values[0])
        close_at = _timestamp_value(values[6])
        if close_at > fetched_at:
            continue
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_at=open_at,
                close_at=close_at,
                open_price=_decimal_value(values[1]),
                high_price=_decimal_value(values[2]),
                low_price=_decimal_value(values[3]),
                close_price=_decimal_value(values[4]),
                volume=_decimal_value(values[5]),
                observed_at=close_at,
                fetched_at=fetched_at,
            )
        )
    if not candles:
        raise MarketDataUnavailableError(
            "market_data_missing",
            "公开行情未提供已收盘 K 线",
        )
    return tuple(sorted(candles, key=lambda candle: candle.open_at))


def _mapping_payload(payload: object) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "公开行情响应格式无效",
        )
    return cast(Mapping[str, object], payload)


def _list_payload(payload: object) -> list[object]:
    if not isinstance(payload, list):
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "公开 K 线响应格式无效",
        )
    return cast(list[object], payload)


def _decimal(payload: Mapping[str, object], field: str) -> Decimal:
    return _decimal_value(payload.get(field))


def _decimal_value(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str):
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "公开行情数值字段无效",
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "公开行情数值字段无效",
        ) from error
    if not parsed.is_finite():
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "公开行情数值字段无效",
        )
    return parsed


def _timestamp(payload: Mapping[str, object], field: str) -> datetime:
    return _timestamp_value(payload.get(field))


def _timestamp_value(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "公开行情时间字段无效",
        )
    seconds, milliseconds = divmod(value, 1000)
    return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(milliseconds=milliseconds)


def _retry_after(response: httpx.Response) -> float:
    header = response.headers.get("Retry-After")
    if header is None:
        return 0.0
    try:
        seconds = Decimal(header)
    except InvalidOperation:
        return 0.0
    if not seconds.is_finite() or seconds < 0:
        return 0.0
    return float(seconds)
