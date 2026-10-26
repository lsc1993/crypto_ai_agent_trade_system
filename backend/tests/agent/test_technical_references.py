# 验证技术计划的证据、方法与数值字段引用。
# 相同数值不代表引用正确，字段、单位和价格角色必须同时匹配。
# 最终价格按冻结十进制值渲染，无候选时只能等待，条件研究不能转为操作指令。
from decimal import Decimal
from uuid import uuid4

import pytest

from app.agent.technical.engine import calculate_technical_analysis
from app.agent.technical.references import (
    build_reference_catalog,
    render_plan_book,
    validate_decision,
)
from app.reports.technical_plan import PlanClaim, TechnicalContext, TechnicalDecisionSummary
from tests.agent.test_technical_engine import NOW, make_technical_detail


# 以确定性引擎生成冻结候选和证据；等待模式调整摘要价格使当前候选不再可用。
def context(*, waiting: bool = False) -> TechnicalContext:
    detail = make_technical_detail()
    if waiting:
        detail = detail.model_copy(
            update={"summary": detail.summary.model_copy(update={"price": Decimal("140")})}
        )
    return TechnicalContext(
        analysis=calculate_technical_analysis(detail, captured_at=NOW),
        summary_price=detail.summary.price,
        latest_closed_prices={"1h": Decimal("106.2")},
        data_cutoff_at=NOW,
    )


# 用引用占位符组成最小合法计划书，价格角色分别引用触发、止损与目标字段。
def decision(ctx: TechnicalContext) -> TechnicalDecisionSummary:
    def claim(ref: str) -> PlanClaim:
        return PlanClaim(
            text="本次冻结事实为{{" + ref + "}}，需结合后续收盘变化复核该判断。",
            evidence_id=ctx.analysis.evidence_id,
            fact_refs=(ref,),
        )

    has_plan = bool(ctx.analysis.plans)
    general = claim("facts.volumeRatio")
    waiting = tuple(
        claim(f"noPlanReasons.{i}") for i in range(len(ctx.analysis.no_plan_reasons))
    ) or (general,)
    return TechnicalDecisionSummary(
        stance="long" if has_plan else "wait",
        selected_plan_ref="plans.0" if has_plan else None,
        market_structure=(general,),
        supporting_evidence=(general,),
        counter_evidence=(general,),
        method_applications=(
            general.model_copy(update={"method_refs": (ctx.analysis.methods[0].id,)}),
        ),
        entry_conditions=(claim("plans.0.triggerLevel") if has_plan else general,),
        stop_rationale=(claim("plans.0.stopLoss") if has_plan else general,),
        target_rationale=(claim("plans.0.target") if has_plan else general,),
        invalidation=(general,),
        alternative=(general,),
        waiting_conditions=waiting,
        risks=(general,),
    )


def test_no_candidate_requires_wait() -> None:
    ctx = context(waiting=True)
    summary = decision(ctx)
    assert validate_decision(summary, build_reference_catalog(ctx)).stance == "wait"
    with pytest.raises(ValueError):
        validate_decision(
            summary.model_copy(update={"stance": "long", "selected_plan_ref": "plans.0"}),
            build_reference_catalog(ctx),
        )


# 证据与方法均须属于当前上下文，任意外来身份都不能通过已有正文掩盖。
def test_rejects_foreign_evidence_and_method() -> None:
    ctx = context()
    summary = decision(ctx)
    for change in ({"evidence_id": uuid4()}, {"method_refs": ("foreign",)}):
        bad = summary.market_structure[0].model_copy(update=change)
        with pytest.raises(ValueError):
            validate_decision(
                summary.model_copy(update={"market_structure": (bad,)}),
                build_reference_catalog(ctx),
            )


# 把目标说明复制为止损说明，验证数值相同或类型相容并不等于用途正确。
def test_same_value_wrong_field_or_unit_rejected() -> None:
    ctx = context()
    summary = decision(ctx)
    with pytest.raises(ValueError):
        validate_decision(
            summary.model_copy(update={"stop_rationale": summary.target_rationale}),
            build_reference_catalog(ctx),
        )


@pytest.mark.parametrize(
    "text",
    [
        "价格达到123美元就会保证盈利。",
        "结构目标为一百美元，届时可以立即下单。",
        "当前需要满仓买入并使用杠杆继续交易。",
        "结构止损设为五，需结合后续收盘变化复核该判断。",
        "结构止损采用五作为参考价位，需结合后续收盘变化复核该判断。",
        "现在已经满足全部条件，可以立即执行入场，无需等待后续确认。",
    ],
)
def test_rejects_unbound_numeric_literals(text: str) -> None:
    with pytest.raises(ValueError) as error:
        PlanClaim(text=text, evidence_id=uuid4(), fact_refs=("facts.volumeRatio",))
    if "五" in text:
        assert "unbound_number" in str(error.value)


def test_conditional_entry_terms_allowed_but_orders_and_promises_rejected() -> None:
    claim = PlanClaim(
        text="条件做多计划需要入场确认，结构止损和目标应随证据一起复核。",
        evidence_id=uuid4(),
        fact_refs=("facts.volumeRatio",),
    )
    assert "止损" in claim.text
    ordinary = PlanClaim(
        text="多周期判断保持一致，一旦出现反向证据便应参考冻结事实重新研究候选计划。",
        evidence_id=uuid4(),
        fact_refs=("facts.volumeRatio",),
    )
    assert "一致" in ordinary.text


# 渲染价格必须来自冻结字段的线协议 Decimal 字符串，最终正文不应残留占位符。
def test_rendered_prices_equal_wire_decimals() -> None:
    ctx = context()
    summary = validate_decision(decision(ctx), build_reference_catalog(ctx))
    rendered = render_plan_book(summary, build_reference_catalog(ctx))
    assert "结构止损" in rendered.stop_rationale[0].text
    assert (
        ctx.analysis.plans[0].model_dump(mode="json")["stopLoss"] in rendered.stop_rationale[0].text
    )
    assert "{{" not in rendered.model_dump_json()


# 附带正确止损引用仍不够，正文实际使用的占位符本身也必须是该价格角色。
@pytest.mark.parametrize(
    "text",
    [
        "止损依据为{{facts.volumeRatio}}美元，需结合后续收盘变化复核该判断。",
        "止损依据为{{facts.volumeRatio}}，需结合后续收盘变化复核该判断。",
    ],
)
def test_actual_price_placeholder_must_match_role(text: str) -> None:
    ctx = context()
    bad = (
        decision(ctx)
        .stop_rationale[0]
        .model_copy(
            update={
                "text": text,
                "fact_refs": ("plans.0.stopLoss", "facts.volumeRatio"),
            }
        )
    )
    # 引用清单中有正确字段不能弥补正文用错占位符，校验必须检查实际使用关系。
    with pytest.raises(ValueError):
        validate_decision(
            decision(ctx).model_copy(update={"stop_rationale": (bad,)}),
            build_reference_catalog(ctx),
        )
