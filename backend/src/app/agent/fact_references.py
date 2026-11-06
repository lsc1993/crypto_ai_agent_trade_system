# 模型传输协议使用独立fact_refs数组；正文先做无自由数值检查，程序再按受限位置追加完整事实。
# 新字段仅在模型边界存在，保存前移除；不改数据库/HTTP契约，不重写历史报告或接受部分候选。
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.agent.model_diagnostics import schema_error_kinds
from app.agent.numeric_facts import (
    NumericFact,
    NumericReferenceError,
    contains_unbound_numeric_claim,
    render_numeric_references,
)

_INDEX = r"(?:0|[1-9][0-9]{0,2})"
_TARGET = re.compile(
    r"market_overview\.summary|"
    rf"(?:short_term|long_term)\.drivers\.{_INDEX}\.detail|"
    rf"(?:short_term|long_term)\.invalidation\.{_INDEX}\.(?:condition|impact)|"
    rf"catalysts\.{_INDEX}\.claim|risks_and_invalidation\.{_INDEX}\.(?:condition|impact)|"
    rf"factor_interpretations\.{_INDEX}\.(?:summary|short_term|long_term|invalidation)"
)
_TARGET_HINT = (
    "target只能指向带evidence_ids的叶子段落：market_overview.summary、"
    "short_term/long_term的drivers.N.detail或invalidation.N.condition/impact、"
    "catalysts.N.claim、risks_and_invalidation.N.condition/impact、"
    "factor_interpretations.N.summary/short_term/long_term/invalidation；"
    "thesis本身没有evidence_ids，不接受fact_refs"
)
# 只有叙述性字段可做句子级省略；标题、枚举、标签和 timing 不接受数字，避免改写成空壳。
_REDACTABLE_FIELDS = frozenset(
    {
        "summary",
        "thesis",
        "detail",
        "claim",
        "condition",
        "impact",
        "short_term",
        "long_term",
        "invalidation",
        "limitations",
    }
)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？\n])")
_REDACTED_SENTENCE = "（含未绑定数值的句子已省略。）"


class FactReference(BaseModel):
    """受限模型传输项：位置必须随后解析到已有正文，ID只能来自本次可见事实。"""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    target: str = Field(min_length=1, max_length=100)
    fact_id: str = Field(pattern=r"^[a-f0-9]{24}$")


def _canonical_uuid(value: str) -> str | None:
    """把模型可接受的大写/无连字符 UUID 统一成规范字符串，避免格式差异误判证据不匹配。"""
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        return None


def _evidence_ids(value: JsonValue) -> set[str]:
    """正文论点无独立引用字段时沿用该观点内驱动/条件引用集合，不借用其他观点证据。"""
    result: set[str] = set()
    if isinstance(value, dict):
        own = value.get("evidence_ids")
        if isinstance(own, list):
            # 只把合法 UUID 纳入绑定集合；最终 Pydantic 契约仍会拒绝非法 UUID。
            return {
                canonical
                for item in own
                if isinstance(item, str) and (canonical := _canonical_uuid(item)) is not None
            }
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


@dataclass(frozen=True)
class StructuredFactRenderResult:
    """部分恢复结果：只保留通过校验的事实，并记录被丢弃/省略项的安全摘要。"""

    content: str
    dropped_count: int
    dropped_paths: tuple[str, ...]
    dropped_categories: tuple[str, ...]
    redacted_claim_count: int = 0
    redacted_paths: tuple[str, ...] = ()
    length_dropped_fact_count: int = 0


def _parse_reference_payload(content: str) -> tuple[dict[str, JsonValue], list[JsonValue]]:
    """解析根对象并取出数组；根形状错误仍整份拒绝，不能伪装成没有事实引用。"""
    raw: JsonValue = json.loads(content)
    if not isinstance(raw, dict):
        raise NumericReferenceError(
            "schema",
            "fact_reference_schema",
            schema_kinds=("wrong_type",),
            hint="根对象必须是 JSON 对象，不能是数组、字符串或 null。",
        )
    refs = raw.pop("fact_refs", [])
    if not isinstance(refs, list) or len(refs) > 16:
        raise NumericReferenceError(
            "fact_refs",
            "fact_reference_schema",
            schema_kinds=("wrong_type" if not isinstance(refs, list) else "length",),
            hint="fact_refs 必须是数组且最多十六项；没有事实引用时返回空数组。",
        )
    return raw, cast(list[JsonValue], refs)


def _collect_fact_references(
    raw: dict[str, JsonValue],
    refs: list[JsonValue],
    catalog: Mapping[str, NumericFact],
) -> tuple[
    list[tuple[dict[str, JsonValue], str, NumericFact]],
    list[NumericReferenceError],
]:
    """逐项校验事实引用；调用方决定整份拒绝还是只丢弃失败项。"""
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
                    hint=f"{path}: 每项只能包含字符串 target 和 24 位小写十六进制 fact_id。",
                )
            )
            continue
        fact = catalog.get(ref.fact_id)
        target = _target(raw, ref.target)
        if fact is None:
            issues.append(
                NumericReferenceError(
                    path + ".fact_id",
                    "unknown_fact_reference",
                    hint=(
                        f"{path}: fact_id 不在本次可见 numeric_facts 中；"
                        "只能使用输入提供的 fact_id，或改为非数量化解释。"
                    ),
                )
            )
        elif target is None:
            issues.append(
                NumericReferenceError(
                    path + ".target",
                    "unknown_fact_target",
                    hint=f"{path}: {_TARGET_HINT}。",
                )
            )
        elif str(fact.evidence_id) not in target[2]:
            issues.append(
                NumericReferenceError(
                    path,
                    "fact_evidence_mismatch",
                    hint=(
                        f"{path}: target={ref.target} 的 evidence_ids 未包含 "
                        f"evidence_id={fact.evidence_id}（fact={fact.label}）；"
                        "请改用已引用该 evidence 的叶子段落，或在同一段的 "
                        "drivers/invalidation 中补上该 UUID。"
                    ),
                )
            )
        elif (ref.target, ref.fact_id) in seen:
            issues.append(
                NumericReferenceError(
                    path,
                    "duplicate_fact_reference",
                    hint=f"{path}: target={ref.target} 已引用同一 fact_id；请删除重复项。",
                )
            )
        elif counts[ref.target] >= 5:
            issues.append(
                NumericReferenceError(
                    path,
                    "excess_fact_reference",
                    hint=(
                        f"{path}: target={ref.target} 已超过每段五条上限；"
                        "请把该事实移到另一个已引用对应 evidence 的叶子段落。"
                    ),
                )
            )
        else:
            additions.append((target[0], target[1], fact))
            seen.add((ref.target, ref.fact_id))
            counts[ref.target] += 1
    return additions, issues


def _finish_structured_render(
    raw: dict[str, JsonValue],
    additions: list[tuple[dict[str, JsonValue], str, NumericFact]],
    *,
    symbol: str,
) -> str:
    """在追加事实前仍执行自由数字门禁，部分恢复不能绕过未绑定数值检查。"""
    render_numeric_references(json.dumps(raw, ensure_ascii=False), (), symbol=symbol)
    for container, key, fact in additions:
        container[key] = cast(str, container[key]) + "\n" + fact.statement
    return json.dumps(raw, ensure_ascii=False)


def render_structured_fact_references(
    content: str, facts: Sequence[NumericFact], *, symbol: str
) -> str:
    """严格模式：任一事实引用错误都拒绝整份，不返回部分渲染结果。"""
    raw, refs = _parse_reference_payload(content)
    additions, issues = _collect_fact_references(
        raw, refs, {fact.reference_id: fact for fact in facts}
    )
    if issues:
        raise NumericReferenceError(issues[0].path, issues[0].category, issues=issues)
    return _finish_structured_render(raw, additions, symbol=symbol)


def _redact_sentences(value: str, *, symbol: str) -> tuple[str, int]:
    """按完整句省略自由数字；占位句本身不含数字，不能截断半个数量。"""
    parts = _SENTENCE_BOUNDARY.split(value)
    output: list[str] = []
    redacted = 0
    for part in parts:
        if not part.strip():
            continue
        if contains_unbound_numeric_claim(part, symbol=symbol):
            redacted += 1
            output.append(_REDACTED_SENTENCE)
        else:
            output.append(part)
    if redacted == 0:
        return value, 0
    sanitized = "".join(output).strip()
    if not any("\u4e00" <= character <= "\u9fff" for character in sanitized):
        raise NumericReferenceError("schema", "unbound_numeric_claim")
    return sanitized, redacted


def _redact_unbound_numeric_claims(
    content: str, *, symbol: str
) -> tuple[str, int, tuple[str, ...]]:
    """只改叙述性字段，按句删除自由数字；标题、枚举、标签和 timing 仍整份拒绝。"""
    raw = json.loads(content)
    if not isinstance(raw, dict):
        raise NumericReferenceError("schema", "unbound_numeric_claim")
    typed_raw = cast(dict[str, JsonValue], raw)
    redacted_paths: list[str] = []
    redacted_count = 0

    def visit(value: JsonValue, path: str, field: str) -> JsonValue:
        nonlocal redacted_count
        if isinstance(value, dict):
            return {
                key: (
                    child
                    if key in {"evidence_ids", "fact_refs"}
                    else visit(child, f"{path}.{key}".strip("."), key)
                )
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [visit(child, f"{path}.{index}", field) for index, child in enumerate(value)]
        if not isinstance(value, str):
            return value
        if not contains_unbound_numeric_claim(value, symbol=symbol):
            return value
        if field not in _REDACTABLE_FIELDS:
            raise NumericReferenceError(path or "schema", "unbound_numeric_claim")
        sanitized, count = _redact_sentences(value, symbol=symbol)
        if count == 0:
            raise NumericReferenceError(path or "schema", "unbound_numeric_claim")
        redacted_count += count
        if path not in redacted_paths:
            redacted_paths.append(path)
        return sanitized

    redacted_raw = visit(typed_raw, "", "")
    return (
        json.dumps(redacted_raw, ensure_ascii=False),
        redacted_count,
        tuple(redacted_paths[:8]),
    )


def render_structured_fact_references_partially(
    content: str, facts: Sequence[NumericFact], *, symbol: str
) -> StructuredFactRenderResult:
    """部分恢复：丢弃失败事实，并按句省略自由数字后保留其余定性正文。

    根 shape 错误仍整份拒绝；非叙述字段或无法保留中文内容时也拒绝，不能无限放宽。
    """
    raw, refs = _parse_reference_payload(content)
    catalog = {fact.reference_id: fact for fact in facts}
    additions, issues = _collect_fact_references(raw, refs, catalog)
    redacted_claim_count = 0
    redacted_paths: tuple[str, ...] = ()
    try:
        content = _finish_structured_render(raw, additions, symbol=symbol)
    except NumericReferenceError as error:
        if not {"unbound_numeric_claim", "numeric_reference"}.intersection(error.categories):
            raise
        try:
            redacted_content, redacted_claim_count, redacted_paths = _redact_unbound_numeric_claims(
                json.dumps(raw, ensure_ascii=False), symbol=symbol
            )
        except NumericReferenceError:
            # 非叙述字段不可省略；保留原始分类、字段和字面量诊断。
            raise error from None
        raw = cast(dict[str, JsonValue], json.loads(redacted_content))
        additions, issues = _collect_fact_references(raw, refs, catalog)
        content = _finish_structured_render(raw, additions, symbol=symbol)
    return StructuredFactRenderResult(
        content=content,
        dropped_count=len(issues),
        dropped_paths=tuple(dict.fromkeys(issue.path for issue in issues))[:8],
        dropped_categories=tuple(sorted({issue.category for issue in issues})),
        redacted_claim_count=redacted_claim_count,
        redacted_paths=redacted_paths,
    )
