from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from pydantic import JsonValue

from app.market.contracts import (
    Candle,
    ContractSymbol,
    MarketDataUnavailableError,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.gateway import PublicMarketGateway
from app.market.repository import (
    DerivativeObservation,
    MarketCaptureBatch,
    MarketRepository,
    MarketSnapshotDraft,
    MetricType,
    snapshot_payload_sha256,
)

CAPTURE_SYMBOLS = (ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT)
CAPTURE_TIMEFRAMES = (
    MarketTimeframe.M15,
    MarketTimeframe.H1,
    MarketTimeframe.H4,
    MarketTimeframe.D1,
)


class MarketCaptureService:
    """将固定范围的公开行情转换为可审计的研究快照。"""

    def __init__(
        self,
        gateway: PublicMarketGateway,
        repository: MarketRepository,
    ) -> None:
        self._gateway = gateway
        self._repository = repository

    async def capture(self, captured_at: datetime) -> tuple[UUID, ...]:
        _require_utc(captured_at)
        batches = await asyncio.gather(
            *(
                self._capture_symbol_batch(symbol, captured_at=captured_at)
                for symbol in CAPTURE_SYMBOLS
            ),
        )
        return await self._repository.persist_batches(tuple(batches))

    async def capture_symbol(
        self,
        symbol: ContractSymbol,
        *,
        captured_at: datetime,
    ) -> UUID:
        _require_utc(captured_at)
        if symbol not in CAPTURE_SYMBOLS:
            raise ValueError("标的未获准进行公开行情采集")
        snapshot_ids = await self._repository.persist_batches(
            (await self._capture_symbol_batch(symbol, captured_at=captured_at),),
        )
        if len(snapshot_ids) != 1:
            raise RuntimeError("单标的采集必须恰好持久化一个快照")
        return snapshot_ids[0]

    async def _capture_symbol_batch(
        self,
        symbol: ContractSymbol,
        *,
        captured_at: datetime,
    ) -> MarketCaptureBatch:
        detail = await self._gateway.get_market(symbol, CAPTURE_TIMEFRAMES)
        if detail.summary.symbol is not symbol:
            raise MarketDataUnavailableError(
                "market_data_invalid",
                "公开行情返回的标的不一致",
            )
        return _capture_batch(detail, captured_at)


def _capture_batch(detail: MarketDetail, captured_at: datetime) -> MarketCaptureBatch:
    candles = tuple(
        candle
        for series in detail.series
        for candle in series.candles
        if candle.close_at <= captured_at
    )
    if not candles:
        raise MarketDataUnavailableError(
            "market_data_missing",
            "公开行情未提供采集时刻前已收盘的 K 线",
        )

    observations = _observations(detail.summary)
    data_as_of = min(
        *(candle.observed_at for candle in candles),
        *(observation.observed_at for observation in observations),
    )
    payload = _snapshot_payload(detail, candles)
    snapshot = MarketSnapshotDraft(
        symbol=detail.summary.symbol,
        source=detail.summary.freshness.source,
        captured_at=captured_at,
        data_as_of=data_as_of,
        data_version="market-v1",
        payload=payload,
        payload_sha256=snapshot_payload_sha256(payload),
    )
    return MarketCaptureBatch(
        symbol=detail.summary.symbol,
        candles=candles,
        observations=observations,
        snapshot=snapshot,
    )


def _observations(summary: MarketSummary) -> tuple[DerivativeObservation, ...]:
    freshness = summary.freshness
    metric_values = (
        (MetricType.PRICE, summary.price),
        (MetricType.FUNDING_RATE, summary.funding_rate),
        (MetricType.OPEN_INTEREST, summary.open_interest),
        (MetricType.CHANGE_24H, summary.change_24h),
        (MetricType.VOLUME_24H, summary.volume_24h),
    )
    return tuple(
        DerivativeObservation(
            symbol=summary.symbol,
            metric_type=metric_type,
            value=value,
            source=freshness.source,
            observed_at=freshness.observed_at,
            fetched_at=freshness.fetched_at,
        )
        for metric_type, value in metric_values
    )


def _snapshot_payload(
    detail: MarketDetail,
    candles: tuple[Candle, ...],
) -> dict[str, JsonValue]:
    latest_closed_candles = tuple(
        max(
            (candle for candle in candles if candle.timeframe is series.timeframe),
            key=lambda candle: candle.close_at,
        )
        for series in detail.series
    )
    raw_payload = {
        "summary": detail.summary.model_dump(mode="json"),
        "latestClosedCandles": [
            candle.model_dump(mode="json") for candle in latest_closed_candles
        ],
    }
    serialized = json.dumps(
        raw_payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return cast(dict[str, JsonValue], json.loads(serialized))


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("采集时间必须是 UTC 且带时区")
