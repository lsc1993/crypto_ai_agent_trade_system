# 验证多腿交易的 FIFO 匹配、手续费与资金费分摊。
# 固定多空成交及现金流覆盖部分匹配与未平仓成本。
# 非法腿状态、浮点值、非 UTC 时间和重复活动标识需拒绝。
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from pydantic import ValidationError

from app.market.contracts import ContractSymbol
from app.trades.calculator import TradeCalculator, TradeValidationError
from app.trades.contracts import (
    TradeCashflowDraft,
    TradeDirection,
    TradeDraft,
    TradeHorizon,
    TradeLegAction,
    TradeLegDraft,
)


def _leg(
    name: str,
    action: TradeLegAction | str,
    executed_at: str,
    sequence: int,
    price: str,
    quantity: str,
    fee: str,
) -> TradeLegDraft:
    return TradeLegDraft(
        id=_identifier(name),
        action=TradeLegAction(action),
        executed_at=_utc(executed_at),
        sequence=sequence,
        price=Decimal(price),
        quantity=Decimal(quantity),
        fee=Decimal(fee),
    )


def _cashflow(name: str, amount: str) -> TradeCashflowDraft:
    return TradeCashflowDraft(
        id=_identifier(name),
        occurred_at=_utc("2026-07-31T00:30:00Z"),
        amount=Decimal(amount),
        reason="test funding cashflow",
    )


def _identifier(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://example.invalid/trades/{name}")


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_calculator_matches_long_lots_in_fifo_order_and_applies_fees_and_funding() -> None:
    result = TradeCalculator().calculate(
        direction=TradeDirection.LONG,
        legs=(
            _leg("open-1", "open", "2026-07-31T00:00:00Z", 0, "100", "2", "0.2"),
            _leg("open-2", "open", "2026-07-31T00:00:00Z", 1, "110", "1", "0.1"),
            _leg("close-1", "close", "2026-07-31T01:00:00Z", 0, "120", "3", "0.3"),
        ),
        cashflows=(
            _cashflow("funding-paid", "-0.4"),
            _cashflow("funding-earned", "0.1"),
        ),
    )

    assert result.gross_realized_pnl == Decimal("50")
    assert result.total_fees == Decimal("0.6")
    assert result.total_funding_cashflow == Decimal("-0.3")
    assert result.net_pnl == Decimal("49.1")
    assert result.remaining_quantity == Decimal("0")
    assert result.is_fully_closed is True
    assert tuple(match.open_leg_id for match in result.matches) == (
        _identifier("open-1"),
        _identifier("open-2"),
    )


# 仅已匹配的部分进入已实现损益，未平仓部分的费用不能提前全部计入。
def test_calculator_calculates_partial_short_without_allocating_unmatched_open_fee() -> None:
    result = TradeCalculator().calculate(
        direction=TradeDirection.SHORT,
        legs=(
            _leg("open", "open", "2026-07-31T00:00:00Z", 0, "100", "4", "0.4"),
            _leg("reduce", "reduce", "2026-07-31T01:00:00Z", 0, "90", "1", "0.1"),
        ),
        cashflows=(),
    )

    assert result.gross_realized_pnl == Decimal("10")
    assert result.total_fees == Decimal("0.2")
    assert result.net_pnl == Decimal("9.8")
    assert result.remaining_quantity == Decimal("3")
    assert result.is_fully_closed is False


@pytest.mark.parametrize(
    ("legs", "message"),
    [
        (
            (
                _leg("open", "open", "2026-07-31T00:00:00Z", 0, "100", "1", "0"),
                _leg("reduce", "reduce", "2026-07-31T01:00:00Z", 0, "90", "1", "0"),
            ),
            "减仓必须保留剩余数量",
        ),
        (
            (
                _leg("open", "open", "2026-07-31T00:00:00Z", 0, "100", "1", "0"),
                _leg("close", "close", "2026-07-31T01:00:00Z", 0, "90", "1", "0"),
                _leg("after-close", "open", "2026-07-31T02:00:00Z", 0, "80", "1", "0"),
            ),
            "平仓后不能继续添加交易腿",
        ),
        (
            (
                _leg("open", "open", "2026-07-31T00:00:00Z", 0, "100", "1", "0"),
                _leg("over-close", "close", "2026-07-31T01:00:00Z", 0, "90", "2", "0"),
            ),
            "减仓或平仓数量不能超过剩余开仓数量",
        ),
    ],
)
def test_calculator_rejects_invalid_leg_transitions(
    legs: tuple[TradeLegDraft, ...],
    message: str,
) -> None:
    with pytest.raises(TradeValidationError, match=message):
        TradeCalculator().calculate(
            direction=TradeDirection.LONG,
            legs=legs,
            cashflows=(),
        )


def test_trade_leg_contract_rejects_non_utc_time_and_float_values() -> None:
    with pytest.raises(ValidationError, match="时间必须是 UTC 且带时区"):
        TradeLegDraft(
            id=_identifier("non-utc"),
            action=TradeLegAction.OPEN,
            executed_at=datetime(
                2026,
                7,
                31,
                tzinfo=timezone(timedelta(hours=8)),
            ),
            sequence=0,
            price=Decimal("100"),
            quantity=Decimal("1"),
            fee=Decimal("0"),
        )

    with pytest.raises(ValidationError, match="浮点数不能作为交易领域输入"):
        TradeLegDraft(
            id=_identifier("float"),
            action=TradeLegAction.OPEN,
            executed_at=_utc("2026-07-31T00:00:00Z"),
            sequence=0,
            price=cast(Decimal, 100.0),
            quantity=Decimal("1"),
            fee=Decimal("0"),
        )


def test_trade_draft_requires_unique_activity_identifiers() -> None:
    first_leg = _leg("draft-open", "open", "2026-07-31T00:00:00Z", 0, "100", "1", "0")
    draft = TradeDraft(
        symbol=ContractSymbol.BTCUSDT,
        direction=TradeDirection.LONG,
        horizon=TradeHorizon.SHORT_TERM,
        labels=("manual",),
        linked_report_id=None,
        leverage=Decimal("2"),
        legs=(first_leg,),
        cashflows=(_cashflow("draft-funding", "-0.1"),),
        thesis="manual trade thesis",
        review="",
    )

    assert draft.symbol.value == "BTCUSDT"
    assert draft.cashflows[0].amount == Decimal("-0.1")

    with pytest.raises(ValidationError, match="交易腿 ID 必须唯一"):
        TradeDraft.model_validate(
            {
                **draft.model_dump(),
                "legs": (first_leg, first_leg),
            },
        )
