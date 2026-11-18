# 解析手动订单的有限价格/数量格点：限价入场、有界市价入场、tick/step 过滤器、
# 订单类型与有效期支持。所有函数都是纯计算，不读取交易所实时规则、不创建订单。
# 价格只允许在候选结构允许的范围内向保守方向移动一格；无合法格点即拒绝，
# 不通过移动结构、放大数量或无上界市价单让计划“通过”。
from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from typing import Literal

from app.research.strategies.contracts import PriceRounding, StrategyDirection
from app.trade_planning.contracts import (
    CALCULATION_PRECISION,
    OrderOperation,
    PlanningCalculationError,
    PlanningReason,
    PlanningRequest,
    PriceGeometry,
    QuantityUnit,
    quantize_decimal,
)

# 首期退出固定为市价触发保护/目标；规则未声明任一项时不能生成可执行清单。
EXIT_ORDER_TYPES = ("STOP_MARKET", "TAKE_PROFIT_MARKET")


# 订单操作到交易所类型的映射固定；新增类型必须同时有规则、清单分支和测试。
def order_type_for(request: PlanningRequest) -> str:
    if request.order_operation is OrderOperation.MARKET:
        return "MARKET"
    return "LIMIT"


# 规则快照未声明该订单类型时明确不支持；不按常见交易所习惯猜测。
def order_type_supported(request: PlanningRequest) -> bool:
    return request.rules.supports_order_type(order_type_for(request))


# 止损和目标退出都需要规则声明对应触发市价类型；仅声明 LIMIT 不够。
def exit_order_types_supported(request: PlanningRequest) -> bool:
    return all(request.rules.supports_order_type(order_type) for order_type in EXIT_ORDER_TYPES)


# 限价单使用 GTC（取消前有效）；规则未声明时必须阻断，市价单不依赖 TIF。
def time_in_force_supported(request: PlanningRequest) -> bool:
    if request.order_operation is OrderOperation.MARKET:
        return True
    return "GTC" in request.rules.time_in_force


# 市价单使用 MARKET_LOT_SIZE，限价单使用 LOT_SIZE；两套过滤器不能混用。
def quantity_step_for(request: PlanningRequest) -> Decimal:
    if request.order_operation is OrderOperation.MARKET:
        return request.rules.market_quantity_step
    return request.rules.quantity_step


def min_quantity_for(request: PlanningRequest) -> Decimal:
    if request.order_operation is OrderOperation.MARKET:
        return request.rules.market_min_quantity
    return request.rules.min_quantity


def max_quantity_for(request: PlanningRequest) -> Decimal:
    if request.order_operation is OrderOperation.MARKET:
        return request.rules.market_max_quantity
    return request.rules.max_quantity


# 数量只能向下取整到步长；上层负责在低于最小量/最小名义额时阻断。
# 这里不提供向上取整入口，避免最小订单冲突被“补齐”为更大风险。
def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if not value.is_finite() or not step.is_finite():
        raise PlanningCalculationError(
            "数量或步长不是有限数值",
            code=PlanningReason.PRECISION_EXCEEDED.value,
        )
    if step <= 0:
        raise PlanningCalculationError(
            "数量步长必须为正",
            code=PlanningReason.CALCULATION_FAILED.value,
        )
    if value < 0:
        raise PlanningCalculationError(
            "数量不能为负",
            code=PlanningReason.CALCULATION_FAILED.value,
        )
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        units = (value / step).to_integral_value(rounding=ROUND_FLOOR)
        quantized = units * step
    return quantize_decimal(quantized, direction="down")


# 判断价格是否精确落在 tick 上；交易规则以真实 PRICE_FILTER.tickSize 为准，
# 不使用 pricePrecision 推断。
def price_on_tick(price: Decimal, tick: Decimal) -> bool:
    if price <= 0 or tick <= 0:
        return False
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        units = price / tick
        return units == units.to_integral_value()


# 数量步长复用 tick 的精确整除判断；MARKET_LOT_SIZE 也有独立 step。
def quantity_on_step(value: Decimal, step: Decimal) -> bool:
    return price_on_tick(value, step)


# 向指定方向取到最近 tick 格点。入场带向内取整；止损/目标只在评估器声明的
# conservative_one_tick 容差内使用，取整后仍重新验证策略几何和风险。
def _tick_round(price: Decimal, tick: Decimal, *, direction: Literal["down", "up"]) -> Decimal:
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        rounding = ROUND_FLOOR if direction == "down" else ROUND_CEILING
        units = (price / tick).to_integral_value(rounding=rounding)
        quantized = units * tick
    return quantize_decimal(quantized, direction="down" if direction == "down" else "up")


# 构造价格几何：限价多单用可执行 band 上界、空单用下界作为最不利入场；
# 市价单必须有用户声明的最大不利成交价，并位于候选允许入场带内。
def resolve_prices(request: PlanningRequest) -> PriceGeometry:
    candidate = request.candidate
    rules = request.rules
    tick = rules.price_tick
    # USDT 线性永续的数量单位是基础资产时，合约乘数固定为 1；与规则快照不一致
    # 时拒绝，避免把“张”和“币”的数量/名义额混算。
    if rules.quantity_unit is QuantityUnit.BASE_ASSET and rules.contract_multiplier != 1:
        raise PlanningCalculationError(
            "基础资产数量单位与合约乘数不一致",
            code=PlanningReason.UNIT_INCONSISTENT.value,
        )
    direction = candidate.direction

    # 入场带按 tick 向内取整：下界 ceil、上界 floor。交易所只能接收 tick 格点，
    # 因此这一步既不放宽策略结构，也不把不可提交的价格标成可实施。
    band_lower = _tick_round(candidate.entry_lower, tick, direction="up")
    band_upper = _tick_round(candidate.entry_upper, tick, direction="down")
    if band_lower > band_upper:
        raise PlanningCalculationError(
            "允许入场区间内没有合法 tick 格点",
            code=PlanningReason.PRICE_GEOMETRY_INVALID.value,
        )
    for label, price in (("入场下界", band_lower), ("入场上界", band_upper)):
        _require_within_filters(price, request, label=label)
    _require_within_filters(candidate.trigger, request, label="触发价")
    # 触发条件仍是策略结构；它必须落在向内取整后的可执行区间内，否则无法用
    # 合法限价表达该候选。
    if not band_lower <= candidate.trigger <= band_upper:
        raise PlanningCalculationError(
            "触发价不在可执行 tick 入场区间内",
            code=PlanningReason.PRICE_GEOMETRY_INVALID.value,
        )

    if request.order_operation is OrderOperation.MARKET:
        entry = request.quote.max_adverse_price
        if entry is None:
            raise PlanningCalculationError(
                "市价单缺少明确的最大不利成交价",
                code=PlanningReason.MARKET_PRICE_BOUND_MISSING.value,
            )
        if not (band_lower <= entry <= band_upper):
            raise PlanningCalculationError(
                "最大不利成交价超出候选允许入场带",
                code=PlanningReason.MARKET_PRICE_BOUND_OUTSIDE_ENTRY.value,
            )
        if not price_on_tick(entry, tick):
            raise PlanningCalculationError(
                "最大不利成交价不在价格步长格点上",
                code=PlanningReason.PRICE_NOT_ON_TICK.value,
            )
        # 市价最不利价必须覆盖当前报价，同时不能超过声明的滑点/价差上界；
        # 否则成本假设与用户填写的最大成交价不是同一个风险边界。比较必须使用
        # 显式高精度上下文，不能继承调用方可能只有 28 位的 Decimal 精度。
        with localcontext() as context:
            context.prec = CALCULATION_PRECISION
            exit_penalty = request.costs.slippage_upper_bound + request.costs.spread_upper_bound
            if direction is StrategyDirection.LONG:
                bound_low = request.quote.price
                bound_high = request.quote.price * (1 + exit_penalty)
                consistent = bound_low <= entry <= bound_high
            else:
                bound_low = request.quote.price * (1 - exit_penalty)
                bound_high = request.quote.price
                consistent = bound_low <= entry <= bound_high
        if not consistent:
            raise PlanningCalculationError(
                "最大不利成交价与当前报价/滑点上界不一致",
                code=PlanningReason.MARKET_PRICE_BOUND_INCONSISTENT.value,
            )
    else:
        entry = band_upper if direction is StrategyDirection.LONG else band_lower

    stop = _resolve_exit_price(
        candidate.stop_loss,
        tick=tick,
        direction=direction,
        rounding=candidate.price_rounding,
    )
    target = _resolve_exit_price(
        candidate.target,
        tick=tick,
        direction=direction,
        rounding=candidate.price_rounding,
    )
    _require_within_filters(entry, request, label="入场价")
    _require_within_filters(stop, request, label="止损价")
    _require_within_filters(target, request, label="目标价")

    # 保守取整后仍必须保持“止损—入场—目标”的顺序；不能把目标移进入场带。
    if direction is StrategyDirection.LONG:
        valid = stop < entry and entry < target
    else:
        valid = target < entry and entry < stop
    if not valid:
        raise PlanningCalculationError(
            "取整后的止损/入场/目标价格次序无效",
            code=PlanningReason.PRICE_GEOMETRY_INVALID.value,
        )

    return PriceGeometry(
        entry=entry,
        stop=stop,
        target=target,
        entry_lower=band_lower,
        trigger=candidate.trigger,
        entry_upper=band_upper,
        quantity_step=quantity_step_for(request),
        price_tick=tick,
    )


# 止损/目标只在 conservative_one_tick 时向风险不利方向取整：
# 多单止损向下、目标向下；空单止损向上、目标向上。
def _resolve_exit_price(
    price: Decimal,
    *,
    tick: Decimal,
    direction: StrategyDirection,
    rounding: PriceRounding,
) -> Decimal:
    if price <= 0:
        raise PlanningCalculationError(
            "退出价格必须为正",
            code=PlanningReason.PRICE_GEOMETRY_INVALID.value,
        )
    if price_on_tick(price, tick):
        return price
    if rounding is PriceRounding.STRICT:
        raise PlanningCalculationError(
            "退出价格不在价格步长格点上",
            code=PlanningReason.PRICE_NOT_ON_TICK.value,
        )

    # 多单：止损和目标都向下；空单：止损和目标都向上。目标向下会降低净收益，
    # 止损向外会增加风险，两者都不会让不合格计划变得更容易通过。
    down = direction is StrategyDirection.LONG
    adjusted = _tick_round(price, tick, direction="down" if down else "up")
    if abs(adjusted - price) > tick:
        raise PlanningCalculationError(
            "价格取整超过一个 tick 的声明容差",
            code=PlanningReason.PRICE_TOLERANCE_EXCEEDED.value,
        )
    if adjusted <= 0:
        raise PlanningCalculationError(
            "取整后退出价格无效",
            code=PlanningReason.PRICE_GEOMETRY_INVALID.value,
        )
    return adjusted


# 价格必须位于公开规则 [min_price, max_price]；tick 和过滤器缺一不可。
def _require_within_filters(price: Decimal, request: PlanningRequest, *, label: str) -> None:
    rules = request.rules
    if price < rules.min_price or price > rules.max_price:
        raise PlanningCalculationError(
            f"{label}超出公开价格过滤器",
            code=PlanningReason.PRICE_OUTSIDE_FILTERS.value,
        )


__all__ = [
    "EXIT_ORDER_TYPES",
    "exit_order_types_supported",
    "floor_to_step",
    "max_quantity_for",
    "min_quantity_for",
    "order_type_for",
    "order_type_supported",
    "price_on_tick",
    "quantity_on_step",
    "quantity_step_for",
    "resolve_prices",
    "time_in_force_supported",
]
