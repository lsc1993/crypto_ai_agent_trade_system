from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.trades.contracts import (
    TradeCashflowDraft,
    TradeDirection,
    TradeLegAction,
    TradeLegDraft,
    TradeValidationError,
)


@dataclass(frozen=True)
class TradeMatch:
    open_leg_id: UUID
    exit_leg_id: UUID
    quantity: Decimal
    gross_pnl: Decimal
    allocated_open_fee: Decimal


@dataclass(frozen=True)
class TradePnl:
    gross_realized_pnl: Decimal
    total_fees: Decimal
    total_funding_cashflow: Decimal
    net_pnl: Decimal
    remaining_quantity: Decimal
    is_fully_closed: bool
    matches: tuple[TradeMatch, ...]


@dataclass
class _OpenLot:
    leg: TradeLegDraft
    remaining_quantity: Decimal
    remaining_fee: Decimal


class TradeCalculator:
    """以 FIFO 规则计算用户手工录入的已实现盈亏。"""

    def calculate(
        self,
        *,
        direction: TradeDirection,
        legs: tuple[TradeLegDraft, ...],
        cashflows: tuple[TradeCashflowDraft, ...],
    ) -> TradePnl:
        if not legs:
            raise TradeValidationError("交易至少需要一条交易腿")

        ordered_legs = tuple(
            sorted(
                legs,
                key=lambda leg: (leg.executed_at, leg.sequence, str(leg.id)),
            )
        )
        lots: list[_OpenLot] = []
        matches: list[TradeMatch] = []
        gross_realized_pnl = Decimal(0)
        total_fees = Decimal(0)
        is_closed = False

        for leg in ordered_legs:
            if is_closed:
                raise TradeValidationError("平仓后不能继续添加交易腿")
            if leg.action is TradeLegAction.OPEN:
                lots.append(
                    _OpenLot(
                        leg=leg,
                        remaining_quantity=leg.quantity,
                        remaining_fee=leg.fee,
                    )
                )
                continue

            remaining_before = _remaining_quantity(lots)
            if remaining_before == Decimal(0):
                raise TradeValidationError("不存在可减仓的开仓数量")
            if leg.quantity > remaining_before:
                raise TradeValidationError("减仓或平仓数量不能超过剩余开仓数量")
            if leg.action is TradeLegAction.REDUCE and leg.quantity == remaining_before:
                raise TradeValidationError("减仓必须保留剩余数量")
            if leg.action is TradeLegAction.CLOSE and leg.quantity != remaining_before:
                raise TradeValidationError("平仓数量必须恰好清空剩余数量")

            total_fees += leg.fee
            quantity_to_match = leg.quantity
            for lot in lots:
                if quantity_to_match == Decimal(0):
                    break
                matched_quantity = min(quantity_to_match, lot.remaining_quantity)
                allocated_open_fee = (
                    lot.remaining_fee * matched_quantity / lot.remaining_quantity
                )
                gross_pnl = _gross_pnl(
                    direction=direction,
                    entry_price=lot.leg.price,
                    exit_price=leg.price,
                    quantity=matched_quantity,
                )
                gross_realized_pnl += gross_pnl
                total_fees += allocated_open_fee
                matches.append(
                    TradeMatch(
                        open_leg_id=lot.leg.id,
                        exit_leg_id=leg.id,
                        quantity=matched_quantity,
                        gross_pnl=gross_pnl,
                        allocated_open_fee=allocated_open_fee,
                    )
                )
                lot.remaining_quantity -= matched_quantity
                lot.remaining_fee -= allocated_open_fee
                quantity_to_match -= matched_quantity

            lots = [lot for lot in lots if lot.remaining_quantity > Decimal(0)]
            if leg.action is TradeLegAction.CLOSE:
                is_closed = True

        remaining_quantity = _remaining_quantity(lots)
        total_funding_cashflow = sum(
            (cashflow.amount for cashflow in cashflows),
            start=Decimal(0),
        )
        return TradePnl(
            gross_realized_pnl=gross_realized_pnl,
            total_fees=total_fees,
            total_funding_cashflow=total_funding_cashflow,
            net_pnl=gross_realized_pnl - total_fees + total_funding_cashflow,
            remaining_quantity=remaining_quantity,
            is_fully_closed=is_closed and remaining_quantity == Decimal(0),
            matches=tuple(matches),
        )


def _remaining_quantity(lots: list[_OpenLot]) -> Decimal:
    return sum((lot.remaining_quantity for lot in lots), start=Decimal(0))


def _gross_pnl(
    *,
    direction: TradeDirection,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
) -> Decimal:
    price_delta = exit_price - entry_price
    return (
        price_delta * quantity
        if direction is TradeDirection.LONG
        else -price_delta * quantity
    )
