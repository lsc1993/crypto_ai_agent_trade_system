# 构造 T12 确定性规划的合成输入：策略候选、公开规则、本地资料、政策与报价。
# 所有金额、费率、保证金和规则均为测试夹具，不是用户真实资料或交易所当前值。
# 这里只生成不可变契约对象，不访问数据库、网络、模型、账户或交易服务。
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.research.strategies.contracts import (
    PriceCandidate,
    PriceRounding,
    StrategyCandidateState,
    StrategyDirection,
)
from app.shared.agent_types import ArtifactRef, ProductKey, VersionRef
from app.trade_planning.contracts import OrderOperation, PlanningQuote, PlanningRequest
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

# 固定时钟便于手算与跨日测试；不读取系统时间，避免测试随运行日期漂移。
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
DECLARED_AT = NOW - timedelta(minutes=5)
STRATEGY_REF = VersionRef(
    version_id=UUID("11111111-1111-4111-8111-111111111111"),
    sha256="a" * 64,
)
COST_VERSION_ID = UUID("22222222-2222-4222-8222-222222222222")
RULES_VERSION_ID = UUID("33333333-3333-4333-8333-333333333333")
PROFILE_VERSION_ID = UUID("44444444-4444-4444-8444-444444444444")
POLICY_VERSION_ID = UUID("55555555-5555-4555-8555-555555555555")
POOL_ID = UUID("66666666-6666-4666-8666-666666666666")
QUOTE_ARTIFACT_ID = UUID("77777777-7777-4777-8777-777777777777")
PARAMETERS_SHA256 = "b" * 64
EVIDENCE_SHA256 = "c" * 64


# 首期产品键；测试只使用 BTCUSDT，其他币种用于验证目录拒绝。
def product(symbol: str = "BTCUSDT") -> ProductKey:
    return ProductKey(
        venue="binance_usdm",
        symbol=symbol,
        settlement="USDT",
        kind="linear_perpetual",
    )


# 成本草稿默认值：双边费率 0.001，滑点/价差/持有成本显式为 0，与计划手算样例一致。
def cost_defaults() -> dict[str, object]:
    return {
        "entry_fee_rate": "0.001",
        "stop_exit_fee_rate": "0.001",
        "target_exit_fee_rate": "0.001",
        "slippage_rate": "0",
        "spread_rate": "0",
        "holding_cost_rate": "0",
        "slippage_upper_bound": "0",
        "spread_upper_bound": "0",
        "holding_cost_upper_bound": "0",
        "source": "合成成本资料",
        "valid_until": NOW + timedelta(minutes=30),
    }


# 保证金资料默认与 190 名义额、2 倍杠杆、95 初始保证金的手算计划一致。
def margin_defaults() -> dict[str, object]:
    return {
        "margin_mode": "isolated",
        "leverage": "2",
        "applicable_notional": "190",
        "applicable_entry_price": "100",
        "applicable_quantity": "1.9",
        "applicable_product": product().model_dump(mode="json", by_alias=False),
        "applicable_direction": "long",
        "maintenance_margin_rate": "0.005",
        "required_margin": "95",
        "liquidation_price_reference": "60",
        "trigger_price_basis": "mark_price",
        "source": "合成交易所界面预览",
        "valid_until": NOW + timedelta(minutes=30),
    }


# 本地资料默认完整；未知值通过 overrides 显式设为 None，不能用零补齐。
def profile_defaults() -> dict[str, object]:
    return {
        "product": product().model_dump(mode="json", by_alias=False),
        "planning_capital": "1000",
        "available_margin": "500",
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
    }


# 风险政策默认把单笔风险额度限制为 10；其余额度更宽松，便于手算 R=10。
def policy_defaults() -> dict[str, object]:
    return {
        "max_risk_per_trade": "10",
        "max_notional": "10000",
        "max_quantity": "100",
        "max_leverage": "3",
        "min_reward_risk_ratio": "1.5",
        "max_daily_loss": "300",
        "max_portfolio_risk": "500",
        "stop_loss_required": True,
        "enforce_cooldown": True,
        "enforce_circuit_breaker": True,
    }


# 公开规则默认全部价格/数量/名义额过滤器齐备；有效期为观测后 30 分钟。
def rules_defaults() -> dict[str, object]:
    return {
        "product": product(),
        "contract_multiplier": "1",
        "quantity_unit": "base_asset",
        "price_tick": "0.5",
        "min_price": "0.5",
        "max_price": "1000000",
        "quantity_step": "0.1",
        "min_quantity": "0.1",
        "max_quantity": "100",
        "market_min_quantity": "0.1",
        "market_max_quantity": "100",
        "market_quantity_step": "0.1",
        "min_notional": "5",
        "trading_status": "TRADING",
        "order_types": ("LIMIT", "MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET"),
        "time_in_force": ("GTC",),
        "source": "合成公开规则快照",
    }


# 多头默认几何：最不利入场 100、止损 95、目标 110，均落在 0.5 tick 格点。
def candidate_defaults(
    direction: StrategyDirection,
    *,
    declared_at: datetime,
    evaluated_at: datetime,
    price_rounding: PriceRounding = PriceRounding.STRICT,
) -> dict[str, object]:
    if direction is StrategyDirection.LONG:
        lower, trigger, upper, stop, target = (
            Decimal("99"),
            Decimal("100"),
            Decimal("100"),
            Decimal("95"),
            Decimal("110"),
        )
    else:
        lower, trigger, upper, stop, target = (
            Decimal("100"),
            Decimal("100"),
            Decimal("101"),
            Decimal("105"),
            Decimal("90"),
        )
    return {
        "strategy_ref": STRATEGY_REF,
        "parameters_sha256": PARAMETERS_SHA256,
        "evaluator_id": "technical_breakout_v1",
        "evaluator_version": "1.0.0",
        "evidence_sha256": EVIDENCE_SHA256,
        "evidence_as_of": declared_at,
        "direction": direction,
        "entry_lower": lower,
        "trigger": trigger,
        "entry_upper": upper,
        "stop_loss": stop,
        "target": target,
        "valid_until": evaluated_at + timedelta(minutes=20),
        "state": StrategyCandidateState.TRIGGERED,
        "price_rounding": price_rounding,
        "applicability_conditions": ("synthetic_fixture",),
    }


# 报价默认在评估时刻前 10 秒观测、50 秒后失效；市场单可显式提供最大不利成交价。
def quote_defaults(
    *,
    evaluated_at: datetime,
    price: Decimal = Decimal("100"),
    max_adverse_price: Decimal | None = None,
) -> dict[str, object]:
    return {
        "artifact": ArtifactRef(artifact_id=QUOTE_ARTIFACT_ID, sha256="d" * 64),
        "price": price,
        "observed_at": evaluated_at - timedelta(seconds=10),
        "expires_at": evaluated_at + timedelta(seconds=50),
        "source": "合成公开报价",
        "max_adverse_price": max_adverse_price,
    }


# 组合完整 PlanningRequest；调用方可覆盖各层字段以验证失败路径。
def build_request(
    *,
    direction: StrategyDirection = StrategyDirection.LONG,
    order_operation: OrderOperation = OrderOperation.LIMIT,
    evaluated_at: datetime = NOW,
    declared_at: datetime = DECLARED_AT,
    profile_generation: int = 1,
    policy_generation: int = 1,
    refs_generation: int = 1,
    cost_overrides: Mapping[str, object] | None = None,
    margin_overrides: Mapping[str, object] | None = None,
    profile_overrides: Mapping[str, object] | None = None,
    policy_overrides: Mapping[str, object] | None = None,
    rules_overrides: Mapping[str, object] | None = None,
    candidate_overrides: Mapping[str, object] | None = None,
    quote_overrides: Mapping[str, object] | None = None,
    price_rounding: PriceRounding = PriceRounding.STRICT,
) -> PlanningRequest:
    cost_payload = cost_defaults()
    cost_payload.update(cost_overrides or {})
    if "valid_until" not in (cost_overrides or {}):
        cost_payload["valid_until"] = declared_at + timedelta(minutes=30)
    cost = CostAssumptions.build(
        version_id=COST_VERSION_ID,
        draft=CostAssumptionsDraft.model_validate(cost_payload),
        declared_at=declared_at,
        expires_at=declared_at + timedelta(minutes=10),
    )

    margin_payload = margin_defaults()
    margin_payload.update(margin_overrides or {})
    if "valid_until" not in (margin_overrides or {}):
        margin_payload["valid_until"] = declared_at + timedelta(minutes=30)
    if "applicable_direction" not in (margin_overrides or {}):
        margin_payload["applicable_direction"] = direction.value
    margin = MarginEvidence.build(
        draft=MarginEvidenceDraft.model_validate(margin_payload),
        declared_at=declared_at,
        expires_at=declared_at + timedelta(minutes=10),
    )

    profile_payload = profile_defaults()
    profile_payload.update(profile_overrides or {})
    if "daily_risk_as_of" not in (profile_overrides or {}):
        profile_payload["daily_risk_as_of"] = declared_at.date()
    profile_payload.update({"costs": cost_payload, "margin_evidence": margin_payload})
    profile = PlanningProfileSnapshot.build(
        version_id=PROFILE_VERSION_ID,
        pool_id=POOL_ID,
        pool_generation=profile_generation,
        draft=PlanningProfileDraft.model_validate(profile_payload),
        margin_evidence=margin,
        costs_ref=cost.ref,
        declared_at=declared_at,
        expires_at=declared_at + timedelta(minutes=10),
    )

    policy_payload = policy_defaults()
    policy_payload.update(policy_overrides or {})
    policy = PlanningRiskPolicy.build(
        version_id=POLICY_VERSION_ID,
        pool_id=POOL_ID,
        pool_generation=policy_generation,
        draft=PlanningRiskPolicyDraft.model_validate(policy_payload),
        declared_at=declared_at,
    )

    rules_payload = rules_defaults()
    rules_payload.update(rules_overrides or {})
    rules = VenueRuleSnapshot.build(
        version_id=RULES_VERSION_ID,
        observed_at=declared_at + timedelta(minutes=1),
        expires_at=declared_at + timedelta(minutes=31),
        **rules_payload,  # type: ignore[arg-type]
    )

    candidate_payload = candidate_defaults(
        direction,
        declared_at=declared_at,
        evaluated_at=evaluated_at,
        price_rounding=price_rounding,
    )
    candidate_payload.update(candidate_overrides or {})
    candidate = PriceCandidate.build(**candidate_payload)  # type: ignore[arg-type]

    quote_payload = quote_defaults(evaluated_at=evaluated_at)
    quote_payload.update(quote_overrides or {})
    quote = PlanningQuote.model_validate(quote_payload)

    refs = PlanningRefs(
        profile=profile.ref,
        policy=policy.ref,
        venue_rules=rules.ref,
        costs=cost.ref,
        pool_id=POOL_ID,
        pool_generation=refs_generation,
    )
    return PlanningRequest(
        candidate=candidate,
        strategy_ref=STRATEGY_REF,
        refs=refs,
        profile=profile,
        policy=policy,
        rules=rules,
        costs=cost,
        quote=quote,
        evaluated_at=evaluated_at,
        order_operation=order_operation,
    )
