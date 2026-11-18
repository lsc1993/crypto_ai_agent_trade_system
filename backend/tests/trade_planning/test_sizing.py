# 验证 T12 确定性数量/成本/保证金手算：多空方向、保守成本上界、步长与最小订单冲突。
# 所有数值均为合成夹具；断言基于独立手算，不调用交易所、模型、数据库或真实资金。
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.research.strategies.contracts import PriceRounding, StrategyDirection
from app.shared.agent_types import VersionRef
from app.trade_planning.contracts import (
    OrderOperation,
    PlanningQuote,
    PlanningReason,
    SizingStatus,
)
from app.trade_planning.sizing import calculate_size
from tests.trade_planning.planning_fixtures import (
    NOW,
    build_request,
    product,
)


# 计划任务 Step 1 的独立手算样例：m=1、e=100、s=95、t=110、双边费率 0.001、
# 滑点/持有成本为 0、R=10、step=0.1、杠杆=2。L=5.195、W=9.79、q=1.9。
def test_long_sizing_matches_independent_hand_calculation() -> None:
    request = build_request()
    size = calculate_size(request)

    assert size.status is SizingStatus.SIZED
    assert size.quantity == Decimal("1.9")
    assert size.stop_path_loss == Decimal("9.8705")
    assert size.target_net_reward == Decimal("18.601")
    assert size.initial_margin == Decimal("95")
    assert size.notional == Decimal("190")
    assert size.risk_budget == Decimal("10")
    assert size.entry_price == Decimal("100")
    assert size.stop_price == Decimal("95")
    assert size.target_price == Decimal("110")
    assert size.stop_exit_quantity == Decimal("1.9")
    assert size.target_exit_quantity == Decimal("1.9")
    assert size.net_reward_risk_ratio == Decimal("1.884504331087584215")
    assert size.expires_at == NOW + timedelta(minutes=20)
    assert size.reason_codes == ()


# 空头将最不利入场取 entry_lower，止损在上方、目标在下方；费用按各自名义额计。
# L=(105-100)+0.1+0.105=5.205，W=(100-90)-0.1-0.09=9.81，q=floor(10/5.205,0.1)=1.9。
def test_short_sizing_mirrors_long_geometry_without_reusing_long_prices() -> None:
    request = build_request(direction=StrategyDirection.SHORT)
    size = calculate_size(request)

    assert size.status is SizingStatus.SIZED
    assert size.quantity == Decimal("1.9")
    assert size.stop_path_loss == Decimal("9.8895")
    assert size.target_net_reward == Decimal("18.639")
    assert size.initial_margin == Decimal("95")
    assert size.entry_price == Decimal("100")
    assert size.stop_price == Decimal("105")
    assert size.target_price == Decimal("90")


# 非零滑点/价差/持有成本使用保守上界：止损退出价向下调整、目标退出价向下调整，
# 入场限价不重复叠加滑点。L=5.579715、W=9.36033，q=1.7。
def test_nonzero_costs_use_conservative_upper_bounds() -> None:
    request = build_request(
        cost_overrides={
            "slippage_rate": "0",
            "spread_rate": "0",
            "holding_cost_rate": "0",
            "slippage_upper_bound": "0.002",
            "spread_upper_bound": "0.001",
            "holding_cost_upper_bound": "0.001",
        }
    )
    size = calculate_size(request)

    assert size.status is SizingStatus.SIZED
    assert size.quantity == Decimal("1.7")
    assert size.stop_path_loss == Decimal("9.4855155")
    assert size.target_net_reward == Decimal("15.912561")
    assert size.initial_margin == Decimal("85")
    assert size.notional == Decimal("170")
    assert size.risk_budget is not None
    assert size.stop_path_loss <= size.risk_budget


# 理论数量 0.962 向下取整为 0.9 后低于最小数量 1；不能为了达到最小订单把数量
# 向上加到 1.0，否则风险会超过 R=5。函数返回明确阻断而不是伪造一个可执行数量。
def test_minimum_order_conflict_blocks_without_increasing_risk() -> None:
    request = build_request(
        policy_overrides={"max_risk_per_trade": "5"},
        rules_overrides={"min_quantity": "1"},
    )
    size = calculate_size(request)

    assert size.status is SizingStatus.BLOCKED
    assert size.quantity == Decimal("0")
    assert PlanningReason.MIN_QUANTITY_NOT_MET in size.reason_codes
    assert size.stop_path_loss == Decimal("0")


# 最小名义额冲突同样阻断；不能通过加大数量或移动止损/目标制造合格结果。
def test_minimum_notional_conflict_blocks_instead_of_resizing_structure() -> None:
    request = build_request(
        policy_overrides={"max_risk_per_trade": "5"},
        rules_overrides={"min_notional": "100"},
    )
    size = calculate_size(request)

    assert size.status is SizingStatus.BLOCKED
    assert size.quantity == Decimal("0")
    assert PlanningReason.MIN_NOTIONAL_NOT_MET in size.reason_codes


# 缺资料时不能把 None 当零计算；数量求解必须先返回待补/阻断，由风险检查说明未知项。
def test_missing_profile_field_blocks_instead_of_using_zero() -> None:
    request = build_request(profile_overrides={"remaining_daily_loss": None})
    size = calculate_size(request)

    assert size.status is SizingStatus.BLOCKED
    assert size.quantity == Decimal("0")
    assert PlanningReason.INPUTS_INCOMPLETE in size.reason_codes


# 市场单必须有明确最大不利成交价；缺失时不能生成无价格上界的可实施计划。
def test_market_order_requires_explicit_max_adverse_price() -> None:
    request = build_request(order_operation=OrderOperation.MARKET)
    size = calculate_size(request)

    assert size.status is SizingStatus.BLOCKED
    assert PlanningReason.MARKET_PRICE_BOUND_MISSING in size.reason_codes


# 有明确最大不利成交价时，市场单以该价格作为 e 重算风险；不额外叠加第二次入场滑点。
# L=(100-95)+0.1+0.095=5.195，q=1.9，结果与限价单边界一致但入口定义不同。
def test_market_order_uses_declared_max_adverse_price() -> None:
    request = build_request(
        order_operation=OrderOperation.MARKET,
        quote_overrides={"max_adverse_price": Decimal("100")},
    )
    size = calculate_size(request)

    assert size.status is SizingStatus.SIZED
    assert size.entry_price == Decimal("100")
    assert size.quantity == Decimal("1.9")
    assert size.stop_path_loss == Decimal("9.8705")


# strict 价格舍入要求候选价格都在 tick 格点上；离格即阻断，不能静默挪动结构。
def test_strict_price_rounding_rejects_off_grid_stop() -> None:
    request = build_request(candidate_overrides={"stop_loss": Decimal("94.9")})
    size = calculate_size(request)

    assert size.status is SizingStatus.BLOCKED
    assert size.quantity == Decimal("0")
    assert PlanningReason.PRICE_NOT_ON_TICK in size.reason_codes


# conservative_one_tick 只在评估器明确声明时向保守方向移动止损一格；移动后重算风险，
# 不移动入场/目标，也不借此放宽风险或盈亏比。
def test_conservative_one_tick_moves_stop_only_toward_risk() -> None:
    request = build_request(
        candidate_overrides={"stop_loss": Decimal("94.9")},
        price_rounding=PriceRounding.CONSERVATIVE_ONE_TICK,
    )
    size = calculate_size(request)

    assert size.status is SizingStatus.SIZED
    assert size.stop_price == Decimal("94.5")
    assert size.quantity == Decimal("1.7")
    assert size.stop_path_loss == Decimal("9.68065")


# 报价不能来自未来；未来观测时刻会制造不可复现的“当前价”，必须在请求边界拒绝。
def test_future_quote_cannot_be_used_as_current_price() -> None:
    with pytest.raises(ValidationError):
        build_request(quote_overrides={"observed_at": NOW + timedelta(seconds=1)})


# NaN、Infinity、指数和超长数值不能进入 Decimal 计算；同名币种但产品不一致也必须拒绝。
def test_reject_nonfinite_units_and_decimal_overflow() -> None:
    for invalid in ("NaN", "Infinity", "-Infinity", "1e3", "1" * 31, 1.0, True):
        with pytest.raises(ValidationError):
            PlanningQuote.model_validate(
                {
                    "artifact": {
                        "artifact_id": "77777777-7777-4777-8777-777777777777",
                        "sha256": "d" * 64,
                    },
                    "price": invalid,
                    "observed_at": NOW - timedelta(seconds=10),
                    "expires_at": NOW + timedelta(seconds=50),
                    "source": "合成公开报价",
                }
            )

    with pytest.raises(ValidationError):
        build_request(rules_overrides={"product": product("ETHUSDT")})

    # 候选绑定的策略版本与请求所选策略不一致时不得计算，避免把候选挂到别的策略。
    other_ref = VersionRef(
        version_id=UUID("99999999-9999-4999-8999-999999999999"),
        sha256="e" * 64,
    )
    with pytest.raises(ValidationError):
        build_request(candidate_overrides={"strategy_ref": other_ref})


# 风险额度取政策、单笔剩余、当日剩余和组合剩余的最小值；这里当日剩余 4 成为 R。
def test_risk_budget_is_minimum_of_declared_remaining_limits() -> None:
    request = build_request(profile_overrides={"remaining_daily_loss": "4"})
    size = calculate_size(request)

    assert size.status is SizingStatus.SIZED
    assert size.risk_budget == Decimal("4")
    assert size.quantity == Decimal("0.7")
    assert size.stop_path_loss == Decimal("3.6365")


# 名义额上限按最不利入场价折算数量；不能先算出超过政策的名义额再靠检查发现。
def test_max_notional_caps_quantity_before_rounding() -> None:
    request = build_request(policy_overrides={"max_notional": "100"})
    size = calculate_size(request)

    assert size.status is SizingStatus.SIZED
    assert size.quantity == Decimal("1")
    assert size.notional == Decimal("100")


# 可用保证金上限使用用户声明的可用额度与规划资金的较小者，再乘声明杠杆。
def test_available_margin_caps_quantity() -> None:
    request = build_request(
        profile_overrides={"available_margin": "50"},
        margin_overrides={"applicable_notional": "100", "required_margin": "50"},
    )
    size = calculate_size(request)

    assert size.status is SizingStatus.SIZED
    assert size.quantity == Decimal("1")
    assert size.notional == Decimal("100")
    assert size.initial_margin == Decimal("50")


# 政策数量上限同样参与最小值；不能因风险额度更大而超过用户的数量上限。
def test_max_quantity_caps_quantity() -> None:
    request = build_request(policy_overrides={"max_quantity": "1.2"})
    size = calculate_size(request)

    assert size.status is SizingStatus.SIZED
    assert size.quantity == Decimal("1.2")
    assert size.notional == Decimal("120")


# 规则未声明限价单时明确阻断；不能按常见交易所习惯假定支持。
def test_unsupported_order_type_blocks_sizing() -> None:
    request = build_request(rules_overrides={"order_types": ("MARKET",)})
    size = calculate_size(request)

    assert size.status is SizingStatus.BLOCKED
    assert PlanningReason.ORDER_TYPE_UNSUPPORTED in size.reason_codes


# 基础资产数量单位与线性永续乘数不一致时拒绝，避免张/币数量混算。
def test_base_asset_unit_with_non_unit_multiplier_is_rejected() -> None:
    request = build_request(
        rules_overrides={"quantity_unit": "base_asset", "contract_multiplier": "2"}
    )
    size = calculate_size(request)

    assert size.status is SizingStatus.BLOCKED
    assert PlanningReason.UNIT_INCONSISTENT in size.reason_codes


# 材料指纹绑定候选/版本/报价/操作，不包含评估时钟；同一材料在有效期内重读不能
# 因检查时刻变化而被 T13 当成另一份计划材料。
def test_material_hash_excludes_evaluation_clock() -> None:
    request = build_request()
    later = request.model_copy(update={"evaluated_at": request.evaluated_at + timedelta(seconds=1)})

    assert later.material_sha256() == request.material_sha256()
    assert later.evaluated_at != request.evaluated_at


# SizingResult 必须绑定本请求的材料指纹；否则旧请求的数量可以套到新政策/资料上。
def test_sizing_result_binds_request_material() -> None:
    request = build_request()
    size = calculate_size(request)

    assert size.material_hash == request.material_sha256()


# 结算精度会把极小的 L/W 量化到 1e-18 格点；返回的净盈亏比必须由最终结算金额
# 复算，不能用未量化的原始比率绕过政策门槛。
def test_ratio_uses_final_quantized_settlement_amounts() -> None:
    request = build_request(
        policy_overrides={"max_notional": "0.0000000000000001"},
        rules_overrides={
            "quantity_step": "0.000000000000000001",
            "min_quantity": "0.000000000000000001",
            "min_notional": "0.000000000000000001",
            "market_quantity_step": "0.000000000000000001",
            "market_min_quantity": "0.000000000000000001",
        },
    )
    size = calculate_size(request)

    assert size.status is SizingStatus.SIZED
    assert size.stop_path_loss == Decimal("0.000000000000000006")
    assert size.target_net_reward == Decimal("0.000000000000000009")
    assert size.net_reward_risk_ratio == Decimal("1.5")


# 若最终收益量化到 0，必须返回 blocked，而不是构造非法的 SizingResult/抛 Pydantic
# ValidationError；否则调用方无法得到稳定原因。
def test_zero_quantized_reward_blocks_without_validation_error() -> None:
    request = build_request(
        policy_overrides={"max_notional": "0.0000000000000001"},
        rules_overrides={
            "quantity_step": "0.000000000000000001",
            "min_quantity": "0.000000000000000001",
            "min_notional": "0.000000000000000001",
            "market_quantity_step": "0.000000000000000001",
            "market_min_quantity": "0.000000000000000001",
        },
        candidate_overrides={"target": Decimal("100.5")},
    )
    size = calculate_size(request)

    assert size.status is SizingStatus.BLOCKED
    assert PlanningReason.REWARD_NOT_POSITIVE in size.reason_codes


# 计算不得继承调用方较低的 Decimal 精度；同一合法请求在低精度上下文中应得到
# 相同数量/风险/收益/比率。
def test_sizing_is_independent_of_caller_decimal_precision() -> None:
    request = build_request()
    baseline = calculate_size(request)
    with localcontext() as context:
        context.prec = 6
        low_precision = calculate_size(request)

    assert low_precision == baseline
