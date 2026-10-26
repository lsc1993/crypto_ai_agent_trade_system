# 按当前冻结事实提供诚实标注的规则降级，不能把规则拼接冒充完整模型分析。
# 有有效分析摘要时确定性渲染摘要；分析缺失时仅展示程序候选、限制及重新研究条件。
"""Clearly labelled rule composition from current frozen facts."""

from app.agent.technical.references import build_reference_catalog, render_plan_book
from app.reports.technical_plan import (
    SECTIONS,
    RenderedClaim,
    RenderedPlanBook,
    TechnicalContext,
    TechnicalDecisionSummary,
)

REASONS = {
    "trend_conflict": "多周期方向冲突，等待短周期方向与大周期背景重新一致。",
    "opposite_breakout": "突破方向与趋势背景相反，等待冲突消除后重新采集研究。",
    "unconfirmed_breakout": "价格越过边界但成交量尚未确认，等待新的已收盘量价证据。",
    "awaiting_distant_trigger": "价格距离确认边界较远，等待靠近区间边界并重新评估。",
    "current_price_invalidates_plan": "摘要价格已经偏离计划允许范围，等待新的结构，不追逐旧信号。",
    "no_structural_stop": "没有可验证的结构止损依据，等待支撑或阻力形成。",
    "no_structural_target": "没有可验证的结构目标，等待新的结构位形成。",
    "reward_risk_below_minimum": "成本后盈亏比不足，等待价格和结构形成更合适的关系。",
    "entry_too_far_from_range": "信号收盘已远离入场区域，等待重新形成结构。",
    "insufficient_volatility": "波动不足以支撑有效计划，等待波动和结构重新形成。",
    "invalid_structure": "价格几何关系无效，等待可复核的新结构。",
    "unsupported_price_precision": "价格精度不能安全展示，当前不生成价格计划。",
}


# 编排失败时保留已通过校验的分析摘要，渲染继续使用同一冻结引用目录。
def build_decision_plan_book(
    context: TechnicalContext, decision: TechnicalDecisionSummary
) -> RenderedPlanBook:
    return render_plan_book(decision, build_reference_catalog(context))


# 分析不可用时使用固定规则文本；没有候选时不给价格，有候选也不视为实时可执行。
def build_rules_plan_book(context: TechnicalContext) -> RenderedPlanBook:
    analysis = context.analysis
    catalog = build_reference_catalog(context)
    plan = analysis.plans[0] if analysis.plans else None

    def claim(text: str, refs: tuple[str, ...] = ("dataCutoffAt",)) -> RenderedClaim:
        return RenderedClaim(
            text=text, evidence_id=analysis.evidence_id, fact_refs=refs, method_refs=()
        )

    general = claim("本次模型分析未完成，以下内容由确定性规则编排；只有冻结事实和程序候选可复核。")
    payload: dict[str, object] = {
        "stance": plan.direction.value if plan else "wait",
        "selected_plan_ref": "plans.0" if plan else None,
    }
    for section in SECTIONS:
        payload[section] = (general,)
    payload["waiting_conditions"] = tuple(
        claim(
            REASONS.get(reason, "数据或结构依据不足，请重新采集并核验本次行情质量。"),
            (f"noPlanReasons.{i}",),
        )
        for i, reason in enumerate(analysis.no_plan_reasons)
    ) or (claim("等待新收盘行情确认结构仍然成立，再重新研究；当前记录不会持续更新触发状态。"),)
    payload["alternative"] = (
        claim(
            "如果新的收盘走势否定当前方向或结构，则取消本次条件假设，重新研究；没有反向价格计划。"
        ),
    )
    payload["invalidation"] = (
        claim("价格离开入场范围、结构被否定或计划到期，均需取消旧假设并重新研究。"),
    )
    if plan:
        for section, ref in (
            ("entry_conditions", "triggerLevel"),
            ("stop_rationale", "stopLoss"),
            ("target_rationale", "target"),
        ):
            key = f"plans.0.{ref}"
            payload[section] = (
                claim(
                    f"{catalog.values[key]}。该价格由程序从冻结结构计算，未包含模型分析。", (key,)
                ),
            )
        payload["entry_conditions"] = (
            claim(
                f"{catalog.values['plans.0.triggerLevel']}。该确认价格属于本次冻结候选。",
                ("plans.0.triggerLevel",),
            ),
            claim(
                "历史触发状态仅对应本次数据截止；后续确认须同时复核收盘方向、成交量及价格范围，不能将旧信号当作实时信号。"
            ),
        )
    else:
        for section in ("entry_conditions", "stop_rationale", "target_rationale"):
            payload[section] = (
                claim(
                    "没有符合规则的候选计划，因此不提供入场、止损或目标价格，先解决等待清单中列出的条件。"
                ),
            )
    return RenderedPlanBook.model_validate(payload)
