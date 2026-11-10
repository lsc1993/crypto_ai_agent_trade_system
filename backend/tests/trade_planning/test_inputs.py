# 验证 C3 本地规划资料的纯契约：十进制拒绝、未知值保留、时效与不可变指纹。
# 所有数值均为合成资料；测试不访问数据库、公开网络、模型或真实账户。
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.shared.agent_types import VersionRef
from app.trade_planning.inputs import (
    CostAssumptions,
    CostAssumptionsDraft,
    MarginEvidence,
    MarginEvidenceDraft,
    PlanningProfileDraft,
    PlanningProfileSnapshot,
    PlanningRefs,
    PlanningRiskPolicy,
    PlanningRiskPolicyDraft,
    VenueRuleSnapshot,
)

NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)


# 读取首轮 tip 144e501 实际生成的合成快照及原始指纹；用于证明历史载荷可读。
def _legacy_fixture(name: str) -> tuple[dict[str, object], str]:
    path = Path(__file__).resolve().parents[1] / "fixtures" / name
    document = json.loads(path.read_text(encoding="utf-8"))
    return document["payload"], document["sha256"]


# 构造首期支持的 Binance USDT 线性永续产品键；测试组合不扩展生产支持目录。
def _product(symbol: str = "BTCUSDT") -> dict[str, str]:
    return {
        "venue": "binance_usdm",
        "symbol": symbol,
        "settlement": "USDT",
        "kind": "linear_perpetual",
    }


# 构造完整合成资料草稿；调用方可覆盖字段以验证缺项或非法值。
def _profile_draft(**overrides: object) -> PlanningProfileDraft:
    payload: dict[str, object] = {
        "product": _product(),
        "planning_capital": "10000",
        "available_margin": "5000",
        "remaining_single_trade_risk": "100",
        "remaining_daily_loss": "300",
        "remaining_portfolio_risk": "500",
        "existing_position_notional": "0",
        "existing_position_margin": "0",
        "existing_position_risk": "0",
        "open_order_notional": "0",
        "open_order_margin": "0",
        "open_order_risk": "0",
        "daily_risk_as_of": NOW.date(),
        "cooldown_status": "none",
        "cooldown_until": None,
        "circuit_breaker_active": False,
        "leverage": "2",
        "margin_mode": "isolated",
        "position_mode": "one_way",
        "margin_evidence": _margin_draft(),
        "costs": _cost_draft(),
    }
    payload.update(overrides)
    return PlanningProfileDraft.model_validate(payload)


# 构造完整合成费率草稿；valid_until 用于验证 15 分钟较早者规则。
def _cost_draft(
    valid_until: datetime = NOW + timedelta(minutes=30),
    *,
    entry_fee_rate: str = "0.0004",
) -> CostAssumptionsDraft:
    return CostAssumptionsDraft.model_validate(
        {
            "entry_fee_rate": entry_fee_rate,
            "stop_exit_fee_rate": "0.0004",
            "target_exit_fee_rate": "0.0004",
            "slippage_rate": "0.0005",
            "spread_rate": "0.0001",
            "holding_cost_rate": "0.0001",
            "slippage_upper_bound": "0.001",
            "spread_upper_bound": "0.0002",
            "holding_cost_upper_bound": "0.0002",
            "source": "合成费率资料",
            "valid_until": valid_until,
        }
    )


# 构造完整合成保证金证据草稿；来源明确为用户声明而非交易所 API 核实。
def _margin_draft(
    valid_until: datetime = NOW + timedelta(minutes=30),
    *,
    leverage: str = "2",
) -> MarginEvidenceDraft:
    return MarginEvidenceDraft.model_validate(
        {
            "margin_mode": "isolated",
            "leverage": leverage,
            "applicable_notional": "5000",
            "maintenance_margin_rate": "0.005",
            "required_margin": "250",
            "liquidation_price_reference": "40000",
            "trigger_price_basis": "mark_price",
            "source": "合成交易所界面预览",
            "valid_until": valid_until,
        }
    )


# 构造完整风险政策草稿；金额、比例和杠杆全部显式给出，不使用默认值。
def _policy_draft(**overrides: object) -> PlanningRiskPolicyDraft:
    payload: dict[str, object] = {
        "max_risk_per_trade": "100",
        "max_notional": "5000",
        "max_quantity": "2",
        "max_leverage": "3",
        "min_reward_risk_ratio": "1.5",
        "max_daily_loss": "300",
        "max_portfolio_risk": "500",
        "stop_loss_required": True,
        "enforce_cooldown": True,
        "enforce_circuit_breaker": True,
    }
    payload.update(overrides)
    return PlanningRiskPolicyDraft.model_validate(payload)


# 构造完整版本化资料快照；成本版本单独冻结后通过 ref 关联。
def _profile_snapshot(
    draft: PlanningProfileDraft | None = None,
    *,
    declared_at: datetime = NOW,
) -> PlanningProfileSnapshot:
    source = draft or _profile_draft()
    cost = CostAssumptions.build(
        version_id=uuid4(),
        draft=source.costs or _cost_draft(),
        declared_at=declared_at,
        expires_at=min(
            declared_at + timedelta(minutes=15),
            (source.costs or _cost_draft()).valid_until,
        ),
    )
    margin = MarginEvidence.build(
        draft=source.margin_evidence or _margin_draft(),
        declared_at=declared_at,
        expires_at=min(
            declared_at + timedelta(minutes=15),
            (source.margin_evidence or _margin_draft()).valid_until,
        ),
    )
    return PlanningProfileSnapshot.build(
        version_id=uuid4(),
        pool_id=uuid4(),
        pool_generation=1,
        draft=source,
        margin_evidence=margin,
        costs_ref=cost.ref,
        declared_at=declared_at,
        expires_at=min(
            declared_at + timedelta(minutes=15),
            cost.expires_at,
            margin.expires_at,
        ),
    )


def test_reject_nonfinite_units_and_decimal_overflow() -> None:
    # NaN、Infinity、指数形式和 31 位整数都必须在契约边界拒绝，不能进入 Decimal 计算。
    for invalid in ("NaN", "Infinity", "-Infinity", "1e3", "1" * 31, 1.0, True):
        with pytest.raises(ValidationError):
            _profile_draft(planning_capital=invalid)

    # USDT 线性永续之外的结算/产品类型不能通过 ProductKey 字面量校验。
    invalid_product = {**_product(), "settlement": "COIN", "kind": "inverse"}
    with pytest.raises(ValidationError):
        _profile_draft(product=invalid_product)

    # 负费率、负风险额和零杠杆都拒绝；拒绝发生在快照构建前。
    with pytest.raises(ValidationError):
        _cost_draft(entry_fee_rate="-0.0001")
    with pytest.raises(ValidationError):
        _profile_draft(remaining_single_trade_risk="-1")
    with pytest.raises(ValidationError):
        _margin_draft(leverage="0")


def test_unknown_occupancy_preserved_as_none_not_zero() -> None:
    # 未申报已有仓位/挂单时字段保持 None，不能自动补零冒充空仓。
    draft = _profile_draft(
        existing_position_notional=None,
        existing_position_margin=None,
        existing_position_risk=None,
        open_order_notional=None,
        open_order_margin=None,
        open_order_risk=None,
    )
    assert draft.existing_position_risk is None
    assert draft.open_order_risk is None
    assert "existing_position_risk" in draft.missing_fields
    assert "open_order_risk" in draft.missing_fields

    profile = _profile_snapshot(draft)
    assert profile.existing_position_risk is None
    assert profile.open_order_risk is None
    assert profile.is_complete is False

    # 显式申报 0 才表示没有占用，并使资料完整。
    complete = _profile_snapshot()
    assert complete.existing_position_risk == Decimal("0")
    assert complete.is_complete is True


def test_legacy_profile_snapshot_reads_original_ref_and_serializes() -> None:
    # 首轮 tip 的实际载荷没有 cooldown_status；必须按旧字段集合校验原指纹。
    payload, expected_sha = _legacy_fixture("v1_planning_profile.json")
    assert "cooldown_status" not in payload
    legacy = PlanningProfileSnapshot.model_validate(payload)
    assert legacy.ref.sha256 == expected_sha
    assert legacy.cooldown_status is None
    assert "cooldown_status" in legacy.missing_fields
    assert legacy.is_complete is False

    # 历史序列化必须保留旧字段集合，不能把默认 None 写成新字段后破坏原 ref。
    serialized = legacy.versioned_payload()
    assert "cooldown_status" not in serialized
    roundtripped = PlanningProfileSnapshot.model_validate(serialized)
    assert roundtripped.ref == legacy.ref
    assert roundtripped.is_complete is False


def test_legacy_profile_with_cooldown_deadline_keeps_unknown_status() -> None:
    # 旧载荷允许只有 cooldown_until；读取时必须保持状态未知，不能推断为 none/active。
    payload, expected_sha = _legacy_fixture("v1_planning_profile_with_cooldown.json")
    assert "cooldown_status" not in payload
    legacy = PlanningProfileSnapshot.model_validate(payload)
    assert legacy.ref.sha256 == expected_sha
    assert legacy.cooldown_status is None
    assert legacy.cooldown_until == NOW + timedelta(minutes=10)
    assert "cooldown_status" in legacy.missing_fields
    assert legacy.is_complete is False

    serialized = legacy.versioned_payload()
    assert "cooldown_status" not in serialized
    assert serialized["cooldown_until"] == "2026-11-09T12:10:00Z"
    roundtripped = PlanningProfileSnapshot.model_validate(serialized)
    assert roundtripped.ref == legacy.ref
    assert roundtripped.cooldown_status is None
    assert roundtripped.is_complete is False


def test_legacy_profile_rejects_tampered_financial_and_nested_content() -> None:
    # 版本感知校验只忽略历史缺失字段，不跳过财务正文或嵌套保证金的指纹检查。
    payload, _ = _legacy_fixture("v1_planning_profile.json")
    tampered_financial = {**payload, "planning_capital": "10001"}
    with pytest.raises(ValidationError):
        PlanningProfileSnapshot.model_validate(tampered_financial)

    margin = payload["margin_evidence"]
    assert isinstance(margin, dict)
    margin_payload = cast(dict[str, object], margin)
    tampered_nested = {
        **payload,
        "margin_evidence": {**margin_payload, "leverage": "3"},
    }
    with pytest.raises(ValidationError):
        PlanningProfileSnapshot.model_validate(tampered_nested)


def test_cooldown_state_must_be_explicit() -> None:
    # 省略冷却状态时必须保持未知，不能因 cooldown_until 为 None 就判为“无冷却”。
    omitted_payload = _profile_draft().model_dump(mode="python", by_alias=False)
    omitted_payload.pop("cooldown_status")
    omitted = PlanningProfileDraft.model_validate(omitted_payload)
    assert omitted.cooldown_status is None
    assert "cooldown_status" in omitted.missing_fields
    omitted_profile = _profile_snapshot(omitted)
    assert omitted_profile.is_complete is False

    # 明确无冷却必须显式声明；此时 deadline 必须为空且资料可完整。
    no_cooldown = _profile_snapshot(_profile_draft(cooldown_status="none"))
    assert no_cooldown.is_complete is True

    # 有效冷却必须有显式状态和晚于声明时间的截止时间。
    active = _profile_snapshot(
        _profile_draft(
            cooldown_status="active",
            cooldown_until=NOW + timedelta(minutes=10),
        )
    )
    assert active.is_complete is True
    assert active.cooldown_until == NOW + timedelta(minutes=10)

    # 状态与截止时间不一致、未知状态携带截止时间都拒绝，避免隐式推断安全。
    for payload in (
        {"cooldown_status": "active", "cooldown_until": None},
        {"cooldown_status": "none", "cooldown_until": NOW + timedelta(minutes=10)},
        {"cooldown_status": None, "cooldown_until": NOW + timedelta(minutes=10)},
    ):
        with pytest.raises(ValidationError):
            _profile_draft(**payload)

    with pytest.raises(ValidationError):
        _profile_snapshot(
            _profile_draft(
                cooldown_status="active",
                cooldown_until=NOW - timedelta(minutes=1),
            )
        )


def test_profile_and_cost_expiry_use_earlier_bound() -> None:
    # 用户声明 30 分钟有效，但本地资料最多 15 分钟；快照取较早者。
    profile = _profile_snapshot()
    assert profile.declared_at == NOW
    assert profile.expires_at == NOW + timedelta(minutes=15)
    assert profile.margin_evidence is not None
    assert profile.margin_evidence.expires_at == NOW + timedelta(minutes=15)
    assert profile.is_expired(NOW + timedelta(minutes=15)) is True
    assert profile.is_expired(NOW + timedelta(minutes=15, microseconds=-1)) is False

    # 用户声明更短有效期时，成本与资料都不能超过该上界。
    short = _cost_draft(valid_until=NOW + timedelta(minutes=5))
    cost = CostAssumptions.build(
        version_id=uuid4(),
        draft=short,
        declared_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    assert cost.expires_at == NOW + timedelta(minutes=5)


def test_snapshot_ref_binds_nested_financial_content() -> None:
    # 版本指纹覆盖嵌套保证金证据和费用引用；篡改任一字段后不能复用旧 ref。
    profile = _profile_snapshot()
    payload = profile.model_dump(mode="json", by_alias=False)
    assert isinstance(payload["margin_evidence"], dict)
    payload["margin_evidence"]["leverage"] = "3"
    with pytest.raises(ValidationError):
        PlanningProfileSnapshot.model_validate(payload)

    # 根对象额外字段同样拒绝，避免未纳入指纹的字段悄悄进入规划域。
    with pytest.raises(ValidationError):
        PlanningProfileSnapshot.model_validate({**profile.model_dump(mode="json"), "secret": "x"})


def test_policy_missing_fields_and_explicit_limits() -> None:
    # 缺项政策可以保存为版本，但不完整，不能组合出可规划引用。
    incomplete = PlanningRiskPolicyDraft()
    assert incomplete.max_risk_per_trade is None
    policy = PlanningRiskPolicy.build(
        version_id=uuid4(),
        pool_id=uuid4(),
        pool_generation=1,
        draft=incomplete,
        declared_at=NOW,
    )
    assert policy.is_complete is False
    assert "max_risk_per_trade" in policy.missing_fields

    complete = PlanningRiskPolicy.build(
        version_id=uuid4(),
        pool_id=uuid4(),
        pool_generation=1,
        draft=_policy_draft(),
        declared_at=NOW,
    )
    assert complete.is_complete is True
    assert complete.max_leverage == Decimal("3")
    assert complete.stop_loss_required is True

    # 首期手动计划必须强制止损；缺项政策可以保存，但显式关闭止损不是合法政策。
    disabled_payload = _policy_draft().model_dump(mode="python", by_alias=False)
    disabled_payload["stop_loss_required"] = False
    with pytest.raises(ValidationError):
        PlanningRiskPolicyDraft.model_validate(disabled_payload)
    for field in ("enforce_cooldown", "enforce_circuit_breaker"):
        hard_constraint_payload = _policy_draft().model_dump(mode="python", by_alias=False)
        hard_constraint_payload[field] = False
        with pytest.raises(ValidationError):
            PlanningRiskPolicyDraft.model_validate(hard_constraint_payload)


def test_margin_evidence_requires_tier_and_liquidation_basis() -> None:
    # 缺少维持保证金依据或强平基准时标记待补，不能当作已核实保证金。
    partial = MarginEvidence.build(
        draft=_margin_draft(),
        declared_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    assert partial.is_complete is True

    missing = MarginEvidenceDraft.model_validate(
        {
            "margin_mode": "isolated",
            "leverage": "2",
            "applicable_notional": "5000",
            "required_margin": "250",
            "source": "合成交易所界面预览",
            "valid_until": NOW + timedelta(minutes=15),
        }
    )
    evidence = MarginEvidence.build(
        draft=missing,
        declared_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    assert evidence.is_complete is False
    assert "maintenance_margin_evidence" in evidence.missing_fields
    assert "liquidation_price_reference" in evidence.missing_fields


def test_venue_rule_snapshot_rejects_mismatched_product_and_ref() -> None:
    # 产品、结算和数量单位必须与线性 USDT 永续一致，且 ref 绑定全部规则字段。
    product = _product()
    snapshot = VenueRuleSnapshot.build(
        version_id=uuid4(),
        product=product,
        contract_multiplier="1",
        quantity_unit="base_asset",
        price_tick="0.10",
        min_price="556.80",
        max_price="4529764",
        quantity_step="0.001",
        min_quantity="0.001",
        max_quantity="1000",
        market_min_quantity="0.001",
        market_max_quantity="120",
        market_quantity_step="0.001",
        min_notional="100",
        trading_status="TRADING",
        order_types=("LIMIT", "MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET"),
        time_in_force=("GTC", "IOC", "FOK"),
        observed_at=NOW,
        expires_at=NOW + timedelta(minutes=60),
        source="binance_usdm_public_exchange_info",
    )
    assert snapshot.price_tick == Decimal("0.10")
    assert snapshot.supports_order_type("STOP_MARKET") is True
    assert snapshot.supports_order_type("TRAILING_STOP_MARKET") is False

    payload = snapshot.model_dump(mode="json", by_alias=False)
    payload["price_tick"] = "0.01"
    with pytest.raises(ValidationError):
        VenueRuleSnapshot.model_validate(payload)

    with pytest.raises(ValidationError):
        VenueRuleSnapshot.build(
            version_id=uuid4(),
            product={**_product(), "kind": "inverse"},
            contract_multiplier="1",
            quantity_unit="base_asset",
            price_tick="0.10",
            min_price="1",
            max_price="2",
            quantity_step="0.001",
            min_quantity="0.001",
            max_quantity="1",
            market_min_quantity="0.001",
            market_max_quantity="1",
            market_quantity_step="0.001",
            min_notional="100",
            trading_status="TRADING",
            order_types=("LIMIT",),
            time_in_force=("GTC",),
            observed_at=NOW,
            expires_at=NOW + timedelta(minutes=60),
            source="synthetic",
        )


def test_planning_refs_requires_all_versions_and_generation() -> None:
    # PlanningRefs 只携带不可变引用、池标识和代次，不内嵌完整财务载荷。
    refs = PlanningRefs(
        profile=VersionRef(version_id=uuid4(), sha256="a" * 64),
        policy=VersionRef(version_id=uuid4(), sha256="b" * 64),
        venue_rules=VersionRef(version_id=uuid4(), sha256="c" * 64),
        costs=VersionRef(version_id=uuid4(), sha256="d" * 64),
        pool_id=uuid4(),
        pool_generation=3,
    )
    dumped = refs.model_dump(mode="json", by_alias=False)
    assert dumped["pool_generation"] == 3
    assert "planning_capital" not in dumped

    with pytest.raises(ValidationError):
        PlanningRefs(
            profile=refs.profile,
            policy=refs.policy,
            venue_rules=refs.venue_rules,
            costs=refs.costs,
            pool_id=refs.pool_id,
            pool_generation=-1,
        )
