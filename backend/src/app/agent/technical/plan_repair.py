# 有限格式纠正只复用逐条通过正文和引用检查的段落，不把整份被拒响应加入下一轮。
# 保留章节位置与索引，重试合并后还需完整契约及跨章节引用校验。
"""Retain only individually validated claims across a bounded format retry."""

import json
from typing import Any, cast

from app.agent.technical.references import ReferenceCatalog, validate_claim
from app.reports.technical_plan import SECTIONS, PlanClaim, TechnicalDecisionSummary


# 先检查总长度与候选立场，再逐条验证；关键价格角色或等待原因缺失时整节不保留。
def validated_retry_claims(
    content: str, catalog: ReferenceCatalog
) -> dict[str, list[dict[str, Any]]]:
    try:
        payload = json.loads(content)
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    record = cast(dict[str, Any], payload)
    text_size = 0
    for section in SECTIONS:
        alias = TechnicalDecisionSummary.model_fields[section].alias or section
        entries: Any = record.get(alias)
        if isinstance(entries, list):
            for item in cast(list[Any], entries):
                if isinstance(item, dict):
                    text: Any = cast(dict[str, Any], item).get("text")
                    if isinstance(text, str):
                        text_size += len(text)
    if text_size > 16000:
        return {}
    stance, selected = record.get("stance"), record.get("selectedPlanRef")
    plans = catalog.context.analysis.plans
    if not (
        (stance == "wait" and selected is None)
        or (plans and selected == "plans.0" and stance == plans[0].direction.value)
    ):
        return {}
    retained: dict[str, list[dict[str, Any]]] = {}
    for section in SECTIONS:
        alias = TechnicalDecisionSummary.model_fields[section].alias or section
        items: Any = record.get(alias)
        limit = 4 if section == "method_applications" else 6
        if not isinstance(items, list):
            continue
        entries = cast(list[Any], items)
        if not 1 <= len(entries) <= limit:
            continue
        for index, item in enumerate(entries):
            try:
                claim = PlanClaim.model_validate(item)
                validate_claim(claim, catalog, section=section, waiting=stance == "wait")
            except ValueError:
                continue
            retained.setdefault(alias, []).append(
                {"index": index, "claim": claim.model_dump(mode="json")}
            )
    # 关键价格占位符缺失时整节重新生成，不能只复用表面合法却不完整的解释。
    if selected == "plans.0":
        for alias, ref in (
            ("entryConditions", "plans.0.triggerLevel"),
            ("stopRationale", "plans.0.stopLoss"),
            ("targetRationale", "plans.0.target"),
        ):
            if not any(
                "{{" + ref + "}}" in item["claim"]["text"] for item in retained.get(alias, [])
            ):
                retained.pop(alias, None)
    # 无计划的等待章节作为整体检查原因覆盖，单条合法不足以证明清单完整。
    if not plans:
        reasons = {
            f"noPlanReasons.{i}" for i in range(len(catalog.context.analysis.no_plan_reasons))
        }
        provided = {
            ref
            for item in retained.get("waitingConditions", [])
            for ref in item["claim"]["factRefs"]
        }
        if not reasons <= provided:
            retained.pop("waitingConditions", None)
    return retained


# 按原索引覆盖新正文；列表布局不兼容则拒绝，不通过增删位置偷偷改变已验段落。
def merge_retry_claims(content: str, retained: dict[str, list[dict[str, Any]]]) -> str:
    if not retained:
        return content
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("repair_layout")
    record = cast(dict[str, Any], payload)
    for alias, claims in retained.items():
        items: Any = record.get(alias)
        if not isinstance(items, list):
            raise ValueError("repair_layout")
        entries = cast(list[Any], items)
        for item in claims:
            index = item["index"]
            if index >= len(entries):
                raise ValueError("repair_layout")
            entries[index] = item["claim"]
    return json.dumps(record, ensure_ascii=False)
