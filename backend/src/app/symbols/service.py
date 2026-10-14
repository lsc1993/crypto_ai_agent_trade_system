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


class SymbolProbeGateway(Protocol):
    async def get_exchange_info(self, symbol: str) -> dict[str, str] | None: ...

    async def get_market(
        self,
        symbol: ResearchSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail: ...

    async def get_research_metrics(self, symbol: ResearchSymbol) -> PublicDerivativesMetrics: ...

    async def get_funding_history(
        self,
        symbol: ResearchSymbol,
        *,
        since: datetime,
        until: datetime,
    ) -> FundingHistory: ...


class SymbolService:
    """Checks a Binance USDⓈ-M contract before it can enter the directory."""

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
        core_statuses = {market[0].status, market[1].status, derivatives.status}
        return CheckResult(
            symbol=symbol,
            supported=core_statuses == {"supported"},
            checks=checks,
            metadata=parsed_metadata,
        )

    async def add(self, request: SymbolInput) -> ResearchSymbolEntry:
        """Recheck on the server, record the check, then atomically queue initial sync."""
        if self._repository is None:
            raise RuntimeError("研究币对存储不可用")
        now = _utc(self._clock())
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


def _research_keywords(keywords: tuple[str, ...], base_asset: str) -> tuple[str, ...]:
    """Always retain the public contract base as a safe default news alias."""
    normalized: dict[str, str] = {base_asset.casefold(): base_asset}
    for keyword in keywords:
        normalized.setdefault(keyword.casefold(), keyword)
    return tuple(normalized.values())


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


def _market_data_failure_message(error: MarketDataUnavailableError, subject: str) -> str:
    """Map known gateway failures to safe, actionable admission feedback."""
    if error.code == "market_data_response_too_large":
        return f"{subject}响应超过系统可接受的大小上限，请稍后重试。"
    if error.code == "market_data_rate_limited":
        return f"{subject}请求频率受限，请稍后重试。"
    if error.code == "market_data_timeout":
        return f"{subject}请求超时，请稍后重试。"
    return f"{subject}暂时无法验证，请重试。"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("研究币对检查时钟必须使用 UTC")
    return value.astimezone(UTC)
