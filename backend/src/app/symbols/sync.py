"""Durable public-data synchronization for admitted research symbols."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import JsonValue

from app.market.capture import MarketCaptureService
from app.market.contracts import MarketDataUnavailableError
from app.market.funding_history import FundingHistory
from app.market.symbols import ResearchSymbol
from app.symbols.contracts import SyncSource
from app.symbols.repository import SymbolRepository


class FundingProbe(Protocol):
    async def get_funding_history(
        self,
        symbol: ResearchSymbol,
        *,
        since: datetime,
        until: datetime,
    ) -> FundingHistory: ...


class ResearchSymbolSyncWorker:
    """Claims one durable job at a time and never invents missing source data."""

    def __init__(
        self,
        *,
        repository: SymbolRepository,
        capture: MarketCaptureService,
        funding: FundingProbe | None,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._capture = capture
        self._funding = funding
        self._clock = clock

    async def run_once(self) -> bool:
        """Process one queued run and retain a source-level audit result."""
        now = _utc(self._clock())
        run = await self._repository.claim(now=now)
        if run is None:
            return False
        try:
            snapshot_id = await self._capture.capture_symbol(
                run.symbol,
                captured_at=now,
            )
            snapshot_payload: dict[str, JsonValue] = {"snapshotId": str(snapshot_id)}
            sources: list[SyncSource] = [
                _source("market", "available", "行情摘要与衍生品指标已同步。", snapshot_payload),
                _source("candles", "available", "四个周期的已收盘 K 线已同步。", snapshot_payload),
                _source("derivatives", "available", "公开衍生品指标已同步。", snapshot_payload),
            ]
            sources.append(await self._sync_funding(run.symbol, now))
            sources.extend(
                (
                    _source("news", "partial", "已登记资讯将在生成研究报告时按需同步。", {}),
                    _source("sentiment", "partial", "公开市场情绪将在生成研究报告时按需同步。", {}),
                    _source("etf", "unsupported", "当前数据源不支持", {}),
                )
            )
            await self._repository.finish(
                run,
                status=(
                    "ready"
                    if all(item.status == "available" for item in sources[:4])
                    else "partial"
                ),
                sources=tuple(sources),
                snapshot_id=snapshot_id,
                error=None,
                now=_utc(self._clock()),
            )
        except MarketDataUnavailableError:
            await self._repository.finish(
                run,
                status="failed",
                sources=(_source("market", "failed", "公开行情同步失败，请稍后重试。", {}),),
                snapshot_id=None,
                error="market_sync_failed",
                now=_utc(self._clock()),
            )
        except Exception:
            # Do not surface third-party exception text into durable user-facing state.
            await self._repository.finish(
                run,
                status="failed",
                sources=(_source("market", "failed", "公开行情同步失败，请稍后重试。", {}),),
                snapshot_id=None,
                error="market_sync_failed",
                now=_utc(self._clock()),
            )
        return True

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Drain queued jobs and wait briefly when the durable queue is empty."""
        while not stop.is_set():
            worked = await self.run_once()
            if worked:
                continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                continue

    async def _sync_funding(self, symbol: ResearchSymbol, now: datetime) -> SyncSource:
        if self._funding is None:
            return _source("funding", "missing", "当前市场网关未提供资金费率历史。", {})
        try:
            history = await self._funding.get_funding_history(
                symbol,
                since=now - timedelta(days=7),
                until=now,
            )
            return _source(
                "funding",
                "available" if history.points else "partial",
                "近七天资金费率历史已同步。" if history.points else "资金费率历史不足。",
                {
                    "pointCount": len(history.points),
                    "fetchedAt": history.fetched_at.isoformat(),
                },
            )
        except (MarketDataUnavailableError, ValueError):
            return _source("funding", "partial", "资金费率历史暂时不可用。", {})


def _source(
    name: str,
    status: str,
    message: str,
    payload: dict[str, JsonValue],
) -> SyncSource:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return SyncSource(
        name=name,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        message=message,
        payload=payload,
        payload_sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("研究币对同步时钟必须使用 UTC")
    return value.astimezone(UTC)
