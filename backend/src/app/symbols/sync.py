# 目录同步任务：一次认领一个已排队任务，并行续租与有界采集，保存逐来源状态；
# 失去租约立即取消采集，过期失败仅可由用户手动重试，不生成报告或订单。
# 研究币种目录：公开合约检查通过后登记币种并排队初始同步；研究准入不扩展交易契约。
"""Durable public-data synchronization for admitted research symbols."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

import structlog
from pydantic import JsonValue

from app.market.capture import MarketCaptureService
from app.market.contracts import MarketDataUnavailableError
from app.market.funding_history import FundingHistory
from app.market.symbols import ResearchSymbol
from app.symbols.contracts import SymbolError, SyncRun, SyncSource
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


# 采集结果先保留在内存，只有有效租约的 finish 才能把快照关联与来源写入同步终态。
@dataclass(frozen=True)
class _SyncResult:
    snapshot_id: UUID
    sources: tuple[SyncSource, ...]


# 心跳无法确认所有权时采用保守退出；与普通采集失败区分，避免再尝试写入终态。
class _LeaseLost(RuntimeError):
    pass


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
        timeout_seconds: float = 120,
        heartbeat_seconds: float = 10,
    ) -> None:
        # 心跳必须短于仓储三十秒租约；时间参数仅用于生命周期，不参与金融计算。
        if (
            not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
            or not math.isfinite(heartbeat_seconds)
            or not 0 < heartbeat_seconds < 30
        ):
            raise ValueError("同步超时须为正数，心跳须小于三十秒租约")
        self._repository = repository
        self._capture = capture
        self._funding = funding
        self._clock = clock
        self._timeout_seconds = timeout_seconds
        self._heartbeat_seconds = heartbeat_seconds

    # 认领并处理一个持久化同步任务，保存逐来源覆盖结果；无任务返回假，已处理返回真。
    async def run_once(self) -> bool:
        """Process one queued run and retain a source-level audit result."""
        now = _utc(self._clock())
        run = await self._repository.claim(now=now)
        if run is None:
            return False
        work = asyncio.create_task(self._collect_and_finish(run, now))
        pulse = asyncio.create_task(self._heartbeat(run))
        try:
            # 总截止覆盖采集、资金费率与终态提交；心跳与采集竞争，心跳先结束优先失败关闭。
            async with asyncio.timeout(self._timeout_seconds):
                done, _ = await asyncio.wait((work, pulse), return_when=asyncio.FIRST_COMPLETED)
                if pulse in done:
                    await pulse
                    raise _LeaseLost()
                await work
        except _LeaseLost:
            # 租约丢失或续租存储故障都不能证明仍可写入；停止工作，留待过期回收。
            pass
        except asyncio.CancelledError:
            work.cancel()
            pulse.cancel()
            await self._fail_if_owned(run, "sync_interrupted", "同步任务已中断，请重试。")
            raise
        except TimeoutError:
            work.cancel()
            pulse.cancel()
            await self._fail_if_owned(run, "sync_timeout", "同步任务超时，请稍后重试。")
        except Exception:
            await self._fail_if_owned(run, "market_sync_failed", "公开行情同步失败，请稍后重试。")
        finally:
            # 终态保存后也必须回收心跳。默认适配器支持协程取消，不让任务跨 run 存活。
            for task in (work, pulse):
                if not task.done():
                    task.cancel()
            try:
                async with asyncio.timeout(2):
                    await asyncio.gather(work, pulse, return_exceptions=True)
            except TimeoutError:
                structlog.get_logger(__name__).info(
                    "symbol_sync_cleanup_timeout", run_id=str(run.id)
                )
        return True

    # 周期续租；存储异常只转成内部所有权丢失，不传播第三方异常正文。
    async def _heartbeat(self, run: SyncRun) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            try:
                renewed = await self._repository.renew(run, now=_utc(self._clock()))
            except Exception:
                raise _LeaseLost() from None
            if not renewed:
                raise _LeaseLost()

    # 把终态提交纳入 work：提交等待期间若心跳失败，run_once 同样取消该事务协程。
    # 已完成的数据库提交无法撤销，仓储不可变终态和租约校验仍是最终写入边界。
    async def _collect_and_finish(self, run: SyncRun, now: datetime) -> None:
        result = await self._collect(run, now)
        await self._repository.finish(
            run,
            status=(
                "ready"
                if all(item.status == "available" for item in result.sources[:4])
                else "partial"
            ),
            sources=result.sources,
            snapshot_id=result.snapshot_id,
            error=None,
            now=_utc(self._clock()),
        )

    # 保存安全失败且限制清理耗时；仓储仍核对租约，不会覆盖已成功提交的不可变终态。
    async def _fail_if_owned(self, run: SyncRun, code: str, message: str) -> None:
        try:
            async with asyncio.timeout(2):
                await self._repository.finish(
                    run,
                    status="failed",
                    sources=(_source("market", "failed", message, {}),),
                    snapshot_id=None,
                    error=code,
                    now=_utc(self._clock()),
                )
        except Exception:
            structlog.get_logger(__name__).info(
                "symbol_sync_finish_unavailable",
                run_id=str(run.id),
                error_code=code,
            )

    # 沿用既有公开采集流程；原始不可变行情可先提交，任务准入只由有效租约 finish 确认。
    async def _collect(self, run: SyncRun, now: datetime) -> _SyncResult:
        snapshot_id = await self._capture.capture_symbol(run.symbol, captured_at=now)
        snapshot_payload: dict[str, JsonValue] = {"snapshotId": str(snapshot_id)}
        sources = [
            _source("market", "available", "行情摘要与衍生品指标已同步。", snapshot_payload),
            _source("candles", "available", "四个周期的已收盘 K 线已同步。", snapshot_payload),
            _source("derivatives", "available", "公开衍生品指标已同步。", snapshot_payload),
            await self._sync_funding(run.symbol, now),
            # 新闻和情绪仍由报告按需采集，不能把登记冒充真实同步完成。
            _source("news", "partial", "已登记资讯将在生成研究报告时按需同步。", {}),
            _source("sentiment", "partial", "公开市场情绪将在生成研究报告时按需同步。", {}),
            _source("etf", "unsupported", "当前数据源不支持", {}),
        ]
        return _SyncResult(snapshot_id, tuple(sources))

    # 消费已排队任务，空队列时等待停止信号；不创建定时采集、报告或交易任务。
    async def run_forever(self, stop: asyncio.Event) -> None:
        """Drain queued jobs and wait briefly when the durable queue is empty."""
        while not stop.is_set():
            try:
                if await self.run_once():
                    continue
            except SymbolError:
                # 暂时不可用不杀死后台消费循环；只保存固定诊断，不记录连接或异常正文。
                structlog.get_logger(__name__).info("symbol_sync_queue_unavailable")
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
