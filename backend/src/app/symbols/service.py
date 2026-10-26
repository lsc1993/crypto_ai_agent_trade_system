# 研究准入：校验公开 USDT 永续合约元数据，并分别探测行情、衍生品及费率；
# 登记前重新检查并保存能力结果。
# 研究币种目录：公开合约检查通过后登记币种并排队初始同步；研究准入不扩展交易契约。
"""Admission checks for public, read-only research symbols."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.market.binance_usdm import PublicDerivativesMetrics
from app.market.contracts import MarketDataUnavailableError, MarketDetail, MarketTimeframe
from app.market.funding_history import FundingHistory
from app.market.symbols import ResearchSymbol
from app.symbols.contracts import (
    Capability,
    CheckResult,
    MarketMetadata,
    ResearchSymbolEntry,
    SymbolError,
    SymbolInput,
)
from app.symbols.repository import SymbolRepository

_TIMEFRAMES = (
    MarketTimeframe.M15,
    MarketTimeframe.H1,
    MarketTimeframe.H4,
    MarketTimeframe.D1,
)


# SymbolProbeGateway 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class SymbolProbeGateway(Protocol):
    # 读取公开合约元数据作为目录准入依据；未找到标的时返回空值。
    async def get_exchange_info(self, symbol: str) -> dict[str, str] | None: ...

    # 读取指定研究标的及周期的行情详情；返回摘要与各周期 K 线。
    async def get_market(
        self,
        symbol: ResearchSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail: ...

    # 读取只读公开衍生品指标并返回带观察和抓取时间的记录。
    async def get_research_metrics(self, symbol: ResearchSymbol) -> PublicDerivativesMetrics: ...

    # 读取指定窗口的已结算公开资金费率历史，不读取账户资金费。
    async def get_funding_history(
        self,
        symbol: ResearchSymbol,
        *,
        since: datetime,
        until: datetime,
    ) -> FundingHistory: ...


# 通过固定公开来源核对合约和核心市场能力，登记前重新检查研究准入。
class SymbolService:
    """Checks a Binance USDⓈ-M contract before it can enter the directory."""

    # 初始化本实例依赖和配置；输入 repository、gateway、clock。
    def __init__(
        self,
        repository: SymbolRepository | None,
        gateway: SymbolProbeGateway,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._clock = clock

    # 先核对公开 USDT 永续元数据，再并发探测行情、衍生品与费率，只返回分项能力结果。
    async def check(self, symbol: ResearchSymbol) -> CheckResult:
        """Return safe, granular capability status without creating a directory row."""
        try:
            metadata = await self._gateway.get_exchange_info(symbol)
        except MarketDataUnavailableError as error:
            return _unverified(symbol, _market_data_failure_message(error, "公开合约信息"))
        except Exception:
            return _unverified(symbol, "公开合约信息暂时无法验证，请重试。")

        parsed_metadata = _metadata(symbol, metadata)
        if parsed_metadata is None:
            return _unsupported(symbol, "未找到可交易的 USDT 永续合约。")
        if (
            parsed_metadata.quote_asset != "USDT"
            or parsed_metadata.margin_asset != "USDT"
            or parsed_metadata.contract_type != "PERPETUAL"
            or parsed_metadata.status != "TRADING"
        ):
            return _unsupported(symbol, "该合约不是处于交易状态的 USDT 永续合约。", parsed_metadata)

        now = _utc(self._clock())
        market, derivatives, funding = await asyncio.gather(
            self._probe_market(symbol),
            self._probe_derivatives(symbol),
            self._probe_funding(symbol, now),
        )
        checks = (
            market[0],
            market[1],
            derivatives,
            funding,
            Capability(
                name="news",
                status="supported",
                message="将使用已登记的公开 RSS 来源同步。",
            ),
            Capability(
                name="sentiment",
                status="supported",
                message="将使用公开市场情绪来源同步。",
            ),
            Capability(name="etf", status="unsupported", message="当前数据源不支持"),
        )
        # 准入由行情、K 线和衍生品三项核心能力共同决定，资金费率不足可以保留分项状态。
        core_statuses = {market[0].status, market[1].status, derivatives.status}
        return CheckResult(
            symbol=symbol,
            supported=core_statuses == {"supported"},
            checks=checks,
            metadata=parsed_metadata,
        )

    # 保存通过准入检查的研究币种及关键词，并由仓储安排初始同步。
    async def add(self, request: SymbolInput) -> ResearchSymbolEntry:
        """Recheck on the server, record the check, then atomically queue initial sync."""
        if self._repository is None:
            raise RuntimeError("研究币对存储不可用")
        now = _utc(self._clock())
        # 不能信任客户端之前显示的检查结果；服务器登记前重新核对当前公开能力。
        result = await self.check(request.symbol)
        await self._repository.record_check(result, now=now)
        if not result.supported:
            raise SymbolError(
                "research_symbol_unsupported",
                "该币对暂不满足研究数据要求。",
                422,
                details={"check": result.model_dump(mode="json")},
            )
        assert result.metadata is not None
        keywords = _research_keywords(request.keywords, result.metadata.base_asset)
        return await self._repository.add(result, keywords=keywords, now=now)

    # 探测行情摘要与四个周期 K 线，核对标的及周期覆盖，返回分项安全能力状态。
    async def _probe_market(self, symbol: ResearchSymbol) -> tuple[Capability, Capability]:
        try:
            detail = await self._gateway.get_market(symbol, _TIMEFRAMES)
            if detail.summary.symbol != symbol:
                raise ValueError("mismatched summary")
            by_timeframe = {series.timeframe: series for series in detail.series}
            if set(by_timeframe) != set(_TIMEFRAMES):
                raise ValueError("missing timeframes")
            if any(
                not series.candles
                or any(candle.symbol != symbol for candle in series.candles)
                for series in by_timeframe.values()
            ):
                raise ValueError("invalid candles")
            return (
                Capability(name="market", status="supported", message="行情摘要可用。"),
                Capability(
                    name="candles",
                    status="supported",
                    message="四个周期的已收盘 K 线可用。",
                ),
            )
        except MarketDataUnavailableError as error:
            return (
                Capability(
                    name="market",
                    status="unverified",
                    message=_market_data_failure_message(error, "公开行情"),
                ),
                Capability(
                    name="candles",
                    status="unverified",
                    message=_market_data_failure_message(error, "公开 K 线"),
                ),
            )
        except Exception:
            return (
                Capability(
                    name="market",
                    status="unverified",
                    message="公开行情响应无效，请重试。",
                ),
                Capability(
                    name="candles",
                    status="unverified",
                    message="公开 K 线响应无效，请重试。",
                ),
            )

    # 探测公开衍生品指标并核对观察时间不晚于抓取时间，失败仅返回安全提示。
    async def _probe_derivatives(self, symbol: ResearchSymbol) -> Capability:
        try:
            metrics = await self._gateway.get_research_metrics(symbol)
            if metrics.observed_at > metrics.fetched_at:
                raise ValueError("time order")
            return Capability(
                name="derivatives",
                status="supported",
                message="公开衍生品指标可用。",
            )
        except MarketDataUnavailableError as error:
            return Capability(
                name="derivatives",
                status="unverified",
                message=_market_data_failure_message(error, "公开衍生品指标"),
            )
        except Exception:
            return Capability(
                name="derivatives",
                status="unverified",
                message="公开衍生品指标响应无效，请重试。",
            )

    # 探测近七天公开费率并核对标的；历史不足或读取失败显示未验证。
    async def _probe_funding(self, symbol: ResearchSymbol, now: datetime) -> Capability:
        try:
            history = await self._gateway.get_funding_history(
                symbol,
                since=now - timedelta(days=7),
                until=now,
            )
            if history.symbol != symbol:
                raise ValueError("mismatched funding")
            if not history.points:
                return Capability(
                    name="funding",
                    status="unverified",
                    message="资金费率历史不足，首次同步将标记部分覆盖。",
                )
            return Capability(
                name="funding",
                status="supported",
                message="近七天已结算资金费率可用。",
            )
        except MarketDataUnavailableError as error:
            return Capability(
                name="funding",
                status="unverified",
                message=_market_data_failure_message(error, "资金费率历史"),
            )
        except Exception:
            return Capability(
                name="funding",
                status="unverified",
                message="资金费率历史响应无效，请重试。",
            )


# 核对元数据标的并提取必需的大写字段；缺失、错标的或空字段返回空值。
def _metadata(symbol: ResearchSymbol, raw: dict[str, str] | None) -> MarketMetadata | None:
    if raw is None or raw.get("symbol") != symbol:
        return None
    values = {
        field: raw.get(source, "").strip().upper()
        for field, source in (
            ("base_asset", "baseAsset"),
            ("quote_asset", "quoteAsset"),
            ("margin_asset", "marginAsset"),
            ("contract_type", "contractType"),
            ("status", "status"),
        )
    }
    if any(not value for value in values.values()):
        return None
    return MarketMetadata(symbol=symbol, **values)


# 保留公开合约基础资产名作为默认新闻别名，再按不区分大小写方式合并用户关键词。
def _research_keywords(keywords: tuple[str, ...], base_asset: str) -> tuple[str, ...]:
    """Always retain the public contract base as a safe default news alias."""
    normalized: dict[str, str] = {base_asset.casefold(): base_asset}
    for keyword in keywords:
        normalized.setdefault(keyword.casefold(), keyword)
    return tuple(normalized.values())


# 构造不满足研究准入要求的能力结果，保留可用合约元数据。
def _unsupported(
    symbol: ResearchSymbol,
    message: str,
    metadata: MarketMetadata | None = None,
) -> CheckResult:
    return CheckResult(
        symbol=symbol,
        supported=False,
        checks=tuple(
            Capability(
                name=name,
                status="unsupported",
                message=message if name == "market" else "当前合约不满足研究准入要求。",
            )
            for name in ("market", "candles", "derivatives", "funding", "news", "sentiment", "etf")
        ),
        metadata=metadata,
    )


# 构造无法完成公开来源验证的能力结果，与明确不支持区分。
def _unverified(symbol: ResearchSymbol, message: str) -> CheckResult:
    return CheckResult(
        symbol=symbol,
        supported=False,
        checks=tuple(
            Capability(name=name, status="unverified", message=message)
            for name in ("market", "candles", "derivatives", "funding", "news", "sentiment", "etf")
        ),
        metadata=None,
    )


# 将已知行情错误映射为安全准入反馈，不展示或保存原始上游错误文本。
def _market_data_failure_message(error: MarketDataUnavailableError, subject: str) -> str:
    """Map known gateway failures to safe, actionable admission feedback."""
    if error.code == "market_data_response_too_large":
        return f"{subject}响应超过系统可接受的大小上限，请稍后重试。"
    if error.code == "market_data_rate_limited":
        return f"{subject}请求频率受限，请稍后重试。"
    if error.code == "market_data_timeout":
        return f"{subject}请求超时，请稍后重试。"
    return f"{subject}暂时无法验证，请重试。"


# 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("研究币对检查时钟必须使用 UTC")
    return value.astimezone(UTC)
