# 验证复盘统计仅纳入已完成且未归档的手动日志。
# 固定仓储样本按平仓时间排序，避免录入顺序影响统计。
# 没有亏损时利润因子为空，不用无穷值代替不可定义结果。
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.market.contracts import ContractSymbol
from app.trades.analytics import PerformanceAnalyticsService
from app.trades.contracts import (
    AnalyticsFilters,
    PersistedTrade,
    TradeDirection,
    TradeHorizon,
    TradeLegAction,
    TradeLegDraft,
    TradeStatus,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_analytics_uses_only_completed_unarchived_trades_and_orders_by_close_time() -> None:
    service = PerformanceAnalyticsService(
        repository=FakeTradeRepository(
            (
                _trade("loss", "-4", NOW + timedelta(days=1)),
                _trade("win", "5", NOW),
                _trade("flat", "0", NOW + timedelta(days=1, minutes=1)),
                _trade("open", "99", None, status=TradeStatus.OPEN),
                _trade("archived", "99", NOW, archived_at=NOW + timedelta(days=2)),
            )
        ),
        clock=lambda: NOW + timedelta(hours=2),
    )

    snapshot = await service.get_snapshot(AnalyticsFilters())

    assert snapshot.net_pnl == Decimal("1")
    assert snapshot.win_rate == Decimal("0.5")
    assert snapshot.profit_factor == Decimal("1.25")
    assert snapshot.expectancy == Decimal("0.3333333333333333333333333333")
    assert snapshot.max_drawdown == Decimal("-4")
    assert tuple(point.equity for point in snapshot.equity_curve) == (
        Decimal("5"),
        Decimal("1"),
        Decimal("1"),
    )
    assert tuple(point.at for point in snapshot.equity_curve) == (
        NOW,
        NOW + timedelta(days=1),
        NOW + timedelta(days=1, minutes=1),
    )
    assert tuple((point.net_pnl, point.trade_count) for point in snapshot.trade_calendar) == (
        (Decimal("5"), 1),
        (Decimal("-4"), 2),
    )
    assert snapshot.generated_at == NOW + timedelta(hours=2)


@pytest.mark.asyncio
async def test_analytics_returns_null_profit_factor_when_no_loss_exists() -> None:
    service = PerformanceAnalyticsService(
        repository=FakeTradeRepository((_trade("win", "5", NOW),)),
        clock=lambda: NOW,
    )

    snapshot = await service.get_snapshot(AnalyticsFilters())

    assert snapshot.profit_factor is None


class FakeTradeRepository:
    def __init__(self, trades: tuple[PersistedTrade, ...]) -> None:
        self.trades = trades
        self.filters: object | None = None

    async def list_closed(self, filters: object) -> tuple[PersistedTrade, ...]:
        self.filters = filters
        return self.trades


def _trade(
    name: str,
    net_pnl: str,
    closed_at: datetime | None,
    *,
    status: TradeStatus = TradeStatus.CLOSED,
    archived_at: datetime | None = None,
) -> PersistedTrade:
    identifier = uuid5(NAMESPACE_URL, f"https://example.invalid/trades/{name}")
    leg = TradeLegDraft(
        id=uuid5(NAMESPACE_URL, f"https://example.invalid/trades/{name}/leg"),
        action=TradeLegAction.OPEN,
        executed_at=NOW,
        sequence=0,
        price=Decimal("100"),
        quantity=Decimal("1"),
        fee=Decimal("0"),
    )
    return PersistedTrade(
        id=identifier,
        symbol=ContractSymbol.BTCUSDT,
        direction=TradeDirection.LONG,
        horizon=TradeHorizon.SHORT_TERM,
        labels=("manual",),
        linked_report_id=None,
        leverage=Decimal("1"),
        legs=(leg,),
        cashflows=(),
        thesis="thesis",
        review="review",
        status=status,
        gross_realized_pnl=Decimal(net_pnl),
        total_fees=Decimal("0"),
        total_funding_cashflow=Decimal("0"),
        net_pnl=Decimal(net_pnl),
        opened_at=NOW,
        closed_at=closed_at,
        archived_at=archived_at,
        created_at=NOW,
        updated_at=NOW,
    )
