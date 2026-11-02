# 显式公开源诊断入口：固定 BTC/ETH 与登记 RSS，可选已治理情绪/ETF，经生产适配器只输出安全元数据。
# 不读取 AppSettings、.env、数据库、账户或模型；不保存新闻、价格或原始响应。
# 本命令不属于默认 full/CI；仅 python -m scripts.check_public_sources 显式执行时联网。
from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import ParseError
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from app.market.binance_usdm import BINANCE_USDM_BASE_URL, BinanceUsdmPublicMarketGateway
from app.market.contracts import MarketDataUnavailableError, MarketTimeframe
from app.market.etf_flows import FARSIDE_BASE_URL, FarsideEtfFlowGateway
from app.market.research_context import ALTERNATIVE_ME_BASE_URL, AlternativeMeFearGreedGateway
from app.news.contracts import ALLOWED_NEWS_SOURCES
from app.news.rss import RssNewsSourceAdapter

Status = Literal["passed", "partial", "failed"]
Reason = Literal[
    "fresh",
    "metadata_available",
    "empty_data",
    "stale_data",
    "future_data",
    "no_recent_news",
    "filtered_entries",
    "entry_limit",
    "incomplete_history",
    "incomplete_disclosure",
    "timeout",
    "rate_limited",
    "upstream_rejected",
    "invalid_response",
    "unavailable",
    "unexpected_error",
    "checks_complete",
    "report_write_failed",
]
NETWORK_MODE = "httpx_default_process_environment; host_process_only; container_network_not_tested"
CHECK_TIMEOUT_SECONDS = 20
NEW_YORK = ZoneInfo("America/New_York")
CONTEXT_CHECK_IDS = frozenset(
    {"alternative_me.fear_greed", "BTCUSDT.etf_flows", "ETHUSDT.etf_flows"}
)
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TIMEFRAME_SECONDS = {
    MarketTimeframe.M15: 900,
    MarketTimeframe.H1: 3600,
    MarketTimeframe.H4: 14400,
    MarketTimeframe.D1: 86400,
}
CHECK_IDS = frozenset(
    [
        f"{symbol}.{part}"
        for symbol in SYMBOLS
        for part in (
            "exchange_info",
            "summary",
            "candles_15m",
            "candles_1h",
            "candles_4h",
            "candles_1d",
            "derivatives",
            "funding_7d",
        )
    ]
    + [f"{source}.rss" for source in ALLOWED_NEWS_SOURCES]
)


@dataclass(frozen=True)
class Observation:
    # 生产读取结果立即收敛到条数、UTC 时间和覆盖标志；此结构没有内容/价格字段。
    count: int
    observed_times: tuple[datetime, ...] = ()
    coverage_complete: bool = True
    rejected_entry_count: int = 0
    omitted_entry_count: int = 0
    latest_trading_date: date | None = None
    disclosure_complete: bool | None = None


@dataclass(frozen=True)
class CheckSpec:
    # 仅代码内固定检查可注入只读操作；不提供任意 URL/标的 CLI 参数。
    check_id: str
    read: Callable[[], Awaitable[Observation]]
    threshold_seconds: int | None
    news: bool = False
    etf: bool = False

    def __post_init__(self) -> None:
        # 在调度前检查标识，保证意外文本不会进入安全报告。
        if self.check_id not in CHECK_IDS | CONTEXT_CHECK_IDS:
            raise ValueError("unknown_check_id")


@dataclass(frozen=True)
class CheckResult:
    # availability 仅代表成功读取/解析；RSS 内容覆盖另由 recent_news_count 与 reason 表达。
    check_id: str
    status: Status
    reason: Reason
    checked_at: datetime
    completed_at: datetime
    observed_at: datetime | None
    count: int
    threshold_seconds: int | None
    availability: Literal["available", "unavailable"]
    recent_news_count: int | None = None
    http_status: int | None = None
    rejected_entry_count: int = 0
    omitted_entry_count: int = 0
    latest_trading_date: date | None = None
    trading_date_timezone: Literal["America/New_York"] | None = None
    threshold_calendar_days: int | None = None
    disclosure_complete: bool | None = None


@dataclass(frozen=True)
class DiagnosticReport:
    # 无自由文本错误字段；退出码由此状态决定，落盘失败也修改本报告而非打印异常。
    status: Status
    reason: Reason
    checked_at: datetime
    completed_at: datetime
    checks: tuple[CheckResult, ...]
    network_mode: str = NETWORK_MODE
    schema_version: Literal[1] = 1

    def to_json(self) -> str:
        # 所有时间显式序列化 UTC；其余字段均来自固定契约和安全投影。
        def encode(value: object) -> str:
            if isinstance(value, datetime):
                return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if isinstance(value, date):
                return value.isoformat()
            raise TypeError("unsupported_report_value")

        return json.dumps(asdict(self), default=encode, ensure_ascii=True, indent=2)


def _safe_error(error: Exception) -> tuple[Reason, int | None]:
    # 只查看异常类型、白名单领域码和安全 HTTP 状态；绝不读取 str(error)、URL 或 body。
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and len(chain) < 8 and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    for cause in chain:
        if isinstance(cause, (TimeoutError, httpx.TimeoutException)):
            return "timeout", None
        if isinstance(cause, httpx.HTTPStatusError):
            status = cause.response.status_code
            if 100 <= status <= 599:
                return ("rate_limited" if status == 429 else "upstream_rejected"), status
    mapping: dict[str, Reason] = {
        "market_data_timeout": "timeout",
        "market_data_rate_limited": "rate_limited",
        "market_data_upstream_rejected": "upstream_rejected",
        "market_data_invalid_response": "invalid_response",
        "market_data_response_too_large": "invalid_response",
        "market_data_missing": "empty_data",
        "market_data_unavailable": "unavailable",
        # 情绪网关将短历史、空数据和部分上游拒绝合并为领域不可用，不能臆断具体根因。
        "market_context_unavailable": "unavailable",
    }
    if isinstance(error, MarketDataUnavailableError):
        return mapping.get(error.code, "unexpected_error"), None
    if isinstance(error, httpx.HTTPError):
        return "unavailable", None
    if isinstance(error, (ValueError, TypeError, ParseError, ValidationError)):
        return "invalid_response", None
    return "unexpected_error", None


async def run_checks(
    specs: Sequence[CheckSpec], *, clock: Callable[[], datetime]
) -> DiagnosticReport:
    # 两个分项并发，每项最多20秒（包括适配器既有重试和 Retry-After），不再叠加重试。
    # 生产行情分项内部最多四组公开请求，所以网络并发也有固定上界。
    started = clock()
    semaphore = asyncio.Semaphore(2)

    async def check(spec: CheckSpec) -> CheckResult:
        async with semaphore:
            checked = clock()
            try:
                async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
                    observation = await spec.read()
                completed = clock()
                times = observation.observed_times
                if min(
                    observation.count,
                    observation.rejected_entry_count,
                    observation.omitted_entry_count,
                ) < 0 or any(
                    value.tzinfo is None or value.utcoffset() != timedelta(0) for value in times
                ):
                    raise ValueError("invalid_observation")
                recent = sum(completed - timedelta(days=7) <= t <= completed for t in times)
                status: Status = "passed"
                reason: Reason = "fresh"
                trading_date = observation.latest_trading_date
                if any(t > completed for t in times) or (
                    spec.etf
                    and trading_date is not None
                    and trading_date > completed.astimezone(NEW_YORK).date()
                ):
                    status, reason = "failed", "future_data"
                elif spec.news and observation.rejected_entry_count:
                    # 已过滤与真空订阅分开；即使全拒绝，也不能隐藏拒绝后报告 empty_data。
                    status, reason = "partial", "filtered_entries"
                elif spec.news and observation.omitted_entry_count:
                    status, reason = "partial", "entry_limit"
                elif observation.count == 0:
                    status, reason = ("partial" if spec.news else "failed"), "empty_data"
                elif spec.etf:
                    # 公开表仅有纽约交易日，没有实际披露时刻；保持 observed_at 为空，
                    # 以当地日历日期诊断七日宽限，避免 UTC 跨天和夏令时造成误判。
                    if trading_date is None:
                        status, reason = "failed", "empty_data"
                    elif observation.disclosure_complete is not True:
                        status, reason = "partial", "incomplete_disclosure"
                    elif (completed.astimezone(NEW_YORK).date() - trading_date).days > 7:
                        status, reason = "partial", "stale_data"
                elif spec.threshold_seconds is None:
                    reason = "metadata_available"
                elif not times:
                    status, reason = "failed", "empty_data"
                elif spec.news and recent == 0:
                    # 官方面向事件披露的低频源不据此断言连接故障，只报告内容覆盖不足。
                    status, reason = "partial", "no_recent_news"
                elif (completed - max(times)).total_seconds() > spec.threshold_seconds:
                    status, reason = "partial", "stale_data"
                elif not observation.coverage_complete:
                    status, reason = "partial", "incomplete_history"
                return CheckResult(
                    spec.check_id,
                    status,
                    reason,
                    checked,
                    completed,
                    max(times, default=None),
                    observation.count,
                    spec.threshold_seconds,
                    "available",
                    recent if spec.news else None,
                    rejected_entry_count=observation.rejected_entry_count,
                    omitted_entry_count=observation.omitted_entry_count,
                    latest_trading_date=trading_date,
                    trading_date_timezone="America/New_York" if spec.etf else None,
                    threshold_calendar_days=7 if spec.etf else None,
                    disclosure_complete=observation.disclosure_complete,
                )
            except Exception as error:
                reason, http_status = _safe_error(error)
                return CheckResult(
                    spec.check_id,
                    "failed",
                    reason,
                    checked,
                    clock(),
                    None,
                    0,
                    spec.threshold_seconds,
                    "unavailable",
                    http_status=http_status,
                    trading_date_timezone="America/New_York" if spec.etf else None,
                    threshold_calendar_days=7 if spec.etf else None,
                )

    results = tuple(await asyncio.gather(*(check(spec) for spec in specs)))
    status: Status = (
        "passed"
        if results and all(r.status == "passed" for r in results)
        else ("failed" if not results or all(r.status == "failed" for r in results) else "partial")
    )
    return DiagnosticReport(status, "checks_complete", started, clock(), results)


def build_checks(
    market_client: httpx.AsyncClient,
    news_client: httpx.AsyncClient,
    *,
    clock: Callable[[], datetime],
) -> tuple[CheckSpec, ...]:
    # 复用生产网关主机/路径白名单、Decimal/XML 解析与禁止重定向；客户端不加载应用配置。
    gateway = BinanceUsdmPublicMarketGateway(client=market_client, clock=clock)
    specs: list[CheckSpec] = []

    def market_specs(symbol: str) -> None:
        # 单独绑定每个标的，避免循环闭包迟绑定使 BTC 检查实际读取 ETH。
        async def metadata() -> Observation:
            result = await gateway.get_exchange_info(symbol)
            eligible = result is not None and all(
                result.get(k) == v
                for k, v in {
                    "symbol": symbol,
                    "quoteAsset": "USDT",
                    "marginAsset": "USDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                }.items()
            )
            return Observation(count=int(eligible))

        async def summary() -> Observation:
            # 生产摘要只公开三个上游分量中最早的观测时间；此处只校验该聚合字段，
            # 不能据此证明其他未公开分量没有未来时间，也不绕过适配器读取原始响应。
            values = await gateway.get_summaries((symbol,))
            return Observation(len(values), tuple(v.freshness.observed_at for v in values))

        async def derivatives() -> Observation:
            # 与摘要相同，公开衍生品契约只提供最早聚合时刻；诊断证明范围止于该字段。
            result = await gateway.get_research_metrics(symbol)
            return Observation(3, (result.observed_at,))

        async def funding() -> Observation:
            until = clock()
            since = until - timedelta(days=7)
            result = await gateway.get_funding_history(symbol, since=since, until=until)
            times = tuple(point.funding_time for point in result.points)
            # BTC/ETH 当前八小时结算：允许12小时边界和间隔，缺少七日覆盖只能 partial。
            complete = bool(times) and len(times) >= 20 and times[0] <= since + timedelta(hours=12)
            complete = complete and all(
                b - a <= timedelta(hours=12) for a, b in zip(times, times[1:])
            )
            return Observation(len(times), times, complete)

        specs.extend(
            (
                CheckSpec(f"{symbol}.exchange_info", metadata, None),
                CheckSpec(f"{symbol}.summary", summary, 300),
            )
        )

        def candles_spec(timeframe: MarketTimeframe) -> CheckSpec:
            async def candles() -> Observation:
                # 这是生产行情详情路径，仍依赖其摘要读取；失败不能解读为独立 klines
                # 端点故障。保持公开接口边界，不调用网关私有方法绕开依赖。
                detail = await gateway.get_market(symbol, (timeframe,))
                values = detail.series[0].candles
                return Observation(len(values), tuple(v.close_at for v in values))

            # 已收盘周期距当前时间天然最多一个周期；另给五分钟采集裕量。
            return CheckSpec(
                f"{symbol}.candles_{timeframe.value}", candles, TIMEFRAME_SECONDS[timeframe] + 300
            )

        specs.extend(candles_spec(timeframe) for timeframe in MarketTimeframe)
        specs.extend(
            (
                CheckSpec(f"{symbol}.derivatives", derivatives, 7200),
                CheckSpec(f"{symbol}.funding_7d", funding, 43200),
            )
        )

    for symbol in SYMBOLS:
        market_specs(symbol)
    for source in ALLOWED_NEWS_SOURCES.values():
        adapter = RssNewsSourceAdapter(source=source, client=news_client, timeout_seconds=5)

        def news_spec(adapter: RssNewsSourceAdapter) -> CheckSpec:
            async def news() -> Observation:
                # 与生产协调器相同，条目与拒绝数量必须来自同一个返回值，避免二次请求与实例串扰。
                result = await adapter.fetch_result(fetched_at=clock())
                return Observation(
                    len(result.items),
                    tuple(v.published_at for v in result.items),
                    coverage_complete=not (result.rejected_count or result.omitted_count),
                    rejected_entry_count=result.rejected_count,
                    omitted_entry_count=result.omitted_count,
                )

            return CheckSpec(f"{adapter.source.source_id}.rss", news, 604800, news=True)

        specs.append(news_spec(adapter))
    return tuple(specs)


def build_context_checks(
    sentiment_client: httpx.AsyncClient,
    etf_client: httpx.AsyncClient,
    *,
    clock: Callable[[], datetime],
) -> tuple[CheckSpec, ...]:
    # 可选范围固定为一个情绪历史与 BTC/ETH 表；直接复用生产解析与主机白名单，
    # 不提供任意 URL、供应商或币种参数，也不改生产报告的证据准入阈值。
    sentiment = AlternativeMeFearGreedGateway(client=sentiment_client, clock=clock)
    etf = FarsideEtfFlowGateway(client=etf_client, clock=clock)

    async def fear_greed() -> Observation:
        readings = await sentiment.get_history()
        times = tuple(reading.observed_at for reading in readings)
        # 生产适配器验证八条倒序记录，但未保证逐日连续；重复日期/缺日需独立降为 partial。
        complete = len(times) == 8 and all(
            (a.date() - b.date()).days == 1 for a, b in zip(times, times[1:])
        )
        return Observation(len(readings), times, coverage_complete=complete)

    def etf_spec(symbol: str) -> CheckSpec:
        async def flows() -> Observation:
            snapshot = await etf.collect(symbol, as_of=clock())
            # days 是适配器保留的最多十五日，非完整历史；未来纽约日期已被生产适配器
            # 过滤，诊断只能检查返回字段，不能证明原始网页没有被过滤的未来日期。
            # 任一返回日披露不全均 partial；不得用 fetched_at 冒充交易日观测时刻。
            return Observation(
                len(snapshot.days),
                latest_trading_date=max(day.trading_date for day in snapshot.days),
                disclosure_complete=all(day.complete for day in snapshot.days),
            )

        return CheckSpec(f"{symbol}.etf_flows", flows, None, etf=True)

    return (
        CheckSpec("alternative_me.fear_greed", fear_greed, 172800),
        *(etf_spec(symbol) for symbol in SYMBOLS),
    )


async def run_diagnostics(*, include_context: bool = False) -> DiagnosticReport:
    # httpx 默认 trust_env=True，与生产默认进程网络方式一致；不读取/输出代理值，
    # 此进程结果不代表 Docker 容器网络。显式关闭重定向，连接池和总分项并发均有限。
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    async with (
        httpx.AsyncClient(
            base_url=BINANCE_USDM_BASE_URL, timeout=5, follow_redirects=False, limits=limits
        ) as market_client,
        httpx.AsyncClient(timeout=5, follow_redirects=False, limits=limits) as news_client,
        AsyncExitStack() as context_stack,
    ):

        def clock() -> datetime:
            return datetime.now(UTC)

        specs = build_checks(market_client, news_client, clock=clock)
        if include_context:
            sentiment_client = await context_stack.enter_async_context(
                httpx.AsyncClient(
                    base_url=ALTERNATIVE_ME_BASE_URL,
                    timeout=5,
                    follow_redirects=False,
                    limits=limits,
                )
            )
            etf_client = await context_stack.enter_async_context(
                httpx.AsyncClient(
                    base_url=FARSIDE_BASE_URL, timeout=5, follow_redirects=False, limits=limits
                )
            )
            specs += build_context_checks(sentiment_client, etf_client, clock=clock)
        return await run_checks(specs, clock=clock)


def main(argv: Sequence[str] | None = None) -> int:
    # --include-context 仅打开代码固定的三项诊断；不存在任意 URL、模型、数据库或账户选项。
    parser = argparse.ArgumentParser(description="Explicit read-only governed public-source checks")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--include-context", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(
            run_diagnostics(include_context=True) if args.include_context else run_diagnostics()
        )
    except Exception:
        # 客户端构造等顶层未知错误同样不输出环境值、traceback 或异常文本。
        now = datetime.now(UTC)
        report = DiagnosticReport("failed", "unexpected_error", now, now, ())
    code = 0 if report.status == "passed" else 1
    if args.report is not None:
        try:
            args.report.write_text(report.to_json() + "\n", encoding="utf-8")
        except (OSError, ValueError):
            report = replace(report, status="failed", reason="report_write_failed")
            code = 2
    print(report.to_json())
    return code


if __name__ == "__main__":
    raise SystemExit(main())
