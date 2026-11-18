# 实现 C7 确定性数量求解：由候选价格、本地资料、风险政策、公开规则和成本假设
# 计算最保守的线性合约数量、止损路径风险、目标情景净收益、保证金与净盈亏比。
# 纯函数只接收已完成版本/指纹校验的 PlanningRequest，不查库、不调模型、不生成订单。
# 关键约束：风险额度取多项限额最小值；数量只向步长下方取整；成本使用声明的
# 保守上界；最小订单冲突时阻断而不是加大数量或移动结构；未知资料不按零计算。
from __future__ import annotations

from decimal import Decimal, localcontext

from app.research.strategies.contracts import StrategyDirection
from app.trade_planning.contracts import (
    CALCULATION_PRECISION,
    OrderOperation,
    PlanningCalculationError,
    PlanningReason,
    PlanningRequest,
    PriceGeometry,
    SizingResult,
    SizingStatus,
    quantize_decimal,
)
from app.trade_planning.margin import initial_margin_for, margin_capacity
from app.trade_planning.order_rules import (
    floor_to_step,
    max_quantity_for,
    min_quantity_for,
    order_type_supported,
    resolve_prices,
    time_in_force_supported,
)


# 单单位成本拆分保留在内部，避免把费用/滑点/持有成本的中间项暴露为公共契约。
class _UnitCosts:
    __slots__ = ("loss", "reward")

    def __init__(self, *, loss: Decimal, reward: Decimal) -> None:
        self.loss = loss
        self.reward = reward


# 计算风险额度 R：用户政策的上限与资料中剩余额度取最小值；任一关键项缺失即阻断。
# max_daily_loss/max_portfolio_risk 是总上限，remaining_* 是当前剩余额度，二者都参与。
def _risk_budget(request: PlanningRequest) -> Decimal:
    values = (
        request.policy.max_risk_per_trade,
        request.policy.max_daily_loss,
        request.policy.max_portfolio_risk,
        request.profile.remaining_single_trade_risk,
        request.profile.remaining_daily_loss,
        request.profile.remaining_portfolio_risk,
    )
    if any(value is None for value in values):
        raise PlanningCalculationError(
            "风险额度资料不完整",
            code=PlanningReason.INPUTS_INCOMPLETE.value,
        )
    budget = min(value for value in values if value is not None)
    if budget <= 0:
        raise PlanningCalculationError(
            "风险额度已耗尽",
            code=PlanningReason.RISK_BUDGET_UNAVAILABLE.value,
        )
    return budget


# 单单位止损路径损失和目标路径净收益。费用/滑点/持有成本只计一次：
# 入场限价用声明的限价，市价用已声明的最大不利成交价；出场滑点/价差只作用于退出价。
# 止损路径损失包含入场/止损退出费用和持有成本；目标路径净收益扣除对应退出费用。
def _unit_costs(
    request: PlanningRequest,
    prices: PriceGeometry,
) -> _UnitCosts:
    direction = request.candidate.direction
    multiplier = request.rules.contract_multiplier
    costs = request.costs
    entry = prices.entry
    stop = prices.stop
    target = prices.target
    exit_penalty = costs.slippage_upper_bound + costs.spread_upper_bound
    holding = costs.holding_cost_upper_bound
    if exit_penalty >= 1:
        raise PlanningCalculationError(
            "滑点与价差上界之和必须小于 1",
            code=PlanningReason.CALCULATION_FAILED.value,
        )

    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        if direction is StrategyDirection.LONG:
            stop_exit = stop * (1 - exit_penalty)
            target_exit = target * (1 - exit_penalty)
            gross_loss = (entry - stop_exit) * multiplier
            gross_reward = (target_exit - entry) * multiplier
        else:
            stop_exit = stop * (1 + exit_penalty)
            target_exit = target * (1 + exit_penalty)
            gross_loss = (stop_exit - entry) * multiplier
            gross_reward = (entry - target_exit) * multiplier

        entry_fee = costs.entry_fee_rate * entry * multiplier
        stop_fee = costs.stop_exit_fee_rate * stop_exit * multiplier
        target_fee = costs.target_exit_fee_rate * target_exit * multiplier
        holding_cost = holding * entry * multiplier

        loss = gross_loss + entry_fee + stop_fee + holding_cost
        reward = gross_reward - entry_fee - target_fee - holding_cost

    if loss <= 0:
        raise PlanningCalculationError(
            "单单位止损路径损失必须为正",
            code=PlanningReason.LOSS_NOT_POSITIVE.value,
        )
    if reward <= 0:
        raise PlanningCalculationError(
            "单单位目标路径净收益必须为正",
            code=PlanningReason.REWARD_NOT_POSITIVE.value,
        )
    return _UnitCosts(loss=loss, reward=reward)


# 初步数量上限取风险、名义额、政策数量、保证金容量和公开规则数量的最小值。
# 这里只给上限；随后按步长向下取整并复验，不向上补齐最小订单。
def _preliminary_quantity(
    request: PlanningRequest,
    *,
    prices: PriceGeometry,
    unit_costs: _UnitCosts,
    risk_budget: Decimal,
) -> Decimal:
    multiplier = request.rules.contract_multiplier
    policy = request.policy
    if policy.max_notional is None or policy.max_quantity is None:
        raise PlanningCalculationError(
            "风险政策缺少名义额或数量上限",
            code=PlanningReason.POLICY_INCOMPLETE.value,
        )
    leverage = request.profile.leverage
    if leverage is None:
        raise PlanningCalculationError(
            "规划资料缺少杠杆",
            code=PlanningReason.INPUTS_INCOMPLETE.value,
        )
    capacity = margin_capacity(request)
    notional_per_unit = multiplier * prices.entry
    if notional_per_unit <= 0:
        raise PlanningCalculationError(
            "单位名义额必须为正",
            code=PlanningReason.CALCULATION_FAILED.value,
        )

    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        caps = (
            risk_budget / unit_costs.loss,
            policy.max_notional / notional_per_unit,
            policy.max_quantity,
            max_quantity_for(request),
            (capacity * leverage) / notional_per_unit,
        )
    if any(value < 0 for value in caps):
        raise PlanningCalculationError(
            "数量上限不能为负",
            code=PlanningReason.CALCULATION_FAILED.value,
        )
    return min(caps)


# 统一构造阻断结果；阻断时数量/风险/收益归零，原因必须是有限稳定码。
def _blocked(
    request: PlanningRequest,
    reasons: tuple[PlanningReason, ...],
    *,
    quantity_step: Decimal,
) -> SizingResult:
    unique = tuple(dict.fromkeys(reasons)) or (PlanningReason.CALCULATION_FAILED,)
    return SizingResult(
        status=SizingStatus.BLOCKED,
        material_hash=request.material_sha256(),
        quantity=Decimal("0"),
        notional=Decimal("0"),
        initial_margin=Decimal("0"),
        stop_path_loss=Decimal("0"),
        target_net_reward=Decimal("0"),
        net_reward_risk_ratio=None,
        risk_budget=None,
        entry_price=None,
        stop_price=None,
        target_price=None,
        entry_lower=None,
        trigger=None,
        entry_upper=None,
        stop_exit_quantity=Decimal("0"),
        target_exit_quantity=Decimal("0"),
        quantity_step=quantity_step,
        price_tick=request.rules.price_tick,
        expires_at=request.candidate.valid_until,
        reason_codes=unique,
    )


# 由已取整数量构造完整结果；所有结算值向保守方向量化，避免低估风险/高估收益。
def _sized_result(
    request: PlanningRequest,
    *,
    prices: PriceGeometry,
    unit_costs: _UnitCosts,
    risk_budget: Decimal,
    quantity: Decimal,
) -> SizingResult:
    multiplier = request.rules.contract_multiplier
    leverage = request.profile.leverage
    if leverage is None or leverage <= 0:
        raise PlanningCalculationError(
            "规划资料缺少有效杠杆",
            code=PlanningReason.INPUTS_INCOMPLETE.value,
        )
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        notional = quantity * multiplier * prices.entry
        loss = unit_costs.loss * quantity
        reward = unit_costs.reward * quantity
    rounded_notional = quantize_decimal(notional, direction="up")
    margin = initial_margin_for(rounded_notional, leverage)
    rounded_loss = quantize_decimal(loss, direction="up")
    rounded_reward = quantize_decimal(reward, direction="down")
    # 结算量化后的金额才是用户看到的计划风险/收益；比率必须由这两个金额复算，
    # 不能用未量化的原始比率绕过最小盈亏比，也不能在收益量化为零时构造非法结果。
    if rounded_loss <= 0:
        raise PlanningCalculationError(
            "结算后的止损路径损失必须为正",
            code=PlanningReason.LOSS_NOT_POSITIVE.value,
        )
    if rounded_reward <= 0:
        raise PlanningCalculationError(
            "结算后的目标净收益必须为正",
            code=PlanningReason.REWARD_NOT_POSITIVE.value,
        )
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        exact_ratio = rounded_reward / rounded_loss
    rounded_ratio = quantize_decimal(exact_ratio, direction="down")
    if rounded_ratio <= 0:
        raise PlanningCalculationError(
            "结算后的净盈亏比必须为正",
            code=PlanningReason.REWARD_NOT_POSITIVE.value,
        )
    return SizingResult(
        status=SizingStatus.SIZED,
        material_hash=request.material_sha256(),
        quantity=quantity,
        notional=rounded_notional,
        initial_margin=margin,
        stop_path_loss=rounded_loss,
        target_net_reward=rounded_reward,
        net_reward_risk_ratio=rounded_ratio,
        risk_budget=risk_budget,
        entry_price=prices.entry,
        stop_price=prices.stop,
        target_price=prices.target,
        entry_lower=prices.entry_lower,
        trigger=prices.trigger,
        entry_upper=prices.entry_upper,
        stop_exit_quantity=quantity,
        target_exit_quantity=quantity,
        quantity_step=prices.quantity_step,
        price_tick=prices.price_tick,
        expires_at=request.candidate.valid_until,
    )


# 对已量化结果复核所有硬上限；用于处理 18 位量化在边界上的微小越界。
def _constraint_failures(
    request: PlanningRequest,
    *,
    result: SizingResult,
    risk_budget: Decimal,
) -> tuple[PlanningReason, ...]:
    reasons: list[PlanningReason] = []
    policy = request.policy
    quantity = result.quantity
    if quantity < min_quantity_for(request):
        reasons.append(PlanningReason.MIN_QUANTITY_NOT_MET)
    if result.notional < request.rules.min_notional:
        reasons.append(PlanningReason.MIN_NOTIONAL_NOT_MET)
    if policy.max_quantity is None or quantity > policy.max_quantity:
        reasons.append(PlanningReason.MAX_QUANTITY_EXCEEDED)
    if quantity > max_quantity_for(request):
        reasons.append(PlanningReason.MAX_QUANTITY_EXCEEDED)
    if policy.max_notional is None or result.notional > policy.max_notional:
        reasons.append(PlanningReason.MAX_NOTIONAL_EXCEEDED)
    if result.initial_margin > margin_capacity(request):
        reasons.append(PlanningReason.MARGIN_EXCEEDS_AVAILABLE)
    if result.stop_path_loss > risk_budget:
        reasons.append(PlanningReason.RISK_BUDGET_EXCEEDED)
    return tuple(dict.fromkeys(reasons))


# 把解析错误转换为稳定原因码；不把异常文本传给 API/模型。
def _reason_for(error: PlanningCalculationError) -> PlanningReason:
    try:
        return PlanningReason(error.code)
    except ValueError:
        return PlanningReason.CALCULATION_FAILED


# C7 数量求解入口。步骤：检查资料完整性 → 解析有限价格格点 → 计算风险额度与
# 单单位成本 → 取多项上限 → 按步长向下取整 → 量化并复核硬约束。
# 任一关键资料缺失/价格无合法格点/最小订单冲突都返回 blocked，不产生可执行数量。
def calculate_size(request: PlanningRequest) -> SizingResult:
    quantity_step = request.rules.quantity_step
    if request.order_operation is OrderOperation.MARKET:
        quantity_step = request.rules.market_quantity_step

    if request.profile.missing_fields:
        return _blocked(
            request,
            (PlanningReason.INPUTS_INCOMPLETE,),
            quantity_step=quantity_step,
        )
    if request.policy.missing_fields:
        return _blocked(
            request,
            (PlanningReason.POLICY_INCOMPLETE,),
            quantity_step=quantity_step,
        )
    if not order_type_supported(request):
        return _blocked(
            request,
            (PlanningReason.ORDER_TYPE_UNSUPPORTED,),
            quantity_step=quantity_step,
        )
    if not time_in_force_supported(request):
        return _blocked(
            request,
            (PlanningReason.TIME_IN_FORCE_UNSUPPORTED,),
            quantity_step=quantity_step,
        )

    try:
        prices = resolve_prices(request)
        risk_budget = _risk_budget(request)
        unit_costs = _unit_costs(request, prices)
        preliminary = _preliminary_quantity(
            request,
            prices=prices,
            unit_costs=unit_costs,
            risk_budget=risk_budget,
        )
    except PlanningCalculationError as error:
        return _blocked(
            request,
            (_reason_for(error),),
            quantity_step=quantity_step,
        )

    quantity = floor_to_step(preliminary, prices.quantity_step)
    if quantity <= 0:
        return _blocked(
            request,
            (PlanningReason.QUANTITY_NOT_SIZED,),
            quantity_step=prices.quantity_step,
        )
    if quantity < min_quantity_for(request):
        return _blocked(
            request,
            (PlanningReason.MIN_QUANTITY_NOT_MET,),
            quantity_step=prices.quantity_step,
        )
    multiplier = request.rules.contract_multiplier
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        entry_notional = quantity * multiplier * prices.entry
    if entry_notional < request.rules.min_notional:
        return _blocked(
            request,
            (PlanningReason.MIN_NOTIONAL_NOT_MET,),
            quantity_step=prices.quantity_step,
        )

    # 量化取舍可能在 18 位边界造成极小越界；最多回退两步，绝不向上加量。
    last_reasons: tuple[PlanningReason, ...] = ()
    for _ in range(3):
        try:
            result = _sized_result(
                request,
                prices=prices,
                unit_costs=unit_costs,
                risk_budget=risk_budget,
                quantity=quantity,
            )
        except PlanningCalculationError as error:
            return _blocked(
                request,
                (_reason_for(error),),
                quantity_step=prices.quantity_step,
            )
        failures = _constraint_failures(request, result=result, risk_budget=risk_budget)
        if not failures:
            return result
        last_reasons = failures
        if (
            PlanningReason.MIN_QUANTITY_NOT_MET in failures
            or PlanningReason.MIN_NOTIONAL_NOT_MET in failures
        ):
            break
        quantity = floor_to_step(quantity - prices.quantity_step, prices.quantity_step)
        if quantity <= 0:
            break

    return _blocked(
        request,
        last_reasons or (PlanningReason.QUANTITY_NOT_SIZED,),
        quantity_step=prices.quantity_step,
    )


__all__ = ["calculate_size"]
