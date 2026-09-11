"""公开衍生品与市场情绪研究上下文模块。

数据流：Binance 公开衍生品指标与 Alternative.me 恐惧贪婪历史并发读取 → 严格校验
数值、时间和来源范围 → 构造早于市场快照时刻的 PublicResearchContext。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.market.binance_usdm import PublicDerivativesMetrics
from app.market.contracts import FreshnessStatus, MarketDataUnavailableError
from app.market.symbols import ResearchSymbol

ALTERNATIVE_ME_BASE_URL = "https://api.alternative.me"
_CONTEXT_ERROR_CODE = "market_context_unavailable"


class PublicResearchContext(BaseModel):
    """可作为 Agent 冻结证据的公开市场上下文，所有数值和时间均已校验。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: ResearchSymbol
    basis_rate: Decimal
    long_short_account_ratio: Decimal
    taker_buy_sell_ratio: Decimal
    fear_greed_value: int = Field(ge=0, le=100)
    fear_greed_classification: str = Field(min_length=1, max_length=100)
    fear_greed_change_7d: int = Field(ge=-100, le=100)
    fear_greed_7d_start_at: datetime
    freshness: FreshnessStatus
    observed_at: datetime
    fetched_at: datetime

    @field_validator(
        "basis_rate",
        "long_short_account_ratio",
        "taker_buy_sell_ratio",
        mode="before",
    )
    @classmethod
    def require_finite_decimal(cls, value: object) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (Decimal, str)):
            raise ValueError("公开市场上下文必须使用十进制数")
        try:
            parsed = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("公开市场上下文必须使用十进制数") from error
        if not parsed.is_finite():
            raise ValueError("公开市场上下文必须使用有限十进制数")
        return parsed

    @field_validator("fear_greed_classification")
    @classmethod
    def normalize_classification(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("恐惧贪婪分类不能为空")
        return normalized

    @field_validator("fear_greed_7d_start_at", "observed_at", "fetched_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def require_observed_before_fetched(self) -> PublicResearchContext:
        if self.observed_at > self.fetched_at:
            raise ValueError("公开市场上下文观测时间不能晚于抓取时间")
        if self.fear_greed_7d_start_at > self.observed_at:
            raise ValueError("恐惧贪婪比较起点不能晚于当前观测时间")
        return self


class PublicDerivativesGateway(Protocol):
    async def get_research_metrics(
        self,
        symbol: Any,
    ) -> PublicDerivativesMetrics: ...


@dataclass(frozen=True)
class FearGreedReading:
    """恐惧贪婪指数的单日原始读数及其观测、抓取时间。"""
    value: int
    classification: str
    observed_at: datetime
    fetched_at: datetime


class AlternativeMeFearGreedGateway:
    """固定主机的 Alternative.me 公开恐惧与贪婪指数读取器。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        clock: Callable[[], datetime],
    ) -> None:
        # 拒绝任意 base URL，避免此只读适配器被配置为访问非预期的外部端点。
        base_url = client.base_url
        if (
            base_url.scheme != "https"
            or base_url.host != "api.alternative.me"
            or base_url.path not in {"", "/"}
        ):
            raise ValueError("Alternative.me 客户端必须使用固定 HTTPS 地址")
        self._client = client
        self._clock = clock

    async def get_history(self) -> tuple[FearGreedReading, ...]:
        """读取最新八条恐惧贪婪数据，以支持当前值与七日前值的比较。"""
        try:
            response = await self._client.get(
                "/fng/",
                params={"limit": "8", "format": "json"},
                timeout=5.0,
            )
        except httpx.HTTPError as error:
            raise _context_unavailable() from error
        if response.status_code >= 400:
            raise _context_unavailable()
        try:
            payload = response.json()
        except ValueError as error:
            raise _context_unavailable() from error
        now = _require_utc(self._clock())
        return _fear_greed_history(payload, fetched_at=now)


class PublicResearchContextCollector:
    """合并两个固定公开来源，并防止晚于快照的未来数据进入研究。"""
    def __init__(
        self,
        *,
        derivatives: PublicDerivativesGateway,
        fear_greed: AlternativeMeFearGreedGateway,
    ) -> None:
        self._derivatives = derivatives
        self._fear_greed = fear_greed

    async def collect(
        self,
        symbol: Any,
        *,
        captured_at: datetime,
    ) -> PublicResearchContext:
        """并发读取公开指标并构造一个与 captured_at 对齐的研究上下文。

        任一来源缺失、格式异常、历史长度不足或观测时间超过快照时刻时，统一返回
        受控的 market_context_unavailable 错误，而不返回部分拼凑结果。
        """
        captured_at = _require_utc(captured_at)
        try:
            # 两组公开指标可并发抓取，但都必须早于本次快照时刻，不能向研究注入未来数据。
            metrics, history = await asyncio.gather(
                self._derivatives.get_research_metrics(symbol),
                self._fear_greed.get_history(),
            )
            newest, seventh_newest = history[0], history[7]
            if metrics.observed_at > captured_at or newest.observed_at > captured_at:
                raise ValueError("公开上下文包含采集时刻后的数据")
            return PublicResearchContext(
                symbol=symbol,
                basis_rate=metrics.basis_rate,
                long_short_account_ratio=metrics.long_short_account_ratio,
                taker_buy_sell_ratio=metrics.taker_buy_sell_ratio,
                fear_greed_value=newest.value,
                fear_greed_classification=newest.classification,
                fear_greed_change_7d=newest.value - seventh_newest.value,
                fear_greed_7d_start_at=seventh_newest.observed_at,
                freshness=FreshnessStatus.FRESH,
                # 上下文的可用时间取各来源中较早者，抓取完成时间则取较晚者。
                observed_at=min(metrics.observed_at, newest.observed_at),
                fetched_at=max(metrics.fetched_at, newest.fetched_at),
            )
        except (MarketDataUnavailableError, TypeError, ValueError, IndexError) as error:
            raise _context_unavailable() from error


def _fear_greed_history(
    payload: object,
    *,
    fetched_at: datetime,
) -> tuple[FearGreedReading, ...]:
    """从 Alternative.me 响应读取并验证按时间倒序的八条历史记录。"""
    if not isinstance(payload, Mapping):
        raise _context_unavailable()
    data = cast(Mapping[str, object], payload).get("data")
    if not isinstance(data, list):
        raise _context_unavailable()
    rows = cast(list[object], data)
    if len(rows) < 8:
        raise _context_unavailable()
    # 需要“最新值 − 7 天前值”，因此至少验证连续返回的 8 条按时间倒序数据。
    readings = tuple(_fear_greed_reading(item, fetched_at=fetched_at) for item in rows[:8])
    observed_at = tuple(reading.observed_at for reading in readings)
    if tuple(sorted(observed_at, reverse=True)) != observed_at:
        raise _context_unavailable()
    return readings


def _fear_greed_reading(item: object, *, fetched_at: datetime) -> FearGreedReading:
    """验证单条上游记录的分数、分类和时间戳，并标准化为领域模型。"""
    if not isinstance(item, Mapping):
        raise _context_unavailable()
    payload = cast(Mapping[str, object], item)
    value = _fear_greed_value(payload.get("value"))
    classification = payload.get("value_classification")
    if not isinstance(classification, str) or not classification.strip():
        raise _context_unavailable()
    return FearGreedReading(
        value=value,
        classification=classification.strip(),
        observed_at=_unix_timestamp(payload.get("timestamp")),
        fetched_at=fetched_at,
    )


def _fear_greed_value(value: object) -> int:
    """解析 0 至 100 的字符串分数，拒绝布尔值和越界内容。"""
    if isinstance(value, bool) or not isinstance(value, str):
        raise _context_unavailable()
    try:
        parsed = int(value)
    except ValueError as error:
        raise _context_unavailable() from error
    if not 0 <= parsed <= 100:
        raise _context_unavailable()
    return parsed


def _unix_timestamp(value: object) -> datetime:
    """将上游秒级 Unix 时间戳转为 UTC，并把溢出映射为上下文不可用。"""
    if isinstance(value, bool) or not isinstance(value, str):
        raise _context_unavailable()
    try:
        seconds = int(value)
    except ValueError as error:
        raise _context_unavailable() from error
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise _context_unavailable() from error


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("公开市场上下文时间必须是 UTC 且带时区")
    return value.astimezone(UTC)


def _context_unavailable() -> MarketDataUnavailableError:
    return MarketDataUnavailableError(
        _CONTEXT_ERROR_CODE,
        "公开市场上下文不可用",
    )
