# 交易日志仓储协议：草稿和计算结果与关联审计一起创建、替换或归档；读取接口返回领域模型，
# 不连接交易所。
# 手工交易日志领域：记录用户录入的历史成交与复盘，按先进先出核算盈亏；不生成交易请求。
from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.trades.calculator import TradePnl
from app.trades.contracts import PersistedTrade, TradeDraft, TradeFilters, TradePage


# TradeRepository 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class TradeRepository(Protocol):
    # 保存手工交易草稿、已计算盈亏和关联审计，返回完整日志。
    async def create(
        self,
        *,
        draft: TradeDraft,
        pnl: TradePnl,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> PersistedTrade: ...

    # 替换活动手工交易并保存重算盈亏及审计；不能更新时返回空值。
    async def replace(
        self,
        *,
        trade_id: UUID,
        draft: TradeDraft,
        pnl: TradePnl,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> PersistedTrade | None: ...

    # 将领域记录标记为归档，保留历史与审计供读取。
    async def archive(
        self,
        trade_id: UUID,
        *,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> bool: ...

    # 按领域记录标识读取详情，不存在时返回空值。
    async def get_by_id(self, trade_id: UUID) -> PersistedTrade | None: ...

    # 按筛选或归档选项读取领域记录集合/分页结果。
    async def list(self, filters: TradeFilters) -> TradePage: ...

    # 读取满足筛选的已平仓手工交易，供应用层再次核对统计资格。
    async def list_closed(self, filters: TradeFilters) -> tuple[PersistedTrade, ...]: ...
