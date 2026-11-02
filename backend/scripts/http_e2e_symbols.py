# 隔离 HTTP 验收的币种同步装配：固定目录元数据、合成行情和受 token 保护的事件门。
# 重试路由、SQL 租约/审计、生产 worker 与快照保存保持真实；不检查公网准入或调用模型。
# SOL 首次失败后部分恢复，XRP 持续失败；这些场景只存在于开发验收，不注册到生产应用。
from __future__ import annotations

import asyncio
import hmac
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes.research_symbols import router as symbols_router
from app.infrastructure.persistence.repository import SqlAlchemyMarketRepository
from app.infrastructure.persistence.symbol_repository import SqlAlchemySymbolRepository
from app.market.capture import MarketCaptureService
from app.market.contracts import MarketDataUnavailableError, MarketDetail, MarketTimeframe
from app.market.symbols import ResearchSymbol
from app.symbols.contracts import CheckResult, MarketMetadata
from app.symbols.sync import ResearchSymbolSyncWorker
from scripts.http_e2e_research import SyntheticMarket

SYNC_SYMBOLS = ("SOLUSDT", "XRPUSDT")


class GatedSyncMarket(SyntheticMarket):
    # 初次采集直接故障；后续等待事件，让浏览器确定观察 running 后再释放，无固定 sleep。
    def __init__(self) -> None:
        super().__init__(symbols=("BTCUSDT", "ETHUSDT", *SYNC_SYMBOLS))
        self.attempts = dict.fromkeys(SYNC_SYMBOLS, 0)
        self.started = {symbol: asyncio.Event() for symbol in SYNC_SYMBOLS}
        self.release = {symbol: asyncio.Event() for symbol in SYNC_SYMBOLS}

    async def get_market(
        self, symbol: ResearchSymbol, timeframes: tuple[MarketTimeframe, ...]
    ) -> MarketDetail:
        # 故障原文含合成私有哨兵，验收要求生产 worker 丢弃它并返回固定安全失败。
        if symbol in self.attempts:
            self.attempts[symbol] += 1
            if self.attempts[symbol] > 1:
                self.started[symbol].set()
                await self.release[symbol].wait()
            if self.attempts[symbol] == 1 or symbol == "XRPUSDT":
                raise MarketDataUnavailableError(
                    "synthetic_failure", "OFFLINE_PRIVATE_sync_failure"
                )
        return await super().get_market(symbol, timeframes)


class SymbolSyncRuntime:
    # 本对象拥有一个后台消费者及事件门；close 完成后才能删除测试 schema。
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.repository = SqlAlchemySymbolRepository(factory)
        self.market = GatedSyncMarket()
        self.worker = ResearchSymbolSyncWorker(
            repository=self.repository,
            capture=MarketCaptureService(
                self.market,
                SqlAlchemyMarketRepository(factory),
                admission=self.enabled,
            ),
            funding=None,
            clock=lambda: datetime.now(UTC),
        )
        self.task: asyncio.Task[None] | None = None
        self.closed = False

    async def enabled(self, symbol: ResearchSymbol) -> bool:
        # 初始同步发生在 ready 之前，只要求目录启用；不把研究准入当作采集前置条件。
        entry = await self.repository.get(symbol)
        return entry is not None and entry.enabled

    async def seed(self) -> None:
        # 先消费迁移预置的 BTC/ETH 队列，避免它们在后续人工重试前抢占 run_once。
        # 固定元数据只为测试登记，不代表真实交易所合约检查通过。
        while await self.worker.run_once():
            pass
        for symbol in SYNC_SYMBOLS:
            await self.repository.add(
                CheckResult(
                    symbol=symbol,
                    supported=True,
                    checks=(),
                    metadata=MarketMetadata(
                        symbol=symbol,
                        base_asset=symbol.removesuffix("USDT"),
                        quote_asset="USDT",
                        margin_asset="USDT",
                        contract_type="PERPETUAL",
                        status="TRADING",
                    ),
                ),
                keywords=(),
                now=datetime.now(UTC),
            )
            # 初次失败经真实 claim/finish 留下历史，不直接写入预制失败终态。
            if not await self.worker.run_once():
                raise RuntimeError("synthetic initial sync was not consumed")

    def install(self, app: FastAPI, *, token: str) -> None:
        # 复用生产目录/重试路由；只在此独立应用增加测试事件门，不提供重置或任意采集能力。
        if not token:
            raise ValueError("HTTP E2E run token is required")
        app.state.symbol_repository = self.repository
        app.include_router(symbols_router, prefix="/api/v1")

        async def release(
            symbol: Literal["SOLUSDT", "XRPUSDT"], x_http_e2e_token: str = Header(default="")
        ) -> Response:
            # 随机 token 只由测试 runner 持有，不进入前端 bundle 或响应。
            if not hmac.compare_digest(x_http_e2e_token, token):
                raise HTTPException(status_code=403, detail="HTTP E2E control token rejected")
            self.market.release[symbol].set()
            return Response(status_code=204)

        app.add_api_route(
            "/__http_e2e__/symbol-sync/{symbol}/release", release, methods=["POST"], status_code=204
        )

    async def close(self) -> None:
        # 取消被事件门阻塞的采集并等待 worker 写入安全中断，再交还 schema 的清理权。
        if self.closed:
            return
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.closed = True


@asynccontextmanager
async def symbol_sync_runtime(
    factory: async_sessionmaker[AsyncSession], *, background: bool = True
) -> AsyncGenerator[SymbolSyncRuntime]:
    # seed 部分失败也回收本对象；单步模式供 SQL 装配测试确定推进生命周期。
    runtime = SymbolSyncRuntime(factory)
    try:
        await runtime.seed()
        if background:
            runtime.task = asyncio.create_task(runtime.worker.run_forever(asyncio.Event()))
        yield runtime
    finally:
        await runtime.close()
