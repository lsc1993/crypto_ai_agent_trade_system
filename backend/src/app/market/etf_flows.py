from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Self, cast
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.market.contracts import ContractSymbol, MarketDataUnavailableError

FARSIDE_BASE_URL = "https://farside.co.uk"
FARSIDE_COMPATIBILITY_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MAX_ETF_PAGE_BYTES = 1_000_000
MAX_ETF_DAYS = 15
_MAX_LIVE_COLLECTION_DELAY = timedelta(minutes=5)
_NEW_YORK = ZoneInfo("America/New_York")
_TICKER_RE = re.compile(r"[A-Z][A-Z0-9]{1,9}")
_NUMBER_RE = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
_MISSING_VALUES = frozenset({"", "-", "–", "—", "N/A"})


class _EtfFlowModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EtfFlowDay(_EtfFlowModel):
    trading_date: date
    funds: dict[str, Decimal | None]
    total_net_flow_usd: Decimal | None
    complete: bool

    @field_validator("funds", mode="before")
    @classmethod
    def validate_funds(cls, value: object) -> object:
        if not isinstance(value, dict) or not value:
            raise ValueError("ETF 基金资金流不能为空")
        funds = cast(dict[object, object], value)
        for ticker, flow in funds.items():
            if not isinstance(ticker, str) or _TICKER_RE.fullmatch(ticker) is None:
                raise ValueError("ETF 基金代码无效")
            _validate_optional_decimal(flow)
        return funds

    @field_validator("total_net_flow_usd", mode="before")
    @classmethod
    def validate_total(cls, value: object) -> object:
        _validate_optional_decimal(value)
        return value

    @model_validator(mode="after")
    def validate_completeness(self) -> Self:
        expected = self.total_net_flow_usd is not None and all(
            value is not None for value in self.funds.values()
        )
        if self.complete is not expected:
            raise ValueError("ETF 披露完整状态与基金数据不一致")
        return self


class EtfFlowSnapshot(_EtfFlowModel):
    symbol: ContractSymbol
    fetched_at: datetime
    source_url: str
    days: tuple[EtfFlowDay, ...]

    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("ETF 抓取时间必须是 UTC 且带时区")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        if value not in {f"{FARSIDE_BASE_URL}/btc/", f"{FARSIDE_BASE_URL}/eth/"}:
            raise ValueError("ETF 来源地址无效")
        return value

    @model_validator(mode="after")
    def validate_days(self) -> Self:
        dates = tuple(day.trading_date for day in self.days)
        if not dates or dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
            raise ValueError("ETF 交易日必须非空、升序且不能重复")
        if len(dates) > MAX_ETF_DAYS:
            raise ValueError("ETF 交易日超过读取上限")
        return self


class FarsideEtfFlowGateway:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        clock: Callable[[], datetime],
    ) -> None:
        base_url = client.base_url
        if str(base_url) and (
            base_url.scheme != "https"
            or base_url.host != "farside.co.uk"
            or base_url.port not in {None, 443}
            or base_url.path not in {"", "/"}
        ):
            raise MarketDataUnavailableError(
                "market_data_invalid_request",
                "ETF 公共数据客户端必须使用固定 Farside 地址",
            )
        self._client = client
        self._clock = clock

    async def collect(
        self,
        symbol: ContractSymbol,
        *,
        as_of: datetime,
    ) -> EtfFlowSnapshot:
        started_at = _utc_time_or_error(self._clock(), "ETF 数据时钟必须返回 UTC 时间")
        requested_at = _utc_time_or_error(as_of, "ETF 数据截止时间必须使用 UTC 时间")
        fetch_date = started_at.astimezone(_NEW_YORK).date()
        requested_date = requested_at.astimezone(_NEW_YORK).date()
        if (
            requested_date != fetch_date
            or requested_at > started_at
            or started_at - requested_at > _MAX_LIVE_COLLECTION_DELAY
        ):
            code = (
                "market_data_historical_unavailable"
                if requested_at < started_at
                else "market_data_invalid_request"
            )
            raise MarketDataUnavailableError(
                code,
                "ETF 公开页面仅支持实时研究采集，不能回填历史时点或读取未来时点",
            )
        source_url = _source_url(symbol)
        html = await self._read_page(source_url)
        fetched_at = _utc_time_or_error(self._clock(), "ETF 数据时钟必须返回 UTC 时间")
        if fetched_at < started_at:
            raise MarketDataUnavailableError("market_data_invalid_response", "ETF 抓取时钟发生回退")
        days = _parse_flow_days(html, current_new_york_date=fetch_date)
        return EtfFlowSnapshot(
            symbol=symbol,
            fetched_at=fetched_at,
            source_url=source_url,
            days=days[-MAX_ETF_DAYS:],
        )

    async def _read_page(self, source_url: str) -> str:
        try:
            async with self._client.stream(
                "GET",
                source_url,
                headers={"User-Agent": FARSIDE_COMPATIBILITY_USER_AGENT},
                timeout=5.0,
                follow_redirects=False,
            ) as response:
                _validate_response_boundary(response, source_url)
                if response.status_code == 429:
                    raise MarketDataUnavailableError(
                        "market_data_rate_limited",
                        "ETF 公开数据请求受到限流",
                    )
                if response.status_code >= 500:
                    raise MarketDataUnavailableError(
                        "market_data_unavailable",
                        "ETF 公开数据服务不可用",
                    )
                if response.status_code >= 400:
                    raise MarketDataUnavailableError(
                        "market_data_upstream_rejected",
                        "ETF 公开数据请求被上游拒绝",
                    )
                if response.status_code >= 300:
                    raise MarketDataUnavailableError(
                        "market_data_upstream_rejected",
                        "ETF 公开数据请求被上游重定向",
                    )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_ETF_PAGE_BYTES:
                        raise MarketDataUnavailableError(
                            "market_data_invalid_response",
                            "ETF 公开数据响应超过大小上限",
                        )
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8"
        except MarketDataUnavailableError:
            raise
        except httpx.TimeoutException as error:
            raise MarketDataUnavailableError(
                "market_data_timeout",
                "ETF 公开数据请求超时",
            ) from error
        except httpx.HTTPError as error:
            raise MarketDataUnavailableError(
                "market_data_unavailable",
                "ETF 公开数据服务不可用",
            ) from error
        try:
            return b"".join(chunks).decode(encoding)
        except (LookupError, UnicodeDecodeError) as error:
            raise MarketDataUnavailableError(
                "market_data_invalid_response",
                "ETF 公开数据响应编码无效",
            ) from error


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_depth = 0
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._current_table = []
            return
        if self._table_depth != 1:
            return
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            if self._table_depth == 1 and self._current_table is not None:
                self.tables.append(self._current_table)
                self._current_table = None
            if self._table_depth:
                self._table_depth -= 1
            return
        if self._table_depth != 1:
            return
        if tag in {"td", "th"} and self._current_cell is not None:
            if self._current_row is not None:
                self._current_row.append(_normalize_text("".join(self._current_cell)))
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if self._current_table is not None:
                self._current_table.append(self._current_row)
            self._current_row = None


def _parse_flow_days(html: str, *, current_new_york_date: date) -> tuple[EtfFlowDay, ...]:
    parser = _TableParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as error:
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "ETF 公开页面 HTML 无效",
        ) from error

    parsed_by_date: dict[date, EtfFlowDay] = {}
    found_header = False
    found_date_row = False
    for table in parser.tables:
        tickers = _find_ticker_header(table)
        if tickers is None:
            continue
        found_header = True
        for row in table:
            trading_date = _parse_date(row[0]) if row else None
            if trading_date is None:
                continue
            found_date_row = True
            day = _parse_date_row(row, tickers=tickers, trading_date=trading_date)
            existing = parsed_by_date.get(trading_date)
            if existing is not None and existing != day:
                raise MarketDataUnavailableError(
                    "market_data_invalid_response",
                    "ETF 公开页面包含冲突交易日",
                )
            parsed_by_date[trading_date] = day

    if not found_header or not found_date_row:
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "ETF 公开页面未提供有效资金流表格",
        )
    days = tuple(
        day
        for trading_date, day in sorted(parsed_by_date.items())
        if trading_date <= current_new_york_date
    )
    if not days:
        raise MarketDataUnavailableError(
            "market_data_missing",
            "ETF 公开页面没有截止日期内的交易日数据",
        )
    return days


def _find_ticker_header(table: list[list[str]]) -> tuple[str, ...] | None:
    for row in table:
        if len(row) < 3 or row[0]:
            continue
        header_cells = tuple(cell.strip().upper() for cell in row[1:])
        # Farside's live table leaves the final total column header blank.
        # It remains a data column on each trading-day row, not a fund code.
        if header_cells and not header_cells[-1]:
            header_cells = header_cells[:-1]
        tickers = header_cells
        if len(tickers) < 2:
            continue
        if any(_TICKER_RE.fullmatch(ticker) is None for ticker in tickers):
            continue
        if len(tickers) != len(set(tickers)):
            raise MarketDataUnavailableError(
                "market_data_invalid_response",
                "ETF 公开页面包含重复基金代码",
            )
        return tickers
    return None


def _parse_date_row(
    row: list[str],
    *,
    tickers: tuple[str, ...],
    trading_date: date,
) -> EtfFlowDay:
    if len(row) != len(tickers) + 2:
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "ETF 公开页面交易日列数无效",
        )
    values = tuple(_parse_flow_value(cell) for cell in row[1:-1])
    total = _parse_flow_value(row[-1])
    disclosed = tuple(value for value in values if value is not None)
    if total is None and len(disclosed) == len(values):
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "ETF 完整基金披露缺少总流量",
        )
    if total is not None:
        tolerance = Decimal("100000") * len(disclosed)
        if abs(sum(disclosed, start=Decimal(0)) - total) > tolerance:
            raise MarketDataUnavailableError(
                "market_data_invalid_response",
                "ETF 基金流量与总计不一致",
            )
    funds = dict(zip(tickers, values, strict=True))
    complete = total is not None and len(disclosed) == len(values)
    return EtfFlowDay(
        trading_date=trading_date,
        funds=funds,
        total_net_flow_usd=total,
        complete=complete,
    )


def _parse_flow_value(value: str) -> Decimal | None:
    normalized = _normalize_text(value)
    if normalized in _MISSING_VALUES:
        return None
    negative_parentheses = normalized.startswith("(") and normalized.endswith(")")
    if negative_parentheses:
        normalized = normalized[1:-1].strip()
        if normalized.startswith(("+", "-")):
            raise MarketDataUnavailableError(
                "market_data_invalid_response",
                "ETF 括号负数不能包含额外符号",
            )
    if _NUMBER_RE.fullmatch(normalized) is None:
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "ETF 公开页面包含无效资金流数值",
        )
    try:
        amount = Decimal(normalized.replace(",", "")) * Decimal("1000000")
    except InvalidOperation as error:
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "ETF 公开页面包含无效资金流数值",
        ) from error
    if negative_parentheses:
        amount = -amount
    if not amount.is_finite():
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "ETF 公开页面包含无效资金流数值",
        )
    return amount


def _parse_date(value: str) -> date | None:
    parts = _normalize_text(value).split(" ")
    if len(parts) != 3 or not parts[0].isdigit() or not parts[2].isdigit():
        return None
    month = _MONTHS.get(parts[1].title())
    if month is None:
        return None
    try:
        return date(int(parts[2]), month, int(parts[0]))
    except ValueError:
        return None


def _source_url(symbol: ContractSymbol) -> str:
    paths = {
        ContractSymbol.BTCUSDT: "/btc/",
        ContractSymbol.ETHUSDT: "/eth/",
    }
    try:
        path = paths[symbol]
    except (KeyError, TypeError) as error:
        raise MarketDataUnavailableError(
            "market_data_invalid_request",
            "ETF 资金流不支持该标的",
        ) from error
    return f"{FARSIDE_BASE_URL}{path}"


def _validate_response_boundary(response: httpx.Response, source_url: str) -> None:
    expected = httpx.URL(source_url)
    if (
        response.url.scheme != "https"
        or response.url.host != "farside.co.uk"
        or response.url.port not in {None, 443}
        or response.url.path != expected.path
        or response.url.query
    ):
        raise MarketDataUnavailableError(
            "market_data_invalid_response",
            "ETF 公开数据响应来自意外地址",
        )


def _utc_time_or_error(value: datetime, message: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise MarketDataUnavailableError("market_data_invalid_request", message)
    return value


def _validate_optional_decimal(value: object) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("ETF 资金流必须是有限 Decimal 或缺失值")


def _normalize_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())
