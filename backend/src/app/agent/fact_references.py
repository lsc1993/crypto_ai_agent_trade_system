# 模型传输协议使用独立fact_refs数组；正文先做无自由数值检查，程序再按受限位置追加完整事实。
# 新字段仅在模型边界存在，保存前移除；不改数据库/HTTP契约，不重写历史报告或接受部分候选。
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Sequence
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.agent.model_diagnostics import schema_error_kinds
from app.agent.numeric_facts import NumericFact, NumericReferenceError, render_numeric_references

_INDEX = r"(?:0|[1-9][0-9]{0,2})"
_TARGET = re.compile(
    r"market_overview\.summary|(?:short_term|long_term)\.thesis|"
    rf"(?:short_term|long_term)\.drivers\.{_INDEX}\.detail|"
    rf"(?:short_term|long_term)\.invalidation\.{_INDEX}\.(?:condition|impact)|"
    rf"catalysts\.{_INDEX}\.claim|risks_and_invalidation\.{_INDEX}\.(?:condition|impact)|"
    rf"factor_interpretations\.{_INDEX}\.(?:summary|short_term|long_term|invalidation)"
)


class FactReference(BaseModel):
    """受限模型传输项：位置必须随后解析到已有正文，ID只能来自本次可见事实。"""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    target: str = Field(min_length=1, max_length=100)
    fact_id: str = Field(pattern=r"^[a-f0-9]{24}$")


def _evidence_ids(value: JsonValue) -> set[str]:
    """正文论点无独立引用字段时沿用该观点内驱动/条件引用集合，不借用其他观点证据。"""
    result: set[str] = set()
    if isinstance(value, dict):
        own = value.get("evidence_ids")
        if isinstance(own, list):
            return {item for item in own if isinstance(item, str)}
        for child in value.values():
            result.update(_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_evidence_ids(child))
    return result


def _target(
    root: dict[str, JsonValue], path: str
) -> tuple[dict[str, JsonValue], str, set[str]] | None:
    """仅遍历JSON键与有界列表下标，不能创建字段、访问属性或执行路径表达式。"""
    if _TARGET.fullmatch(path) is None:
        return None
    parts = path.split(".")
    current: JsonValue = root
    for part in parts[:-1]:
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    if not isinstance(current, dict) or not isinstance(current.get(parts[-1]), str):
        return None
    return current, parts[-1], _evidence_ids(current)


def render_structured_fact_references(
    content: str, facts: Sequence[NumericFact], *, symbol: str
) -> str:
    """先验证所有绑定和定性正文，再一次性追加；任一错误都不返回部分结果。"""
    raw: JsonValue = json.loads(content)
    if not isinstance(raw, dict):
        raise NumericReferenceError("schema", "fact_reference_schema", schema_kinds=("wrong_type",))
    refs = raw.pop("fact_refs", [])
    if not isinstance(refs, list) or len(refs) > 16:
        raise NumericReferenceError(
            "fact_refs",
            "fact_reference_schema",
            schema_kinds=("wrong_type" if not isinstance(refs, list) else "length",),
        )
    catalog = {fact.reference_id: fact for fact in facts}
    issues: list[NumericReferenceError] = []
    additions: list[tuple[dict[str, JsonValue], str, NumericFact]] = []
    seen: set[tuple[str, str]] = set()
    counts: Counter[str] = Counter()
    for index, item in enumerate(refs):
        path = f"fact_refs.{index}"
        try:
            ref = FactReference.model_validate(item)
        except ValidationError as error:
            errors = error.errors(include_input=False, include_context=False, include_url=False)
            issues.append(
                NumericReferenceError(
                    path,
                    "fact_reference_schema",
                    schema_kinds=schema_error_kinds(str(e["type"]) for e in errors),
                )
            )
            continue
        fact = catalog.get(ref.fact_id)
        target = _target(raw, ref.target)
        if fact is None:
            issues.append(NumericReferenceError(path + ".fact_id", "unknown_fact_reference"))
        elif target is None:
            issues.append(NumericReferenceError(path + ".target", "unknown_fact_target"))
        elif str(fact.evidence_id) not in target[2]:
            issues.append(NumericReferenceError(path, "fact_evidence_mismatch"))
        elif (ref.target, ref.fact_id) in seen or counts[ref.target] >= 3:
            issues.append(NumericReferenceError(path, "duplicate_or_excess_fact_reference"))
        else:
            additions.append((target[0], target[1], fact))
            seen.add((ref.target, ref.fact_id))
            counts[ref.target] += 1
    if issues:
        raise NumericReferenceError(issues[0].path, issues[0].category, issues=issues)
    # 空目录调用旧词法门禁，任何内联旧token或自由数字仍拒绝；字段诊断保持有界聚合。
    render_numeric_references(json.dumps(raw, ensure_ascii=False), (), symbol=symbol)
    for container, key, fact in additions:
        container[key] = cast(str, container[key]) + "\n" + fact.statement
    return json.dumps(raw, ensure_ascii=False)
