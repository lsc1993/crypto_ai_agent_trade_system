from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.market.binance_usdm import PublicDerivativesMetrics
from app.market.contracts import ContractSymbol, FreshnessStatus, MarketDataUnavailableError

ALTERNATIVE_ME_BASE_URL = "https://api.alternative.me"
_CONTEXT_ERROR_CODE = "market_context_unavailable"


class PublicResearchContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: ContractSymbol
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
        symbol: ContractSymbol,
    ) -> PublicDerivativesMetrics: ...


@dataclass(frozen=True)
class FearGreedReading:
    value: int
    classification: str
    observed_at: datetime
    fetched_at: datetime


class AlternativeMeFearGreedGateway:
    """Fixed-host reader for Alternative.me's public fear-and-greed feed."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        clock: Callable[[], datetime],
    ) -> None:
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
        symbol: ContractSymbol,
        *,
        captured_at: datetime,
    ) -> PublicResearchContext:
        captured_at = _require_utc(captured_at)
        try:
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
    if not isinstance(payload, Mapping):
        raise _context_unavailable()
    data = cast(Mapping[str, object], payload).get("data")
    if not isinstance(data, list):
        raise _context_unavailable()
    rows = cast(list[object], data)
    if len(rows) < 8:
        raise _context_unavailable()
    readings = tuple(_fear_greed_reading(item, fetched_at=fetched_at) for item in rows[:8])
    observed_at = tuple(reading.observed_at for reading in readings)
    if tuple(sorted(observed_at, reverse=True)) != observed_at:
        raise _context_unavailable()
    return readings


def _fear_greed_reading(item: object, *, fetched_at: datetime) -> FearGreedReading:
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
