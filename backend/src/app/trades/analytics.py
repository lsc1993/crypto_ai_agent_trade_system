# 日志绩效：仅聚合未归档且完整平仓记录，按平仓时间累计净盈亏、回撤与 UTC 日历；
# 持平交易不计入胜率分母。
# 手工交易日志领域：记录用户录入的历史成交与复盘，按先进先出核算盈亏；不生成交易请求。
"""已实现交易绩效统计模块。

数据流：仓储返回的已平仓交易 → 应用层资格筛选与稳定排序 → 累积权益曲线、回撤、
胜率、盈亏比和 UTC 日历聚合。归档或未完全平仓交易不会进入已实现统计。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from app.trades.contracts import (
    AnalyticsFilters,
    AnalyticsSnapshot,
    EquityPoint,
    PersistedTrade,
    TradeCalendarPoint,
    TradeFilters,
    TradeStatus,
)


# ClosedTradeReader 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class ClosedTradeReader(Protocol):
    # 读取满足筛选的已平仓手工交易，供应用层再次核对统计资格。
    async def list_closed(self, filters: TradeFilters) -> tuple[PersistedTrade, ...]: ...


# 按需汇总已完整平仓、未归档交易的已实现净盈亏。
class PerformanceAnalyticsService:
    """按需汇总已完整平仓、未归档交易的已实现净盈亏。"""

    # 初始化本实例依赖和配置；输入 repository、clock。
    def __init__(
        self,
        *,
        repository: ClosedTradeReader,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._clock = clock

    # 读取并二次筛选符合条件的已平仓交易，返回按 UTC 时间生成的统计快照。
    async def get_snapshot(self, filters: AnalyticsFilters) -> AnalyticsSnapshot:
        """读取并二次筛选符合条件的已平仓交易，返回按 UTC 时间生成的统计快照。"""
        trades = await self._repository.list_closed(_repository_filters(filters))
        # 再次在应用层筛选，避免仓储实现变化时把归档或未完成交易混入已实现绩效。
        completed = tuple(
            sorted(
                (
                    trade
                    for trade in trades
                    if _is_eligible(trade, filters)
                ),
                key=lambda trade: (trade.closed_at, str(trade.id)),
            )
        )
        return _aggregate(completed, generated_at=_utc_time(self._clock()))


# 将统计筛选投影为仓储查询，只请求 closed 状态以缩小读取范围。
def _repository_filters(filters: AnalyticsFilters) -> TradeFilters:
    """将统计筛选投影为仓储查询，只请求 closed 状态以缩小读取范围。"""
    return TradeFilters(
        page=1,
        page_size=100,
        symbol=filters.symbol,
        direction=filters.direction,
        horizon=filters.horizon,
        status=TradeStatus.CLOSED,
        label=filters.label,
        from_at=filters.from_at,
        to_at=filters.to_at,
    )


# 在应用层确认交易已完全平仓、未归档且满足所有可选筛选条件。
def _is_eligible(trade: PersistedTrade, filters: AnalyticsFilters) -> bool:
    """在应用层确认交易已完全平仓、未归档且满足所有可选筛选条件。"""
    if (
        trade.status is not TradeStatus.CLOSED
        or trade.archived_at is not None
        or trade.closed_at is None
    ):
        return False
    if filters.symbol is not None and trade.symbol is not filters.symbol:
        return False
    if filters.direction is not None and trade.direction is not filters.direction:
        return False
    if filters.horizon is not None and trade.horizon is not filters.horizon:
        return False
    if filters.label is not None and filters.label not in trade.labels:
        return False
    if filters.from_at is not None and trade.closed_at < filters.from_at:
        return False
    return filters.to_at is None or trade.closed_at <= filters.to_at


# 按平仓时间顺序累积交易净盈亏并计算权益、回撤、日历和汇总指标。
def _aggregate(
    trades: tuple[PersistedTrade, ...],
    *,
    generated_at: datetime,
) -> AnalyticsSnapshot:
    """按平仓时间顺序累积交易净盈亏并计算权益、回撤、日历和汇总指标。"""
    net_pnl = Decimal(0)
    peak_equity = Decimal(0)
    max_drawdown = Decimal(0)
    gross_profit = Decimal(0)
    gross_loss = Decimal(0)
    win_rate_denominator = 0
    winning_trades = 0
    equity_curve: list[EquityPoint] = []
    calendar: dict[datetime, tuple[Decimal, int]] = {}

    for trade in trades:
        closed_at = trade.closed_at
        assert closed_at is not None
        trade_pnl = trade.net_pnl
        net_pnl += trade_pnl
        if trade_pnl > Decimal(0):
            gross_profit += trade_pnl
            winning_trades += 1
            win_rate_denominator += 1
        elif trade_pnl < Decimal(0):
            gross_loss += -trade_pnl
            win_rate_denominator += 1

        # 权益曲线从零累计，回撤仅与此前的累计高点比较，结果为零或负数。
        peak_equity = max(peak_equity, net_pnl)
        max_drawdown = min(max_drawdown, net_pnl - peak_equity)
        equity_curve.append(
            EquityPoint(at=closed_at, equity=net_pnl, net_pnl=net_pnl)
        )

        # 日历按 UTC 自然日归组，而不是按运行机器或用户浏览器的本地时区归组。
        date_start = closed_at.astimezone(UTC).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        calendar_pnl, trade_count = calendar.get(date_start, (Decimal(0), 0))
        calendar[date_start] = (calendar_pnl + trade_pnl, trade_count + 1)

    trade_count = len(trades)
    win_rate = (
        Decimal(winning_trades) / Decimal(win_rate_denominator)
        if win_rate_denominator
        else Decimal(0)
    )
    # 没有已实现亏损时盈亏比没有有限分母，返回空值；所有已平仓记录仍参与单笔期望计算。
    profit_factor = None if gross_loss == Decimal(0) else gross_profit / gross_loss
    expectancy = net_pnl / Decimal(trade_count) if trade_count else Decimal(0)
    trade_calendar = tuple(
        TradeCalendarPoint(at=at, net_pnl=entry[0], trade_count=entry[1])
        for at, entry in sorted(calendar.items())
    )
    return AnalyticsSnapshot(
        net_pnl=net_pnl,
        win_rate=win_rate,
        profit_factor=profit_factor,
        expectancy=expectancy,
        max_drawdown=max_drawdown,
        equity_curve=tuple(equity_curve),
        trade_calendar=trade_calendar,
        generated_at=generated_at,
    )


# 拒绝非 UTC 时钟结果，避免统计生成时间与 UTC 日历边界产生歧义。
def _utc_time(value: datetime) -> datetime:
    """拒绝非 UTC 时钟结果，避免统计生成时间与 UTC 日历边界产生歧义。"""
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None:
        raise ValueError("统计时钟必须返回带时区的 UTC 时间")
    if offset != timedelta(0):
        raise ValueError("统计时钟必须返回 UTC 时间")
    return value.astimezone(UTC)
