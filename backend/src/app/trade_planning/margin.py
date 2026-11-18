# 计算逐仓保证金与强平方向核对。保证金证据只来自用户填写的交易所界面预览/
# 规则资料，标记 user_declared；本模块不读取私有账户、不声称余额或强平价已核实。
# 初始保证金只做确定性名义额/杠杆计算；维持保证金档位、强平参考和止损安全距离
# 必须由证据与实际计划一致，缺失时返回 unknown 而不是套用简化公式。
from __future__ import annotations

from decimal import Decimal, localcontext

from app.research.strategies.contracts import StrategyDirection
from app.trade_planning.contracts import (
    CALCULATION_PRECISION,
    PlanningCalculationError,
    PlanningReason,
    PlanningRequest,
    quantize_decimal,
)


# 逐仓初始保证金 = 名义额 / 用户声明杠杆；向上量化，避免低估资金占用。
def initial_margin_for(notional: Decimal, leverage: Decimal) -> Decimal:
    if notional <= 0 or leverage <= 0:
        raise PlanningCalculationError(
            "计算初始保证金需要正名义额和正杠杆",
            code=PlanningReason.CALCULATION_FAILED.value,
        )
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        margin = notional / leverage
    return quantize_decimal(margin, direction="up")


# 可用保证金同时受声明可用额度和规划资金约束；未知值不能按零处理。
def margin_capacity(request: PlanningRequest) -> Decimal:
    available = request.profile.available_margin
    capital = request.profile.planning_capital
    if available is None or capital is None:
        raise PlanningCalculationError(
            "规划资料缺少可用保证金或规划资金",
            code=PlanningReason.INPUTS_INCOMPLETE.value,
        )
    return min(available, capital)


# 用户保证金预览必须匹配本次计划的名义额和初始保证金；数量/价格变化后旧预览
# 不再适用，必须由用户补充新预览，不能把旧档位套到新数量。
def margin_preview_reasons(
    request: PlanningRequest,
    *,
    notional: Decimal,
    initial_margin: Decimal,
) -> tuple[PlanningReason, ...]:
    if notional <= 0 or initial_margin <= 0:
        raise PlanningCalculationError(
            "保证金预览核对需要正名义额和正保证金",
            code=PlanningReason.CALCULATION_FAILED.value,
        )
    evidence = request.profile.margin_evidence
    if evidence is None:
        return (PlanningReason.MARGIN_EVIDENCE_INCOMPLETE,)

    reasons: list[PlanningReason] = []
    if not evidence.is_complete:
        reasons.append(PlanningReason.MARGIN_EVIDENCE_INCOMPLETE)
    if evidence.applicable_notional != notional:
        reasons.append(PlanningReason.MARGIN_PREVIEW_NOT_APPLICABLE)
    if evidence.required_margin != initial_margin:
        reasons.append(PlanningReason.MARGIN_PREVIEW_MISMATCH)
    return tuple(reasons)


# 保护性止损必须位于强平参考价的安全一侧：多头强平价更低、空头更高。
# 证据缺失返回 None（unknown）；这里不能保证交易所最终强平价与用户预览一致。
def liquidation_distance_ok(request: PlanningRequest, stop_price: Decimal) -> bool | None:
    if stop_price <= 0:
        raise PlanningCalculationError(
            "止损价格必须为正",
            code=PlanningReason.PRICE_GEOMETRY_INVALID.value,
        )
    evidence = request.profile.margin_evidence
    if evidence is None or evidence.liquidation_price_reference is None:
        return None
    liquidation = evidence.liquidation_price_reference
    if request.candidate.direction is StrategyDirection.LONG:
        return stop_price > liquidation
    return stop_price < liquidation


__all__ = [
    "initial_margin_for",
    "liquidation_distance_ok",
    "margin_capacity",
    "margin_preview_reasons",
]
