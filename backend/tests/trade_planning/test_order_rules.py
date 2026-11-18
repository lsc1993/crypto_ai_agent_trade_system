# 验证 T12 订单/价格/数量规则：tick 格点、保守一格调整、步长向下取整、
# 限价/市价操作边界、价格过滤器、订单类型与有效期支持。
# 规则快照为合成公开数据，不读取交易所实时规则或账户。
from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext

import pytest

from app.research.strategies.contracts import PriceRounding, StrategyDirection
from app.trade_planning.contracts import OrderOperation, PlanningCalculationError, PlanningReason
from app.trade_planning.order_rules import (
    floor_to_step,
    max_quantity_for,
    min_quantity_for,
    order_type_for,
    order_type_supported,
    resolve_prices,
    time_in_force_supported,
)
from tests.trade_planning.planning_fixtures import build_request


# 数量只能向步长下方取整；最小订单冲突由上层阻断，不能在这里向上补齐。
def test_quantity_floors_to_step_and_never_rounds_up() -> None:
    assert floor_to_step(Decimal("1.99"), Decimal("0.1")) == Decimal("1.9")
    assert floor_to_step(Decimal("1.9"), Decimal("0.1")) == Decimal("1.9")
    assert floor_to_step(Decimal("0.09"), Decimal("0.1")) == Decimal("0")
    assert floor_to_step(Decimal("2"), Decimal("0.25")) == Decimal("2")

    with pytest.raises(PlanningCalculationError):
        floor_to_step(Decimal("1"), Decimal("0"))
    with pytest.raises(PlanningCalculationError):
        floor_to_step(Decimal("-1"), Decimal("0.1"))


# 限价多单以 entry_upper 为最不利入场，空单以 entry_lower；止损/目标保持候选结构。
def test_limit_price_geometry_uses_worst_entry_by_direction() -> None:
    long_request = build_request()
    long_prices = resolve_prices(long_request)
    assert long_prices.entry == Decimal("100")
    assert long_prices.stop == Decimal("95")
    assert long_prices.target == Decimal("110")
    assert long_prices.quantity_step == Decimal("0.1")

    short_request = build_request(direction=StrategyDirection.SHORT)
    short_prices = resolve_prices(short_request)
    assert short_prices.entry == Decimal("100")
    assert short_prices.stop == Decimal("105")
    assert short_prices.target == Decimal("90")


# strict 模式拒绝离格止损/目标；入场带本身按 tick 向内取整，但如果没有合法
# 格点（下界 ceil 大于上界 floor）则阻断，不能悄悄放宽策略结构。
def test_strict_mode_rejects_off_grid_exits_and_empty_entry_band() -> None:
    off_grid_stop = build_request(candidate_overrides={"stop_loss": Decimal("94.9")})
    with pytest.raises(PlanningCalculationError) as stop_error:
        resolve_prices(off_grid_stop)
    assert stop_error.value.code == PlanningReason.PRICE_NOT_ON_TICK.value

    empty_band = build_request(
        candidate_overrides={
            "entry_lower": Decimal("99.2"),
            "trigger": Decimal("99.2"),
            "entry_upper": Decimal("99.2"),
        }
    )
    with pytest.raises(PlanningCalculationError) as entry_error:
        resolve_prices(empty_band)
    assert entry_error.value.code == PlanningReason.PRICE_GEOMETRY_INVALID.value


# 入场带下界 ceil、上界 floor；候选结构不被放大，计划只使用可提交的 tick 价。
def test_entry_band_rounds_inward_to_tick_grid() -> None:
    request = build_request(
        candidate_overrides={
            "entry_lower": Decimal("99.2"),
            "trigger": Decimal("100"),
            "entry_upper": Decimal("100.2"),
        }
    )
    prices = resolve_prices(request)

    assert prices.entry_lower == Decimal("99.5")
    assert prices.entry_upper == Decimal("100")
    assert prices.trigger == Decimal("100")
    assert prices.entry == Decimal("100")


# conservative_one_tick 只向风险不利方向调整止损/目标；多单向下、空单向上，并重验
# 价格过滤器。入场带和触发价仍必须精确落在 tick 上。
def test_conservative_adjustment_moves_protection_only_outward() -> None:
    long_request = build_request(
        candidate_overrides={"stop_loss": Decimal("94.9"), "target": Decimal("109.8")},
        price_rounding=PriceRounding.CONSERVATIVE_ONE_TICK,
    )
    prices = resolve_prices(long_request)
    assert prices.entry == Decimal("100")
    assert prices.stop == Decimal("94.5")
    assert prices.target == Decimal("109.5")

    short_request = build_request(
        direction=StrategyDirection.SHORT,
        candidate_overrides={"stop_loss": Decimal("105.2"), "target": Decimal("90.2")},
        price_rounding=PriceRounding.CONSERVATIVE_ONE_TICK,
    )
    short_prices = resolve_prices(short_request)
    assert short_prices.stop == Decimal("105.5")
    assert short_prices.target == Decimal("90.5")


# 调整后价格仍须满足公开规则上下界；不能因为“保守取整”越过过滤器。
def test_adjusted_prices_must_stay_within_filters() -> None:
    request = build_request(
        candidate_overrides={"stop_loss": Decimal("94.9")},
        price_rounding=PriceRounding.CONSERVATIVE_ONE_TICK,
        rules_overrides={"min_price": "95"},
    )
    with pytest.raises(PlanningCalculationError) as error:
        resolve_prices(request)
    assert error.value.code == PlanningReason.PRICE_OUTSIDE_FILTERS.value


# 市价单必须以用户声明的最大不利成交价作为入场，且该价格位于候选允许入场带；
# 不能把没有价格上界的市价单算成可实施计划。
def test_market_order_requires_bounded_price_inside_candidate_range() -> None:
    missing = build_request(order_operation=OrderOperation.MARKET)
    with pytest.raises(PlanningCalculationError) as missing_error:
        resolve_prices(missing)
    assert missing_error.value.code == PlanningReason.MARKET_PRICE_BOUND_MISSING.value

    outside = build_request(
        order_operation=OrderOperation.MARKET,
        quote_overrides={"max_adverse_price": Decimal("101")},
    )
    with pytest.raises(PlanningCalculationError) as outside_error:
        resolve_prices(outside)
    assert outside_error.value.code == PlanningReason.MARKET_PRICE_BOUND_OUTSIDE_ENTRY.value

    bounded = build_request(
        order_operation=OrderOperation.MARKET,
        quote_overrides={"max_adverse_price": Decimal("100")},
    )
    assert resolve_prices(bounded).entry == Decimal("100")


# 规则必须声明对应订单类型和 GTC；缺少时为明确不支持，不按常见交易所习惯猜测。
def test_order_type_and_time_in_force_must_be_declared() -> None:
    request = build_request()
    assert order_type_for(request) == "LIMIT"
    assert order_type_supported(request) is True
    assert time_in_force_supported(request) is True

    unsupported = build_request(rules_overrides={"order_types": ("MARKET",)})
    assert order_type_supported(unsupported) is False

    no_gtc = build_request(rules_overrides={"time_in_force": ("IOC",)})
    assert time_in_force_supported(no_gtc) is False


# 市价单使用 MARKET_LOT_SIZE 步长/上下限；限价单使用 LOT_SIZE，不能混用两套过滤器。
def test_market_and_limit_quantity_filters_are_separate() -> None:
    limit_request = build_request()
    assert min_quantity_for(limit_request) == Decimal("0.1")
    assert max_quantity_for(limit_request) == Decimal("100")

    market_request = build_request(
        order_operation=OrderOperation.MARKET,
        quote_overrides={"max_adverse_price": Decimal("100")},
        rules_overrides={
            "market_min_quantity": "0.2",
            "market_max_quantity": "50",
            "market_quantity_step": "0.2",
        },
    )
    assert min_quantity_for(market_request) == Decimal("0.2")
    assert max_quantity_for(market_request) == Decimal("50")
    assert resolve_prices(market_request).quantity_step == Decimal("0.2")


# 市价最大不利成交价必须与当前报价和声明的滑点/价差上界一致；超出即拒绝，
# 不能把成本假设与用户填写的成交上界当成两个互不相干的风险边界。
def test_market_bound_must_align_with_quote_and_slippage() -> None:
    request = build_request(
        order_operation=OrderOperation.MARKET,
        quote_overrides={"max_adverse_price": Decimal("100.5")},
        candidate_overrides={"entry_upper": Decimal("101")},
    )
    with pytest.raises(PlanningCalculationError) as error:
        resolve_prices(request)
    assert error.value.code == PlanningReason.MARKET_PRICE_BOUND_INCONSISTENT.value


# 基础资产单位只适用于乘数为 1 的线性永续规则；乘数不匹配时拒绝而不是混算。
def test_base_asset_unit_requires_unit_contract_multiplier() -> None:
    request = build_request(
        rules_overrides={"quantity_unit": "base_asset", "contract_multiplier": "2"}
    )
    with pytest.raises(PlanningCalculationError) as error:
        resolve_prices(request)
    assert error.value.code == PlanningReason.UNIT_INCONSISTENT.value


# 触发价是人工观察阈值，不是交易所订单价格：允许离格但必须落在可执行入场带。
def test_off_grid_trigger_is_a_manual_observation_threshold() -> None:
    request = build_request(candidate_overrides={"trigger": Decimal("99.9")})
    prices = resolve_prices(request)

    assert prices.trigger == Decimal("99.9")
    assert prices.entry_lower <= prices.trigger <= prices.entry_upper
    assert prices.entry == Decimal("100")


# 市价上界比较必须使用显式高精度上下文，不能依赖调用方当前 Decimal 精度。
def test_market_bound_is_independent_of_caller_decimal_precision() -> None:
    price = Decimal("1234567890123456789012345678.123456789012345678")
    penalty = Decimal("0.000000000000000001")
    with localcontext() as context:
        context.prec = 80
        exact = price * (1 + penalty)
        max_adverse = exact.quantize(Decimal("0.000000000000000001"), rounding=ROUND_CEILING)
    request = build_request(
        order_operation=OrderOperation.MARKET,
        quote_overrides={"price": price, "max_adverse_price": max_adverse},
        cost_overrides={
            "slippage_upper_bound": penalty,
            "spread_upper_bound": "0",
        },
        rules_overrides={
            "price_tick": "0.000000000000000001",
            "max_price": "111111111111111111111111111111",
            "min_price": "0.5",
        },
        candidate_overrides={
            "entry_lower": price,
            "trigger": price,
            "entry_upper": max_adverse,
            "stop_loss": price - 1,
            "target": max_adverse + 1,
        },
    )
    with pytest.raises(PlanningCalculationError) as error:
        resolve_prices(request)
    assert error.value.code == PlanningReason.MARKET_PRICE_BOUND_INCONSISTENT.value


# 审查报告 F8 的精确边界：合法上界在低精度上下文中仍应通过，再加一个 tick
# 则必须拒绝；比较不能依赖调用方 Decimal 精度。
def test_reported_market_boundary_is_precision_independent() -> None:
    price = Decimal("100000000000.123456789012345678")
    penalty = Decimal("0.01")
    with localcontext() as context:
        context.prec = 80
        exact = price * (1 + penalty)
        legal = exact.quantize(Decimal("0.000000000000000001"), rounding=ROUND_FLOOR)
        illegal = legal + Decimal("0.000000000000000001")

    def request_for(bound: Decimal):
        return build_request(
            order_operation=OrderOperation.MARKET,
            quote_overrides={"price": price, "max_adverse_price": bound},
            cost_overrides={
                "slippage_upper_bound": penalty,
                "spread_upper_bound": "0",
            },
            rules_overrides={
                "price_tick": "0.000000000000000001",
                "max_price": "111111111111111111111111111111",
                "min_price": "0.5",
            },
            candidate_overrides={
                "entry_lower": price,
                "trigger": price,
                "entry_upper": bound,
                "stop_loss": price - 1,
                "target": bound + 1,
            },
        )

    legal_request = request_for(legal)
    illegal_request = request_for(illegal)
    with localcontext() as context:
        context.prec = 6
        assert resolve_prices(legal_request).entry == legal
        with pytest.raises(PlanningCalculationError) as error:
            resolve_prices(illegal_request)
    assert error.value.code == PlanningReason.MARKET_PRICE_BOUND_INCONSISTENT.value


# R3：保守一格调整量的减法/绝对值也必须使用高精度；报告中的止损距上一 tick
# 小于一个 tick，在低精度调用方上下文中不能误报 price_tolerance_exceeded。
def test_conservative_tolerance_is_independent_of_caller_decimal_precision() -> None:
    price = Decimal("99.999999099999999180")
    tick = Decimal("0.123456789012345678")
    request = build_request(
        order_operation=OrderOperation.MARKET,
        quote_overrides={"price": price, "max_adverse_price": price},
        cost_overrides={"slippage_upper_bound": "0", "spread_upper_bound": "0"},
        rules_overrides={
            "price_tick": tick,
            "min_price": "1",
            "max_price": "1000000",
            "quantity_step": "0.001",
            "min_quantity": "0.001",
            "min_notional": "100",
        },
        candidate_overrides={
            "entry_lower": price,
            "trigger": price,
            "entry_upper": price,
            "stop_loss": Decimal("93.950616438395060957"),
            "target": Decimal("111.111110111111110200"),
        },
        price_rounding=PriceRounding.CONSERVATIVE_ONE_TICK,
    )
    with localcontext() as context:
        context.prec = 6
        prices = resolve_prices(request)

    assert prices.stop == Decimal("93.827159649382715280")
    assert prices.target == Decimal("111.111110111111110200")
