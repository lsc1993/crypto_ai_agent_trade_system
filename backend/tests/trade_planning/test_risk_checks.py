# 验证 T12 逐项确定性风险检查：输入完整/时效、冷却熔断、仓位杠杆、订单约束、
# 计划风险、净盈亏比、保证金预览和强平方向；缺失资料必须为 unknown 而不是 pass。
# 测试只使用合成资料，不访问数据库、网络、模型、账户或交易服务。
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.trade_planning.contracts import (
    CheckBasis,
    CheckStatus,
    PlanningRequest,
    SizingResult,
    ValidationCheck,
)
from app.trade_planning.risk_checks import evaluate_planning_risk
from app.trade_planning.sizing import calculate_size
from tests.trade_planning.planning_fixtures import NOW, build_request


# 按检查名建立索引；重复检查名会让调用方无法稳定读取，因此另做唯一性断言。
def _checks_by_name(
    request: PlanningRequest,
) -> tuple[SizingResult, dict[str, ValidationCheck]]:
    size = calculate_size(request)
    checks = evaluate_planning_risk(request, size)
    assert len({check.name for check in checks}) == len(checks)
    return size, {check.name: check for check in checks}


# 完整合成资料下，所有必需检查必须明确 pass；不能有缺项被默认通过。
def test_complete_synthetic_request_passes_all_required_checks() -> None:
    request = build_request()
    size = calculate_size(request)
    checks = evaluate_planning_risk(request, size)
    failed = [
        (check.name, check.status.value, check.reason_code)
        for check in checks
        if check.required and check.status is not CheckStatus.PASS
    ]

    assert failed == []
    assert size.status.value == "sized"
    # 检查必须绑定同一材料指纹，后续 T13 才能判断采纳/重验是否仍对应本材料。
    assert {check.material_hash for check in checks} == {request.material_sha256()}


# 资料/规则/报价/日损声明过期后，原检查不能继续 pass；跨 UTC 日界线尤其不能
# 把昨天的剩余日损额度当成今天仍有效。
def test_stale_inputs_and_previous_day_risk_declaration_fail() -> None:
    request = build_request(evaluated_at=NOW + timedelta(days=1))
    _, checks = _checks_by_name(request)

    assert checks["profile_current"].status is CheckStatus.FAIL
    assert checks["costs_current"].status is CheckStatus.FAIL
    assert checks["rules_current"].status is CheckStatus.FAIL
    assert checks["margin_evidence_current"].status is CheckStatus.FAIL
    assert checks["daily_risk_current"].status is CheckStatus.FAIL
    assert checks["daily_risk_current"].reason_code == "daily_risk_declaration_stale"
    # 报价在测试夹具中始终相对评估时刻生成，因此报价本身仍新鲜；不能因此忽略
    # 其他资料和跨日声明已失效。
    assert checks["quote_current"].status is CheckStatus.PASS


# 缺资料/未知占用必须为 unknown；显式非零已有仓位/挂单为 fail，不能被当成空仓。
def test_missing_and_existing_exposure_are_not_treated_as_zero() -> None:
    missing = build_request(profile_overrides={"remaining_daily_loss": None})
    missing_size = calculate_size(missing)
    missing_checks = {check.name: check for check in evaluate_planning_risk(missing, missing_size)}
    assert missing_checks["profile_complete"].status is CheckStatus.UNKNOWN
    assert missing_checks["profile_complete"].reason_code == "profile_incomplete"

    unknown_exposure = build_request(profile_overrides={"open_order_risk": None})
    unknown_size = calculate_size(unknown_exposure)
    unknown_checks = {
        check.name: check for check in evaluate_planning_risk(unknown_exposure, unknown_size)
    }
    assert unknown_checks["existing_exposure_supported"].status is CheckStatus.UNKNOWN

    occupied = build_request(profile_overrides={"existing_position_notional": "1"})
    occupied_size = calculate_size(occupied)
    occupied_checks = {
        check.name: check for check in evaluate_planning_risk(occupied, occupied_size)
    }
    assert occupied_checks["existing_exposure_supported"].status is CheckStatus.FAIL
    assert occupied_checks["existing_exposure_supported"].reason_code == (
        "existing_position_unsupported"
    )


# 有效冷却、熔断和超过用户政策的杠杆都是确定性阻断；不能靠减少数量放行。
def test_cooldown_breaker_and_leverage_excess_block() -> None:
    cooldown = build_request(
        profile_overrides={
            "cooldown_status": "active",
            "cooldown_until": NOW + timedelta(minutes=10),
        }
    )
    _, cooldown_checks = _checks_by_name(cooldown)
    assert cooldown_checks["cooldown_inactive"].status is CheckStatus.FAIL

    breaker = build_request(profile_overrides={"circuit_breaker_active": True})
    _, breaker_checks = _checks_by_name(breaker)
    assert breaker_checks["circuit_breaker_inactive"].status is CheckStatus.FAIL

    leverage = build_request(
        profile_overrides={"leverage": "4"},
        margin_overrides={"leverage": "4", "required_margin": "47.5"},
    )
    _, leverage_checks = _checks_by_name(leverage)
    assert leverage_checks["leverage_within_policy"].status is CheckStatus.FAIL
    assert leverage_checks["leverage_within_policy"].reason_code == "leverage_exceeds_policy"


# 最小净盈亏比由政策确定；该检查不通过时计划仍可展示草案，但不能被 T13 判为可实施。
def test_reward_risk_ratio_below_policy_fails() -> None:
    request = build_request(policy_overrides={"min_reward_risk_ratio": "2"})
    size, checks = _checks_by_name(request)

    assert size.status.value == "sized"
    assert checks["reward_risk_ratio_met"].status is CheckStatus.FAIL
    assert checks["reward_risk_ratio_met"].reason_code == "reward_risk_ratio_below_minimum"


# 强平参考价必须位于止损的安全一侧；多头止损低于强平价才安全，空头相反。
def test_liquidation_reference_must_be_beyond_protective_stop() -> None:
    unsafe_long = build_request(margin_overrides={"liquidation_price_reference": "96"})
    _, long_checks = _checks_by_name(unsafe_long)
    assert long_checks["liquidation_distance_safe"].status is CheckStatus.FAIL

    from app.research.strategies.contracts import StrategyDirection

    unsafe_short = build_request(
        direction=StrategyDirection.SHORT,
        margin_overrides={"liquidation_price_reference": "100"},
    )
    _, short_checks = _checks_by_name(unsafe_short)
    assert short_checks["liquidation_distance_safe"].status is CheckStatus.FAIL


# 保证金资料是用户声明；检查依据不能伪装成公共 API 已核实，也不能把不完整预览当 pass。
def test_margin_checks_are_user_declared_and_incomplete_preview_is_unknown() -> None:
    request = build_request()
    _, checks = _checks_by_name(request)

    for name in (
        "margin_evidence_current",
        "margin_evidence_complete",
        "margin_preview_matches",
        "liquidation_distance_safe",
    ):
        assert checks[name].basis is CheckBasis.USER_DECLARED
        assert "verified" not in checks[name].source.lower()

    incomplete = build_request(
        margin_overrides={
            "applicable_notional": "500",
            "required_margin": "250",
        }
    )
    _, incomplete_checks = _checks_by_name(incomplete)
    assert incomplete_checks["margin_preview_matches"].status is CheckStatus.FAIL
    assert incomplete_checks["margin_preview_matches"].reason_code == (
        "margin_preview_not_applicable"
    )


# 最小订单冲突时，相关检查必须 fail 并保留原因；其他未知项不能因此被写成 pass。
def test_minimum_order_failure_is_visible_to_readiness_consumers() -> None:
    request = build_request(
        policy_overrides={"max_risk_per_trade": "5"},
        rules_overrides={"min_quantity": "1"},
    )
    size, checks = _checks_by_name(request)

    assert size.quantity == Decimal("0")
    assert checks["quantity_sized"].status is CheckStatus.FAIL
    assert checks["min_quantity_met"].status is CheckStatus.FAIL
    assert checks["min_quantity_met"].reason_code == "min_quantity_not_met"
    # 已知冲突不能伪装成“未知待补”；T13 应据此派生 blocked，而不是 needs_inputs。
    assert checks["min_quantity_met"].reason_code != "profile_incomplete"


# 过期候选和停止交易仍应可构造检查记录并明确 fail，而不是在请求/计算前丢弃。
def test_expired_candidate_and_non_trading_rules_fail() -> None:
    expired = build_request(candidate_overrides={"valid_until": NOW - timedelta(minutes=4)})
    _, expired_checks = _checks_by_name(expired)
    assert expired_checks["candidate_current"].status is CheckStatus.FAIL
    assert expired_checks["candidate_current"].reason_code == "planning_candidate_expired"

    halted = build_request(rules_overrides={"trading_status": "BREAK"})
    _, halted_checks = _checks_by_name(halted)
    assert halted_checks["rules_current"].status is CheckStatus.FAIL
    assert halted_checks["rules_current"].reason_code == "planning_rules_not_trading"


# 保证金档位/强平参考不完整时，预览和强平检查必须是 unknown，不是 fail 或 pass。
def test_incomplete_margin_evidence_makes_preview_and_liquidation_unknown() -> None:
    request = build_request(
        margin_overrides={
            "maintenance_margin_rate": None,
            "maintenance_margin_amount": None,
            "liquidation_price_reference": None,
        }
    )
    _, checks = _checks_by_name(request)

    assert checks["margin_evidence_complete"].status is CheckStatus.UNKNOWN
    assert checks["margin_preview_matches"].status is CheckStatus.UNKNOWN
    assert checks["liquidation_distance_safe"].status is CheckStatus.UNKNOWN
