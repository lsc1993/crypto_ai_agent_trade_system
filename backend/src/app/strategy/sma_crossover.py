# 均线交叉：比较前后短长均线关系，按已有仓位决定开多或平多，输出意图或无信号；不计算下单数量。
# 确定性策略领域：只从历史行情生成结构化交易意图，数量与成交由风控和模拟执行决定。
"""SMA(20/50) 交叉策略。

数据流：连续已收盘 K 线 → 前后两组短/长均线 → 金叉或死叉判断 → 仅包含方向和
幂等信息的 TradeIntent；仓位与成交数量始终由后续风控、执行层决定。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.market.contracts import Candle, ContractSymbol
from app.strategy.contracts import IntentAction, IntentSource, TradeIntent


# 仅从已收盘 K 线生成开多或平多 TradeIntent 的确定性均线策略。
class SmaCrossoverStrategy:
    """仅从已收盘 K 线生成开多或平多 TradeIntent 的确定性均线策略。"""

    # 配置短期与长期均线窗口，并拒绝无法形成交叉判断的窗口组合。
    def __init__(self, *, fast_window: int = 20, slow_window: int = 50) -> None:
        """配置短期与长期均线窗口，并拒绝无法形成交叉判断的窗口组合。"""
        if fast_window <= 0 or slow_window <= 0:
            raise ValueError("均线窗口必须是正整数")
        if fast_window >= slow_window:
            raise ValueError("fast_window 必须小于 slow_window")
        self._fast_window = fast_window
        self._slow_window = slow_window

    # 根据最后一根已收盘 K 线是否发生均线穿越生成意图。
    def decide(
        self,
        *,
        run_id: UUID,
        candles: tuple[Candle, ...],
        position_is_open: bool,
    ) -> TradeIntent | None:
        """根据最后一根已收盘 K 线是否发生均线穿越生成意图。

        返回 None 表示数据不足或没有新信号；策略只生成开多和平多意图，不计算仓位，
        也不会直接调用任何订单接口。
        """
        if len(candles) < self._slow_window + 1:
            return None

        # 比较前一根与当前一根的均线相对位置，识别“穿越”而非持续处于多头/空头的状态。
        previous_fast = _sma(candles[-self._fast_window - 1 : -1])
        previous_slow = _sma(candles[-self._slow_window - 1 : -1])
        current_fast = _sma(candles[-self._fast_window :])
        current_slow = _sma(candles[-self._slow_window :])
        action = _action_for_cross(
            previous_fast=previous_fast,
            previous_slow=previous_slow,
            current_fast=current_fast,
            current_slow=current_slow,
            position_is_open=position_is_open,
        )
        if action is None:
            return None

        # 决策时间固定为最后一根已收盘 K 线，执行层会在后续报价或下一根 K 线处理它。
        decision_at = candles[-1].close_at
        return TradeIntent(
            run_id=run_id,
            symbol=ContractSymbol(candles[-1].symbol),
            action=action,
            decision_at=decision_at,
            source=IntentSource.STRATEGY,
            strategy_id="sma_crossover",
            strategy_version="v1",
            idempotency_key=(
                f"{run_id}:sma_crossover:v1:{decision_at.isoformat()}:{action.value}"
            ),
        )


# 计算给定已收盘 K 线的简单移动平均价。
def _sma(candles: tuple[Candle, ...]) -> Decimal:
    """计算给定已收盘 K 线的简单移动平均价。"""
    return sum((candle.close_price for candle in candles), start=Decimal("0")) / len(candles)


# 将前后均线相对位置转为仓位允许的单向交易动作。
def _action_for_cross(
    *,
    previous_fast: Decimal,
    previous_slow: Decimal,
    current_fast: Decimal,
    current_slow: Decimal,
    position_is_open: bool,
) -> IntentAction | None:
    """将前后均线相对位置转为仓位允许的单向交易动作。"""
    # 策略不反向开仓：金叉只开多，死叉只在已有多仓时平仓。
    if not position_is_open and previous_fast <= previous_slow and current_fast > current_slow:
        return IntentAction.OPEN_LONG
    if position_is_open and previous_fast >= previous_slow and current_fast < current_slow:
        return IntentAction.CLOSE_LONG
    return None
