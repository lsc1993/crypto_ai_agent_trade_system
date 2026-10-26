# ETF 资金流：只读取固定 BTC/ETH 公开表，按纽约交易日解析披露状态，百万美元转美元；
# 实时页面不可回填历史时点。
# 公开行情领域：统一研究行情模型、固定公开来源适配器与冻结快照读取；不访问私有账户。
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Self, cast
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.market.contracts import ContractSymbol, MarketDataUnavailableError
from app.market.symbols import ResearchSymbol

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


# ETF 资金流契约的冻结基类，拒绝额外字段。
class _EtfFlowModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# 纽约交易日的逐基金美元流量与总额，空值表示未披露，完整标志必须与数据覆盖相符。
class EtfFlowDay(_EtfFlowModel):
    trading_date: date
    funds: dict[str, Decimal | None]
    total_net_flow_usd: Decimal | None
    complete: bool

    # 校验funds 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：ETF 基金资金流不能为空；ETF 基金代码无效。
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

    # 校验total_net_flow_usd 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    @field_validator("total_net_flow_usd", mode="before")
    @classmethod
    def validate_total(cls, value: object) -> object:
        _validate_optional_decimal(value)
        return value

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：ETF 披露完整状态与基金数据不一致。
    @model_validator(mode="after")
    def validate_completeness(self) -> Self:
        expected = self.total_net_flow_usd is not None and all(
            value is not None for value in self.funds.values()
        )
        if self.complete is not expected:
            raise ValueError("ETF 披露完整状态与基金数据不一致")
        return self


# 一次公开 ETF 表读取的冻结结果，包含来源、UTC 抓取时刻与升序交易日。
class EtfFlowSnapshot(_EtfFlowModel):
    symbol: ResearchSymbol
    fetched_at: datetime
    source_url: str
    days: tuple[EtfFlowDay, ...]

    # 校验fetched_at 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：ETF 抓取时间必须是 UTC 且带时区。
    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("ETF 抓取时间必须是 UTC 且带时区")
        return value

    # 校验source_url 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：ETF 来源地址无效。
    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        if value not in {f"{FARSIDE_BASE_URL}/btc/", f"{FARSIDE_BASE_URL}/eth/"}:
            raise ValueError("ETF 来源地址无效")
        return value

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：ETF 交易日必须非空、升序且不能重复；ETF 交易日超过读取上限。
    @model_validator(mode="after")
    def validate_days(self) -> Self:
        dates = tuple(day.trading_date for day in self.days)
        if not dates or dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
            raise ValueError("ETF 交易日必须非空、升序且不能重复")
        if len(dates) > MAX_ETF_DAYS:
            raise ValueError("ETF 交易日超过读取上限")
        return self


# 固定 ETF 公开页面读取器，仅支持实时 BTC/ETH 研究，不提供通用爬取或历史回填。
class FarsideEtfFlowGateway:
    # 初始化本实例依赖和配置；输入 client、clock。
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

    # 检查实时采集窗口，读取固定 ETF 页面并按纽约交易日解析，返回最近最多十五个交易日。
    async def collect(
        self,
        symbol: Any,
        *,
        as_of: datetime,
    ) -> EtfFlowSnapshot:
        started_at = _utc_time_or_error(self._clock(), "ETF 数据时钟必须返回 UTC 时间")
        requested_at = _utc_time_or_error(as_of, "ETF 数据截止时间必须使用 UTC 时间")
        # ETF 日期按美国市场的纽约时区解释，不能直接用 UTC 日期截断交易日。
        fetch_date = started_at.astimezone(_NEW_YORK).date()
        requested_date = requested_at.astimezone(_NEW_YORK).date()
        # 实时网页会持续更新，因此只接受同日且延迟很小的研究请求，避免回填产生未来数据泄漏。
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

    # 读取固定公开页面并限制响应大小；网络、状态码与编码错误统一转为安全领域错误。
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


# 轻量公开表解析状态机，仅为顶层表建立行列结构；已有单元格仍累计内部文本。
class _TableParser(HTMLParser):
    # 初始化实例内部缓冲或预置状态，供后续方法复用。
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_depth = 0
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    # 按嵌套深度仅建立顶层行列状态；嵌套文字仍由 handle_data 写入当前单元格。
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

    # 将解析器当前单元格内的文本片段累计起来，等待闭合时统一清理。
    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    # 关闭单元格、行或顶层表时依次提交缓冲内容，并维护表格嵌套深度。
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


# 从公开 HTML 表识别基金列与交易日，拒绝冲突日期，剔除纽约当前日期之后记录并升序返回。
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


# 识别基金代码表头，允许总计列标题为空，但拒绝重复基金代码。
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


# 解析基金列和总计列，检查数量与披露总额误差，保存缺失值和完整披露标记。
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
        # 公开表以百万美元小数披露，每个已披露基金保留舍入容差，不能要求展示金额绝对精确求和。
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


# 将百万美元文本解析成美元 Decimal；横线等未披露标记返回空值，括号表示负流量。
def _parse_flow_value(value: str) -> Decimal | None:
    normalized = _normalize_text(value)
    # 未披露与真实零流量语义不同，保留空值供完整性校验和前端显示。
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


# 按公开表的日、英文月份和年解析日期；非日期行或无效日期返回空值。
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


# 只将静态 BTC/ETH 标的映射为固定来源页面；其他研究币种返回不支持。
def _source_url(symbol: ResearchSymbol) -> str:
    paths: dict[str, str] = {
        ContractSymbol.BTCUSDT.value: "/btc/",
        ContractSymbol.ETHUSDT.value: "/eth/",
    }
    try:
        path = paths[symbol]
    except (KeyError, TypeError) as error:
        raise MarketDataUnavailableError(
            "market_data_unsupported",
            "当前数据源不支持",
        ) from error
    return f"{FARSIDE_BASE_URL}{path}"


# 核对 ETF 响应固定主机、端口、请求路径且无查询参数，拒绝非批准页面。
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


# 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
def _utc_time_or_error(value: datetime, message: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise MarketDataUnavailableError("market_data_invalid_request", message)
    return value


# 空值表示未披露；非空金额必须是有限 Decimal，拒绝布尔值和其他类型。
def _validate_optional_decimal(value: object) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("ETF 资金流必须是有限 Decimal 或缺失值")


# 清理不可见空格和多余空白，保留公开表的文字内容。
def _normalize_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())
