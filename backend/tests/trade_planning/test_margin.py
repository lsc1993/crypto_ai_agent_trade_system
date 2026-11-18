# 验证 T12 保证金与强平核对：初始保证金确定性计算、用户预览与计划数量一致、
# 缺失档位/强平参考为 unknown，多头/空头止损必须位于强平价的安全一侧。
# 保证金资料均为合成用户声明，不读取私有账户、交易所档位或真实余额。
from __future__ import annotations

from decimal import Decimal

import pytest

from app.research.strategies.contracts import StrategyDirection
from app.trade_planning.contracts import PlanningCalculationError, PlanningReason
from app.trade_planning.margin import (
    initial_margin_for,
    liquidation_distance_ok,
    margin_preview_reasons,
)
from tests.trade_planning.planning_fixtures import build_request, product


def _product(symbol: str):
    return product(symbol)


# 逐仓初始保证金 = 名义额 / 声明杠杆；除法结果向上保留到 18 位，避免低估占用。
def test_initial_margin_is_derived_from_notional_and_declared_leverage() -> None:
    assert initial_margin_for(Decimal("190"), Decimal("2")) == Decimal("95")
    assert initial_margin_for(Decimal("100"), Decimal("3")) == Decimal("33.333333333333333334")

    with pytest.raises(PlanningCalculationError):
        initial_margin_for(Decimal("100"), Decimal("0"))


# 用户预览只对声明的名义额和保证金有效；计划数量变化后不能继续套用旧预览。
def test_margin_preview_must_match_plan_notional_and_initial_margin() -> None:
    request = build_request()

    assert (
        margin_preview_reasons(
            request,
            entry_price=Decimal("100"),
            quantity=Decimal("1.9"),
            notional=Decimal("190"),
            initial_margin=Decimal("95"),
        )
        == ()
    )

    notional_mismatch = margin_preview_reasons(
        request,
        entry_price=Decimal("100"),
        quantity=Decimal("1.7"),
        notional=Decimal("170"),
        initial_margin=Decimal("85"),
    )
    assert PlanningReason.MARGIN_PREVIEW_NOT_APPLICABLE in notional_mismatch

    margin_mismatch = margin_preview_reasons(
        request,
        entry_price=Decimal("100"),
        quantity=Decimal("1.9"),
        notional=Decimal("190"),
        initial_margin=Decimal("94"),
    )
    assert PlanningReason.MARGIN_PREVIEW_MISMATCH in margin_mismatch


# 维持保证金档位/强平参考任一缺失时不得用简化公式替代；结果为 unknown。
def test_incomplete_margin_tier_evidence_is_unknown() -> None:
    request = build_request(
        margin_overrides={
            "maintenance_margin_rate": None,
            "maintenance_margin_amount": None,
            "liquidation_price_reference": None,
        }
    )
    evidence = request.profile.margin_evidence
    assert evidence is not None
    assert "maintenance_margin_evidence" in evidence.missing_fields
    assert "liquidation_price_reference" in evidence.missing_fields
    assert liquidation_distance_ok(request, Decimal("95")) is None


# 强平参考价必须越过保护性止损：多头强平更低、空头强平更高；缺失时保持 unknown。
def test_liquidation_side_depends_on_direction() -> None:
    long_request = build_request()
    assert liquidation_distance_ok(long_request, Decimal("95")) is True

    unsafe_long = build_request(margin_overrides={"liquidation_price_reference": "96"})
    assert liquidation_distance_ok(unsafe_long, Decimal("95")) is False

    short_request = build_request(
        direction=StrategyDirection.SHORT,
        margin_overrides={"liquidation_price_reference": "150"},
    )
    assert liquidation_distance_ok(short_request, Decimal("105")) is True

    unsafe_short = build_request(
        direction=StrategyDirection.SHORT,
        margin_overrides={"liquidation_price_reference": "100"},
    )
    assert liquidation_distance_ok(unsafe_short, Decimal("105")) is False


# 声明杠杆、名义额和所需保证金都是正数；非法值在契约边界已拒绝，纯函数仍防御。
def test_margin_helpers_reject_non_positive_inputs() -> None:
    with pytest.raises(PlanningCalculationError):
        initial_margin_for(Decimal("0"), Decimal("2"))
    with pytest.raises(PlanningCalculationError):
        initial_margin_for(Decimal("-1"), Decimal("2"))

    request = build_request()
    with pytest.raises(PlanningCalculationError):
        margin_preview_reasons(
            request,
            entry_price=Decimal("0"),
            quantity=Decimal("0"),
            notional=Decimal("0"),
            initial_margin=Decimal("0"),
        )


# 名义额和初始保证金相同不代表同一预览：必须绑定实际入场价和数量，避免把
# 50×3.8 的强平参考套到 100×1.9 的计划。
def test_preview_binds_entry_price_and_quantity() -> None:
    request = build_request(
        margin_overrides={
            "applicable_entry_price": "50",
            "applicable_quantity": "3.8",
        }
    )

    reasons = margin_preview_reasons(
        request,
        entry_price=Decimal("100"),
        quantity=Decimal("1.9"),
        notional=Decimal("190"),
        initial_margin=Decimal("95"),
    )
    assert PlanningReason.MARGIN_PREVIEW_MISMATCH in reasons


# 预览还必须绑定产品与方向；同一数量/名义额不能跨多头/空头或不同产品复用。
def test_preview_binds_product_and_direction() -> None:
    wrong_direction = build_request(
        direction=StrategyDirection.SHORT,
        margin_overrides={"applicable_direction": "long"},
    )
    direction_reasons = margin_preview_reasons(
        wrong_direction,
        entry_price=Decimal("100"),
        quantity=Decimal("1.9"),
        notional=Decimal("190"),
        initial_margin=Decimal("95"),
    )
    assert PlanningReason.MARGIN_PREVIEW_MISMATCH in direction_reasons

    wrong_product = build_request(margin_overrides={"applicable_product": _product("ETHUSDT")})
    product_reasons = margin_preview_reasons(
        wrong_product,
        entry_price=Decimal("100"),
        quantity=Decimal("1.9"),
        notional=Decimal("190"),
        initial_margin=Decimal("95"),
    )
    assert PlanningReason.MARGIN_PREVIEW_MISMATCH in product_reasons
