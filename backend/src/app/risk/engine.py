"""风控决策模块。

数据流：TradeIntent 与 PortfolioSnapshot、当前价格进入 RiskEngine，按固定顺序检查
价格、仓位、熔断、冷却和日损失限制，输出唯一的 RiskDecision 供执行层消费。
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from app.risk.contracts import (
    PortfolioSnapshot,
    RiskConfig,
    RiskDecision,
    RiskRejectionCode,
)
from app.strategy.contracts import IntentAction, TradeIntent


class RiskEngine:
    """在订单进入执行层前运行的确定性风控关卡。

    此处不信任策略或模型的仓位建议；引擎只依据账户快照、固定配置和当前价格
    得出可复现的放行或拒绝结果。
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config

    def evaluate(
        self,
        intent: TradeIntent,
        portfolio: PortfolioSnapshot,
        close_price: Decimal,
    ) -> RiskDecision:
        """审核一条交易意图并计算允许成交的数量。

        平仓只验证已有仓位；开仓依次应用账户级限制，并以现金和最大敞口中较小者
        计算数量。该方法不创建订单，因此任何调用方都必须把返回决策交给执行层。
        """
        # 先验证独立于交易方向的行情输入，避免无效价格参与仓位计算。
        if close_price <= Decimal("0"):
            return RiskDecision(
                approved=False,
                reason=RiskRejectionCode.INVALID_MARK_PRICE,
            )
        if intent.action is IntentAction.CLOSE_LONG:
            # 平仓只能关闭已有仓位，且不受开仓预算、冷却期等限制影响。
            if portfolio.position_quantity <= Decimal("0"):
                return RiskDecision(
                    approved=False,
                    reason=RiskRejectionCode.NO_OPEN_POSITION,
                )
            return RiskDecision(approved=True, quantity=portfolio.position_quantity)

        # 开仓检查按“全局熔断 → 持仓互斥 → 时间限制 → 当日损失”的顺序短路，
        # 使审计事件能够对应最先触发、也是最需要用户处理的拒绝原因。
        if self._circuit_breaker_triggered(portfolio):
            return RiskDecision(
                approved=False,
                reason=RiskRejectionCode.CIRCUIT_BREAKER,
            )
        if portfolio.position_quantity > Decimal("0"):
            return RiskDecision(
                approved=False,
                reason=RiskRejectionCode.POSITION_ALREADY_OPEN,
            )
        if portfolio.cooldown_remaining > 0:
            return RiskDecision(
                approved=False,
                reason=RiskRejectionCode.COOLDOWN,
            )
        if portfolio.daily_realized_loss >= (
            portfolio.daily_start_equity * self._config.daily_loss_fraction
        ):
            return RiskDecision(
                approved=False,
                reason=RiskRejectionCode.DAILY_LOSS_LIMIT,
            )

        # 可用现金和最大敞口两者共同限制名义金额；向下取整绝不因精度扩大仓位。
        budget = min(
            portfolio.cash,
            portfolio.equity * self._config.max_exposure_fraction,
        )
        quantity = (budget / close_price).quantize(
            self._config.quantity_increment,
            rounding=ROUND_DOWN,
        )
        return RiskDecision(approved=True, quantity=quantity)

    def stop_loss_triggered(
        self,
        portfolio: PortfolioSnapshot,
        *,
        close_price: Decimal,
    ) -> bool:
        """根据持仓实际入场价判断当前价格是否已触发固定比例止损。"""
        if portfolio.position_quantity <= Decimal("0") or portfolio.entry_price is None:
            return False
        # 止损阈值从实际入场价推导，因此同一配置会随每笔交易的成交价变化。
        threshold = portfolio.entry_price * (Decimal("1") - self._config.stop_loss_fraction)
        return close_price <= threshold

    def _circuit_breaker_triggered(self, portfolio: PortfolioSnapshot) -> bool:
        """用账户历史权益高点计算回撤，避免峰值为零时发生除零。"""
        if portfolio.peak_equity <= Decimal("0"):
            return False
        drawdown = (portfolio.peak_equity - portfolio.equity) / portfolio.peak_equity
        return drawdown >= self._config.max_drawdown_fraction
