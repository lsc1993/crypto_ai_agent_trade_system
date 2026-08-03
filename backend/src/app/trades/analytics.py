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


class ClosedTradeReader(Protocol):
    async def list_closed(self, filters: TradeFilters) -> tuple[PersistedTrade, ...]: ...


class PerformanceAnalyticsService:
    """按需汇总已完整平仓、未归档交易的已实现净盈亏。"""

    def __init__(
        self,
        *,
        repository: ClosedTradeReader,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._clock = clock

    async def get_snapshot(self, filters: AnalyticsFilters) -> AnalyticsSnapshot:
        trades = await self._repository.list_closed(_repository_filters(filters))
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


def _repository_filters(filters: AnalyticsFilters) -> TradeFilters:
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


def _is_eligible(trade: PersistedTrade, filters: AnalyticsFilters) -> bool:
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


def _aggregate(
    trades: tuple[PersistedTrade, ...],
    *,
    generated_at: datetime,
) -> AnalyticsSnapshot:
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

        peak_equity = max(peak_equity, net_pnl)
        max_drawdown = min(max_drawdown, net_pnl - peak_equity)
        equity_curve.append(
            EquityPoint(at=closed_at, equity=net_pnl, net_pnl=net_pnl)
        )

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


def _utc_time(value: datetime) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None:
        raise ValueError("统计时钟必须返回带时区的 UTC 时间")
    if offset != timedelta(0):
        raise ValueError("统计时钟必须返回 UTC 时间")
    return value.astimezone(UTC)
