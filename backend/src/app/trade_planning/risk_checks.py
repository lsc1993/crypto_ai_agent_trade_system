# 逐项核验手动计划的确定性风险与市场规则：资料完整/时效、冷却熔断、产品与
# 已有占用、杠杆、价格格点、订单类型、数量与最小订单、风险额度、净盈亏比、
# 保证金预览和强平方向。所有检查只返回 pass/fail/unknown 与来源/时刻/指纹，
# 不修改计划、不调用 LLM、不生成 TradeIntent；unknown 不能被 T13 当作通过。
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.trade_planning.contracts import (
    CheckBasis,
    CheckStatus,
    OrderOperation,
    PlanningCalculationError,
    PlanningReason,
    PlanningRequest,
    SizingResult,
    SizingStatus,
    ValidationCheck,
)
from app.trade_planning.margin import (
    liquidation_distance_ok,
    margin_capacity,
    margin_preview_reasons,
)
from app.trade_planning.order_rules import (
    order_type_supported,
    resolve_prices,
    time_in_force_supported,
)
from app.trade_planning.product_support import PlanningProductCatalog


# 构造检查的统一入口；pass 不带原因，fail/unknown 必须带稳定原因码。
def _check(
    *,
    request: PlanningRequest,
    name: str,
    required: bool,
    status: CheckStatus,
    basis: CheckBasis,
    source: str,
    time: datetime | None,
    expires_at: datetime | None,
    reason: PlanningReason | None = None,
) -> ValidationCheck:
    return ValidationCheck(
        name=name,
        required=required,
        status=status,
        basis=basis,
        source=source,
        time=time,
        material_hash=request.material_sha256(),
        expires_at=expires_at,
        reason_code=None if reason is None else reason.value,
    )


# 资料/政策完整性：缺项是 unknown（待补），不是 pass；显式零和缺失保持不同语义。
def _completeness_checks(
    request: PlanningRequest,
) -> tuple[ValidationCheck, ValidationCheck]:
    profile_missing = request.profile.missing_fields
    profile = _check(
        request=request,
        name="profile_complete",
        required=True,
        status=CheckStatus.UNKNOWN if profile_missing else CheckStatus.PASS,
        basis=CheckBasis.USER_DECLARED,
        source="profile",
        time=request.profile.declared_at,
        expires_at=request.profile.expires_at,
        reason=PlanningReason.PROFILE_INCOMPLETE if profile_missing else None,
    )
    policy_missing = request.policy.missing_fields
    policy = _check(
        request=request,
        name="policy_complete",
        required=True,
        status=CheckStatus.UNKNOWN if policy_missing else CheckStatus.PASS,
        basis=CheckBasis.USER_DECLARED,
        source="policy",
        time=request.policy.declared_at,
        expires_at=None,
        reason=PlanningReason.POLICY_INCOMPLETE if policy_missing else None,
    )
    return profile, policy


# 时效检查分别绑定各自来源的声明/观测与失效时刻；跨 UTC 日界线还要单独核对
# 当日损益资料日期，不能仅因资料尚未过期就继续使用昨天的剩余日损额度。
def _freshness_checks(request: PlanningRequest) -> tuple[ValidationCheck, ...]:
    now = request.evaluated_at
    profile_current = _check(
        request=request,
        name="profile_current",
        required=True,
        status=CheckStatus.PASS if now < request.profile.expires_at else CheckStatus.FAIL,
        basis=CheckBasis.USER_DECLARED,
        source="profile",
        time=request.profile.declared_at,
        expires_at=request.profile.expires_at,
        reason=PlanningReason.PROFILE_EXPIRED if now >= request.profile.expires_at else None,
    )
    costs_current = _check(
        request=request,
        name="costs_current",
        required=True,
        status=CheckStatus.PASS if now < request.costs.expires_at else CheckStatus.FAIL,
        basis=CheckBasis.USER_DECLARED,
        source="costs",
        time=request.costs.declared_at,
        expires_at=request.costs.expires_at,
        reason=PlanningReason.COSTS_EXPIRED if now >= request.costs.expires_at else None,
    )
    if not request.rules.is_trading:
        rules_current = _check(
            request=request,
            name="rules_current",
            required=True,
            status=CheckStatus.FAIL,
            basis=CheckBasis.PUBLIC_SOURCE,
            source="venue_rules",
            time=request.rules.observed_at,
            expires_at=request.rules.expires_at,
            reason=PlanningReason.RULES_NOT_TRADING,
        )
    else:
        rules_current = _check(
            request=request,
            name="rules_current",
            required=True,
            status=CheckStatus.PASS if now < request.rules.expires_at else CheckStatus.FAIL,
            basis=CheckBasis.PUBLIC_SOURCE,
            source="venue_rules",
            time=request.rules.observed_at,
            expires_at=request.rules.expires_at,
            reason=PlanningReason.RULES_EXPIRED if now >= request.rules.expires_at else None,
        )
    quote_current = _check(
        request=request,
        name="quote_current",
        required=True,
        status=CheckStatus.PASS if now < request.quote.expires_at else CheckStatus.FAIL,
        basis=CheckBasis.PUBLIC_SOURCE,
        source="quote",
        time=request.quote.observed_at,
        expires_at=request.quote.expires_at,
        reason=PlanningReason.QUOTE_EXPIRED if now >= request.quote.expires_at else None,
    )
    candidate_current = _check(
        request=request,
        name="candidate_current",
        required=True,
        status=(CheckStatus.PASS if now < request.candidate.valid_until else CheckStatus.FAIL),
        basis=CheckBasis.DETERMINISTIC_CALCULATION,
        source="candidate",
        time=request.candidate.evidence_as_of,
        expires_at=request.candidate.valid_until,
        reason=(PlanningReason.CANDIDATE_EXPIRED if now >= request.candidate.valid_until else None),
    )
    daily_current = _check(
        request=request,
        name="daily_risk_current",
        required=True,
        status=(
            CheckStatus.PASS if request.profile.daily_risk_as_of == now.date() else CheckStatus.FAIL
        ),
        basis=CheckBasis.USER_DECLARED,
        source="profile",
        time=request.profile.declared_at,
        expires_at=request.profile.expires_at,
        reason=(
            None
            if request.profile.daily_risk_as_of == now.date()
            else PlanningReason.DAILY_RISK_STALE
        ),
    )
    return (
        profile_current,
        costs_current,
        rules_current,
        quote_current,
        candidate_current,
        daily_current,
    )


# 冷却/熔断是硬阻断；状态未知时保持 unknown，不能因为截止时间为空推断“无冷却”。
def _guard_checks(request: PlanningRequest) -> tuple[ValidationCheck, ValidationCheck]:
    profile = request.profile
    now = request.evaluated_at
    if profile.cooldown_status is None:
        cooldown = _check(
            request=request,
            name="cooldown_inactive",
            required=True,
            status=CheckStatus.UNKNOWN,
            basis=CheckBasis.USER_DECLARED,
            source="profile",
            time=profile.declared_at,
            expires_at=profile.expires_at,
            reason=PlanningReason.PROFILE_INCOMPLETE,
        )
    else:
        active = profile.cooldown_status.value == "active" and (
            profile.cooldown_until is None or profile.cooldown_until > now
        )
        cooldown = _check(
            request=request,
            name="cooldown_inactive",
            required=True,
            status=CheckStatus.FAIL if active else CheckStatus.PASS,
            basis=CheckBasis.USER_DECLARED,
            source="profile",
            time=profile.declared_at,
            expires_at=profile.expires_at,
            reason=PlanningReason.COOLDOWN_ACTIVE if active else None,
        )

    if profile.circuit_breaker_active is None:
        breaker = _check(
            request=request,
            name="circuit_breaker_inactive",
            required=True,
            status=CheckStatus.UNKNOWN,
            basis=CheckBasis.USER_DECLARED,
            source="profile",
            time=profile.declared_at,
            expires_at=profile.expires_at,
            reason=PlanningReason.PROFILE_INCOMPLETE,
        )
    else:
        breaker = _check(
            request=request,
            name="circuit_breaker_inactive",
            required=True,
            status=(CheckStatus.FAIL if profile.circuit_breaker_active else CheckStatus.PASS),
            basis=CheckBasis.USER_DECLARED,
            source="profile",
            time=profile.declared_at,
            expires_at=profile.expires_at,
            reason=(
                PlanningReason.CIRCUIT_BREAKER_ACTIVE if profile.circuit_breaker_active else None
            ),
        )
    return cooldown, breaker


# 产品/模式/订单类型和已有仓位/挂单占用由首期固定目录判断；未知占用优先 unknown，
# 非零占用直接 fail，因为同品种合并风险尚未实现。
def _product_checks(request: PlanningRequest) -> tuple[ValidationCheck, ValidationCheck]:
    catalog = PlanningProductCatalog()
    zero = Decimal("0")
    product_decision = catalog.evaluate(
        product=request.profile.product,
        margin_mode=request.profile.margin_mode,
        position_mode=request.profile.position_mode,
        existing_position_notional=zero,
        existing_position_margin=zero,
        existing_position_risk=zero,
        open_order_notional=zero,
        open_order_margin=zero,
        open_order_risk=zero,
        requested_order_types=(),
    )
    product_supported = product_decision.reason_code == "supported"
    product = _check(
        request=request,
        name="product_supported",
        required=True,
        status=CheckStatus.PASS if product_supported else CheckStatus.FAIL,
        basis=CheckBasis.DETERMINISTIC_CALCULATION,
        source="product_catalog",
        time=request.profile.declared_at,
        expires_at=request.profile.expires_at,
        reason=(None if product_supported else _support_reason(product_decision.reason_code)),
    )

    exposure_decision = catalog.evaluate(
        product=request.profile.product,
        margin_mode=request.profile.margin_mode,
        position_mode=request.profile.position_mode,
        existing_position_notional=request.profile.existing_position_notional,
        existing_position_margin=request.profile.existing_position_margin,
        existing_position_risk=request.profile.existing_position_risk,
        open_order_notional=request.profile.open_order_notional,
        open_order_margin=request.profile.open_order_margin,
        open_order_risk=request.profile.open_order_risk,
        requested_order_types=(),
    )
    if exposure_decision.reason_code == "supported":
        exposure_status = CheckStatus.PASS
        exposure_reason = None
    elif exposure_decision.reason_code == "existing_exposure_unknown":
        exposure_status = CheckStatus.UNKNOWN
        exposure_reason = PlanningReason.EXPOSURE_UNKNOWN
    else:
        exposure_status = CheckStatus.FAIL
        exposure_reason = _support_reason(exposure_decision.reason_code)
    exposure = _check(
        request=request,
        name="existing_exposure_supported",
        required=True,
        status=exposure_status,
        basis=CheckBasis.USER_DECLARED,
        source="profile",
        time=request.profile.declared_at,
        expires_at=request.profile.expires_at,
        reason=exposure_reason,
    )
    return product, exposure


# 产品目录返回有限字符串原因；转换为 PlanningReason，未知值折叠为产品不支持。
def _support_reason(code: str) -> PlanningReason:
    mapping = {
        "product_not_supported": PlanningReason.PRODUCT_UNSUPPORTED,
        "margin_mode_unsupported": PlanningReason.MARGIN_MODE_UNSUPPORTED,
        "position_mode_unsupported": PlanningReason.POSITION_MODE_UNSUPPORTED,
        "existing_exposure_unknown": PlanningReason.EXPOSURE_UNKNOWN,
        "existing_position_unsupported": PlanningReason.EXISTING_POSITION_UNSUPPORTED,
        "open_orders_unsupported": PlanningReason.OPEN_ORDERS_UNSUPPORTED,
        "order_type_unsupported": PlanningReason.ORDER_TYPE_UNSUPPORTED,
    }
    return mapping.get(code, PlanningReason.PRODUCT_UNSUPPORTED)


# 杠杆必须不超过用户政策；资料/政策缺项保持 unknown。
def _leverage_check(request: PlanningRequest) -> ValidationCheck:
    leverage = request.profile.leverage
    maximum = request.policy.max_leverage
    if leverage is None or maximum is None:
        return _check(
            request=request,
            name="leverage_within_policy",
            required=True,
            status=CheckStatus.UNKNOWN,
            basis=CheckBasis.USER_DECLARED,
            source="profile",
            time=request.profile.declared_at,
            expires_at=request.profile.expires_at,
            reason=PlanningReason.PROFILE_INCOMPLETE,
        )
    exceeded = leverage > maximum
    return _check(
        request=request,
        name="leverage_within_policy",
        required=True,
        status=CheckStatus.FAIL if exceeded else CheckStatus.PASS,
        basis=CheckBasis.USER_DECLARED,
        source="profile",
        time=request.profile.declared_at,
        expires_at=request.profile.expires_at,
        reason=PlanningReason.LEVERAGE_EXCEEDS_POLICY if exceeded else None,
    )


# 价格/订单检查独立于数量求解结果：即使数量因最小订单冲突阻断，也应明确原因。
def _order_checks(request: PlanningRequest) -> tuple[ValidationCheck, ...]:
    price_error: PlanningCalculationError | None = None
    try:
        resolve_prices(request)
    except PlanningCalculationError as error:
        price_error = error
    price_reason = _reason_for_error(price_error) if price_error is not None else None
    price_status = CheckStatus.PASS if price_error is None else CheckStatus.FAIL
    price_check = _check(
        request=request,
        name="price_grid_valid",
        required=True,
        status=price_status,
        basis=CheckBasis.DETERMINISTIC_CALCULATION,
        source="deterministic_calculation",
        time=request.evaluated_at,
        expires_at=request.candidate.valid_until,
        reason=price_reason,
    )

    order_supported = order_type_supported(request)
    order_check = _check(
        request=request,
        name="order_type_supported",
        required=True,
        status=CheckStatus.PASS if order_supported else CheckStatus.FAIL,
        basis=CheckBasis.PUBLIC_SOURCE,
        source="venue_rules",
        time=request.rules.observed_at,
        expires_at=request.rules.expires_at,
        reason=None if order_supported else PlanningReason.ORDER_TYPE_UNSUPPORTED,
    )

    if request.order_operation is OrderOperation.MARKET:
        tif_check = _check(
            request=request,
            name="order_time_in_force_supported",
            required=False,
            status=CheckStatus.PASS,
            basis=CheckBasis.PUBLIC_SOURCE,
            source="venue_rules",
            time=request.rules.observed_at,
            expires_at=request.rules.expires_at,
        )
    else:
        tif_supported = time_in_force_supported(request)
        tif_check = _check(
            request=request,
            name="order_time_in_force_supported",
            required=True,
            status=CheckStatus.PASS if tif_supported else CheckStatus.FAIL,
            basis=CheckBasis.PUBLIC_SOURCE,
            source="venue_rules",
            time=request.rules.observed_at,
            expires_at=request.rules.expires_at,
            reason=None if tif_supported else PlanningReason.TIME_IN_FORCE_UNSUPPORTED,
        )

    if request.order_operation is OrderOperation.MARKET:
        if request.quote.max_adverse_price is None:
            market_status = CheckStatus.FAIL
            market_reason = PlanningReason.MARKET_PRICE_BOUND_MISSING
        elif price_error is not None:
            market_status = CheckStatus.FAIL
            market_reason = _reason_for_error(price_error)
        else:
            market_status = CheckStatus.PASS
            market_reason = None
        market_check = _check(
            request=request,
            name="market_price_bound_supported",
            required=True,
            status=market_status,
            basis=CheckBasis.DETERMINISTIC_CALCULATION,
            source="deterministic_calculation",
            time=request.quote.observed_at,
            expires_at=request.quote.expires_at,
            reason=market_reason,
        )
    else:
        market_check = _check(
            request=request,
            name="market_price_bound_supported",
            required=False,
            status=CheckStatus.PASS,
            basis=CheckBasis.DETERMINISTIC_CALCULATION,
            source="deterministic_calculation",
            time=request.quote.observed_at,
            expires_at=request.quote.expires_at,
        )
    return price_check, order_check, tif_check, market_check


# 把求解错误转换为有限原因；未知错误折叠为计算失败，不回显异常文本。
def _reason_for_error(error: PlanningCalculationError | None) -> PlanningReason:
    if error is None:
        return PlanningReason.CALCULATION_FAILED
    try:
        return PlanningReason(error.code)
    except ValueError:
        return PlanningReason.CALCULATION_FAILED


# 数量相关检查：数量求解成功时全部 pass；资料/政策缺失时 unknown；只有实际
# 出现的确定性冲突才 fail，不能把所有未知原因都误标成同一项失败。
def _quantity_checks(request: PlanningRequest, size: SizingResult) -> tuple[ValidationCheck, ...]:
    if size.status is SizingStatus.SIZED:
        return (
            _deterministic_check(request, "quantity_sized", CheckStatus.PASS, None),
            _deterministic_check(request, "min_quantity_met", CheckStatus.PASS, None),
            _deterministic_check(request, "min_notional_met", CheckStatus.PASS, None),
            _deterministic_check(request, "max_quantity_respected", CheckStatus.PASS, None),
            _deterministic_check(request, "max_notional_respected", CheckStatus.PASS, None),
            _deterministic_check(request, "risk_within_budget", CheckStatus.PASS, None),
            _deterministic_check(request, "stop_exit_quantity_valid", CheckStatus.PASS, None),
            _deterministic_check(request, "target_exit_quantity_valid", CheckStatus.PASS, None),
            _deterministic_check(request, "exit_allocation_complete", CheckStatus.PASS, None),
        )

    reasons = set(size.reason_codes)
    first_reason = size.reason_codes[0] if size.reason_codes else PlanningReason.QUANTITY_NOT_SIZED
    input_unknown = bool(
        {PlanningReason.INPUTS_INCOMPLETE, PlanningReason.POLICY_INCOMPLETE} & reasons
    )

    def blocked(name: str, failure: PlanningReason) -> ValidationCheck:
        if failure in reasons:
            return _deterministic_check(request, name, CheckStatus.FAIL, failure)
        return _deterministic_check(request, name, CheckStatus.UNKNOWN, first_reason)

    quantity = _deterministic_check(
        request,
        "quantity_sized",
        CheckStatus.UNKNOWN if input_unknown else CheckStatus.FAIL,
        first_reason,
    )
    if PlanningReason.RISK_BUDGET_UNAVAILABLE in reasons:
        risk = _deterministic_check(
            request,
            "risk_within_budget",
            CheckStatus.FAIL,
            PlanningReason.RISK_BUDGET_UNAVAILABLE,
        )
    else:
        risk = blocked("risk_within_budget", PlanningReason.RISK_BUDGET_EXCEEDED)
    return (
        quantity,
        blocked("min_quantity_met", PlanningReason.MIN_QUANTITY_NOT_MET),
        blocked("min_notional_met", PlanningReason.MIN_NOTIONAL_NOT_MET),
        blocked("max_quantity_respected", PlanningReason.MAX_QUANTITY_EXCEEDED),
        blocked("max_notional_respected", PlanningReason.MAX_NOTIONAL_EXCEEDED),
        risk,
        blocked("stop_exit_quantity_valid", PlanningReason.EXIT_ALLOCATION_INCOMPLETE),
        blocked("target_exit_quantity_valid", PlanningReason.EXIT_ALLOCATION_INCOMPLETE),
        blocked("exit_allocation_complete", PlanningReason.EXIT_ALLOCATION_INCOMPLETE),
    )


# 确定性检查共用时间/来源；阻断结果没有价格，故统一以评估时刻和候选有效期记录。
def _deterministic_check(
    request: PlanningRequest,
    name: str,
    status: CheckStatus,
    reason: PlanningReason | None,
) -> ValidationCheck:
    return _check(
        request=request,
        name=name,
        required=True,
        status=status,
        basis=CheckBasis.DETERMINISTIC_CALCULATION,
        source="deterministic_calculation",
        time=request.evaluated_at,
        expires_at=request.candidate.valid_until,
        reason=reason,
    )


# 风险/收益/保证金检查基于已求解数量；数量未求解时为 unknown，不能猜一个比例。
# 保证金证据是否完整/有效独立于数量求解，因此即使数量阻断也要如实报告。
def _risk_and_margin_checks(
    request: PlanningRequest,
    size: SizingResult,
) -> tuple[ValidationCheck, ...]:
    evidence = request.profile.margin_evidence
    if evidence is None:
        current_status = CheckStatus.UNKNOWN
        current_reason: PlanningReason | None = PlanningReason.MARGIN_EVIDENCE_INCOMPLETE
        complete_status = CheckStatus.UNKNOWN
        complete_reason: PlanningReason | None = PlanningReason.MARGIN_EVIDENCE_INCOMPLETE
    else:
        if request.evaluated_at >= evidence.expires_at:
            current_status = CheckStatus.FAIL
            current_reason = PlanningReason.MARGIN_EVIDENCE_EXPIRED
        else:
            current_status = CheckStatus.PASS
            current_reason = None
        if evidence.is_complete:
            complete_status = CheckStatus.PASS
            complete_reason = None
        else:
            complete_status = CheckStatus.UNKNOWN
            complete_reason = PlanningReason.MARGIN_EVIDENCE_INCOMPLETE

    evidence_current = _check(
        request=request,
        name="margin_evidence_current",
        required=True,
        status=current_status,
        basis=CheckBasis.USER_DECLARED,
        source="margin_evidence",
        time=None if evidence is None else evidence.declared_at,
        expires_at=None if evidence is None else evidence.expires_at,
        reason=current_reason,
    )
    evidence_complete = _check(
        request=request,
        name="margin_evidence_complete",
        required=True,
        status=complete_status,
        basis=CheckBasis.USER_DECLARED,
        source="margin_evidence",
        time=None if evidence is None else evidence.declared_at,
        expires_at=None if evidence is None else evidence.expires_at,
        reason=complete_reason,
    )

    if size.status is not SizingStatus.SIZED:
        reason = size.reason_codes[0] if size.reason_codes else PlanningReason.QUANTITY_NOT_SIZED
        return (
            _deterministic_check(request, "reward_risk_ratio_met", CheckStatus.UNKNOWN, reason),
            _deterministic_check(
                request,
                "initial_margin_within_capital",
                CheckStatus.UNKNOWN,
                reason,
            ),
            evidence_current,
            evidence_complete,
            _deterministic_check(request, "margin_preview_matches", CheckStatus.UNKNOWN, reason),
            _deterministic_check(request, "liquidation_distance_safe", CheckStatus.UNKNOWN, reason),
        )

    minimum_ratio = request.policy.min_reward_risk_ratio
    if minimum_ratio is None or size.net_reward_risk_ratio is None:
        ratio_status = CheckStatus.UNKNOWN
        ratio_reason: PlanningReason | None = PlanningReason.POLICY_INCOMPLETE
    else:
        ratio_ok = size.net_reward_risk_ratio >= minimum_ratio
        ratio_status = CheckStatus.PASS if ratio_ok else CheckStatus.FAIL
        ratio_reason = None if ratio_ok else PlanningReason.REWARD_RISK_BELOW_MIN
    ratio_check = _deterministic_check(
        request,
        "reward_risk_ratio_met",
        ratio_status,
        ratio_reason,
    )

    try:
        capacity = margin_capacity(request)
    except PlanningCalculationError:
        capacity = None
    if capacity is None:
        margin_capital_check = _deterministic_check(
            request,
            "initial_margin_within_capital",
            CheckStatus.UNKNOWN,
            PlanningReason.INPUTS_INCOMPLETE,
        )
    else:
        within = size.initial_margin <= capacity
        margin_capital_check = _deterministic_check(
            request,
            "initial_margin_within_capital",
            CheckStatus.PASS if within else CheckStatus.FAIL,
            None if within else PlanningReason.MARGIN_EXCEEDS_AVAILABLE,
        )

    if evidence is None or not evidence.is_complete:
        preview_status = CheckStatus.UNKNOWN
        preview_reason: PlanningReason | None = PlanningReason.MARGIN_EVIDENCE_INCOMPLETE
    else:
        preview_reasons = margin_preview_reasons(
            request,
            notional=size.notional,
            initial_margin=size.initial_margin,
        )
        preview_status = CheckStatus.PASS if not preview_reasons else CheckStatus.FAIL
        preview_reason = None if not preview_reasons else preview_reasons[0]
    preview_check = _check(
        request=request,
        name="margin_preview_matches",
        required=True,
        status=preview_status,
        basis=CheckBasis.USER_DECLARED,
        source="margin_evidence",
        time=None if evidence is None else evidence.declared_at,
        expires_at=None if evidence is None else evidence.expires_at,
        reason=preview_reason,
    )

    liquidation_ok = (
        None if size.stop_price is None else liquidation_distance_ok(request, size.stop_price)
    )
    if liquidation_ok is None:
        liquidation_status = CheckStatus.UNKNOWN
        liquidation_reason: PlanningReason | None = PlanningReason.MARGIN_EVIDENCE_INCOMPLETE
    else:
        liquidation_status = CheckStatus.PASS if liquidation_ok else CheckStatus.FAIL
        liquidation_reason = None if liquidation_ok else PlanningReason.LIQUIDATION_DISTANCE_UNSAFE
    liquidation_check = _check(
        request=request,
        name="liquidation_distance_safe",
        required=True,
        status=liquidation_status,
        basis=CheckBasis.USER_DECLARED,
        source="margin_evidence",
        time=None if evidence is None else evidence.declared_at,
        expires_at=None if evidence is None else evidence.expires_at,
        reason=liquidation_reason,
    )

    return (
        ratio_check,
        margin_capital_check,
        evidence_current,
        evidence_complete,
        preview_check,
        liquidation_check,
    )


# C7 风险检查入口：返回固定顺序、唯一名称的 required 检查。调用方不得删除
# 任一 required fail/unknown 来绕过采纳；T13 会据此派生 blocked/needs_inputs。
def evaluate_planning_risk(
    request: PlanningRequest,
    size: SizingResult,
) -> tuple[ValidationCheck, ...]:
    profile_complete, policy_complete = _completeness_checks(request)
    checks: list[ValidationCheck] = [profile_complete, policy_complete]
    checks.extend(_freshness_checks(request))
    checks.extend(_guard_checks(request))
    checks.extend(_product_checks(request))
    checks.append(_leverage_check(request))
    checks.extend(_order_checks(request))
    checks.extend(_quantity_checks(request, size))
    checks.extend(_risk_and_margin_checks(request, size))
    return tuple(checks)


__all__ = ["evaluate_planning_risk"]
