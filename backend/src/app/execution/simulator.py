# 确定性撮合：将历史下一根开盘或冻结报价施加不利滑点、成交比例与手续费，返回模拟成交，不更新账户。
# 模拟执行领域：风控批准的模拟订单按冻结报价计算滑点、手续费和部分成交；不连接真实交易。
"""确定性模拟撮合模块。

数据流：已获风控批准的 SimulatedOrder 加上冻结的 K 线或报价，应用配置中的滑点、
成交比例和手续费，生成不触及真实交易所的 SimulatedFill。
"""

from __future__ import annotations

from decimal import Decimal

from app.execution.contracts import (
    ExecutionConfig,
    ExecutionQuote,
    OrderStatus,
    SimulatedFill,
    SimulatedOrder,
)
from app.market.contracts import Candle, ContractSymbol


# 以下一根 K 线开盘价进行的确定性离线模拟撮合。
class SimulatedExecutionService:
    """以下一根 K 线开盘价进行的确定性离线模拟撮合。

    本服务只把已经通过风控的模拟订单转换为成交，不连接交易所，也不维护账户状态。
    """

    # 初始化本实例依赖和配置；输入 config。
    def __init__(self, config: ExecutionConfig) -> None:
        self._config = config

    # 在下一根 K 线开盘价撮合订单，用于保持回测的时间因果关系。
    def submit_and_fill(self, order: SimulatedOrder, candle: Candle) -> SimulatedFill:
        """在下一根 K 线开盘价撮合订单，用于保持回测的时间因果关系。"""
        if candle.symbol is not order.symbol:
            raise ValueError("订单标的必须与成交 K 线一致")
        if candle.open_price <= Decimal("0"):
            raise ValueError("下一根 K 线开盘价必须为正")

        # 回测在下一根 K 线开盘才成交，防止用当前收盘价产生未来数据泄漏。
        return self.submit_and_fill_at_quote(
            order,
            ExecutionQuote(
                symbol=ContractSymbol(candle.symbol),
                price=candle.open_price,
                observed_at=candle.open_at,
                fetched_at=candle.fetched_at,
                source="historical_candle",
            ),
        )

    # 按指定冻结报价计算成交结果。
    def submit_and_fill_at_quote(
        self,
        order: SimulatedOrder,
        quote: ExecutionQuote,
    ) -> SimulatedFill:
        """按指定冻结报价计算成交结果。

        该方法集中施加对账户不利的买卖滑点、部分成交比例和手续费，并保留订单的
        幂等键，使上层可以将订单、成交和审计事件关联起来。
        """
        if quote.symbol is not order.symbol:
            raise ValueError("订单标的必须与行情报价一致")

        # 买入抬高、卖出压低成交价，滑点方向始终对账户不利。
        signed_slippage = (
            self._config.slippage_rate if order.is_buy else -self._config.slippage_rate
        )
        price = quote.price * (Decimal("1") + signed_slippage)
        # 成交比例小于 1 时保留原始申请量，供上层记录部分成交而非伪装成全额成交。
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
            filled_at=quote.observed_at,
            requested_quantity=order.requested_quantity,
            quantity=quantity,
            price=price,
            fee=fee,
            status=status,
        )
