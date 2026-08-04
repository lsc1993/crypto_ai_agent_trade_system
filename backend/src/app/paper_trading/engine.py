from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from json import dumps

from pydantic import JsonValue

from app.execution.contracts import ExecutionQuote, SimulatedFill, SimulatedOrder
from app.execution.simulator import SimulatedExecutionService
from app.paper_trading.contracts import (
    PaperAccount,
    PaperAccountStateError,
    PaperAccountStatus,
    PaperActionOutcome,
    PaperActionOutcomeKind,
    PaperAuditEvent,
    PaperEventKind,
    PaperLedgerEntry,
    PaperMarketSnapshot,
    PaperPosition,
    PaperTransition,
)
from app.risk.contracts import PortfolioSnapshot
from app.risk.engine import RiskEngine
from app.strategy.contracts import IntentAction, IntentSource, TradeIntent


class PaperTradingEngine:
    """只根据冻结报价和领域状态推进模拟账户。"""

    def apply(
        self,
        *,
        account: PaperAccount,
        position: PaperPosition,
        intent: TradeIntent | None,
        quote: ExecutionQuote,
        latest_closed_candle_at: datetime,
    ) -> PaperTransition:
        self._validate_inputs(account, position, intent, quote, latest_closed_candle_at)
        advanced_account = self._advance_account(
            account,
            position=position,
            quote=quote,
            latest_closed_candle_at=latest_closed_candle_at,
        )
        snapshot = PaperMarketSnapshot.from_quote(
            quote,
            payload_hash=_snapshot_hash(quote),
        )
        events: list[PaperAuditEvent] = []

        if intent is None:
            _append_event(
                events,
                kind=PaperEventKind.NO_SIGNAL,
                occurred_at=quote.observed_at,
                idempotency_key=None,
                payload={"symbol": quote.symbol.value},
            )
            return PaperTransition(
                account=advanced_account,
                position=position,
                snapshot=snapshot,
                orders=(),
                fills=(),
                ledger_entries=(),
                events=tuple(events),
                outcome=PaperActionOutcome(
                    kind=PaperActionOutcomeKind.NO_SIGNAL,
                    source=None,
                    idempotency_key=None,
                ),
            )

        _append_event(
            events,
            kind=PaperEventKind.INTENT,
            occurred_at=intent.decision_at,
            idempotency_key=intent.idempotency_key,
            payload={"action": intent.action.value, "source": intent.source.value},
        )
        risk_engine = RiskEngine(advanced_account.risk_config)
        risk_exit_reason = self._risk_exit_reason(
            risk_engine,
            account=advanced_account,
            position=position,
            quote=quote,
        )
        if risk_exit_reason is not None:
            risk_intent = TradeIntent(
                run_id=account.id,
                symbol=account.symbol,
                action=IntentAction.CLOSE_LONG,
                decision_at=quote.observed_at,
                source=IntentSource.RISK,
                idempotency_key=(
                    f"{account.id}:risk-exit:{risk_exit_reason}:{quote.observed_at.isoformat()}"
                ),
            )
            _append_event(
                events,
                kind=PaperEventKind.RISK_EXIT,
                occurred_at=quote.observed_at,
                idempotency_key=risk_intent.idempotency_key,
                payload={"reason": risk_exit_reason},
            )
            return self._evaluate_and_fill(
                account=advanced_account,
                position=position,
                intent=risk_intent,
                quote=quote,
                snapshot=snapshot,
                events=events,
                risk_exit=True,
                outcome_kind=PaperActionOutcomeKind.RISK_EXIT,
                outcome_reason=risk_exit_reason,
            )

        return self._evaluate_and_fill(
            account=advanced_account,
            position=position,
            intent=intent,
            quote=quote,
            snapshot=snapshot,
            events=events,
            risk_exit=False,
            outcome_kind=PaperActionOutcomeKind.FILLED,
            outcome_reason=None,
        )

    @staticmethod
    def _validate_inputs(
        account: PaperAccount,
        position: PaperPosition,
        intent: TradeIntent | None,
        quote: ExecutionQuote,
        latest_closed_candle_at: datetime,
    ) -> None:
        if account.status is not PaperAccountStatus.ACTIVE:
            raise PaperAccountStateError("归档模拟账户不可操作")
        if position.account_id != account.id:
            raise ValueError("模拟仓位必须属于当前账户")
        if quote.symbol is not account.symbol:
            raise ValueError("模拟盘行情标的必须与账户一致")
        if intent is not None and (
            intent.run_id != account.id or intent.symbol is not account.symbol
        ):
            raise ValueError("模拟盘意图必须属于当前账户和标的")
        if (
            latest_closed_candle_at.tzinfo is None
            or latest_closed_candle_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("最近已收盘 K 线时间必须是 UTC 且带时区")

    def _advance_account(
        self,
        account: PaperAccount,
        *,
        position: PaperPosition,
        quote: ExecutionQuote,
        latest_closed_candle_at: datetime,
    ) -> PaperAccount:
        latest_close = latest_closed_candle_at.astimezone(UTC)
        if (
            account.last_closed_candle_at is not None
            and latest_close < account.last_closed_candle_at
        ):
            raise PaperAccountStateError("最近已收盘 K 线时间不能倒退")
        elapsed_candles = 0
        if account.last_closed_candle_at is not None:
            elapsed_candles = int(
                (latest_close - account.last_closed_candle_at) / timedelta(hours=1)
            )
        equity = account.cash + position.quantity * quote.price
        peak_equity = max(account.peak_equity, equity)
        daily_day = latest_close.date()
        if daily_day != account.daily_day:
            daily_start_equity = equity
            daily_realized_loss = Decimal("0")
        else:
            daily_start_equity = account.daily_start_equity
            daily_realized_loss = account.daily_realized_loss
        return account.model_copy(
            update={
                "equity": equity,
                "peak_equity": peak_equity,
                "daily_day": daily_day,
                "daily_start_equity": daily_start_equity,
                "daily_realized_loss": daily_realized_loss,
                "cooldown_remaining": max(0, account.cooldown_remaining - elapsed_candles),
                "last_closed_candle_at": latest_close,
            }
        )

    @staticmethod
    def _portfolio(
        account: PaperAccount,
        position: PaperPosition,
    ) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            cash=account.cash,
            equity=account.equity,
            peak_equity=account.peak_equity,
            daily_start_equity=account.daily_start_equity,
            daily_realized_loss=account.daily_realized_loss,
            position_quantity=position.quantity,
            entry_price=position.average_entry_price,
            cooldown_remaining=account.cooldown_remaining,
        )

    def _risk_exit_reason(
        self,
        risk_engine: RiskEngine,
        *,
        account: PaperAccount,
        position: PaperPosition,
        quote: ExecutionQuote,
    ) -> str | None:
        portfolio = self._portfolio(account, position)
        if risk_engine.stop_loss_triggered(portfolio, close_price=quote.price):
            return "stop_loss"
        if (
            position.quantity > Decimal("0")
            and account.peak_equity > Decimal("0")
            and (account.peak_equity - account.equity) / account.peak_equity
            >= account.risk_config.max_drawdown_fraction
        ):
            return "circuit_breaker"
        return None

    def _evaluate_and_fill(
        self,
        *,
        account: PaperAccount,
        position: PaperPosition,
        intent: TradeIntent,
        quote: ExecutionQuote,
        snapshot: PaperMarketSnapshot,
        events: list[PaperAuditEvent],
        risk_exit: bool,
        outcome_kind: PaperActionOutcomeKind,
        outcome_reason: str | None,
    ) -> PaperTransition:
        decision = RiskEngine(account.risk_config).evaluate(
            intent,
            self._portfolio(account, position),
            quote.price,
        )
        if not decision.approved:
            _append_event(
                events,
                kind=PaperEventKind.RISK_REJECTED,
                occurred_at=quote.observed_at,
                idempotency_key=intent.idempotency_key,
                payload={
                    "reason": (
                        decision.reason.value if decision.reason is not None else "unknown"
                    )
                },
            )
            return PaperTransition(
                account=account,
                position=position,
                snapshot=snapshot,
                orders=(),
                fills=(),
                ledger_entries=(),
                events=tuple(events),
                outcome=PaperActionOutcome(
                    kind=PaperActionOutcomeKind.RISK_REJECTED,
                    source=intent.source,
                    idempotency_key=intent.idempotency_key,
                    reason=None if decision.reason is None else decision.reason.value,
                ),
            )
        _append_event(
            events,
            kind=PaperEventKind.RISK_APPROVED,
            occurred_at=quote.observed_at,
            idempotency_key=intent.idempotency_key,
            payload={"quantity": _decimal_text(decision.quantity)},
        )
        order = SimulatedOrder.from_risk_decision(
            intent,
            decision,
            submitted_at=quote.observed_at,
        )
        _append_event(
            events,
            kind=PaperEventKind.ORDER,
            occurred_at=order.submitted_at,
            idempotency_key=order.idempotency_key,
            payload={
                "action": order.action.value,
                "requested_quantity": _decimal_text(order.requested_quantity),
            },
        )
        fill = SimulatedExecutionService(account.execution_config).submit_and_fill_at_quote(
            order,
            quote,
        )
        updated_account, updated_position, ledger_entry = self._apply_fill(
            account,
            position=position,
            fill=fill,
            quote=quote,
            risk_exit=risk_exit,
        )
        _append_event(
            events,
            kind=PaperEventKind.FILL,
            occurred_at=fill.filled_at,
            idempotency_key=fill.order_idempotency_key,
            payload={
                "action": fill.action.value,
                "quantity": _decimal_text(fill.quantity),
                "price": _decimal_text(fill.price),
                "fee": _decimal_text(fill.fee),
                "status": fill.status.value,
            },
        )
        return PaperTransition(
            account=updated_account,
            position=updated_position,
            snapshot=snapshot,
            orders=(order,),
            fills=(fill,),
            ledger_entries=(ledger_entry,),
            events=tuple(events),
            outcome=PaperActionOutcome(
                kind=outcome_kind,
                source=intent.source,
                idempotency_key=intent.idempotency_key,
                reason=outcome_reason,
            ),
        )

    @staticmethod
    def _apply_fill(
        account: PaperAccount,
        *,
        position: PaperPosition,
        fill: SimulatedFill,
        quote: ExecutionQuote,
        risk_exit: bool,
    ) -> tuple[PaperAccount, PaperPosition, PaperLedgerEntry]:
        if fill.action is IntentAction.OPEN_LONG:
            cost = fill.quantity * fill.price + fill.fee
            cash_after = account.cash - cost
            if position.quantity == Decimal("0"):
                average_entry_price = fill.price
                opened_at = fill.filled_at
            else:
                if position.average_entry_price is None:
                    raise PaperAccountStateError("模拟仓位缺少开仓均价")
                total_notional = (
                    position.quantity * position.average_entry_price + fill.quantity * fill.price
                )
                average_entry_price = total_notional / (position.quantity + fill.quantity)
                opened_at = position.opened_at
            quantity_after = position.quantity + fill.quantity
            position_after = PaperPosition(
                account_id=position.account_id,
                quantity=quantity_after,
                average_entry_price=average_entry_price,
                remaining_entry_cost=position.remaining_entry_cost + cost,
                opened_at=opened_at,
                updated_at=fill.filled_at,
            )
            account_after = _mark_account(account, position_after, quote=quote, cash=cash_after)
            ledger = PaperLedgerEntry(
                occurred_at=fill.filled_at,
                kind=fill.action,
                cash_delta=-cost,
                position_delta=fill.quantity,
                realized_pnl=Decimal("0"),
                fee=fill.fee,
                cash_after=cash_after,
                quantity_after=quantity_after,
            )
            return account_after, position_after, ledger

        if fill.quantity > position.quantity:
            raise PaperAccountStateError("模拟平仓数量超过当前仓位")
        allocated_cost = position.remaining_entry_cost * fill.quantity / position.quantity
        proceeds = fill.quantity * fill.price - fill.fee
        realized_pnl = proceeds - allocated_cost
        cash_after = account.cash + proceeds
        quantity_after = position.quantity - fill.quantity
        position_after = PaperPosition(
            account_id=position.account_id,
            quantity=quantity_after,
            average_entry_price=(
                None if quantity_after == Decimal("0") else position.average_entry_price
            ),
            remaining_entry_cost=(
                Decimal("0")
                if quantity_after == Decimal("0")
                else position.remaining_entry_cost - allocated_cost
            ),
            opened_at=None if quantity_after == Decimal("0") else position.opened_at,
            updated_at=fill.filled_at,
        )
        account_after = _mark_account(
            account,
            position_after,
            quote=quote,
            cash=cash_after,
            daily_realized_loss=account.daily_realized_loss + max(-realized_pnl, Decimal("0")),
            cooldown_remaining=(
                account.risk_config.cooldown_candles
                if risk_exit and quantity_after == Decimal("0")
                else account.cooldown_remaining
            ),
        )
        ledger = PaperLedgerEntry(
            occurred_at=fill.filled_at,
            kind=fill.action,
            cash_delta=proceeds,
            position_delta=-fill.quantity,
            realized_pnl=realized_pnl,
            fee=fill.fee,
            cash_after=cash_after,
            quantity_after=quantity_after,
        )
        return account_after, position_after, ledger


def _mark_account(
    account: PaperAccount,
    position: PaperPosition,
    *,
    quote: ExecutionQuote,
    cash: Decimal,
    daily_realized_loss: Decimal | None = None,
    cooldown_remaining: int | None = None,
) -> PaperAccount:
    equity = cash + position.quantity * quote.price
    return account.model_copy(
        update={
            "cash": cash,
            "equity": equity,
            "peak_equity": max(account.peak_equity, equity),
            "daily_realized_loss": (
                account.daily_realized_loss if daily_realized_loss is None else daily_realized_loss
            ),
            "cooldown_remaining": (
                account.cooldown_remaining if cooldown_remaining is None else cooldown_remaining
            ),
        }
    )


def _append_event(
    events: list[PaperAuditEvent],
    *,
    kind: PaperEventKind,
    occurred_at: datetime,
    idempotency_key: str | None,
    payload: dict[str, JsonValue],
) -> None:
    events.append(
        PaperAuditEvent(
            sequence=len(events),
            kind=kind,
            occurred_at=occurred_at,
            idempotency_key=idempotency_key,
            payload=payload,
        )
    )


def _snapshot_hash(quote: ExecutionQuote) -> str:
    payload = {
        "fetched_at": quote.fetched_at.isoformat(),
        "observed_at": quote.observed_at.isoformat(),
        "price": _decimal_text(quote.price),
        "source": quote.source,
        "symbol": quote.symbol.value,
    }
    return sha256(dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value, "f")
