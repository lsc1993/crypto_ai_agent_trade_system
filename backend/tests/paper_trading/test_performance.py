from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import JsonValue

from app.execution.contracts import DEFAULT_EXECUTION_CONFIG, OrderStatus, SimulatedFill
from app.market.contracts import ContractSymbol
from app.paper_trading.contracts import (
    PaperAccount,
    PaperAccountStatus,
    PaperAccountValuation,
    PaperAuditEvent,
    PaperEventKind,
    PaperHistoryStatus,
    PaperLedgerEntry,
    PaperPerformanceData,
    PaperPosition,
    PaperValuationKind,
)
from app.paper_trading.performance import aggregate_paper_performance
from app.risk.contracts import DEFAULT_RISK_CONFIG
from app.strategy.contracts import IntentAction

ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000907")
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000908")
NOW = datetime(2026, 8, 6, 12, tzinfo=UTC)


def test_aggregate_paper_performance_calculates_loss_drawdown_and_audit_counts() -> None:
    snapshot = aggregate_paper_performance(
        PaperPerformanceData(
            account=_account(cash="8000", equity="9500", peak_equity="11000"),
            position=_position(quantity="10", remaining_entry_cost="1400"),
            valuations=(
                _valuation(0, PaperValuationKind.INITIAL, "10000"),
                _valuation(1, PaperValuationKind.MARKET_VALUATION, "11000"),
                _valuation(2, PaperValuationKind.MARKET_VALUATION, "9500"),
            ),
            fills=(
                _fill(IntentAction.OPEN_LONG, fee="3"),
                _fill(IntentAction.CLOSE_LONG, fee="4"),
            ),
            ledger_entries=(
                _ledger(IntentAction.OPEN_LONG, realized_pnl="0"),
                _ledger(IntentAction.CLOSE_LONG, realized_pnl="-600"),
            ),
            events=(
                _event(0, PaperEventKind.INTENT, {"source": "manual"}),
                _event(1, PaperEventKind.NO_SIGNAL, {"source": "strategy"}),
                _event(2, PaperEventKind.RISK_REJECTED, {"reason": "cooldown"}),
                _event(3, PaperEventKind.RISK_EXIT, {"reason": "stop_loss"}),
                _event(4, PaperEventKind.ORDER, {"action": "open_long"}),
                _event(5, PaperEventKind.FILL, {"action": "open_long"}),
            ),
        ),
        generated_at=NOW + timedelta(minutes=5),
    )

    assert snapshot.net_pnl == Decimal("-500")
    assert snapshot.return_fraction == Decimal("-0.05")
    assert snapshot.realized_pnl == Decimal("-600")
    assert snapshot.unrealized_pnl == Decimal("100")
    assert snapshot.total_fee == Decimal("7")
    assert snapshot.max_drawdown_amount == Decimal("1500")
    assert snapshot.max_drawdown_fraction == Decimal("1500") / Decimal("11000")
    assert snapshot.open_fill_count == 1
    assert snapshot.close_fill_count == 1
    assert snapshot.profitable_close_count == 0
    assert snapshot.unprofitable_close_count == 1
    assert snapshot.break_even_close_count == 0
    assert snapshot.close_win_rate == Decimal("0")
    assert snapshot.decision_stats.manual_intent_count == 1
    assert snapshot.decision_stats.strategy_evaluation_count == 1
    assert snapshot.decision_stats.no_signal_count == 1
    assert snapshot.decision_stats.risk_rejected_count == 1
    assert snapshot.decision_stats.risk_exit_count == 1
    assert snapshot.decision_stats.order_count == 1
    assert snapshot.decision_stats.fill_count == 2
    assert snapshot.history_status is PaperHistoryStatus.COMPLETE
    assert tuple(point.equity for point in snapshot.equity_curve) == (
        Decimal("10000"),
        Decimal("11000"),
        Decimal("9500"),
    )


def test_aggregate_paper_performance_marks_migration_baseline_as_partial_history() -> None:
    snapshot = aggregate_paper_performance(
        PaperPerformanceData(
            account=_account(cash="10000", equity="10000", peak_equity="10000"),
            position=_position(),
            valuations=(
                _valuation(0, PaperValuationKind.INITIAL, "10000"),
                _valuation(1, PaperValuationKind.MIGRATION_BASELINE, "10000"),
            ),
            fills=(),
            ledger_entries=(),
            events=(),
        ),
        generated_at=NOW,
    )

    assert snapshot.history_status is PaperHistoryStatus.PARTIAL
    assert snapshot.close_fill_count == 0
    assert snapshot.close_win_rate == Decimal("0")
    assert snapshot.max_drawdown_amount == Decimal("0")
    assert snapshot.max_drawdown_fraction == Decimal("0")


def _account(*, cash: str, equity: str, peak_equity: str) -> PaperAccount:
    return PaperAccount(
        id=ACCOUNT_ID,
        status=PaperAccountStatus.ACTIVE,
        symbol=ContractSymbol.BTCUSDT,
        initial_cash=Decimal("10000"),
        cash=Decimal(cash),
        equity=Decimal(equity),
        peak_equity=Decimal(peak_equity),
        daily_start_equity=Decimal("10000"),
        daily_realized_loss=Decimal("0"),
        daily_day=NOW.date(),
        cooldown_remaining=0,
        last_closed_candle_at=None,
        risk_config=DEFAULT_RISK_CONFIG,
        execution_config=DEFAULT_EXECUTION_CONFIG,
        created_at=NOW,
        archived_at=None,
    )


def _position(
    *,
    quantity: str = "0",
    remaining_entry_cost: str = "0",
) -> PaperPosition:
    is_open = Decimal(quantity) > Decimal("0")
    return PaperPosition(
        account_id=ACCOUNT_ID,
        quantity=Decimal(quantity),
        average_entry_price=Decimal("140") if is_open else None,
        remaining_entry_cost=Decimal(remaining_entry_cost),
        opened_at=NOW if is_open else None,
        updated_at=NOW,
    )


def _valuation(
    sequence: int,
    kind: PaperValuationKind,
    equity: str,
) -> PaperAccountValuation:
    return PaperAccountValuation(
        account_id=ACCOUNT_ID,
        sequence=sequence,
        kind=kind,
        snapshot_id=None if kind is PaperValuationKind.INITIAL else SNAPSHOT_ID,
        valued_at=NOW + timedelta(hours=sequence),
        cash=Decimal(equity),
        position_quantity=Decimal("0"),
        equity=Decimal(equity),
        peak_equity=max(Decimal("10000"), Decimal(equity)),
    )


def _fill(action: IntentAction, *, fee: str) -> SimulatedFill:
    return SimulatedFill(
        run_id=ACCOUNT_ID,
        symbol=ContractSymbol.BTCUSDT,
        action=action,
        order_idempotency_key=f"paper:performance:{action.value}:{fee}",
        submitted_at=NOW,
        filled_at=NOW,
        requested_quantity=Decimal("1"),
        quantity=Decimal("1"),
        price=Decimal("100"),
        fee=Decimal(fee),
        status=OrderStatus.FILLED,
    )


def _ledger(action: IntentAction, *, realized_pnl: str) -> PaperLedgerEntry:
    return PaperLedgerEntry(
        occurred_at=NOW,
        kind=action,
        cash_delta=Decimal("0"),
        position_delta=Decimal("0"),
        realized_pnl=Decimal(realized_pnl),
        fee=Decimal("0"),
        cash_after=Decimal("10000"),
        quantity_after=Decimal("0"),
    )


def _event(
    sequence: int,
    kind: PaperEventKind,
    payload: dict[str, JsonValue],
) -> PaperAuditEvent:
    return PaperAuditEvent(
        sequence=sequence,
        kind=kind,
        occurred_at=NOW,
        idempotency_key=f"paper:performance:event:{sequence}",
        payload=payload,
    )
