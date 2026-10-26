# 建立类型化冻结事实引用目录，校验章节引用后将占位符确定性渲染为标签及数值。
# 方法只能解释分析方式，不能当市场证据；历史触发和到期说明由渲染器固定表达。
"""Typed fact references and deterministic rendering of numeric anchors."""

import re
from dataclasses import dataclass
from typing import cast

from pydantic import JsonValue

from app.reports.technical_plan import (
    SECTIONS,
    PlanClaim,
    RenderedClaim,
    RenderedPlanBook,
    TechnicalContext,
    TechnicalDecisionSummary,
)

_LABELS = {
    "summaryPrice": "摘要价格",
    "volumeRatio": "相对成交量（倍）",
    "atr14": "波动幅度（USDT）",
    "rangeHigh": "区间高点（USDT）",
    "rangeLow": "区间低点（USDT）",
    "triggerLevel": "突破确认价格（USDT）",
    "entryLower": "入场区间下沿（USDT）",
    "entryUpper": "入场区间上沿（USDT）",
    "stopLoss": "结构止损（USDT）",
    "target": "结构目标（USDT）",
    "rewardRisk": "成本后盈亏比",
    "feeRatePerSide": "每侧手续费率",
    "slippageRatePerSide": "每侧滑点率",
    "validUntil": "计划有效至（UTC）",
    "state": "冻结信号状态",
    "direction": "计划方向",
    "dataCutoffAt": "数据截止（UTC）",
}
_PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_.]+)\}\}")


# 目录绑定当前上下文，字段路径只映射该次冻结值，不能查询实时状态。
@dataclass(frozen=True)
class ReferenceCatalog:
    context: TechnicalContext
    values: dict[str, str]


# 递归展开事实、候选及无计划原因；跳过空值，防止不存在的值成为可引用证据。
def build_reference_catalog(context: TechnicalContext) -> ReferenceCatalog:
    values: dict[str, str] = {}

    def visit(value: JsonValue, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, (tuple, list)):
            for index, child in enumerate(value):
                visit(child, f"{path}.{index}")
        elif value is not None:
            label = _LABELS.get(path.rsplit(".", 1)[-1], path)
            values[path] = f"{label}：{value}"

    payload = cast(dict[str, JsonValue], context.model_dump(mode="json"))
    analysis = cast(dict[str, JsonValue], payload.pop("analysis"))
    visit(payload, "")
    visit(analysis["facts"], "facts")
    visit(analysis["plans"], "plans")
    visit(analysis["noPlanReasons"], "noPlanReasons")
    return ReferenceCatalog(context=context, values=values)


# 重新验证进程内对象，并核对候选方向、各章节价格角色以及所有等待原因的覆盖。
def validate_decision(
    summary: TechnicalDecisionSummary, catalog: ReferenceCatalog
) -> TechnicalDecisionSummary:
    # Revalidate even objects returned by in-process implementations/model_copy.
    summary = TechnicalDecisionSummary.model_validate_json(summary.model_dump_json())
    analysis = catalog.context.analysis
    if summary.stance == "wait":
        if summary.selected_plan_ref is not None:
            raise ValueError("wait_plan")
    elif (
        not analysis.plans
        or summary.selected_plan_ref != "plans.0"
        or summary.stance != analysis.plans[0].direction.value
    ):
        raise ValueError("candidate_reference")
    for section in SECTIONS:
        for claim in getattr(summary, section):
            validate_claim(claim, catalog, section=section, waiting=summary.stance == "wait")
    # 候选各角色必须在对应章节正文出现，不能仅列在引用数组里而漏掉读者可见说明。
    if summary.selected_plan_ref:
        for section, required in (
            ("entry_conditions", "plans.0.triggerLevel"),
            ("stop_rationale", "plans.0.stopLoss"),
            ("target_rationale", "plans.0.target"),
        ):
            claims = getattr(summary, section)
            if not any(required in _PLACEHOLDER.findall(claim.text) for claim in claims):
                raise ValueError("plan_role_reference")
            incompatible = {"plans.0.stopLoss", "plans.0.target"} - {required}
            if any(incompatible & set(claim.fact_refs) for claim in claims):
                raise ValueError("plan_role_reference")
    # 无候选时等待清单必须覆盖全部程序原因，防止模型选择性省略拒绝依据。
    if not analysis.plans:
        reasons = {f"noPlanReasons.{i}" for i in range(len(analysis.no_plan_reasons))}
        if reasons and not reasons <= {
            ref for claim in summary.waiting_conditions for ref in claim.fact_refs
        }:
            raise ValueError("waiting_reason_reference")
    return summary


# 同时校验证据、事实和方法归属；等待立场不得引用候选，止损与目标字段不可串用。
def validate_claim(
    claim: PlanClaim, catalog: ReferenceCatalog, *, section: str, waiting: bool
) -> None:
    analysis = catalog.context.analysis
    methods = {method.id for method in analysis.methods}
    if (
        claim.evidence_id != analysis.evidence_id
        or not set(claim.fact_refs) <= catalog.values.keys()
        or not set(claim.method_refs) <= methods
    ):
        raise ValueError("evidence_reference")
    if not set(_PLACEHOLDER.findall(claim.text)) <= set(claim.fact_refs):
        raise ValueError("placeholder_reference")
    if section == "method_applications" and not claim.method_refs:
        raise ValueError("method_reference")
    if waiting and any(ref.startswith("plans.") for ref in claim.fact_refs):
        raise ValueError("wait_candidate_reference")
    if section == "stop_rationale" and "plans.0.target" in claim.fact_refs:
        raise ValueError("plan_role_reference")
    if section == "target_rationale" and "plans.0.stopLoss" in claim.fact_refs:
        raise ValueError("plan_role_reference")
    if section == "entry_conditions" and {"plans.0.stopLoss", "plans.0.target"} & set(
        claim.fact_refs
    ):
        raise ValueError("plan_role_reference")


# 完整验证通过才替换数值占位符，额外写入冻结触发状态与有效期，禁止推断实时可执行性。
def render_plan_book(book: TechnicalDecisionSummary, catalog: ReferenceCatalog) -> RenderedPlanBook:
    book = validate_decision(book, catalog)
    payload: dict[str, object] = {
        "stance": book.stance,
        "selected_plan_ref": book.selected_plan_ref,
    }
    for key in SECTIONS:
        payload[key] = tuple(
            RenderedClaim(
                text=_PLACEHOLDER.sub(lambda match: catalog.values[match[1]], claim.text),
                evidence_id=claim.evidence_id,
                fact_refs=claim.fact_refs,
                method_refs=claim.method_refs,
            )
            for claim in getattr(book, key)
        )
    # State and expiry wording is owned by the renderer, never inferred as a live signal.
    if book.selected_plan_ref:
        plan = catalog.context.analysis.plans[0]
        status = (
            "截至冻结数据时间已确认突破；仅为历史信号，后续必须重新核验，不能据此立即执行。"
            if plan.state == "triggered"
            else "冻结数据尚未确认突破；须等待后续已收盘行情达到候选确认条件，再重新核验。"
        )
        entry = cast(tuple[RenderedClaim, ...], payload["entry_conditions"])
        payload["entry_conditions"] = (
            RenderedClaim(
                text=f"{status}数据截止（UTC）：{catalog.context.data_cutoff_at.isoformat()}；"
                f"计划有效至（UTC）：{plan.valid_until.isoformat()}；超过该时点必须重新研究。",
                evidence_id=catalog.context.analysis.evidence_id,
                fact_refs=("dataCutoffAt", "plans.0.state", "plans.0.validUntil"),
                method_refs=(),
            ),
            *entry,
        )
    return RenderedPlanBook.model_validate(payload)
