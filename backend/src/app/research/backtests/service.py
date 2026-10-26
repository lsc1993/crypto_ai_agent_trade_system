# 回测应用协调：先创建运行记录，加载预热到结束时刻的行情，调用纯回放引擎；可预期失败保存安全终态。
# 历史回测领域：先冻结连续行情，再按收盘决策与下一根开盘成交回放；保留输入哈希和审计。
"""回测应用服务。

数据流：BacktestRequest → 先创建 pending 审计记录 → 加载受限历史 K 线 → 纯回放
引擎 → complete 或 fail 终态。服务负责 I/O、时间和运行生命周期，计算在引擎内完成。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.market.contracts import MarketDataUnavailableError
from app.market.gateway import HistoricalCandleGateway
from app.research.backtests.contracts import (
    BacktestFilters,
    BacktestNotFoundError,
    BacktestPage,
    BacktestRequest,
    ExpectedBacktestFailure,
    PersistedBacktestRun,
)
from app.research.backtests.engine import DeterministicBacktestEngine
from app.research.backtests.repository import BacktestRepository


# 协调受限历史行情、纯回放引擎和可审计回测仓储。
class BacktestService:
    """协调受限历史行情、纯回放引擎和可审计回测仓储。"""

    # 初始化本实例依赖和配置；输入 history、repository、engine、clock。
    def __init__(
        self,
        *,
        history: HistoricalCandleGateway,
        repository: BacktestRepository,
        engine: DeterministicBacktestEngine,
        clock: Callable[[], datetime],
    ) -> None:
        self._history = history
        self._repository = repository
        self._engine = engine
        self._clock = clock

    # 启动一个可审计回测，并保证市场或输入失败也会将 pending 运行结束为失败。
    async def start(self, request: BacktestRequest) -> PersistedBacktestRun:
        """启动一个可审计回测，并保证市场或输入失败也会将 pending 运行结束为失败。"""
        # 先创建 pending 记录，确保数据加载或回放失败也拥有可追踪的运行 ID 和终态。
        pending = await self._repository.create_pending(
            request,
            occurred_at=self._now(),
        )
        try:
            candles = await self._history.load_closed_candles(
                request.symbol,
                request.timeframe,
                start_at=request.warmup_start_at,
                end_at=request.end_at,
            )
            result = self._engine.run(pending.id, request, candles)
            return await self._repository.complete(
                pending.id,
                result,
                candles,
                occurred_at=self._now(),
            )
        # 外部历史数据故障保留稳定错误码后继续向上抛出，调用方可区分“失败”与正常降级。
        except MarketDataUnavailableError as error:
            await self._repository.fail(
                pending.id,
                code=error.code,
                message=str(error),
                occurred_at=self._now(),
            )
            raise
        # 可预期的输入/策略约束失败被安全地持久化为失败结果，而不是暴露为服务异常。
        except ExpectedBacktestFailure as error:
            return await self._repository.fail(
                pending.id,
                code=error.code,
                message=error.safe_message,
                occurred_at=self._now(),
            )

    # 分页读取已保存回测运行及其筛选结果。
    async def list(self, filters: BacktestFilters) -> BacktestPage:
        """分页读取已保存回测运行及其筛选结果。"""
        return await self._repository.list(filters)

    # 按 ID 读取一条回测运行，缺失时返回领域未找到错误。
    async def get(self, run_id: UUID) -> PersistedBacktestRun:
        """按 ID 读取一条回测运行，缺失时返回领域未找到错误。"""
        run = await self._repository.get_by_id(run_id)
        if run is None:
            raise BacktestNotFoundError("回测运行不存在")
        return run

    # 读取并验证服务时钟为 UTC，确保仓储生命周期事件可排序。
    def _now(self) -> datetime:
        """读取并验证服务时钟为 UTC，确保仓储生命周期事件可排序。"""
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("回测服务时钟必须返回 UTC 带时区时间")
        return value.astimezone(UTC)
