# 定义版本化策略包、不可变发布内容、参数白名单和只读评估结果。
# 策略正文只作为数据保存；参数 Schema 仅允许有界 object/string/decimal/integer/boolean/array，
# 不加载代码、远端 $ref、正则或任意表达式，避免策略文本或知识内容扩权。
# 候选只含价格几何与证据/参数指纹，不含资金、数量、订单或 TradeIntent。
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, JsonValue, ValidationError, field_validator, model_validator

from app.market.contracts import MarketTimeframe
from app.market.symbols import ResearchSymbol
from app.shared.agent_types import (
    AgentModel,
    DecimalText,
    JsonObject,
    UtcDateTime,
    VersionRef,
    is_sha256,
    parse_decimal_text,
    require_utc,
    serialize_decimal_text,
    sha256_json,
)

_STRATEGY_ID_PATTERN = r"[a-z][a-z0-9_]{2,63}$"
_EVALUATOR_VERSION_PATTERN = r"[a-z0-9][a-z0-9_.-]{0,31}$"
_ROLE_PATTERN = r"[a-z][a-z0-9_]{0,63}$"
_REASON_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_MAX_SCHEMA_DEPTH = 6
_MAX_SCHEMA_NODES = 256
_MAX_SCHEMA_PROPERTIES = 32
_MAX_PARAMETER_BYTES = 32 * 1024


# 契约错误带固定原因码；Pydantic 会把业务校验失败包装为 ValidationError。
class StrategyContractError(ValueError):
    def __init__(self, message: str, *, code: str = "strategy_contract_violation") -> None:
        super().__init__(message)
        self.code = code


class StrategySchemaError(StrategyContractError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_parameter_schema")


class StrategyParameterError(StrategyContractError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_parameters")


class StrategyCatalogError(StrategyContractError):
    pass


class StrategyConflictError(StrategyCatalogError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="strategy_conflict")


class StrategyNotAvailableError(StrategyCatalogError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="strategy_not_available")


class StrategyIntegrityError(StrategyCatalogError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="strategy_integrity_violation")


class StrategyEvaluatorError(StrategyContractError):
    def __init__(self, message: str, *, code: str = "strategy_evaluator_failed") -> None:
        super().__init__(message, code=code)


# 策略包类型：单策略或用户定义组合；组合只冻结引用，不执行任意表达式。
class StrategyKind(StrEnum):
    SINGLE = "single"
    COMPOSITE = "composite"


# 能力分别标记；manual_planning 只表示可进入流程，不表示任何具体计划可实施。
class StrategyCapability(StrEnum):
    RESEARCH = "research"
    PRICE_CANDIDATE = "price_candidate"
    MANUAL_PLANNING = "manual_planning"
    BACKTEST = "backtest"
    PAPER = "paper"


class StrategyDirection(StrEnum):
    LONG = "long"
    SHORT = "short"


class StrategyCandidateState(StrEnum):
    TRIGGERED = "triggered"
    AWAITING_CONFIRMATION = "awaiting_confirmation"


class PriceRounding(StrEnum):
    STRICT = "strict"
    CONSERVATIVE_ONE_TICK = "conservative_one_tick"


class StrategyEvaluationStatus(StrEnum):
    EVALUATED = "evaluated"
    NO_EVALUATOR = "no_evaluator"
    INVALID_PARAMETERS = "invalid_parameters"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class StrategyApplicability(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


# 组合中的一个角色；strategy_ref 必须精确指向已发布组成版本，parameters 由组成 Schema 校验。
class StrategyComponent(AgentModel):
    role: str = Field(pattern=_ROLE_PATTERN)
    strategy_ref: VersionRef
    parameters: JsonObject = Field(default_factory=dict)

    # 组合参数可能在草稿与发布对象间传递；构造时深拷贝，避免外部改原字典影响冻结正文。
    @field_validator("parameters", mode="before")
    @classmethod
    def isolate_parameters(cls, value: object) -> object:
        return copy.deepcopy(value)


# 单条确定性事实；数值由程序计算，模型只能引用，不能自行改写。
class StrategyFact(AgentModel):
    fact_id: str = Field(pattern=r"[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=200)
    value: DecimalText | None = None
    text: str | None = Field(default=None, min_length=1, max_length=500)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=20)

    @field_validator("label", "text", "unit")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("事实文本不能为空")
        return normalized

    @model_validator(mode="after")
    def validate_fact(self) -> StrategyFact:
        if self.value is None and self.text is None:
            raise ValueError("事实必须包含数值或文本")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("事实证据标识不能重复")
        return self


# 可编辑策略内容；草稿与发布版本共用字段，发布后再叠加不可变引用和归档状态。
class _StrategyContent(AgentModel):
    strategy_id: UUID
    name: str = Field(min_length=1, max_length=200)
    method_text: str = Field(min_length=1, max_length=20000)
    kind: StrategyKind
    components: tuple[StrategyComponent, ...] = Field(default=(), max_length=32)
    composition_rules: str | None = Field(default=None, max_length=5000)
    parameter_schema: JsonObject
    supported_symbols: tuple[ResearchSymbol, ...] = Field(min_length=1, max_length=50)
    supported_timeframes: tuple[MarketTimeframe, ...] = Field(min_length=1, max_length=4)
    warmup_candles: int = Field(ge=0, le=10000)
    evaluator_id: str = Field(pattern=_STRATEGY_ID_PATTERN)
    capabilities: tuple[StrategyCapability, ...] = Field(min_length=1)
    risk_notes: str = Field(min_length=1, max_length=5000)

    @field_validator("name", "method_text", "composition_rules", "risk_notes")
    @classmethod
    def strip_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("策略文本不能为空")
        return normalized

    @field_validator("parameter_schema")
    @classmethod
    def validate_schema(cls, value: JsonObject) -> JsonObject:
        validate_parameter_schema(value)
        return value

    # 参数 Schema 和组成对象在模型边界深拷贝，避免草稿/发布版本与调用方共享嵌套可变对象。
    @field_validator("components", "parameter_schema", mode="before")
    @classmethod
    def isolate_nested_content(cls, value: object) -> object:
        return copy.deepcopy(value)

    @model_validator(mode="after")
    def validate_content(self) -> _StrategyContent:
        if len(set(self.supported_symbols)) != len(self.supported_symbols):
            raise ValueError("支持币种不能重复")
        if len(set(self.supported_timeframes)) != len(self.supported_timeframes):
            raise ValueError("支持周期不能重复")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("策略能力不能重复")
        if self.kind is StrategyKind.SINGLE:
            if self.components or self.composition_rules is not None:
                raise ValueError("单策略不能声明组合组成或组合规则")
        else:
            if not self.components or self.composition_rules is None:
                raise ValueError("组合策略必须有组成和组合规则")
            roles = tuple(component.role for component in self.components)
            if len(set(roles)) != len(roles):
                raise ValueError("组合角色不能重复")
        return self


# 可编辑草稿；state_version 是乐观并发版本，发布或归档后该草稿不再可改。
class StrategyDraft(_StrategyContent):
    draft_id: UUID
    state_version: int = Field(default=0, ge=0)


# 已发布不可变版本；state_version 记录发布时的目录代次，归档只改变目录状态而不改正文。
class StrategyVersion(_StrategyContent):
    ref: VersionRef
    published_at: UtcDateTime
    state_version: int = Field(ge=1)
    archived: bool = False
    archived_at: UtcDateTime | None = None

    @field_validator("published_at", "archived_at")
    @classmethod
    def validate_times(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value)

    @model_validator(mode="after")
    def validate_version(self) -> StrategyVersion:
        if self.ref.sha256 != strategy_content_sha256(self):
            raise ValueError("发布版本内容指纹与版本引用不一致")
        if self.archived != (self.archived_at is not None):
            raise ValueError("归档状态与归档时间必须一致")
        return self

    # 从草稿冻结发布版本；先深拷贝并重新校验草稿，避免后续修改草稿嵌套对象影响发布版本。
    @classmethod
    def from_draft(
        cls,
        draft: StrategyDraft,
        *,
        published_at: datetime,
        state_version: int,
        archived: bool = False,
        archived_at: datetime | None = None,
    ) -> StrategyVersion:
        snapshot = StrategyDraft.model_validate(
            copy.deepcopy(draft.model_dump(mode="python", by_alias=False))
        )
        return cls(
            ref=VersionRef(
                version_id=snapshot.draft_id,
                sha256=strategy_draft_sha256(snapshot),
            ),
            strategy_id=snapshot.strategy_id,
            name=snapshot.name,
            method_text=snapshot.method_text,
            kind=snapshot.kind,
            components=snapshot.components,
            composition_rules=snapshot.composition_rules,
            parameter_schema=snapshot.parameter_schema,
            supported_symbols=snapshot.supported_symbols,
            supported_timeframes=snapshot.supported_timeframes,
            warmup_candles=snapshot.warmup_candles,
            evaluator_id=snapshot.evaluator_id,
            capabilities=snapshot.capabilities,
            risk_notes=snapshot.risk_notes,
            published_at=published_at,
            state_version=state_version,
            archived=archived,
            archived_at=archived_at,
        )

    # 在消费入口创建隔离快照并重新校验正文哈希；嵌套 Schema/组成参数被改后不得沿用旧 ref。
    def validated_snapshot(self) -> StrategyVersion:
        try:
            snapshot = StrategyVersion.model_validate(
                copy.deepcopy(self.model_dump(mode="python", by_alias=False))
            )
        except (ValidationError, TypeError, ValueError) as error:
            raise StrategyIntegrityError("发布版本正文与版本指纹不一致") from error
        if snapshot.ref != self.ref:
            raise StrategyIntegrityError("发布版本引用与正文不一致")
        return snapshot


# 计算草稿内容哈希；draft_id/state_version 不进入语义哈希，编辑正文后哈希必变。
def strategy_draft_sha256(draft: StrategyDraft) -> str:
    return strategy_content_sha256(draft)


# 发布正文哈希覆盖策略身份、方法、组合引用、参数 Schema、适用范围、评估器和能力。
def strategy_content_sha256(content: _StrategyContent) -> str:
    payload: JsonObject = {
        "strategyId": str(content.strategy_id),
        "name": content.name,
        "methodText": content.method_text,
        "kind": content.kind.value,
        "components": [
            component.model_dump(mode="json", by_alias=False) for component in content.components
        ],
        "compositionRules": content.composition_rules,
        "parameterSchema": content.parameter_schema,
        "supportedSymbols": [str(symbol) for symbol in content.supported_symbols],
        "supportedTimeframes": [timeframe.value for timeframe in content.supported_timeframes],
        "warmupCandles": content.warmup_candles,
        "evaluatorId": content.evaluator_id,
        "capabilities": [capability.value for capability in content.capabilities],
        "riskNotes": content.risk_notes,
    }
    return sha256_json(cast(JsonValue, payload))


# 只读价格候选；candidate_id 由全部内容字段、参数、证据和评估器版本共同确定。
class PriceCandidate(AgentModel):
    candidate_id: UUID
    strategy_ref: VersionRef
    component_refs: tuple[VersionRef, ...] = Field(default=(), max_length=32)
    parameters_sha256: str
    evaluator_id: str = Field(pattern=_STRATEGY_ID_PATTERN)
    evaluator_version: str = Field(pattern=_EVALUATOR_VERSION_PATTERN)
    evidence_sha256: str
    evidence_as_of: UtcDateTime
    direction: StrategyDirection
    entry_lower: DecimalText
    trigger: DecimalText
    entry_upper: DecimalText
    stop_loss: DecimalText
    target: DecimalText
    valid_until: UtcDateTime
    state: StrategyCandidateState
    price_rounding: PriceRounding = PriceRounding.STRICT
    applicability_conditions: tuple[str, ...] = Field(default=(), max_length=20)

    @field_validator("parameters_sha256", "evidence_sha256")
    @classmethod
    def validate_fingerprints(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("候选指纹必须是 64 位小写十六进制")
        return value

    @field_validator("evidence_as_of", "valid_until")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("applicability_conditions")
    @classmethod
    def validate_conditions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            not condition or len(condition) > 64 or not condition.replace("_", "").isalnum()
            for condition in value
        ):
            raise ValueError("适用条件必须是稳定短标识")
        if len(set(value)) != len(value):
            raise ValueError("适用条件不能重复")
        return value

    @model_validator(mode="after")
    def validate_candidate(self) -> PriceCandidate:
        if self.candidate_id != candidate_id_for(_candidate_payload(self)):
            raise ValueError("候选标识与候选内容不一致")
        if any(
            price <= 0
            for price in (
                self.entry_lower,
                self.trigger,
                self.entry_upper,
                self.stop_loss,
                self.target,
            )
        ):
            raise ValueError("候选价格必须为正")
        if not self.entry_lower <= self.trigger <= self.entry_upper:
            raise ValueError("触发价必须位于入场区间")
        if self.direction is StrategyDirection.LONG and not (
            self.stop_loss < self.entry_lower and self.entry_upper < self.target
        ):
            raise ValueError("多头候选价格顺序无效")
        if self.direction is StrategyDirection.SHORT and not (
            self.target < self.entry_lower and self.entry_upper < self.stop_loss
        ):
            raise ValueError("空头候选价格顺序无效")
        if self.valid_until <= self.evidence_as_of:
            raise ValueError("候选有效期必须晚于证据截止时间")
        if len(set(self.component_refs)) != len(self.component_refs):
            raise ValueError("组成引用不能重复")
        return self

    # 计算候选 ID 后构造模型；调用方只需提供价格几何和绑定指纹，不手写候选 ID。
    @classmethod
    def build(
        cls,
        *,
        strategy_ref: VersionRef,
        component_refs: tuple[VersionRef, ...] = (),
        parameters_sha256: str,
        evaluator_id: str,
        evaluator_version: str,
        evidence_sha256: str,
        evidence_as_of: datetime,
        direction: StrategyDirection,
        entry_lower: Decimal,
        trigger: Decimal,
        entry_upper: Decimal,
        stop_loss: Decimal,
        target: Decimal,
        valid_until: datetime,
        state: StrategyCandidateState,
        price_rounding: PriceRounding = PriceRounding.STRICT,
        applicability_conditions: tuple[str, ...] = (),
    ) -> PriceCandidate:
        payload: JsonObject = {
            "strategyRef": strategy_ref.model_dump(mode="json", by_alias=False),
            "componentRefs": [
                ref.model_dump(mode="json", by_alias=False) for ref in component_refs
            ],
            "parametersSha256": parameters_sha256,
            "evaluatorId": evaluator_id,
            "evaluatorVersion": evaluator_version,
            "evidenceSha256": evidence_sha256,
            "evidenceAsOf": evidence_as_of.isoformat(),
            "direction": direction.value,
            "entryLower": serialize_decimal_text(entry_lower),
            "trigger": serialize_decimal_text(trigger),
            "entryUpper": serialize_decimal_text(entry_upper),
            "stopLoss": serialize_decimal_text(stop_loss),
            "target": serialize_decimal_text(target),
            "validUntil": valid_until.isoformat(),
            "state": state.value,
            "priceRounding": price_rounding.value,
            "applicabilityConditions": list(applicability_conditions),
        }
        return cls(
            candidate_id=candidate_id_for(payload),
            strategy_ref=strategy_ref,
            component_refs=component_refs,
            parameters_sha256=parameters_sha256,
            evaluator_id=evaluator_id,
            evaluator_version=evaluator_version,
            evidence_sha256=evidence_sha256,
            evidence_as_of=evidence_as_of,
            direction=direction,
            entry_lower=entry_lower,
            trigger=trigger,
            entry_upper=entry_upper,
            stop_loss=stop_loss,
            target=target,
            valid_until=valid_until,
            state=state,
            price_rounding=price_rounding,
            applicability_conditions=applicability_conditions,
        )


# 候选指纹规范化载荷；字段顺序固定并通过 JSON 键排序实现稳定哈希。
def _candidate_payload(candidate: PriceCandidate) -> JsonObject:
    return {
        "strategyRef": candidate.strategy_ref.model_dump(mode="json", by_alias=False),
        "componentRefs": [
            ref.model_dump(mode="json", by_alias=False) for ref in candidate.component_refs
        ],
        "parametersSha256": candidate.parameters_sha256,
        "evaluatorId": candidate.evaluator_id,
        "evaluatorVersion": candidate.evaluator_version,
        "evidenceSha256": candidate.evidence_sha256,
        "evidenceAsOf": candidate.evidence_as_of.isoformat(),
        "direction": candidate.direction.value,
        "entryLower": serialize_decimal_text(candidate.entry_lower),
        "trigger": serialize_decimal_text(candidate.trigger),
        "entryUpper": serialize_decimal_text(candidate.entry_upper),
        "stopLoss": serialize_decimal_text(candidate.stop_loss),
        "target": serialize_decimal_text(candidate.target),
        "validUntil": candidate.valid_until.isoformat(),
        "state": candidate.state.value,
        "priceRounding": candidate.price_rounding.value,
        "applicabilityConditions": list(candidate.applicability_conditions),
    }


# 由候选规范化载荷生成稳定 UUID；不同参数/证据/几何不会共享候选 ID。
def candidate_id_for(payload: JsonObject) -> UUID:
    return uuid5(NAMESPACE_URL, f"strategy-candidate:{sha256_json(cast(JsonValue, payload))}")


# 只读评估结果；即使没有候选或无评估器也保留所选版本、参数和证据绑定。
class StrategyEvaluation(AgentModel):
    strategy_ref: VersionRef
    evaluator_id: str = Field(pattern=_STRATEGY_ID_PATTERN)
    evaluator_version: str = Field(pattern=_EVALUATOR_VERSION_PATTERN)
    parameters_sha256: str
    evidence_sha256: str
    status: StrategyEvaluationStatus
    applicability: StrategyApplicability
    facts: tuple[StrategyFact, ...] = Field(default=(), max_length=64)
    candidates: tuple[PriceCandidate, ...] = Field(default=(), max_length=32)
    reason_codes: tuple[str, ...] = Field(default=(), max_length=20)

    @field_validator("parameters_sha256", "evidence_sha256")
    @classmethod
    def validate_fingerprints(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("评估指纹必须是 64 位小写十六进制")
        return value

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_REASON_CODE_PATTERN.fullmatch(code) is None for code in value):
            raise ValueError("评估原因码必须是有界小写标识")
        if len(set(value)) != len(value):
            raise ValueError("评估原因码不能重复")
        return value

    @model_validator(mode="after")
    def validate_evaluation(self) -> StrategyEvaluation:
        fact_ids = tuple(fact.fact_id for fact in self.facts)
        if len(set(fact_ids)) != len(fact_ids):
            raise ValueError("事实标识不能重复")
        candidate_ids = tuple(str(candidate.candidate_id) for candidate in self.candidates)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("候选标识不能重复")
        if self.status is not StrategyEvaluationStatus.EVALUATED:
            if self.candidates:
                raise ValueError("未完成评估不能返回候选")
            if not self.reason_codes:
                raise ValueError("非评估完成状态必须给出原因")
            if self.applicability is StrategyApplicability.APPLICABLE:
                raise ValueError("无效状态不能标记为适用")
        else:
            if not self.candidates and not self.reason_codes:
                raise ValueError("已评估但无候选时必须给出原因")
            if self.candidates and self.applicability is not StrategyApplicability.APPLICABLE:
                raise ValueError("有候选时必须标记为适用")
            if not self.candidates and self.applicability is StrategyApplicability.APPLICABLE:
                raise ValueError("无候选时不能标记为适用")
        for candidate in self.candidates:
            if candidate.strategy_ref != self.strategy_ref:
                raise ValueError("候选策略版本与评估绑定不一致")
            if candidate.parameters_sha256 != self.parameters_sha256:
                raise ValueError("候选参数指纹与评估绑定不一致")
            if candidate.evidence_sha256 != self.evidence_sha256:
                raise ValueError("候选证据指纹与评估绑定不一致")
            if (
                candidate.evaluator_id != self.evaluator_id
                or candidate.evaluator_version != self.evaluator_version
            ):
                raise ValueError("候选评估器版本与评估绑定不一致")
        return self


# 参数 Schema 白名单：公共关键字加各类型专属关键字，未知组合直接拒绝。
_COMMON_SCHEMA_KEYS = {"type", "description"}
_TYPE_SCHEMA_KEYS = {
    "object": {"properties", "required", "additionalProperties"},
    "string": {"enum", "minLength", "maxLength"},
    "decimal": {"enum", "minimum", "maximum"},
    "integer": {"enum", "minimum", "maximum"},
    "boolean": {"enum"},
    "array": {"items", "minItems", "maxItems"},
}
_SCHEMA_TYPES = {"object", "string", "decimal", "integer", "boolean", "array"}
_PROPERTY_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


# 校验根 Schema 并递归检查每个子节点；根必须是 object，不接受远程引用、代码类型和未知关键字。
def validate_parameter_schema(schema: JsonObject) -> None:
    if schema.get("type") != "object":
        raise StrategySchemaError("参数 Schema 根节点必须是 object")
    _validate_schema_node(schema, depth=0, counter=[0])


# 递归校验 Schema 节点；计数器限制总节点数，深度限制嵌套数组/对象。
def _validate_schema_node(node: JsonObject, *, depth: int, counter: list[int]) -> None:
    if depth > _MAX_SCHEMA_DEPTH:
        raise StrategySchemaError("参数 Schema 嵌套过深")
    counter[0] += 1
    if counter[0] > _MAX_SCHEMA_NODES:
        raise StrategySchemaError("参数 Schema 节点过多")
    node_type = node.get("type")
    if not isinstance(node_type, str) or node_type not in _SCHEMA_TYPES:
        raise StrategySchemaError("参数 Schema 类型不受支持")
    unknown = set(node) - (_COMMON_SCHEMA_KEYS | _TYPE_SCHEMA_KEYS[node_type])
    if unknown:
        raise StrategySchemaError("参数 Schema 包含不支持的关键字")
    description = node.get("description")
    if description is not None and (not isinstance(description, str) or len(description) > 500):
        raise StrategySchemaError("参数 Schema 说明必须是有界文本")

    if node_type == "object":
        _validate_object_schema(node, depth=depth, counter=counter)
    elif node_type == "string":
        _validate_string_schema(node)
    elif node_type == "decimal":
        _validate_decimal_schema(node)
    elif node_type == "integer":
        _validate_integer_schema(node)
    elif node_type == "boolean":
        _validate_boolean_schema(node)
    else:
        _validate_array_schema(node, depth=depth, counter=counter)


# object 必须显式关闭额外字段，属性名和 required 必须是稳定小写标识。
def _validate_object_schema(node: JsonObject, *, depth: int, counter: list[int]) -> None:
    properties = node.get("properties")
    if not isinstance(properties, dict):
        raise StrategySchemaError("object 参数必须声明 properties")
    if len(properties) > _MAX_SCHEMA_PROPERTIES:
        raise StrategySchemaError("object 参数属性过多")
    if node.get("additionalProperties") is not False:
        raise StrategySchemaError("object 参数必须显式禁止额外字段")
    for name, child in properties.items():
        if _PROPERTY_NAME.fullmatch(name) is None:
            raise StrategySchemaError("参数属性名必须是小写标识")
        if not isinstance(child, dict):
            raise StrategySchemaError("参数属性 Schema 必须是对象")
        _validate_schema_node(child, depth=depth + 1, counter=counter)
    required = node.get("required", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise StrategySchemaError("required 必须是字符串数组")
    if len(set(required)) != len(required) or not set(required) <= set(properties):
        raise StrategySchemaError("required 必须唯一且指向已声明属性")


# string 只接受长度和枚举约束，不允许正则或 format。
def _validate_string_schema(node: JsonObject) -> None:
    minimum = node.get("minLength", 0)
    maximum = node.get("maxLength", 1024)
    if (
        not isinstance(minimum, int)
        or isinstance(minimum, bool)
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or not 0 <= minimum <= maximum <= 1024
    ):
        raise StrategySchemaError("string 长度范围无效")
    enum = node.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum or len(enum) > 50:
            raise StrategySchemaError("string 枚举必须是有界数组")
        if any(not isinstance(item, str) or len(item) > 1024 for item in enum):
            raise StrategySchemaError("string 枚举值必须是有界文本")
        if len(set(enum)) != len(enum):
            raise StrategySchemaError("string 枚举值不能重复")


# decimal 以十进制字符串输入，边界也是十进制字符串；不接受浮点数字面量。
def _validate_decimal_schema(node: JsonObject) -> None:
    minimum = node.get("minimum")
    maximum = node.get("maximum")
    parsed_minimum = _schema_decimal(minimum, "minimum") if minimum is not None else None
    parsed_maximum = _schema_decimal(maximum, "maximum") if maximum is not None else None
    if (
        parsed_minimum is not None
        and parsed_maximum is not None
        and parsed_minimum > parsed_maximum
    ):
        raise StrategySchemaError("decimal 最小值不能大于最大值")
    enum = node.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum or len(enum) > 50:
            raise StrategySchemaError("decimal 枚举必须是有界数组")
        values = tuple(_schema_decimal(item, "enum") for item in enum)
        if len(set(values)) != len(values):
            raise StrategySchemaError("decimal 枚举值不能重复")
        if parsed_minimum is not None and any(value < parsed_minimum for value in values):
            raise StrategySchemaError("decimal 枚举值低于最小值")
        if parsed_maximum is not None and any(value > parsed_maximum for value in values):
            raise StrategySchemaError("decimal 枚举值超过最大值")


# integer 约束使用普通整数并有界；布尔值不能冒充整数。
def _validate_integer_schema(node: JsonObject) -> None:
    minimum = node.get("minimum")
    maximum = node.get("maximum")
    for value in (minimum, maximum):
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or abs(value) > 10**18
        ):
            raise StrategySchemaError("integer 边界必须是有界整数")
    if (
        isinstance(minimum, int)
        and not isinstance(minimum, bool)
        and isinstance(maximum, int)
        and not isinstance(maximum, bool)
        and minimum > maximum
    ):
        raise StrategySchemaError("integer 最小值不能大于最大值")
    enum = node.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum or len(enum) > 50:
            raise StrategySchemaError("integer 枚举必须是有界数组")
        if any(
            not isinstance(item, int) or isinstance(item, bool) or abs(item) > 10**18
            for item in enum
        ):
            raise StrategySchemaError("integer 枚举值必须是有界整数")
        if len(set(enum)) != len(enum):
            raise StrategySchemaError("integer 枚举值不能重复")


# boolean 只允许布尔枚举，不接受字符串形式的 true/false。
def _validate_boolean_schema(node: JsonObject) -> None:
    enum = node.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum or len(enum) > 2:
            raise StrategySchemaError("boolean 枚举必须是最多两项的数组")
        if any(not isinstance(item, bool) for item in enum):
            raise StrategySchemaError("boolean 枚举值必须是布尔")
        if len(set(enum)) != len(enum):
            raise StrategySchemaError("boolean 枚举值不能重复")


# array 必须有单一 items Schema，长度上限最多 100，避免无界输入。
def _validate_array_schema(node: JsonObject, *, depth: int, counter: list[int]) -> None:
    items = node.get("items")
    if not isinstance(items, dict):
        raise StrategySchemaError("array 参数必须声明 items")
    minimum = node.get("minItems", 0)
    maximum = node.get("maxItems", 100)
    if (
        not isinstance(minimum, int)
        or isinstance(minimum, bool)
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or not 0 <= minimum <= maximum <= 100
    ):
        raise StrategySchemaError("array 长度范围无效")
    _validate_schema_node(items, depth=depth + 1, counter=counter)


# 将 Schema 中声明为 decimal 的边界/枚举值解析成 Decimal，拒绝指数和超范围。
def _schema_decimal(value: object, label: str) -> Decimal:
    if not isinstance(value, str):
        raise StrategySchemaError(f"decimal {label} 必须是十进制字符串")
    try:
        return parse_decimal_text(value)
    except ValueError as error:
        raise StrategySchemaError(f"decimal {label} 不是合法十进制文本") from error


# 按 Schema 校验参数并规范化 decimal 文本；未知字段、缺失必填和类型不符都拒绝。
def validate_parameters(schema: JsonObject, parameters: JsonObject) -> JsonObject:
    validate_parameter_schema(schema)
    try:
        encoded = json.dumps(
            parameters,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise StrategyParameterError("参数必须是 JSON 安全值") from error
    if len(encoded) > _MAX_PARAMETER_BYTES:
        raise StrategyParameterError("参数超过大小上限")
    normalized = _validate_value(schema, parameters, path="$")
    if not isinstance(normalized, dict):
        raise StrategyParameterError("根参数必须是对象")
    return normalized


# 递归校验并规范化一个参数值；路径只用于本地错误信息，不含用户财务值。
def _validate_value(schema: JsonObject, value: JsonValue, *, path: str) -> JsonValue:
    node_type = schema.get("type")
    if node_type == "object":
        if not isinstance(value, dict):
            raise StrategyParameterError(f"{path} 必须是对象")
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise StrategyParameterError(f"{path} 的 Schema 无效")
        unknown = set(value) - set(properties)
        if unknown:
            raise StrategyParameterError(f"{path} 包含未声明字段")
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise StrategyParameterError(f"{path} 的 required 无效")
        missing = set(required) - set(value)
        if missing:
            raise StrategyParameterError(f"{path} 缺少必填字段")
        normalized: JsonObject = {}
        for key, item in value.items():
            child_schema = properties[key]
            if not isinstance(child_schema, dict):
                raise StrategyParameterError(f"{path}.{key} 的 Schema 无效")
            normalized[key] = _validate_value(child_schema, item, path=f"{path}.{key}")
        return normalized
    if node_type == "array":
        if not isinstance(value, list):
            raise StrategyParameterError(f"{path} 必须是数组")
        minimum = schema.get("minItems", 0)
        maximum = schema.get("maxItems", 100)
        if not isinstance(minimum, int) or not isinstance(maximum, int):
            raise StrategyParameterError(f"{path} 的数组边界无效")
        if not minimum <= len(value) <= maximum:
            raise StrategyParameterError(f"{path} 数组长度超出范围")
        items = schema.get("items")
        if not isinstance(items, dict):
            raise StrategyParameterError(f"{path} 的 items Schema 无效")
        return [
            _validate_value(items, item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if node_type == "string":
        if not isinstance(value, str):
            raise StrategyParameterError(f"{path} 必须是字符串")
        minimum = schema.get("minLength", 0)
        maximum = schema.get("maxLength", 1024)
        if not isinstance(minimum, int) or not isinstance(maximum, int):
            raise StrategyParameterError(f"{path} 的字符串边界无效")
        if not minimum <= len(value) <= maximum:
            raise StrategyParameterError(f"{path} 长度超出范围")
        enum = schema.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise StrategyParameterError(f"{path} 不在允许枚举内")
        return value
    if node_type == "decimal":
        if not isinstance(value, str):
            raise StrategyParameterError(f"{path} 必须是十进制字符串")
        try:
            parsed = parse_decimal_text(value)
        except ValueError as error:
            raise StrategyParameterError(f"{path} 不是合法十进制文本") from error
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, str) and parsed < parse_decimal_text(minimum):
            raise StrategyParameterError(f"{path} 低于最小值")
        if isinstance(maximum, str) and parsed > parse_decimal_text(maximum):
            raise StrategyParameterError(f"{path} 超过最大值")
        enum = schema.get("enum")
        if isinstance(enum, list):
            allowed = {parse_decimal_text(item) for item in enum if isinstance(item, str)}
            if parsed not in allowed:
                raise StrategyParameterError(f"{path} 不在允许枚举内")
        return serialize_decimal_text(parsed)
    if node_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise StrategyParameterError(f"{path} 必须是整数")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, int) and value < minimum:
            raise StrategyParameterError(f"{path} 低于最小值")
        if isinstance(maximum, int) and value > maximum:
            raise StrategyParameterError(f"{path} 超过最大值")
        enum = schema.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise StrategyParameterError(f"{path} 不在允许枚举内")
        return value
    if node_type == "boolean":
        if not isinstance(value, bool):
            raise StrategyParameterError(f"{path} 必须是布尔")
        enum = schema.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise StrategyParameterError(f"{path} 不在允许枚举内")
        return value
    raise StrategyParameterError(f"{path} 的类型不受支持")


# 计算参数规范化指纹；调用方先通过 Schema 校验，避免不同文本表示得到同一策略参数。
def parameter_sha256(parameters: JsonObject) -> str:
    return sha256_json(cast(JsonValue, parameters))


__all__ = [
    "PriceCandidate",
    "PriceRounding",
    "StrategyApplicability",
    "StrategyCandidateState",
    "StrategyCapability",
    "StrategyCatalogError",
    "StrategyComponent",
    "StrategyConflictError",
    "StrategyContractError",
    "StrategyDirection",
    "StrategyDraft",
    "StrategyEvaluation",
    "StrategyEvaluationStatus",
    "StrategyEvaluatorError",
    "StrategyFact",
    "StrategyIntegrityError",
    "StrategyKind",
    "StrategyNotAvailableError",
    "StrategyParameterError",
    "StrategySchemaError",
    "StrategyVersion",
    "candidate_id_for",
    "parameter_sha256",
    "strategy_content_sha256",
    "strategy_draft_sha256",
    "validate_parameter_schema",
    "validate_parameters",
]
