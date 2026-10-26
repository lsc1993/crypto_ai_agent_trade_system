# 模拟盘仓储协议：账户、操作结果和状态转换通过统一接口保存；幂等键关联一次请求及其审计结果。
# 模拟盘领域：手动请求或单次策略评估推进本地账户、仓位和审计；仅支持当前静态标的契约。
from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.paper_trading.contracts import (
    PaperAccountCreate,
    PaperAccountDetail,
    PaperAccountFilters,
    PaperAccountPage,
    PaperActionOutcome,
    PaperPerformanceData,
    PaperTransition,
)


# PaperTradingRepository 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class PaperTradingRepository(Protocol):
    # 创建模拟账户的初始资金、空仓与审计状态，返回账户详情。
    async def create_account(
        self,
        request: PaperAccountCreate,
        *,
        occurred_at: datetime,
    ) -> PaperAccountDetail: ...

    # 按筛选或归档选项读取领域记录集合/分页结果。
    async def list(self, filters: PaperAccountFilters) -> PaperAccountPage: ...

    # 按领域记录标识读取详情，不存在时返回空值。
    async def get_by_id(self, account_id: UUID) -> PaperAccountDetail | None: ...

    # 读取指定模拟账户的估值、成交、账本与事件供纯聚合计算。
    async def get_performance_data(
        self,
        account_id: UUID,
    ) -> PaperPerformanceData | None: ...

    # 按账户与幂等键查找已记录操作结果，帮助重试复用已有状态。
    async def find_outcome(
        self,
        account_id: UUID,
        idempotency_key: str,
    ) -> PaperActionOutcome | None: ...

    # 按账户与幂等键保存领域转换中的状态、订单、成交、账本及审计。
    async def apply_transition(
        self,
        account_id: UUID,
        idempotency_key: str,
        transition: PaperTransition,
        *,
        occurred_at: datetime,
    ) -> PaperAccountDetail: ...

    # 为一次模拟操作保存安全行情失败事件，保留请求关联。
    async def record_market_failure(
        self,
        account_id: UUID,
        idempotency_key: str,
        *,
        code: str,
        occurred_at: datetime,
    ) -> PaperAccountDetail: ...

    # 将领域记录标记为归档，保留历史与审计供读取。
    async def archive(
        self,
        account_id: UUID,
        *,
        occurred_at: datetime,
    ) -> PaperAccountDetail: ...
