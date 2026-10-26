# 历史回放：先校验连续行情，逐根成交上一轮订单、估值、风险检查和策略决策；最终返回统计、
# 事件与输入哈希。
# 历史回测领域：先冻结连续行情，再按收盘决策与下一根开盘成交回放；保留输入哈希和审计。
"""离线确定性回测引擎。

数据流：连续已收盘 1h K 线与配置 → 每根收盘时的策略/风控决策 → 下一根开盘模拟
成交 → 账户状态、审计事件、平仓记录和输入快照哈希。引擎不读取网络或数据库。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, cast
from uuid import UUID

from pydantic import JsonValue

from app.execution.contracts import SimulatedFill, SimulatedOrder
from app.execution.simulator import SimulatedExecutionService
from app.market.contracts import Candle, ContractSymbol
from app.market.repository import snapshot_payload_sha256
from app.research.backtests.contracts import (
    BacktestAuditEvent,
    BacktestClosedTrade,
    BacktestEventKind,
    BacktestRequest,
    BacktestResult,
    BacktestSummary,
    ExpectedBacktestFailure,
    candle_snapshot_payload,
)
from app.risk.contracts import PortfolioSnapshot, RiskDecision
from app.risk.engine import RiskEngine
from app.strategy.contracts import IntentAction, IntentSource, TradeIntent
from app.strategy.sma_crossover import SmaCrossoverStrategy

_HOUR = timedelta(hours=1)


# BacktestStrategy 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class BacktestStrategy(Protocol):
    # 从截至当前时点的历史 K 线和仓位状态生成结构化意图或无信号结果。
    def decide(
        self,
        *,
        run_id: UUID,
        candles: tuple[Candle, ...],
        position_is_open: bool,
    ) -> TradeIntent | None: ...


# 下一根开盘撮合的模拟订单，风险退出标记用于成交后设置冷却。
@dataclass
class _ScheduledOrder:
    order: SimulatedOrder
    risk_exit: bool


# 回放内部可变账户，跟踪剩余成本、盈亏、日损失、冷却及历史熔断状态。
@dataclass
class _BacktestState:
    cash: Decimal
    position_quantity: Decimal
    entry_price: Decimal | None
    remaining_entry_cost: Decimal
    opened_at: datetime | None
    opened_quantity: Decimal
    current_trade_pnl: Decimal
    realized_pnl: Decimal
    peak_equity: Decimal
    max_drawdown_fraction: Decimal
    daily_day: date | None
    daily_start_equity: Decimal
    daily_realized_loss: Decimal
    cooldown_remaining: int
    circuit_breaker_triggered: bool


# 只按顺序消费已收盘 K 线的离线、确定性回放引擎。
class DeterministicBacktestEngine:
    """只按顺序消费已收盘 K 线的离线、确定性回放引擎。

    决策在本根 K 线收盘时作出，订单只在下一根开盘成交；这一时序是防止未来数据
    泄漏的核心约束。
    """

    # 初始化本实例依赖和配置；输入 strategy。
    def __init__(self, *, strategy: BacktestStrategy | None = None) -> None:
        self._strategy = strategy or SmaCrossoverStrategy()

    # 按时间顺序回放一组完整 K 线，并返回可审计的回测结果。
    def run(
        self,
        run_id: UUID,
        request: BacktestRequest,
        candles: tuple[Candle, ...],
    ) -> BacktestResult:
        """按时间顺序回放一组完整 K 线，并返回可审计的回测结果。

        预热 K 线仅供策略计算；性能区间内的决策在收盘生成、订单在下一根开盘成交，
        从而避免未来数据泄漏。所有风控拒绝和成交都写入 events。
        """
        self._validate_candles(candles, request)
        risk_engine = RiskEngine(request.risk_config)
        execution_service = SimulatedExecutionService(request.execution_config)
        state = _BacktestState(
            cash=request.initial_cash,
            position_quantity=Decimal("0"),
            entry_price=None,
            remaining_entry_cost=Decimal("0"),
            opened_at=None,
            opened_quantity=Decimal("0"),
            current_trade_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            peak_equity=request.initial_cash,
            max_drawdown_fraction=Decimal("0"),
            daily_day=None,
            daily_start_equity=request.initial_cash,
            daily_realized_loss=Decimal("0"),
            cooldown_remaining=0,
            circuit_breaker_triggered=False,
        )
        events: list[BacktestAuditEvent] = []
        closed_trades: list[BacktestClosedTrade] = []
        scheduled_orders: dict[datetime, list[_ScheduledOrder]] = {}
        seen_idempotency_keys: set[str] = set()

        for index, candle in enumerate(candles):
            # 循环开头先成交上一根收盘后排队的订单，再用本根收盘价估值和决策。
            self._reset_daily_loss_if_needed(state, candle)
            self._fill_scheduled_orders(
                scheduled_orders.pop(candle.open_at, ()),
                candle=candle,
                candle_sequence=index,
                state=state,
                execution_service=execution_service,
                events=events,
                closed_trades=closed_trades,
                cooldown_candles=request.risk_config.cooldown_candles,
            )
            self._mark_equity(state, candle.close_price)

            # 预热区间只提供策略指标；最后一根没有“下一根开盘”，不能再创建订单。
            if candle.open_at < request.start_at or index == len(candles) - 1:
                continue

            next_candle = candles[index + 1]
            self._evaluate_close(
                run_id=run_id,
                request=request,
                # 策略只能看到截至当前 K 线的切片；下一根仅用于调度成交，不作为信号输入。
                candles=candles[: index + 1],
                candle=candle,
                candle_sequence=index,
                next_candle=next_candle,
                state=state,
                risk_engine=risk_engine,
                events=events,
                scheduled_orders=scheduled_orders,
                seen_idempotency_keys=seen_idempotency_keys,
            )
            if state.cooldown_remaining > 0:
                state.cooldown_remaining -= 1

        final_equity = self._equity(state, candles[-1].close_price)
        unrealized_pnl = (
            state.position_quantity * candles[-1].close_price - state.remaining_entry_cost
        )
        # 将完整输入序列哈希写入结果，后续可以验证回测结论对应的精确市场样本。
        snapshot_hash = snapshot_payload_sha256(candle_snapshot_payload(candles))
        summary = BacktestSummary(
            initial_cash=request.initial_cash,
            final_equity=final_equity,
            net_pnl=final_equity - request.initial_cash,
            realized_pnl=state.realized_pnl,
            unrealized_pnl=unrealized_pnl,
            return_fraction=(final_equity - request.initial_cash) / request.initial_cash,
            max_drawdown_fraction=state.max_drawdown_fraction,
            win_rate=_win_rate(closed_trades),
            profit_factor=_profit_factor(closed_trades),
            closed_trade_count=len(closed_trades),
            fill_count=sum(event.kind is BacktestEventKind.FILL for event in events),
            rejection_count=sum(
                event.kind is BacktestEventKind.RISK_REJECTED for event in events
            ),
            open_position_quantity=state.position_quantity,
            candle_count=sum(candle.open_at >= request.start_at for candle in candles),
            snapshot_hash=snapshot_hash,
        )
        self._append_event(
            events,
            kind=BacktestEventKind.COMPLETED,
            occurred_at=candles[-1].close_at,
            candle_sequence=len(candles) - 1,
            payload={
                "final_equity": final_equity,
                "snapshot_hash": snapshot_hash,
            },
        )
        return BacktestResult(
            summary=summary,
            events=tuple(events),
            closed_trades=tuple(closed_trades),
        )

    # 验证输入 K 线覆盖完整预热与性能区间、标的/周期一致且按小时连续。
    def _validate_candles(
        self,
        candles: tuple[Candle, ...],
        request: BacktestRequest,
    ) -> None:
        """验证输入 K 线覆盖完整预热与性能区间、标的/周期一致且按小时连续。"""
        if not candles:
            raise ExpectedBacktestFailure("candles_missing", "回测至少需要一根 K 线")
        if candles[0].open_at != request.warmup_start_at:
            raise ExpectedBacktestFailure("warmup_missing", "回测 K 线缺少完整预热区间")
        if candles[-1].close_at != request.end_at:
            raise ExpectedBacktestFailure("range_mismatch", "回测 K 线与请求区间不一致")
        if any(
            candle.symbol is not request.symbol or candle.timeframe is not request.timeframe
            for candle in candles
        ):
            raise ExpectedBacktestFailure("candle_scope_invalid", "回测 K 线标的或周期不一致")
        if any(candle.close_at - candle.open_at != _HOUR for candle in candles):
            raise ExpectedBacktestFailure("candle_duration_invalid", "回测 K 线必须为完整 1h")
        if any(
            following.open_at - previous.open_at != _HOUR
            for previous, following in zip(candles, candles[1:], strict=False)
        ):
            raise ExpectedBacktestFailure("candles_not_contiguous", "回测 K 线必须连续")

        performance_count = sum(candle.open_at >= request.start_at for candle in candles)
        if performance_count < 1 or performance_count > 1_000:
            raise ExpectedBacktestFailure("performance_range_invalid", "回测 K 线数量超出限制")

    # 在一根 K 线收盘时优先处理风险退出，再生成并审核策略意图。
    def _evaluate_close(
        self,
        *,
        run_id: UUID,
        request: BacktestRequest,
        candles: tuple[Candle, ...],
        candle: Candle,
        candle_sequence: int,
        next_candle: Candle,
        state: _BacktestState,
        risk_engine: RiskEngine,
        events: list[BacktestAuditEvent],
        scheduled_orders: dict[datetime, list[_ScheduledOrder]],
        seen_idempotency_keys: set[str],
    ) -> None:
        """在一根 K 线收盘时优先处理风险退出，再生成并审核策略意图。"""
        # 风险退出先于策略信号：一旦止损或回撤熔断触发，不允许策略在同一根 K 线上反向覆盖。
        if state.position_quantity > Decimal("0") and risk_engine.stop_loss_triggered(
            self._portfolio(state, candle.close_price),
            close_price=candle.close_price,
        ):
            self._schedule_risk_exit(
                run_id=run_id,
                reason="stop_loss",
                candle=candle,
                candle_sequence=candle_sequence,
                next_candle=next_candle,
                state=state,
                risk_engine=risk_engine,
                events=events,
                scheduled_orders=scheduled_orders,
                seen_idempotency_keys=seen_idempotency_keys,
            )
            return

        if self._drawdown_exceeds_limit(state, request):
            if not state.circuit_breaker_triggered:
                state.circuit_breaker_triggered = True
                self._append_event(
                    events,
                    kind=BacktestEventKind.CIRCUIT_BREAKER,
                    occurred_at=candle.close_at,
                    candle_sequence=candle_sequence,
                    payload={"max_drawdown_fraction": state.max_drawdown_fraction},
                )
            if state.position_quantity > Decimal("0"):
                self._schedule_risk_exit(
                    run_id=run_id,
                    reason="circuit_breaker",
                    candle=candle,
                    candle_sequence=candle_sequence,
                    next_candle=next_candle,
                    state=state,
                    risk_engine=risk_engine,
                    events=events,
                    scheduled_orders=scheduled_orders,
                    seen_idempotency_keys=seen_idempotency_keys,
                )
            return

        if state.circuit_breaker_triggered:
            return

        intent = self._strategy.decide(
            run_id=run_id,
            candles=candles,
            position_is_open=state.position_quantity > Decimal("0"),
        )
        if intent is None:
            return
        if intent.run_id != run_id or intent.symbol is not request.symbol:
            raise ExpectedBacktestFailure("strategy_intent_invalid", "策略输出与回测范围不一致")

        self._append_event(
            events,
            kind=BacktestEventKind.DECISION,
            occurred_at=intent.decision_at,
            candle_sequence=candle_sequence,
            idempotency_key=intent.idempotency_key,
            payload={"action": intent.action, "strategy_id": intent.strategy_id},
        )
        # 即使策略异常重复输出相同意图，也只留下拒绝审计事件，绝不重复排队订单。
        if intent.idempotency_key in seen_idempotency_keys:
            self._append_event(
                events,
                kind=BacktestEventKind.RISK_REJECTED,
                occurred_at=candle.close_at,
                candle_sequence=candle_sequence,
                idempotency_key=intent.idempotency_key,
                payload={"reason": "duplicate_idempotency_key"},
            )
            return
        seen_idempotency_keys.add(intent.idempotency_key)
        self._evaluate_and_schedule(
            intent=intent,
            close_price=candle.close_price,
            candle=candle,
            candle_sequence=candle_sequence,
            next_candle=next_candle,
            state=state,
            risk_engine=risk_engine,
            events=events,
            scheduled_orders=scheduled_orders,
            risk_exit=False,
        )

    # 构造带稳定幂等键的风险平仓意图，并安排其在下一根开盘成交。
    def _schedule_risk_exit(
        self,
        *,
        run_id: UUID,
        reason: str,
        candle: Candle,
        candle_sequence: int,
        next_candle: Candle,
        state: _BacktestState,
        risk_engine: RiskEngine,
        events: list[BacktestAuditEvent],
        scheduled_orders: dict[datetime, list[_ScheduledOrder]],
        seen_idempotency_keys: set[str],
    ) -> None:
        """构造带稳定幂等键的风险平仓意图，并安排其在下一根开盘成交。"""
        intent = TradeIntent(
            run_id=run_id,
            symbol=ContractSymbol(candle.symbol),
            action=IntentAction.CLOSE_LONG,
            decision_at=candle.close_at,
            source=IntentSource.RISK,
            idempotency_key=f"{run_id}:risk-exit:{reason}:{candle.close_at.isoformat()}",
        )
        if intent.idempotency_key in seen_idempotency_keys:
            return
        seen_idempotency_keys.add(intent.idempotency_key)
        self._append_event(
            events,
            kind=BacktestEventKind.RISK_EXIT,
            occurred_at=candle.close_at,
            candle_sequence=candle_sequence,
            idempotency_key=intent.idempotency_key,
            payload={"reason": reason},
        )
        self._evaluate_and_schedule(
            intent=intent,
            close_price=candle.close_price,
            candle=candle,
            candle_sequence=candle_sequence,
            next_candle=next_candle,
            state=state,
            risk_engine=risk_engine,
            events=events,
            scheduled_orders=scheduled_orders,
            risk_exit=True,
        )

    # 经 RiskEngine 审核意图；获准后创建订单和审计事件并延迟到下一根撮合。
    def _evaluate_and_schedule(
        self,
        *,
        intent: TradeIntent,
        close_price: Decimal,
        candle: Candle,
        candle_sequence: int,
        next_candle: Candle,
        state: _BacktestState,
        risk_engine: RiskEngine,
        events: list[BacktestAuditEvent],
        scheduled_orders: dict[datetime, list[_ScheduledOrder]],
        risk_exit: bool,
    ) -> None:
        """经 RiskEngine 审核意图；获准后创建订单和审计事件并延迟到下一根撮合。"""
        decision = risk_engine.evaluate(
            intent,
            self._portfolio(state, close_price),
            close_price,
        )
        self._append_risk_event(
            events,
            decision=decision,
            candle=candle,
            candle_sequence=candle_sequence,
            idempotency_key=intent.idempotency_key,
        )
        if not decision.approved:
            return
        order = SimulatedOrder.from_risk_decision(
            intent,
            decision,
            submitted_at=candle.close_at,
        )
        self._append_event(
            events,
            kind=BacktestEventKind.ORDER,
            occurred_at=order.submitted_at,
            candle_sequence=candle_sequence,
            idempotency_key=order.idempotency_key,
            payload={"action": order.action, "requested_quantity": order.requested_quantity},
        )
        # 已批准的订单只绑定下一根开盘时刻；撮合服务据此施加滑点、费用和部分成交。
        scheduled_orders.setdefault(next_candle.open_at, []).append(
            _ScheduledOrder(order=order, risk_exit=risk_exit)
        )

    # 在当前开盘价撮合已排队订单，更新状态、成交事件与风险退出后的冷却期。
    def _fill_scheduled_orders(
        self,
        scheduled_orders: list[_ScheduledOrder] | tuple[()],
        *,
        candle: Candle,
        candle_sequence: int,
        state: _BacktestState,
        execution_service: SimulatedExecutionService,
        events: list[BacktestAuditEvent],
        closed_trades: list[BacktestClosedTrade],
        cooldown_candles: int,
    ) -> None:
        """在当前开盘价撮合已排队订单，更新状态、成交事件与风险退出后的冷却期。"""
        for scheduled in scheduled_orders:
            fill = execution_service.submit_and_fill(scheduled.order, candle)
            self._apply_fill(state, fill, closed_trades)
            self._append_event(
                events,
                kind=BacktestEventKind.FILL,
                occurred_at=fill.filled_at,
                candle_sequence=candle_sequence,
                idempotency_key=fill.order_idempotency_key,
                payload={
                    "action": fill.action,
                    "requested_quantity": fill.requested_quantity,
                    "quantity": fill.quantity,
                    "price": fill.price,
                    "fee": fill.fee,
                    "status": fill.status,
                },
            )
            # 风险退出完全平仓后才开始冷却；部分成交仍须继续管理剩余仓位。
            if scheduled.risk_exit and state.position_quantity == Decimal("0"):
                state.cooldown_remaining = cooldown_candles

    # 将一笔开仓或平仓成交应用到回测现金、持仓、成本和已实现盈亏。
    def _apply_fill(
        self,
        state: _BacktestState,
        fill: SimulatedFill,
        closed_trades: list[BacktestClosedTrade],
    ) -> None:
        """将一笔开仓或平仓成交应用到回测现金、持仓、成本和已实现盈亏。"""
        if fill.action is IntentAction.OPEN_LONG:
            cost = fill.quantity * fill.price + fill.fee
            state.cash -= cost
            if state.position_quantity == Decimal("0"):
                state.entry_price = fill.price
                state.opened_at = fill.filled_at
                state.opened_quantity = Decimal("0")
                state.current_trade_pnl = Decimal("0")
            else:
                if state.entry_price is None:
                    raise ExpectedBacktestFailure(
                        "position_state_invalid",
                        "回测仓位状态无效",
                    )
                total_notional = (
                    state.position_quantity * state.entry_price
                    + fill.quantity * fill.price
                )
                state.entry_price = total_notional / (state.position_quantity + fill.quantity)
            state.position_quantity += fill.quantity
            state.remaining_entry_cost += cost
            state.opened_quantity += fill.quantity
            return

        if fill.quantity > state.position_quantity:
            raise ExpectedBacktestFailure("fill_quantity_invalid", "模拟平仓数量超过当前仓位")
        previous_quantity = state.position_quantity
        # 部分平仓按当前剩余数量分摊入场总成本，手续费已在入场成本内，防止重复计费。
        allocated_entry_cost = state.remaining_entry_cost * fill.quantity / previous_quantity
        proceeds = fill.quantity * fill.price - fill.fee
        trade_pnl = proceeds - allocated_entry_cost
        state.cash += proceeds
        state.position_quantity -= fill.quantity
        state.remaining_entry_cost -= allocated_entry_cost
        state.realized_pnl += trade_pnl
        state.current_trade_pnl += trade_pnl
        state.daily_realized_loss += max(-trade_pnl, Decimal("0"))
        if state.position_quantity == Decimal("0"):
            if state.opened_at is None:
                raise ExpectedBacktestFailure("position_state_invalid", "回测仓位状态无效")
            closed_trades.append(
                BacktestClosedTrade(
                    opened_at=state.opened_at,
                    closed_at=fill.filled_at,
                    quantity=state.opened_quantity,
                    net_pnl=state.current_trade_pnl,
                )
            )
            state.entry_price = None
            state.remaining_entry_cost = Decimal("0")
            state.opened_at = None
            state.opened_quantity = Decimal("0")
            state.current_trade_pnl = Decimal("0")

    # 把内部回测状态投影为 RiskEngine 所需的账户快照。
    def _portfolio(self, state: _BacktestState, mark_price: Decimal) -> PortfolioSnapshot:
        """把内部回测状态投影为 RiskEngine 所需的账户快照。"""
        return PortfolioSnapshot(
            cash=state.cash,
            equity=self._equity(state, mark_price),
            peak_equity=state.peak_equity,
            daily_start_equity=state.daily_start_equity,
            daily_realized_loss=state.daily_realized_loss,
            position_quantity=state.position_quantity,
            entry_price=state.entry_price,
            cooldown_remaining=state.cooldown_remaining,
        )

    # 按当前标记价格计算现金加持仓市值，不把未实现收益当作已实现现金。
    @staticmethod
    def _equity(state: _BacktestState, mark_price: Decimal) -> Decimal:
        return state.cash + state.position_quantity * mark_price

    # 按当前收盘价更新权益、高水位和历史最大回撤。
    def _mark_equity(self, state: _BacktestState, close_price: Decimal) -> None:
        """按当前收盘价更新权益、高水位和历史最大回撤。"""
        equity = self._equity(state, close_price)
        state.peak_equity = max(state.peak_equity, equity)
        if state.peak_equity > Decimal("0"):
            drawdown = (state.peak_equity - equity) / state.peak_equity
            state.max_drawdown_fraction = max(state.max_drawdown_fraction, drawdown)

    # 将已观察到的最大回撤与请求安全上限比较，决定是否触发回测熔断。
    @staticmethod
    def _drawdown_exceeds_limit(state: _BacktestState, request: BacktestRequest) -> bool:
        return state.max_drawdown_fraction >= request.risk_config.max_drawdown_fraction

    # 跨 UTC 自然日时重置日内已实现损失，并以当时权益作为新的日初权益。
    def _reset_daily_loss_if_needed(self, state: _BacktestState, candle: Candle) -> None:
        """跨 UTC 自然日时重置日内已实现损失，并以当时权益作为新的日初权益。"""
        candle_day = candle.open_at.astimezone(UTC).date()
        if state.daily_day == candle_day:
            return
        state.daily_day = candle_day
        state.daily_start_equity = self._equity(state, candle.open_price)
        state.daily_realized_loss = Decimal("0")

    # 记录风控放行或拒绝事件，使每个策略/风险意图都有独立审核结果。
    def _append_risk_event(
        self,
        events: list[BacktestAuditEvent],
        *,
        decision: RiskDecision,
        candle: Candle,
        candle_sequence: int,
        idempotency_key: str,
    ) -> None:
        """记录风控放行或拒绝事件，使每个策略/风险意图都有独立审核结果。"""
        if decision.approved:
            self._append_event(
                events,
                kind=BacktestEventKind.RISK_APPROVED,
                occurred_at=candle.close_at,
                candle_sequence=candle_sequence,
                idempotency_key=idempotency_key,
                payload={"quantity": decision.quantity},
            )
            return
        self._append_event(
            events,
            kind=BacktestEventKind.RISK_REJECTED,
            occurred_at=candle.close_at,
            candle_sequence=candle_sequence,
            idempotency_key=idempotency_key,
            payload={"reason": decision.reason},
        )

    # 追加结构化回测事件，sequence 与 K 线序号共同保留因果和时间位置。
    @staticmethod
    def _append_event(
        events: list[BacktestAuditEvent],
        *,
        kind: BacktestEventKind,
        occurred_at: datetime,
        candle_sequence: int,
        payload: dict[str, object],
        idempotency_key: str | None = None,
    ) -> None:
        """追加结构化回测事件，sequence 与 K 线序号共同保留因果和时间位置。"""
        events.append(
            BacktestAuditEvent(
                sequence=len(events),
                kind=kind,
                occurred_at=occurred_at,
                candle_sequence=candle_sequence,
                idempotency_key=idempotency_key,
                payload=cast(dict[str, JsonValue], _jsonify(payload)),
            )
        )


# 递归转换 Decimal、UTC 时间、枚举和标识为安全 JSON 值；未知对象拒绝序列化。
def _jsonify(value: object) -> JsonValue:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (tuple, list)):
        sequence = cast(tuple[object, ...] | list[object], value)
        return [_jsonify(item) for item in sequence]
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {str(key): _jsonify(item) for key, item in mapping.items()}
    raise TypeError("回测审计载荷包含不可序列化的值")


# 按完整平仓记录计算盈利交易占比，无已平仓交易时返回零。
def _win_rate(closed_trades: list[BacktestClosedTrade]) -> Decimal:
    if not closed_trades:
        return Decimal("0")
    winners = sum(trade.net_pnl > Decimal("0") for trade in closed_trades)
    return Decimal(winners) / Decimal(len(closed_trades))


# 用已平仓盈利总额除亏损绝对值总额；没有亏损时返回空值以避免无穷指标。
def _profit_factor(closed_trades: list[BacktestClosedTrade]) -> Decimal | None:
    gross_loss = sum(
        (-trade.net_pnl for trade in closed_trades if trade.net_pnl < Decimal("0")),
        start=Decimal("0"),
    )
    if gross_loss == Decimal("0"):
        return None
    gross_profit = sum(
        (trade.net_pnl for trade in closed_trades if trade.net_pnl > Decimal("0")),
        start=Decimal("0"),
    )
    return gross_profit / gross_loss
