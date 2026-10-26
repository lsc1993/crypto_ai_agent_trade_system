# 验证模拟盘引擎的风控限量、止损顺序与资金账本追加。
# 固定账户、仓位和报价可直接核对成交、现金和审计变化。
# 已有仓位止损先于新的手动开仓请求，不能跳过风险处理顺序。
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.execution.contracts import DEFAULT_EXECUTION_CONFIG, ExecutionQuote
from app.market.contracts import ContractSymbol
from app.paper_trading.contracts import (
    PaperAccount,
    PaperAccountStatus,
    PaperActionOutcomeKind,
    PaperPosition,
)
from app.paper_trading.engine import PaperTradingEngine
from app.risk.contracts import DEFAULT_RISK_CONFIG
from app.strategy.contracts import IntentAction, IntentSource, TradeIntent

ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000901")
NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)
HOUR_CLOSE = NOW


def test_engine_opens_at_risk_limited_quote_and_appends_ledger() -> None:
    transition = PaperTradingEngine().apply(
        account=_account(cash="10000"),
        position=_position(),
        intent=_manual_intent(IntentAction.OPEN_LONG),
        quote=_quote("100"),
        latest_closed_candle_at=HOUR_CLOSE,
    )

    assert transition.position.quantity == Decimal("95.000000")
    assert transition.position.average_entry_price == Decimal("100.0500")
    assert transition.account.cash == Decimal("485.7452500000")
    assert transition.account.equity == Decimal("9985.7452500000")
    assert transition.ledger_entries[0].cash_delta == Decimal("-9514.2547500000")
    assert transition.ledger_entries[0].position_delta == Decimal("95.000000")
    assert [event.kind.value for event in transition.events] == [
        "intent",
        "risk_approved",
        "order",
        "fill",
    ]
    assert transition.outcome.kind is PaperActionOutcomeKind.FILLED


# 先处理已有风险再评估新意图，避免手动请求覆盖已触发的止损。
def test_engine_executes_stop_loss_before_the_requested_manual_open() -> None:
    transition = PaperTradingEngine().apply(
        account=_account(cash="500", peak_equity="1000"),
        position=_position(
            quantity="1",
            average_entry_price="100",
            remaining_entry_cost="100",
            opened_at=NOW - timedelta(hours=1),
        ),
        intent=_manual_intent(IntentAction.OPEN_LONG),
        quote=_quote("94"),
        latest_closed_candle_at=HOUR_CLOSE,
    )

    assert transition.outcome.kind is PaperActionOutcomeKind.RISK_EXIT
    assert transition.outcome.reason == "stop_loss"
    assert transition.position.quantity == Decimal("0")
    assert transition.account.cooldown_remaining == 3
    assert transition.account.cash == Decimal("593.8590470000")
    assert transition.account.daily_realized_loss == Decimal("6.1409530000")
    assert [event.kind.value for event in transition.events] == [
        "intent",
        "risk_exit",
        "risk_approved",
        "order",
        "fill",
    ]


def _account(
    *,
    cash: str,
    peak_equity: str | None = None,
) -> PaperAccount:
    return PaperAccount(
        id=ACCOUNT_ID,
        status=PaperAccountStatus.ACTIVE,
        symbol=ContractSymbol.BTCUSDT,
        initial_cash=Decimal("10000"),
        cash=Decimal(cash),
        equity=Decimal(cash),
        peak_equity=Decimal(peak_equity or cash),
        daily_start_equity=Decimal(cash),
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
    average_entry_price: str | None = None,
    remaining_entry_cost: str = "0",
    opened_at: datetime | None = None,
) -> PaperPosition:
    return PaperPosition(
        account_id=ACCOUNT_ID,
        quantity=Decimal(quantity),
        average_entry_price=(
            None if average_entry_price is None else Decimal(average_entry_price)
        ),
        remaining_entry_cost=Decimal(remaining_entry_cost),
        opened_at=opened_at,
        updated_at=NOW,
    )


def _manual_intent(action: IntentAction) -> TradeIntent:
    return TradeIntent(
        run_id=ACCOUNT_ID,
        symbol=ContractSymbol.BTCUSDT,
        action=action,
        decision_at=NOW,
        source=IntentSource.MANUAL,
        idempotency_key=f"paper:manual:{action.value}",
    )


def _quote(price: str) -> ExecutionQuote:
    return ExecutionQuote(
        symbol=ContractSymbol.BTCUSDT,
        price=Decimal(price),
        observed_at=NOW,
        fetched_at=NOW,
        source="binance_usdm_public",
    )
