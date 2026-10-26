# 目录同步任务：一次认领一个已排队任务，采集公开市场快照和费率，保存逐来源状态；
# 不会自动生成报告或订单。
# 研究币种目录：公开合约检查通过后登记币种并排队初始同步；研究准入不扩展交易契约。
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


# FundingProbe 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class FundingProbe(Protocol):
    # 读取指定窗口的已结算公开资金费率历史，不读取账户资金费。
    async def get_funding_history(
        self,
        symbol: ResearchSymbol,
        *,
        since: datetime,
        until: datetime,
    ) -> FundingHistory: ...


# 认领持久化目录同步任务，保存真实逐来源覆盖，不编造缺失数据。
class ResearchSymbolSyncWorker:
    """Claims one durable job at a time and never invents missing source data."""

    # 初始化本实例依赖和配置；输入 repository、capture、funding、clock。
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

    # 认领并处理一个持久化同步任务，保存逐来源覆盖结果；无任务返回假，已处理返回真。
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
                    # 新闻和情绪留待用户生成报告时采集，初始同步只记录部分覆盖，不伪称已经获取。
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

    # 消费已排队任务，空队列时等待停止信号；不创建定时采集、报告或交易任务。
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

    # 同步近七天费率的覆盖元数据；缺少网关或失败分别记录缺失、部分覆盖，不编造历史。
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


# 将逐来源载荷稳定序列化并计算哈希，生成带状态与安全提示的同步记录。
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


# 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("研究币对同步时钟必须使用 UTC")
    return value.astimezone(UTC)
