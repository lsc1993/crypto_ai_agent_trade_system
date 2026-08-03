from __future__ import annotations

from decimal import Decimal

from app.execution.contracts import (
    ExecutionConfig,
    OrderStatus,
    SimulatedFill,
    SimulatedOrder,
)
from app.market.contracts import Candle


class SimulatedExecutionService:
    """以下一根 K 线开盘价进行的确定性离线模拟撮合。"""

    def __init__(self, config: ExecutionConfig) -> None:
        self._config = config

    def submit_and_fill(self, order: SimulatedOrder, candle: Candle) -> SimulatedFill:
        if candle.symbol is not order.symbol:
            raise ValueError("订单标的必须与成交 K 线一致")
        if candle.open_price <= Decimal("0"):
            raise ValueError("下一根 K 线开盘价必须为正")

        signed_slippage = (
            self._config.slippage_rate if order.is_buy else -self._config.slippage_rate
        )
        price = candle.open_price * (Decimal("1") + signed_slippage)
        quantity = order.requested_quantity * self._config.fill_ratio
        fee = quantity * price * self._config.fee_rate
        status = (
            OrderStatus.FILLED
            if quantity == order.requested_quantity
            else OrderStatus.PARTIALLY_FILLED
        )
        return SimulatedFill(
            run_id=order.run_id,
            symbol=order.symbol,
            action=order.action,
            order_idempotency_key=order.idempotency_key,
            submitted_at=order.submitted_at,
            filled_at=candle.open_at,
            requested_quantity=order.requested_quantity,
            quantity=quantity,
            price=price,
            fee=fee,
            status=status,
        )
