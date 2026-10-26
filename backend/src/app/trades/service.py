# 手工日志协调：写入前重算先进先出盈亏，生成 UTC 审计时刻和关联 ID；已归档记录不能继续更新。
# 手工交易日志领域：记录用户录入的历史成交与复盘，按先进先出核算盈亏；不生成交易请求。
"""手工交易日志应用服务。

数据流：TradeDraft → FIFO 盈亏计算 → 仓储创建/替换/归档及关联审计事件。服务只管理
用户录入的历史交易，不生成策略意图，也不连接交易所。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.trades.calculator import TradeCalculator, TradePnl
from app.trades.contracts import PersistedTrade, TradeDraft, TradeValidationError
from app.trades.repository import TradeRepository


# 请求的活动交易不存在，或已经归档。
class TradeNotFoundError(LookupError):
    """请求的活动交易不存在，或已经归档。"""


# 手工交易日志的应用服务：先计算派生盈亏，再与审计事件一起持久化。
class TradeService:
    """手工交易日志的应用服务：先计算派生盈亏，再与审计事件一起持久化。"""

    """在写入前重算手工交易的确定性派生盈亏。"""

    # 初始化本实例依赖和配置；输入 repository、calculator、clock、correlation_id_factory。
    def __init__(
        self,
        *,
        repository: TradeRepository,
        calculator: TradeCalculator | None = None,
        clock: Callable[[], datetime] | None = None,
        correlation_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repository = repository
        self._calculator = calculator or TradeCalculator()
        self._clock = clock or _utc_now
        self._correlation_id_factory = correlation_id_factory

    # 计算草稿的派生盈亏并创建交易及其关联审计事件。
    async def create_trade(self, draft: TradeDraft) -> PersistedTrade:
        """计算草稿的派生盈亏并创建交易及其关联审计事件。"""
        # 计算在写库前完成，仓储接收的是不可与交易腿脱节的已实现盈亏快照。
        pnl = self._calculate(draft)
        occurred_at = self._event_time()
        return await self._repository.create(
            draft=draft,
            pnl=pnl,
            occurred_at=occurred_at,
            correlation_id=self._correlation_id_factory(),
        )

    # 仅替换存在且未归档交易的内容，并为新版本重新计算 FIFO 盈亏。
    async def update_trade(self, trade_id: UUID, draft: TradeDraft) -> PersistedTrade:
        """仅替换存在且未归档交易的内容，并为新版本重新计算 FIFO 盈亏。"""
        # 已归档记录不可复写，保留审计时间线而不是恢复旧记录后覆盖。
        current = await self._repository.get_by_id(trade_id)
        if current is None or current.archived_at is not None:
            raise TradeNotFoundError("交易不存在或已归档")
        pnl = self._calculate(draft)
        occurred_at = self._event_time()
        updated = await self._repository.replace(
            trade_id=trade_id,
            draft=draft,
            pnl=pnl,
            occurred_at=occurred_at,
            correlation_id=self._correlation_id_factory(),
        )
        if updated is None:
            raise TradeNotFoundError("交易不存在或已归档")
        return updated

    # 归档一笔活动交易而非物理删除，使历史审计和统计筛选仍可解释。
    async def archive_trade(self, trade_id: UUID) -> None:
        """归档一笔活动交易而非物理删除，使历史审计和统计筛选仍可解释。"""
        archived = await self._repository.archive(
            trade_id,
            occurred_at=self._event_time(),
            correlation_id=self._correlation_id_factory(),
        )
        if not archived:
            raise TradeNotFoundError("交易不存在或已归档")

    # 委托纯计算器按交易方向、交易腿和现金流得出可持久化的盈亏快照。
    def _calculate(self, draft: TradeDraft) -> TradePnl:
        """委托纯计算器按交易方向、交易腿和现金流得出可持久化的盈亏快照。"""
        return self._calculator.calculate(
            direction=draft.direction,
            legs=draft.legs,
            cashflows=draft.cashflows,
        )

    # 读取并校验 UTC 服务时钟，作为交易变更和审计事件的统一发生时间。
    def _event_time(self) -> datetime:
        """读取并校验 UTC 服务时钟，作为交易变更和审计事件的统一发生时间。"""
        # 审计事件只接受 UTC 时钟，避免跨时区排序或日报聚合出现歧义。
        occurred_at = self._clock()
        if occurred_at.tzinfo is None or occurred_at.utcoffset() != timedelta(0):
            raise TradeValidationError("服务时钟必须返回 UTC 且带时区的时间")
        return occurred_at.astimezone(UTC)


# 读取当前带时区 UTC 时间，作为默认审计时钟。
def _utc_now() -> datetime:
    return datetime.now(UTC)
