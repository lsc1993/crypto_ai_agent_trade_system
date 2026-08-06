from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from app.paper_trading.contracts import (
    PaperAccountValuation,
    PaperDecisionStats,
    PaperEventKind,
    PaperHistoryStatus,
    PaperPerformanceData,
    PaperPerformancePoint,
    PaperPerformanceSnapshot,
    PaperValuationKind,
)
from app.strategy.contracts import IntentAction, IntentSource


def aggregate_paper_performance(
    data: PaperPerformanceData,
    *,
    generated_at: datetime,
) -> PaperPerformanceSnapshot:
    _require_utc(generated_at)
    valuations = tuple(sorted(data.valuations, key=lambda value: value.sequence))
    _validate_valuation_history(valuations)

    net_pnl = data.account.equity - data.account.initial_cash
    realized_pnl = sum((entry.realized_pnl for entry in data.ledger_entries), Decimal("0"))
    unrealized_pnl = (
        data.account.equity - data.account.cash - data.position.remaining_entry_cost
    )
    max_drawdown_amount, max_drawdown_fraction = _maximum_drawdown(valuations)
    profitable_close_count, unprofitable_close_count, break_even_close_count = _close_counts(
        data
    )
    close_denominator = profitable_close_count + unprofitable_close_count

    return PaperPerformanceSnapshot(
        account_id=data.account.id,
        initial_cash=data.account.initial_cash,
        current_equity=data.account.equity,
        net_pnl=net_pnl,
        return_fraction=net_pnl / data.account.initial_cash,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_fee=sum((fill.fee for fill in data.fills), Decimal("0")),
        max_drawdown_amount=max_drawdown_amount,
        max_drawdown_fraction=max_drawdown_fraction,
        open_fill_count=sum(
            fill.action is IntentAction.OPEN_LONG for fill in data.fills
        ),
        close_fill_count=sum(
            fill.action is IntentAction.CLOSE_LONG for fill in data.fills
        ),
        profitable_close_count=profitable_close_count,
        unprofitable_close_count=unprofitable_close_count,
        break_even_close_count=break_even_close_count,
        close_win_rate=(
            Decimal(profitable_close_count) / Decimal(close_denominator)
            if close_denominator
            else Decimal("0")
        ),
        decision_stats=_decision_stats(data),
        history_status=(
            PaperHistoryStatus.PARTIAL
            if any(
                value.kind is PaperValuationKind.MIGRATION_BASELINE
                for value in valuations
            )
            else PaperHistoryStatus.COMPLETE
        ),
        history_started_at=valuations[0].valued_at,
        history_ended_at=valuations[-1].valued_at,
        equity_curve=tuple(
            PaperPerformancePoint(
                at=value.valued_at,
                cash=value.cash,
                position_quantity=value.position_quantity,
                equity=value.equity,
                net_pnl=value.equity - data.account.initial_cash,
            )
            for value in valuations
        ),
        generated_at=generated_at,
    )


def _validate_valuation_history(values: tuple[PaperAccountValuation, ...]) -> None:
    if not values:
        raise ValueError("模拟盘绩效缺少估值历史")
    sequences = tuple(value.sequence for value in values)
    if sequences != tuple(range(len(values))):
        raise ValueError("模拟盘绩效估值序号必须从零连续递增")
    if values[0].kind is not PaperValuationKind.INITIAL:
        raise ValueError("模拟盘绩效首个估值必须是初始估值")


def _maximum_drawdown(
    values: tuple[PaperAccountValuation, ...],
) -> tuple[Decimal, Decimal]:
    peak_equity = Decimal("0")
    maximum_amount = Decimal("0")
    maximum_fraction = Decimal("0")
    for value in values:
        equity = value.equity
        peak_equity = max(peak_equity, equity)
        drawdown_amount = peak_equity - equity
        drawdown_fraction = (
            drawdown_amount / peak_equity if peak_equity else Decimal("0")
        )
        maximum_amount = max(maximum_amount, drawdown_amount)
        maximum_fraction = max(maximum_fraction, drawdown_fraction)
    return maximum_amount, maximum_fraction


def _close_counts(data: PaperPerformanceData) -> tuple[int, int, int]:
    profitable = 0
    unprofitable = 0
    break_even = 0
    for entry in data.ledger_entries:
        if entry.kind is not IntentAction.CLOSE_LONG:
            continue
        if entry.realized_pnl > Decimal("0"):
            profitable += 1
        elif entry.realized_pnl < Decimal("0"):
            unprofitable += 1
        else:
            break_even += 1
    return profitable, unprofitable, break_even


def _decision_stats(data: PaperPerformanceData) -> PaperDecisionStats:
    manual_intent_count = 0
    strategy_evaluation_count = 0
    no_signal_count = 0
    risk_rejected_count = 0
    risk_exit_count = 0
    order_count = 0

    for event in data.events:
        source = _event_source(event.payload.get("source"))
        if event.kind is PaperEventKind.INTENT:
            if source is IntentSource.MANUAL:
                manual_intent_count += 1
            if source is IntentSource.STRATEGY:
                strategy_evaluation_count += 1
        elif event.kind is PaperEventKind.NO_SIGNAL:
            no_signal_count += 1
            if source is IntentSource.STRATEGY:
                strategy_evaluation_count += 1
        elif event.kind is PaperEventKind.RISK_REJECTED:
            risk_rejected_count += 1
        elif event.kind is PaperEventKind.RISK_EXIT:
            risk_exit_count += 1
        elif event.kind is PaperEventKind.ORDER:
            order_count += 1

    return PaperDecisionStats(
        manual_intent_count=manual_intent_count,
        strategy_evaluation_count=strategy_evaluation_count,
        no_signal_count=no_signal_count,
        risk_rejected_count=risk_rejected_count,
        risk_exit_count=risk_exit_count,
        order_count=order_count,
        fill_count=len(data.fills),
    )


def _event_source(value: object) -> IntentSource | None:
    if not isinstance(value, str):
        return None
    try:
        return IntentSource(value)
    except ValueError:
        return None


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("模拟盘绩效生成时间必须是 UTC 且带时区")
