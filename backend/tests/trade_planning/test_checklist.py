# 验证 T12 手动实施清单：操作步骤、程序/用户声明/人工核对分层、未成交/部分成交/
# 跳价/超时/到期分支，以及所有阻断检查如实展示；清单不生成任何交易所订单请求。
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.trade_planning.checklist import build_manual_checklist
from app.trade_planning.contracts import (
    ChecklistVerification,
    CheckStatus,
    ManualChecklist,
    PlanningRequest,
)
from app.trade_planning.risk_checks import evaluate_planning_risk
from app.trade_planning.sizing import calculate_size
from tests.trade_planning.planning_fixtures import NOW, build_request


# 构建完整清单，供多个断言复用；检查与数量都来自同一请求，避免测试自造绿色状态。
def _checklist(request: PlanningRequest) -> ManualChecklist:
    size = calculate_size(request)
    checks = evaluate_planning_risk(request, size)
    return build_manual_checklist(request, size, checks)


# 清单必须覆盖入场、数量/名义额、保护性止损、目标退出、到期和人工反馈；
# 异常分支至少包含未成交、部分成交、跳价、超时和计划到期。
def test_checklist_covers_required_manual_steps_and_exception_branches() -> None:
    request = build_request()
    checklist = _checklist(request)
    item_codes = {item.code for item in checklist.items}
    branch_codes = {branch.code for branch in checklist.exception_branches}

    assert {
        "verify_product_and_venue",
        "verify_margin_mode_and_leverage",
        "verify_available_margin_and_positions",
        "verify_entry_condition",
        "place_entry_order_manually",
        "place_protective_stop_manually",
        "place_target_exit_manually",
        "verify_order_quantity_and_notional",
        "verify_expiry_and_cancel_condition",
        "record_execution_feedback",
    } <= item_codes
    assert {
        "entry_not_filled",
        "entry_partially_filled",
        "price_moved_outside_range",
        "order_timeout",
        "plan_expired",
        "costs_or_rules_changed",
    } <= branch_codes

    assert checklist.execution_mode == "manual"
    assert all(branch.automatic_order_action is False for branch in checklist.exception_branches)
    assert all(branch.requires_user_action is True for branch in checklist.exception_branches)
    assert checklist.expires_at == request.candidate.valid_until


# 核对项必须显式区分程序已验证、用户声明和仍需在交易所人工核对，不能混为账户已验证。
def test_checklist_separates_verification_sources() -> None:
    checklist = _checklist(build_request())
    by_code = {item.code: item for item in checklist.items}

    assert by_code["verify_order_quantity_and_notional"].verification is (
        ChecklistVerification.PROGRAM_VERIFIED
    )
    assert by_code["verify_margin_mode_and_leverage"].verification is (
        ChecklistVerification.USER_DECLARED
    )
    assert by_code["verify_available_margin_and_positions"].verification is (
        ChecklistVerification.MANUAL_CONFIRMATION_REQUIRED
    )
    assert checklist.quantity == Decimal("1.9")
    assert checklist.notional == Decimal("190")
    assert checklist.initial_margin == Decimal("95")
    assert checklist.stop_path_loss == Decimal("9.8705")
    assert checklist.target_net_reward == Decimal("18.601")


# 任一必需检查 fail/unknown 都进入 blocking_checks；清单可以展示草案，但不能暗示可实施。
def test_blocking_checks_are_explicit_and_not_hidden() -> None:
    checklist = _checklist(
        build_request(
            policy_overrides={"max_risk_per_trade": "5"},
            rules_overrides={"min_quantity": "1"},
        )
    )

    assert "min_quantity_met" in checklist.blocking_checks
    assert "quantity_sized" in checklist.blocking_checks
    assert checklist.quantity == Decimal("0")
    # 清单没有 ready_for_manual_execution 之类的布尔捷径，采纳/可实施状态只由 T13 派生。
    assert not hasattr(checklist, "ready_for_manual_execution")


# 未知/过期资料也要出现在阻断清单中，避免“检查列表为空”被误读为通过。
def test_unknown_required_check_is_blocking() -> None:
    checklist = _checklist(build_request(profile_overrides={"remaining_daily_loss": None}))
    checks_with_unknown = [
        check.name for check in checklist.checks if check.status is CheckStatus.UNKNOWN
    ]

    assert "profile_complete" in checks_with_unknown
    assert "profile_complete" in checklist.blocking_checks
    assert checklist.quantity == Decimal("0")


# 清单是人工操作说明，不是订单对象；序列化后不得出现 TradeIntent、订单号或
# 任何“已下单/已挂单/已撤单”的系统行为声明。
def test_checklist_has_no_order_execution_artifact_or_claim() -> None:
    checklist = _checklist(build_request())
    payload = checklist.model_dump_json()

    for forbidden in (
        "TradeIntent",
        "order_id",
        "clientOrderId",
        "已下单",
        "已挂单",
        "已撤单",
        "自动下单",
    ):
        assert forbidden not in payload


# 计划时间绑定候选有效期与评估时刻，不由客户端时钟决定；清单只展示不可变字段。
def test_checklist_binds_immutable_times_and_material_hash() -> None:
    request = build_request()
    checklist = _checklist(request)

    assert checklist.material_hash == request.material_sha256()
    assert checklist.expires_at == NOW + timedelta(minutes=20)
    assert checklist.order_type == "LIMIT"
    assert checklist.time_in_force == "GTC"


# 市价操作必须使用有界最大不利成交价，并显示市价入场步骤；市价单不虚构 GTC。
def test_market_operation_checklist_has_bounded_entry_and_no_tif() -> None:
    from app.trade_planning.contracts import OrderOperation

    request = build_request(
        order_operation=OrderOperation.MARKET,
        quote_overrides={"max_adverse_price": Decimal("100")},
    )
    checklist = _checklist(request)
    item_codes = {item.code for item in checklist.items}

    assert checklist.order_type == "MARKET"
    assert checklist.time_in_force is None
    assert "place_market_entry_manually" in item_codes
    assert checklist.planned_entry == Decimal("100")
    assert checklist.entry_lower <= checklist.trigger <= checklist.entry_upper


# 清单必须拒绝混合其他规划材料的检查，避免把旧检查结果套到当前计划。
def test_checklist_rejects_checks_from_another_material() -> None:
    request = build_request()
    size = calculate_size(request)
    checks = evaluate_planning_risk(request, size)
    foreign = checks[0].model_copy(update={"material_hash": "f" * 64})

    from app.trade_planning.contracts import PlanningCalculationError

    with pytest.raises(PlanningCalculationError):
        build_manual_checklist(request, size, (foreign, *checks[1:]))
