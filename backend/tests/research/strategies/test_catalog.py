# 验证策略目录纯契约：参数 Schema 白名单、草稿/发布哈希、组合冻结与候选指纹。
# 这些断言不依赖数据库，先固定版本不可变和“无评估器/无候选”分离的边界。
# 测试只使用合成策略文本和随机标识，不包含用户策略算法、账户或真实财务资料。
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.market.contracts import MarketTimeframe
from app.research.strategies.contracts import (
    PriceCandidate,
    PriceRounding,
    StrategyApplicability,
    StrategyCandidateState,
    StrategyCapability,
    StrategyComponent,
    StrategyDirection,
    StrategyDraft,
    StrategyEvaluation,
    StrategyEvaluationStatus,
    StrategyKind,
    StrategyParameterError,
    StrategySchemaError,
    StrategyVersion,
    strategy_draft_sha256,
    validate_parameter_schema,
    validate_parameters,
)
from app.shared.agent_types import JsonObject, VersionRef

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)


# 构造固定版本引用；哈希只用于契约校验，不对应任何真实策略版本。
def _ref(*, version_id: UUID | None = None, sha256: str = "a" * 64) -> VersionRef:
    return VersionRef(version_id=version_id or uuid4(), sha256=sha256)


# 技术突破适配器支持的参数 Schema；最低盈亏比只能收紧，不能放宽旧规则。
def _schema() -> JsonObject:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "minimum_reward_risk": {"type": "decimal", "minimum": "1.5", "maximum": "10"},
            "allowed_states": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["triggered", "awaiting_confirmation"],
                },
                "minItems": 1,
                "maxItems": 2,
            },
        },
        "required": ["minimum_reward_risk", "allowed_states"],
    }


# 生成单策略草稿；覆盖字段用于验证编辑后的内容哈希变化。
def _draft(**overrides: object) -> StrategyDraft:
    values: dict[str, Any] = {
        "draft_id": uuid4(),
        "strategy_id": uuid4(),
        "name": "技术突破规则",
        "method_text": "仅使用已收盘 K 线的成交量突破与结构位方法。",
        "kind": StrategyKind.SINGLE,
        "components": (),
        "composition_rules": None,
        "parameter_schema": _schema(),
        "supported_symbols": ("BTCUSDT",),
        "supported_timeframes": (
            MarketTimeframe.H1,
            MarketTimeframe.H4,
            MarketTimeframe.D1,
        ),
        "warmup_candles": 60,
        "evaluator_id": "technical_breakout_v1",
        "capabilities": (
            StrategyCapability.RESEARCH,
            StrategyCapability.PRICE_CANDIDATE,
            StrategyCapability.MANUAL_PLANNING,
        ),
        "risk_notes": "结构止损不保证成交价；成本门槛来自旧研究规则。",
        "state_version": 0,
    }
    values.update(overrides)
    return StrategyDraft.model_validate(values)


# 构造一个合法的多头候选；所有财务字段都是十进制，不包含数量或资金。
def _candidate_values() -> dict[str, Any]:
    return {
        "strategy_ref": _ref(),
        "component_refs": (),
        "parameters_sha256": "b" * 64,
        "evaluator_id": "technical_breakout_v1",
        "evaluator_version": "1",
        "evidence_sha256": "c" * 64,
        "evidence_as_of": NOW,
        "direction": StrategyDirection.LONG,
        "entry_lower": Decimal("106"),
        "trigger": Decimal("106.2"),
        "entry_upper": Decimal("106.3"),
        "stop_loss": Decimal("97.3"),
        "target": Decimal("125"),
        "valid_until": NOW + timedelta(hours=4),
        "state": StrategyCandidateState.TRIGGERED,
        "price_rounding": PriceRounding.STRICT,
        "applicability_conditions": ("closed_candles_only",),
    }


# 在固定候选上覆盖单个字段，避免测试内联合字典造成类型推断歧义。
def _candidate(**overrides: object) -> PriceCandidate:
    values = _candidate_values()
    values.update(overrides)
    return PriceCandidate.build(**values)


# 只接受有界参数 Schema；远程引用、代码类型、正则和过深结构必须失败。
def test_parameter_schema_supports_bounded_fields_and_rejects_executable_extensions() -> None:
    validate_parameter_schema(_schema())
    validate_parameter_schema(
        {"type": "object", "additionalProperties": False, "properties": {}, "required": []}
    )

    invalid_schemas: list[JsonObject] = [
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"value": {"$ref": "https://example.invalid/schema.json"}},
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"value": {"type": "function"}},
        },
        {"type": "object", "properties": {"value": {"type": "string"}}},
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"value": {"type": "string", "pattern": "^a+$"}},
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "nested": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "array",
                                    "items": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                        },
                    },
                }
            },
        },
    ]
    for schema in invalid_schemas:
        with pytest.raises(StrategySchemaError):
            validate_parameter_schema(schema)


# 十进制参数只接受普通十进制字符串并规范化；浮点、指数、越界和未知字段均拒绝。
def test_validate_parameters_canonicalizes_decimal_text_and_rejects_unsafe_values() -> None:
    normalized = validate_parameters(
        _schema(),
        {"minimum_reward_risk": "1.50", "allowed_states": ["triggered"]},
    )
    assert normalized == {"minimum_reward_risk": "1.5", "allowed_states": ["triggered"]}

    invalid_parameters: list[JsonObject] = [
        {"minimum_reward_risk": 1.5, "allowed_states": ["triggered"]},
        {"minimum_reward_risk": "1e3", "allowed_states": ["triggered"]},
        {"minimum_reward_risk": "0.1", "allowed_states": ["triggered"]},
        {"minimum_reward_risk": "1.5", "allowed_states": []},
        {"minimum_reward_risk": "1.5", "allowed_states": ["triggered"], "extra": True},
        {"minimum_reward_risk": "1.5"},
    ]
    for parameters in invalid_parameters:
        with pytest.raises(StrategyParameterError):
            validate_parameters(_schema(), parameters)


# 已发布版本哈希必须与内容一致；编辑任何内容后旧哈希不能再冒充新版本。
def test_published_version_hash_is_bound_to_content_and_differs_after_edit() -> None:
    draft = _draft()
    published = StrategyVersion.from_draft(draft, published_at=NOW, state_version=1)

    assert published.ref.version_id == draft.draft_id
    assert published.ref.sha256 == strategy_draft_sha256(draft)
    assert published.ref.sha256 != strategy_draft_sha256(
        _draft(
            draft_id=draft.draft_id,
            strategy_id=draft.strategy_id,
            method_text=draft.method_text + " 本次修订改变了内容。",
        )
    )

    tampered = published.model_dump(mode="json", by_alias=False)
    tampered["method_text"] = "被替换的方法文本"
    with pytest.raises(ValidationError):
        StrategyVersion.model_validate(tampered)


# 组合版本只冻结组成引用；重复角色、空组成和缺失冲突规则不能发布。
def test_composite_version_freezes_component_refs_and_rejects_duplicate_roles() -> None:
    frozen_component_refs = (_ref(), _ref())
    components = (
        StrategyComponent(
            role="trend",
            strategy_ref=frozen_component_refs[0],
            parameters={},
        ),
        StrategyComponent(
            role="confirmation",
            strategy_ref=frozen_component_refs[1],
            parameters={},
        ),
    )
    composite = StrategyVersion.from_draft(
        _draft(
            kind=StrategyKind.COMPOSITE,
            components=components,
            composition_rules="仅由已登记测试评估器解释组合，不执行任意表达式。",
            evaluator_id="test_composite_v1",
        ),
        published_at=NOW,
        state_version=1,
    )

    assert composite.components == components
    assert (
        tuple(component.strategy_ref for component in composite.components) == frozen_component_refs
    )

    with pytest.raises(ValidationError):
        _draft(
            kind=StrategyKind.COMPOSITE,
            components=(
                StrategyComponent(role="trend", strategy_ref=_ref(), parameters={}),
                StrategyComponent(role="trend", strategy_ref=_ref(), parameters={}),
            ),
            composition_rules="重复角色。",
            evaluator_id="test_composite_v1",
        )
    with pytest.raises(ValidationError):
        _draft(
            kind=StrategyKind.COMPOSITE,
            components=(),
            composition_rules=None,
            evaluator_id="test_composite_v1",
        )


# 候选 ID 是内容、参数、证据与评估器版本的稳定指纹；篡改内容不能保留旧 ID。
def test_price_candidate_id_binds_parameters_evidence_and_geometry() -> None:
    first = _candidate()
    same = _candidate(strategy_ref=first.strategy_ref)
    assert first.candidate_id == same.candidate_id
    assert first.candidate_id == _candidate(strategy_ref=first.strategy_ref).candidate_id

    changed_parameters = _candidate(parameters_sha256="d" * 64)
    changed_evidence = _candidate(evidence_sha256="e" * 64)
    changed_geometry = _candidate(stop_loss=Decimal("97.4"))
    assert (
        len(
            {
                first.candidate_id,
                changed_parameters.candidate_id,
                changed_evidence.candidate_id,
                changed_geometry.candidate_id,
            }
        )
        == 4
    )

    tampered = first.model_dump(mode="json", by_alias=False)
    tampered["target"] = "126"
    with pytest.raises(ValidationError):
        PriceCandidate.model_validate(tampered)


# 无评估器是无能力状态，无候选是已评估但规则不适用；两者必须保留所选版本绑定。
def test_evaluation_distinguishes_missing_evaluator_from_no_candidates() -> None:
    selected_ref = _ref()
    no_evaluator = StrategyEvaluation(
        strategy_ref=selected_ref,
        evaluator_id="missing_evaluator_v1",
        evaluator_version="unavailable",
        parameters_sha256="a" * 64,
        evidence_sha256="b" * 64,
        status=StrategyEvaluationStatus.NO_EVALUATOR,
        applicability=StrategyApplicability.UNKNOWN,
        reason_codes=("evaluator_unavailable",),
    )
    no_candidates = StrategyEvaluation(
        strategy_ref=selected_ref,
        evaluator_id="technical_breakout_v1",
        evaluator_version="1",
        parameters_sha256="a" * 64,
        evidence_sha256="b" * 64,
        status=StrategyEvaluationStatus.EVALUATED,
        applicability=StrategyApplicability.NOT_APPLICABLE,
        reason_codes=("trend_conflict",),
    )

    assert no_evaluator.strategy_ref == selected_ref
    assert no_evaluator.candidates == ()
    assert no_candidates.strategy_ref == selected_ref
    assert no_candidates.candidates == ()
    assert no_evaluator.status is not no_candidates.status

    with pytest.raises(ValidationError):
        StrategyEvaluation(
            strategy_ref=selected_ref,
            evaluator_id="missing_evaluator_v1",
            evaluator_version="unavailable",
            parameters_sha256="a" * 64,
            evidence_sha256="b" * 64,
            status=StrategyEvaluationStatus.NO_EVALUATOR,
            applicability=StrategyApplicability.UNKNOWN,
            reason_codes=(),
        )
