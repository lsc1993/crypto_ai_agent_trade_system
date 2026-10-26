# 回测仓储协议：先创建待运行记录，再以完成或失败终态结束，保存结果和行情输入供后续审计。
# 历史回测领域：先冻结连续行情，再按收盘决策与下一根开盘成交回放；保留输入哈希和审计。
from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.market.contracts import Candle
from app.research.backtests.contracts import (
    BacktestFilters,
    BacktestPage,
    BacktestRequest,
    BacktestResult,
    PersistedBacktestRun,
)


# BacktestRepository 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class BacktestRepository(Protocol):
    # 先保存待运行回测请求及时间，为行情加载或计算失败保留运行身份。
    async def create_pending(
        self,
        request: BacktestRequest,
        *,
        occurred_at: datetime,
    ) -> PersistedBacktestRun: ...

    # 将回测结果和精确行情输入保存为完成终态。
    async def complete(
        self,
        run_id: UUID,
        result: BacktestResult,
        candles: tuple[Candle, ...],
        *,
        occurred_at: datetime,
    ) -> PersistedBacktestRun: ...

    # 保存回测失败终态及安全错误码与提示。
    async def fail(
        self,
        run_id: UUID,
        *,
        code: str,
        message: str,
        occurred_at: datetime,
    ) -> PersistedBacktestRun: ...

    # 按筛选或归档选项读取领域记录集合/分页结果。
    async def list(self, filters: BacktestFilters) -> BacktestPage: ...

    # 按领域记录标识读取详情，不存在时返回空值。
    async def get_by_id(self, run_id: UUID) -> PersistedBacktestRun | None: ...
