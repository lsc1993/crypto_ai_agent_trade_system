# 模拟盘绩效：校验估值序号连续性，再计算权益、回撤、已实现盈亏和决策计数；迁移基线需显示部分历史。
# 模拟盘领域：手动请求或单次策略评估推进本地账户、仓位和审计；仅支持当前静态标的契约。
"""模拟盘绩效聚合模块。

数据流：账户当前状态、连续估值历史、账本、成交和审计事件 → 盈亏/回撤/胜率/决策
统计及权益曲线。所有金额保持 Decimal，所有时间按 UTC 解释。
"""

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


# 将一个账户的原始模拟盘历史汇总为供 API 和前端展示的绩效快照。
def aggregate_paper_performance(
    data: PaperPerformanceData,
    *,
    generated_at: datetime,
) -> PaperPerformanceSnapshot:
    """将一个账户的原始模拟盘历史汇总为供 API 和前端展示的绩效快照。"""
    _require_utc(generated_at)
    # 绩效曲线以审计序号而非数据库返回顺序为准，先校验连续性再计算派生指标。
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
    # 胜率按账本平仓记录的盈利和亏损次数计算，持平与部分平仓统计应按记录口径理解。
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
        # 迁移生成的基线没有逐笔历史，前端须显示“部分历史”而不能当作完整业绩。
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


# 确保估值历史非空、从初始值开始且 sequence 连续，避免指标基于残缺时间线。
def _validate_valuation_history(values: tuple[PaperAccountValuation, ...]) -> None:
    """确保估值历史非空、从初始值开始且 sequence 连续，避免指标基于残缺时间线。"""
    if not values:
        raise ValueError("模拟盘绩效缺少估值历史")
    sequences = tuple(value.sequence for value in values)
    if sequences != tuple(range(len(values))):
        raise ValueError("模拟盘绩效估值序号必须从零连续递增")
    if values[0].kind is not PaperValuationKind.INITIAL:
        raise ValueError("模拟盘绩效首个估值必须是初始估值")


# 扫描估值权益的历史高水位，返回最大金额回撤与最大比例回撤。
def _maximum_drawdown(
    values: tuple[PaperAccountValuation, ...],
) -> tuple[Decimal, Decimal]:
    """扫描估值权益的历史高水位，返回最大金额回撤与最大比例回撤。"""
    peak_equity = Decimal("0")
    maximum_amount = Decimal("0")
    maximum_fraction = Decimal("0")
    # 高水位随时间单向更新；每个时点只和此前峰值比较，符合最大回撤定义。
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


# 按账本中已实现平仓盈亏统计盈利、亏损和持平次数。
def _close_counts(data: PaperPerformanceData) -> tuple[int, int, int]:
    """按账本中已实现平仓盈亏统计盈利、亏损和持平次数。"""
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


# 从审计事件重建手工/策略决策、无信号、拒绝、风险退出和订单统计。
def _decision_stats(data: PaperPerformanceData) -> PaperDecisionStats:
    """从审计事件重建手工/策略决策、无信号、拒绝、风险退出和订单统计。"""
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


# 把事件中的来源字符串解析为有限来源枚举，类型或枚举无效时返回空值。
def _event_source(value: object) -> IntentSource | None:
    if not isinstance(value, str):
        return None
    try:
        return IntentSource(value)
    except ValueError:
        return None


# 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("模拟盘绩效生成时间必须是 UTC 且带时区")
