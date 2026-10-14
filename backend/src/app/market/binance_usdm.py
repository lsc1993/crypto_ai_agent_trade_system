"""Binance USDⓈ-M 公共市场数据适配器。

数据流：受限的公开 REST 路径 → 严格 JSON/Decimal/UTC 校验 → 短 TTL 缓存的行情摘要
与已收盘 K 线。适配器不接受凭证，不访问账户、订单或资金相关端点。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast

import httpx

from app.market.cache import AsyncTtlCache
from app.market.contracts import (
    Candle,
    CandleSeries,
    DataFreshness,
    FreshnessStatus,
    MarketDataUnavailableError,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.funding_history import FundingHistory, FundingPoint
from app.market.symbols import ResearchSymbol

BINANCE_USDM_BASE_URL = "https://fapi.binance.com"
SOURCE_NAME = "binance_usdm_public_rest"
ALLOWED_PATHS = frozenset(
    # 适配器只能调用这些公开只读端点；没有账户、订单或资金相关路径。
    {
        "/fapi/v1/ticker/24hr",
        "/fapi/v1/exchangeInfo",
        "/fapi/v1/klines",
        "/fapi/v1/openInterest",
        "/fapi/v1/premiumIndex",
        "/fapi/v1/fundingRate",
        "/futures/data/basis",
        "/futures/data/globalLongShortAccountRatio",
        "/futures/data/takerlongshortRatio",
    },
)
SUMMARY_TTL = timedelta(seconds=10)
CANDLE_TTL = timedelta(seconds=60)
EXCHANGE_INFO_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 2
MAX_BACKTEST_CANDLES = 1049
MAX_PUBLIC_JSON_BYTES = 1_500_000
MAX_FUNDING_POINTS = 1000

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class PublicDerivativesMetrics:
    """来自三个公开衍生品端点、且以同一读取时刻封装的研究指标。"""
    basis_rate: Decimal
    long_short_account_ratio: Decimal
    taker_buy_sell_ratio: Decimal
    observed_at: datetime
    fetched_at: datetime


class BinanceUsdmPublicMarketGateway:
    """Binance USDⓈ-M 公共 REST 的唯一只读边界。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        clock: Callable[[], datetime],
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        # 强制 HTTPS 固定主机，避免调用方通过自定义 httpx client 绕过公开行情边界。
        base_url = client.base_url
        if (
            base_url.scheme != "https"
            or base_url.host != "fapi.binance.com"
            or base_url.port not in {None, 443}
            or base_url.path not in {"", "/"}
        ):
            raise ValueError("公共市场数据客户端必须使用固定 Binance USDⓈ-M 地址")
        self._client = client
        self._clock = clock
        self._sleep = sleep
        self._summary_cache: AsyncTtlCache[MarketSummary] = AsyncTtlCache(clock)
        self._candle_cache: AsyncTtlCache[CandleSeries] = AsyncTtlCache(clock)
        self._exchange_info_cache: AsyncTtlCache[dict[str, str] | None] = AsyncTtlCache(clock)

    async def get_exchange_info(self, symbol: str) -> dict[str, str] | None:
        """Read only contract metadata used to admit an eligible research symbol."""
        return await self._exchange_info_cache.get_or_load(
            f"exchange-info:{symbol}",
            lambda: self._fetch_exchange_info(symbol),
            EXCHANGE_INFO_TTL,
        )

    async def _fetch_exchange_info(self, symbol: str) -> dict[str, str] | None:
        payload = _mapping_payload(await self._get_public_json("/fapi/v1/exchangeInfo", {}))
        rows = payload.get("symbols")
        if not isinstance(rows, list):
            raise MarketDataUnavailableError("market_data_invalid_response", "公开合约信息响应无效")
        rows = cast(list[object], rows)
        matches: list[Mapping[str, object]] = []
        for candidate in rows:
            if not isinstance(candidate, Mapping):
                continue
            row = cast(Mapping[str, object], candidate)
            if row.get("symbol") == symbol:
                matches.append(row)
        if len(matches) > 1:
            raise MarketDataUnavailableError(
                "market_data_invalid_response",
                "公开合约信息包含重复标的",
            )
        if not matches:
            return None
        row = matches[0]
        values: dict[str, str] = {}
        for field in ("symbol", "baseAsset", "quoteAsset", "marginAsset", "contractType", "status"):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                raise MarketDataUnavailableError(
                    "market_data_invalid_response",
                    "公开合约信息字段无效",
                )
            values[field] = value.strip()
        return values

    async def get_summaries(
        self,
        symbols: tuple[ResearchSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        """并发获取多个白名单标的的缓存行情摘要。"""
        summaries = await asyncio.gather(
            *(self._get_summary(symbol) for symbol in symbols),
        )
        return tuple(summaries)

    async def get_market(
        self,
        symbol: ResearchSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        """获取一个标的的摘要与指定周期 K 线，并由各缓存独立控制新鲜度。"""
        summary = await self._get_summary(symbol)
        series = await asyncio.gather(
            *(self._get_candles(symbol, timeframe) for timeframe in timeframes),
        )
        return MarketDetail(summary=summary, series=tuple(series))

    async def get_research_metrics(
        self,
        symbol: ResearchSymbol,
    ) -> PublicDerivativesMetrics:
        """读取基差、多空账户比与主动买卖比，并以最早观测时间标识数据截止点。"""
        # 三个互不依赖的公开衍生品指标并发读取，最终按最早观测时间标记数据截止点。
        basis, long_short, taker = await asyncio.gather(
            self._get_public_json(
                "/futures/data/basis",
                {"pair": symbol, "contractType": "PERPETUAL", "period": "1h", "limit": "1"},
            ),
            self._get_public_json(
                "/futures/data/globalLongShortAccountRatio",
                {"symbol": symbol, "period": "1h", "limit": "1"},
            ),
            self._get_public_json(
                "/futures/data/takerlongshortRatio",
                {"symbol": symbol, "period": "1h", "limit": "1"},
            ),
        )
        basis_payload = _latest_metric_payload(basis)
        long_short_payload = _latest_metric_payload(long_short)
        taker_payload = _latest_metric_payload(taker)
        fetched_at = self._now()
        return PublicDerivativesMetrics(
            basis_rate=_decimal(basis_payload, "basisRate"),
            long_short_account_ratio=_decimal(long_short_payload, "longShortRatio"),
            taker_buy_sell_ratio=_decimal(taker_payload, "buySellRatio"),
            observed_at=min(
                _timestamp(basis_payload, "timestamp"),
                _timestamp(long_short_payload, "timestamp"),
                _timestamp(taker_payload, "timestamp"),
            ),
            fetched_at=fetched_at,
        )

    async def get_funding_history(
        self,
        symbol: ResearchSymbol,
        *,
        since: datetime,
        until: datetime,
    ) -> FundingHistory:
        """读取指定 UTC 窗口内的已结算资金费率。"""
        _validate_funding_range(since, until)
        payload = await self._get_public_json(
            "/fapi/v1/fundingRate",
            {
                "symbol": symbol,
                "startTime": str(int(since.timestamp() * 1000)),
                "endTime": str(int(until.timestamp() * 1000)),
                "limit": "1000",
            },
        )
        fetched_at = self._now()
        rows = _list_payload(payload)
        if len(rows) > MAX_FUNDING_POINTS:
            raise MarketDataUnavailableError(
                "market_data_invalid_response",
                "公开资金费率响应超过记录上限",
            )
        if not rows:
            raise MarketDataUnavailableError(
                "market_data_missing",
                "公开行情未提供请求范围内的资金费率",
            )
        points: list[FundingPoint] = []
        response_times: list[datetime] = []
        for raw_row in rows:
            row = _mapping_payload(raw_row)
            if row.get("symbol") != symbol:
                raise MarketDataUnavailableError(
                    "market_data_invalid_response",
                    "公开资金费率响应标的无效",
                )
            funding_time = _timestamp(row, "fundingTime")
            funding_rate = _decimal(row, "fundingRate")
            response_times.append(funding_time)
            if funding_time < since or funding_time > until or funding_time > fetched_at:
                raise MarketDataUnavailableError(
                    "market_data_invalid_response",
                    "公开资金费率响应包含窗口外时间",
                )
            points.append(
                FundingPoint(
                    funding_time=funding_time,
                    funding_rate=funding_rate,
                )
            )
        if response_times != sorted(response_times) or len(response_times) != len(
            set(response_times)
        ):
            raise MarketDataUnavailableError(
                "market_data_invalid_response",
                "公开资金费率响应时间无序或重复",
            )
        return FundingHistory(
            symbol=symbol,
            since=since,
            until=until,
            fetched_at=fetched_at,
            points=tuple(points),
        )

    async def load_closed_candles(
        self,
        symbol: ResearchSymbol,
        timeframe: MarketTimeframe,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[Candle, ...]:
        """为回测加载指定 UTC 区间内连续的已收盘 1h K 线。

        网关响应会先过滤尚未收盘行，再按请求区间裁剪；缺失、重复或不支持周期均
        转为稳定的 MarketDataUnavailableError。
        """
        if timeframe is not MarketTimeframe.H1:
            raise ValueError("历史回测仅支持 1h K 线")
        _validate_utc_range(start_at, end_at)
        payload = await self._get_public_json(
            "/fapi/v1/klines",
            {
                "symbol": symbol,
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
        # API 的 endTime 语义并不等同于闭区间；再按开盘时刻裁剪，确保请求范围可复现。
        requested_candles = tuple(
            candle for candle in candles if start_at <= candle.open_at < end_at
        )
        if not requested_candles:
            raise MarketDataUnavailableError(
                "market_data_missing",
                "公开行情未提供请求范围内的已收盘 K 线",
            )
        return requested_candles

    async def _get_summary(self, symbol: ResearchSymbol) -> MarketSummary:
        """通过摘要缓存读取一个标的，缓存未命中时调用 _fetch_summary。"""
        return await self._summary_cache.get_or_load(
            f"summary:{symbol}",
            lambda: self._fetch_summary(symbol),
            SUMMARY_TTL,
        )

    async def _fetch_summary(self, symbol: ResearchSymbol) -> MarketSummary:
        """并发读取 ticker、资金费率和未平仓量，并组装为带来源时间的摘要。"""
        ticker, premium, open_interest = await asyncio.gather(
            self._get_public_json("/fapi/v1/ticker/24hr", {"symbol": symbol}),
            self._get_public_json("/fapi/v1/premiumIndex", {"symbol": symbol}),
            self._get_public_json("/fapi/v1/openInterest", {"symbol": symbol}),
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
        symbol: ResearchSymbol,
        timeframe: MarketTimeframe,
    ) -> CandleSeries:
        """通过周期缓存读取 K 线序列，避免页面轮询频繁访问上游。"""
        return await self._candle_cache.get_or_load(
            f"candles:{symbol}:{timeframe.value}",
            lambda: self._fetch_candles(symbol, timeframe),
            CANDLE_TTL,
        )

    async def _fetch_candles(
        self,
        symbol: ResearchSymbol,
        timeframe: MarketTimeframe,
    ) -> CandleSeries:
        """请求最多 200 根 K 线，并只保留采集时已经结束的行。"""
        payload = await self._get_public_json(
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": timeframe.value, "limit": "200"},
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
        """访问白名单公开端点并将网络、限流、状态码和 JSON 异常映射为稳定错误码。"""
        # 路径校验在发请求前执行，即使此方法被未来调用点复用也不能越过白名单。
        if path not in ALLOWED_PATHS:
            raise ValueError("公开市场数据路径不在允许列表中")

        for attempt in range(MAX_ATTEMPTS):
            try:
                async with self._client.stream(
                    "GET",
                    path,
                    params=params,
                    timeout=5.0,
                    follow_redirects=False,
                ) as response:
                    _validate_public_response_boundary(response, path)
                    status_code = response.status_code
                    retry_after = _retry_after(response)
                    response_body = (
                        await _read_bounded_body(response)
                        if status_code < 300
                        else b""
                    )
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

            # 限流与短暂上游故障允许有限重试；客户端错误和非 JSON 响应直接失败并使用稳定错误码。
            if status_code == 429:
                if attempt + 1 == MAX_ATTEMPTS:
                    raise MarketDataUnavailableError(
                        "market_data_rate_limited",
                        "公开行情请求受到限流",
                    )
                await self._sleep(retry_after)
                continue
            if status_code >= 500:
                if attempt + 1 == MAX_ATTEMPTS:
                    raise MarketDataUnavailableError(
                        "market_data_unavailable",
                        "公开行情服务不可用",
                    )
                await self._sleep(0)
                continue
            if status_code >= 400:
                raise MarketDataUnavailableError(
                    "market_data_upstream_rejected",
                    "公开行情请求被上游拒绝",
                )
            if status_code >= 300:
                raise MarketDataUnavailableError(
                    "market_data_upstream_rejected",
                    "公开行情请求被上游重定向",
                )
            try:
                return cast(object, json.loads(response_body))
            except (UnicodeDecodeError, ValueError) as error:
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
    """验证历史 K 线的半开时间区间使用 UTC 且起点早于终点。"""
    for value in (start_at, end_at):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("历史 K 线范围必须使用 UTC 带时区时间")
    if start_at >= end_at:
        raise ValueError("历史 K 线开始时间必须早于结束时间")


def _validate_funding_range(since: datetime, until: datetime) -> None:
    for value in (since, until):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise MarketDataUnavailableError(
                "market_data_invalid_request",
                "资金费率历史范围必须使用 UTC 带时区时间",
            )
    if since >= until:
        raise MarketDataUnavailableError(
            "market_data_invalid_request",
            "资金费率历史开始时间必须早于结束时间",
        )


def _closed_candles_from_payload(
    payload: object,
    *,
    symbol: ResearchSymbol,
    timeframe: MarketTimeframe,
    fetched_at: datetime,
) -> tuple[Candle, ...]:
    """校验 Binance K 线数组并转换成统一的 Candle 模型，只返回已收盘记录。"""
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
        inclusive_close_at = _timestamp_value(values[6])
        # Binance 的 closeTime 是闭区间末毫秒；尚未结束的 K 线不会进入研究、回测或策略输入。
        if inclusive_close_at > fetched_at:
            continue
        close_at = inclusive_close_at + timedelta(milliseconds=1)
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


def _latest_metric_payload(payload: object) -> Mapping[str, object]:
    rows = _list_payload(payload)
    if not rows:
        raise MarketDataUnavailableError(
            "market_data_missing",
            "公开衍生品指标响应为空",
        )
    return _mapping_payload(rows[-1])


def _decimal(payload: Mapping[str, object], field: str) -> Decimal:
    return _decimal_value(payload.get(field))


def _decimal_value(value: object) -> Decimal:
    """把上游十进制字符串转换为有限 Decimal，拒绝 float、布尔值和非数值。"""
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
    """把上游毫秒 Unix 时间戳转换为带 UTC 时区的 datetime。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "公开行情时间字段无效",
        )
    seconds, milliseconds = divmod(value, 1000)
    try:
        return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(milliseconds=milliseconds)
    except (OverflowError, OSError, ValueError) as error:
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "公开行情时间字段无效",
        ) from error


def _retry_after(response: httpx.Response) -> float:
    """读取限流响应的 Retry-After；无效或负值退化为立即重试。"""
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


async def _read_bounded_body(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_PUBLIC_JSON_BYTES:
            raise MarketDataUnavailableError(
                "market_data_response_too_large",
                "公开行情响应超过大小上限",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_public_response_boundary(response: httpx.Response, path: str) -> None:
    if (
        response.url.scheme != "https"
        or response.url.host != "fapi.binance.com"
        or response.url.port not in {None, 443}
        or response.url.path != path
    ):
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "公开行情响应来自意外地址",
        )
