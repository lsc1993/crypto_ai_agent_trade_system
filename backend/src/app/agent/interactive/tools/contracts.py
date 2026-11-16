# 定义 C6 工具守卫的公共纯契约：登记工具、模型请求、处理器结果和审计观察。
# 所有 Schema 只允许有界 object/string/integer/boolean/array，不加载远端 $ref、正则或代码。
# 本模块不执行工具、不访问数据库/网络、不读取私有账户；治理内核也不通过这里路由工具。
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Protocol, cast
from uuid import UUID

from pydantic import Field, JsonValue, field_validator, model_validator

from app.agent_runs.contracts import RunSnapshot
from app.agent_runs.segments import ExecutionContext
from app.shared.agent_types import (
    AgentModel,
    ArtifactRef,
    JsonObject,
    UtcDateTime,
    is_sha256,
    require_utc,
    sha256_json,
)

# 输入参数、处理器摘要和目录描述均有独立上限；8 KiB 是模型可见工具摘要上限。
MAX_TOOL_ARGUMENT_BYTES = 16_384
MAX_TOOL_SUMMARY_BYTES = 8_192
MAX_TOOL_RESULT_BYTES = 64 * 1024
MAX_TOOL_DESCRIPTION_CHARS = 2_000
TOOL_TIMEOUT_SECONDS = 30
# 工具步骤使用独立高位区段，避免与 T08 证据传输区段和后续低序号模型步骤冲突。
TOOL_ACTION_SEQUENCE_BASE = 2_000_000
_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_TOOL_VERSION = re.compile(r"[a-z0-9][a-z0-9_.-]{0,31}\Z")
_MODEL_TOOL_VERSION = re.compile(r"[a-z0-9_]{1,64}\Z")
_CALL_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_PROPERTY_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_SAFE_DESCRIPTION = re.compile(r"[\x20-\x7e\u00a0-\uffff\n\t]*\Z")
_SCHEMA_DEPTH_LIMIT = 4
_SCHEMA_NODE_LIMIT = 128
_SCHEMA_PROPERTY_LIMIT = 32
_SCHEMA_ARRAY_LIMIT = 32
_SCHEMA_STRING_LIMIT = 8_192
_SCHEMA_INTEGER_LIMIT = 10**9
_SCHEMA_TYPES = frozenset({"object", "string", "integer", "boolean", "array"})
_COMMON_SCHEMA_KEYS = frozenset({"type", "description"})


# 稳定公开错误；调用方只按 code 记录安全失败，不回显上游异常或原始参数。
class ToolContractError(ValueError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class ToolSchemaError(ToolContractError):
    def __init__(self, message: str) -> None:
        super().__init__("invalid_tool_schema", message)


class ToolArgumentsError(ToolContractError):
    def __init__(self, message: str) -> None:
        super().__init__("invalid_arguments", message)


# 首期工具全部是只读研究能力；不存在模型可调用的写入、账户或订单能力。
class ToolCapability(StrEnum):
    READ_ONLY_RESEARCH = "read_only_research"


class ToolQuality(StrEnum):
    VALID = "valid"
    PARTIAL = "partial"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"


class ToolResultStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"


class ToolObservationStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    REJECTED = "rejected"
    FAILED = "failed"
    UNKNOWN = "unknown"


# 工具范围由服务端登记声明；网关只会用这些布尔项收紧请求，不能由模型扩展。
class ToolScope(AgentModel):
    symbol_bound: bool = True
    timeframes_bound: bool = True
    refresh_requires_current_mode: bool = False


# 服务端登记的工具描述；指纹由目录构造时从完整描述计算，模型不能自报版本或权限。
class RegisteredTool(AgentModel):
    name: str
    version: str
    description: str = Field(min_length=1, max_length=MAX_TOOL_DESCRIPTION_CHARS)
    input_schema: JsonObject
    output_schema: JsonObject
    capabilities: tuple[ToolCapability, ...] = Field(min_length=1)
    scope: ToolScope = Field(default_factory=ToolScope)
    timeout_seconds: int = Field(default=TOOL_TIMEOUT_SECONDS, ge=1, le=60)
    max_result_bytes: int = Field(default=MAX_TOOL_SUMMARY_BYTES, ge=1, le=MAX_TOOL_RESULT_BYTES)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if _TOOL_NAME.fullmatch(value) is None:
            raise ValueError("工具名称必须是稳定小写标识")
        return value

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if _TOOL_VERSION.fullmatch(value) is None:
            raise ValueError("工具版本必须是稳定短标识")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or _SAFE_DESCRIPTION.fullmatch(value) is None:
            raise ValueError("工具描述必须有界且不能包含控制字符")
        return normalized

    @field_validator("input_schema", "output_schema", mode="before")
    @classmethod
    def isolate_schema(cls, value: object) -> object:
        return copy.deepcopy(value)

    @field_validator("capabilities")
    @classmethod
    def validate_unique_capabilities(
        cls,
        value: tuple[ToolCapability, ...],
    ) -> tuple[ToolCapability, ...]:
        if len(set(value)) != len(value):
            raise ValueError("工具能力不能重复")
        # 本批只允许只读研究；未来新增能力必须显式实现守卫和拒绝回归。
        if set(value) != {ToolCapability.READ_ONLY_RESEARCH}:
            raise ValueError("首期只允许只读研究工具")
        return value

    @model_validator(mode="after")
    def validate_schemas(self) -> RegisteredTool:
        validate_tool_schema(self.input_schema)
        validate_tool_schema(self.output_schema)
        return self

    # 输入/输出 Schema 指纹是稳定公开元数据；目录摘要还会覆盖能力、范围和超时。
    @property
    def input_schema_sha256(self) -> str:
        return sha256_json(cast(JsonValue, self.input_schema))

    @property
    def output_schema_sha256(self) -> str:
        return sha256_json(cast(JsonValue, self.output_schema))

    # 目录条目用于构造模型可见版本和完整目录指纹；不包含处理函数或凭据。
    def catalog_entry(self) -> JsonObject:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "inputSchema": copy.deepcopy(self.input_schema),
            "outputSchemaSha256": self.output_schema_sha256,
            "capabilities": [item.value for item in self.capabilities],
            "scope": self.scope.model_dump(mode="json"),
            "timeoutSeconds": self.timeout_seconds,
            "maxResultBytes": self.max_result_bytes,
        }


# 模型提出的工具调用只包含名称、参数和供应商 call_id；版本/权限始终由服务端解析。
class ToolRequest(AgentModel):
    name: str
    arguments: JsonObject = Field(default_factory=dict)
    call_id: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if _TOOL_NAME.fullmatch(value) is None:
            raise ValueError("工具名称必须是稳定小写标识")
        return value

    @field_validator("call_id")
    @classmethod
    def validate_call_id(cls, value: str) -> str:
        if _CALL_ID.fullmatch(value) is None:
            raise ValueError("工具调用标识必须是稳定短标识")
        return value

    @field_validator("arguments", mode="before")
    @classmethod
    def isolate_arguments(cls, value: object) -> object:
        return copy.deepcopy(value)

    @model_validator(mode="after")
    def validate_arguments(self) -> ToolRequest:
        ensure_json_size(self.arguments, MAX_TOOL_ARGUMENT_BYTES, "工具参数")
        return self


# 处理器返回的安全结果；它只包含有界摘要、质量、原因和可选持久化引用。
class ToolResult(AgentModel):
    status: ToolResultStatus
    safe_summary: str
    quality: ToolQuality
    result_ref: ArtifactRef | None = None
    reason_code: str | None = None
    observed_at: UtcDateTime
    expires_at: UtcDateTime | None = None

    @field_validator("safe_summary")
    @classmethod
    def validate_safe_summary(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("工具摘要必须非空且不能包含 NUL")
        if len(normalized.encode("utf-8")) > MAX_TOOL_RESULT_BYTES:
            raise ValueError("工具结果超过 64 KiB 上限")
        return normalized

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _REASON_CODE.fullmatch(value) is None:
            raise ValueError("工具原因必须是稳定短码")
        return value

    @field_validator("observed_at", "expires_at")
    @classmethod
    def validate_times(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def validate_shape(self) -> ToolResult:
        if self.quality is ToolQuality.UNKNOWN:
            raise ValueError("已结算工具结果不能使用未知质量")
        if self.status is ToolResultStatus.DEGRADED and self.reason_code is None:
            raise ValueError("降级工具结果必须给出原因")
        if self.status is ToolResultStatus.OK and self.reason_code is not None:
            raise ValueError("正常工具结果不能夹带降级原因")
        if self.expires_at is not None and self.expires_at < self.observed_at:
            raise ValueError("工具结果到期时间不能早于观测时间")
        return self


# 网关返回给模型循环的观察；拒绝/失败也要带安全原因，成功才允许携带结果引用。
class ToolObservation(AgentModel):
    status: ToolObservationStatus
    tool_name: str
    tool_version: str
    tool_catalog_sha256: str
    call_id: str
    arguments_sha256: str
    step_id: UUID | None = None
    attempt_id: UUID | None = None
    result_ref: ArtifactRef | None = None
    safe_summary: str
    quality: ToolQuality
    reason_code: str | None = None
    observed_at: UtcDateTime
    expires_at: UtcDateTime | None = None
    sent: bool = False

    @field_validator("tool_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if _TOOL_NAME.fullmatch(value) is None:
            raise ValueError("工具名称必须是稳定小写标识")
        return value

    @field_validator("tool_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if _MODEL_TOOL_VERSION.fullmatch(value) is None:
            raise ValueError("模型可见工具版本必须是稳定短标识")
        return value

    @field_validator("tool_catalog_sha256", "arguments_sha256")
    @classmethod
    def validate_sha(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("工具目录/参数指纹必须是 64 位小写十六进制")
        return value

    @field_validator("call_id")
    @classmethod
    def validate_call_id(cls, value: str) -> str:
        if _CALL_ID.fullmatch(value) is None:
            raise ValueError("工具调用标识必须是稳定短标识")
        return value

    @field_validator("safe_summary")
    @classmethod
    def validate_safe_summary(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("工具观察摘要必须非空且不能包含 NUL")
        if len(normalized.encode("utf-8")) > MAX_TOOL_SUMMARY_BYTES:
            raise ValueError("工具观察摘要超过 8 KiB 上限")
        return normalized

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _REASON_CODE.fullmatch(value) is None:
            raise ValueError("工具原因必须是稳定短码")
        return value

    @field_validator("observed_at", "expires_at")
    @classmethod
    def validate_times(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def validate_shape(self) -> ToolObservation:
        if (self.step_id is None) != (self.attempt_id is None):
            raise ValueError("工具步骤与尝试标识必须同时存在或同时为空")
        if self.sent and self.attempt_id is None:
            raise ValueError("已发送观察必须有尝试标识")
        if self.expires_at is not None and self.expires_at < self.observed_at:
            raise ValueError("工具观察到期时间不能早于观测时间")
        succeeded = self.status in {
            ToolObservationStatus.OK,
            ToolObservationStatus.DEGRADED,
        }
        if succeeded:
            if self.result_ref is None:
                raise ValueError("成功/降级观察必须有结果引用")
            if self.quality is ToolQuality.UNKNOWN:
                raise ValueError("已结算观察不能使用未知质量")
        else:
            if self.result_ref is not None:
                raise ValueError("未成功观察不能携带结果引用")
            if self.reason_code is None:
                raise ValueError("拒绝/失败/未知观察必须给出原因")
        if self.status is ToolObservationStatus.OK and self.reason_code is not None:
            raise ValueError("正常观察不能夹带降级原因")
        return self


# 处理器协议；网关在预算预留和发送提交后调用它，处理器不得自行扩大范围或改预算。
class ToolHandler(Protocol):
    tool: RegisteredTool

    async def handle(
        self,
        context: ExecutionContext,
        snapshot: RunSnapshot,
        arguments: JsonObject,
        *,
        sent_at: datetime,
    ) -> ToolResult: ...


# 工具结果 Schema 固定同一安全投影形状；各工具可再声明更窄的上限。
_TOOL_RESULT_PROPERTIES: JsonObject = {
    "status": {"type": "string", "enum": ["ok", "degraded"]},
    "safe_summary": {"type": "string", "minLength": 1, "maxLength": MAX_TOOL_SUMMARY_BYTES},
    "quality": {
        "type": "string",
        "enum": ["valid", "partial", "stale", "missing"],
    },
    "result_ref": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "artifact_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "sha256": {"type": "string", "minLength": 64, "maxLength": 64},
        },
        "required": ["artifact_id", "sha256"],
    },
    "reason_code": {"type": "string", "minLength": 1, "maxLength": 64},
    "observed_at": {"type": "string", "minLength": 1, "maxLength": 64},
    "expires_at": {"type": "string", "minLength": 1, "maxLength": 64},
}
TOOL_RESULT_SCHEMA: JsonObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": copy.deepcopy(_TOOL_RESULT_PROPERTIES),
    "required": ["status", "safe_summary", "quality", "observed_at"],
}


# 校验目录 Schema 的受限子集；拒绝远端引用、正则、任意表达式、未知关键字和超深嵌套。
def validate_tool_schema(schema: JsonObject) -> None:
    if schema.get("type") != "object":
        raise ToolSchemaError("工具 Schema 根节点必须是 object")
    _validate_schema_node(schema, depth=0, counter=[0])


def _validate_schema_node(node: JsonObject, *, depth: int, counter: list[int]) -> None:
    if depth > _SCHEMA_DEPTH_LIMIT:
        raise ToolSchemaError("工具 Schema 嵌套过深")
    counter[0] += 1
    if counter[0] > _SCHEMA_NODE_LIMIT:
        raise ToolSchemaError("工具 Schema 节点过多")
    node_type = node.get("type")
    if not isinstance(node_type, str) or node_type not in _SCHEMA_TYPES:
        raise ToolSchemaError("工具 Schema 类型不受支持")
    allowed = _COMMON_SCHEMA_KEYS | _allowed_keys(node_type)
    if set(node) - allowed:
        raise ToolSchemaError("工具 Schema 包含不支持的关键字")
    description = node.get("description")
    if description is not None and (not isinstance(description, str) or len(description) > 500):
        raise ToolSchemaError("工具 Schema 说明必须是有界文本")

    if node_type == "object":
        properties = node.get("properties")
        if not isinstance(properties, dict):
            raise ToolSchemaError("object 必须声明 properties")
        if len(properties) > _SCHEMA_PROPERTY_LIMIT:
            raise ToolSchemaError("object 属性过多")
        if node.get("additionalProperties") is not False:
            raise ToolSchemaError("object 必须显式禁止额外字段")
        for name, child in properties.items():
            if _PROPERTY_NAME.fullmatch(name) is None or not isinstance(child, dict):
                raise ToolSchemaError("object 属性名或子 Schema 无效")
            _validate_schema_node(child, depth=depth + 1, counter=counter)
        required = node.get("required", [])
        if (
            not isinstance(required, list)
            or any(not isinstance(item, str) for item in required)
            or len(set(required)) != len(required)
            or not set(required) <= set(properties)
        ):
            raise ToolSchemaError("required 必须唯一且指向已声明属性")
    elif node_type == "array":
        items = node.get("items")
        if not isinstance(items, dict):
            raise ToolSchemaError("array 必须声明 items")
        minimum = node.get("minItems", 0)
        maximum = node.get("maxItems", _SCHEMA_ARRAY_LIMIT)
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or not 0 <= minimum <= maximum <= _SCHEMA_ARRAY_LIMIT
        ):
            raise ToolSchemaError("array 长度范围无效")
        _validate_schema_node(items, depth=depth + 1, counter=counter)
    elif node_type == "string":
        minimum = node.get("minLength", 0)
        maximum = node.get("maxLength", 1024)
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or not 0 <= minimum <= maximum <= _SCHEMA_STRING_LIMIT
        ):
            raise ToolSchemaError("string 长度范围无效")
        enum = node.get("enum")
        if enum is not None:
            if (
                not isinstance(enum, list)
                or not enum
                or len(enum) > 50
                or any(not isinstance(item, str) or len(item) > 1024 for item in enum)
                or len(set(enum)) != len(enum)
            ):
                raise ToolSchemaError("string 枚举无效")
    elif node_type == "integer":
        minimum = node.get("minimum")
        maximum = node.get("maximum")
        for value in (minimum, maximum):
            if value is not None and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or abs(value) > _SCHEMA_INTEGER_LIMIT
            ):
                raise ToolSchemaError("integer 边界必须是有界整数")
        if (
            isinstance(minimum, int)
            and not isinstance(minimum, bool)
            and isinstance(maximum, int)
            and not isinstance(maximum, bool)
            and minimum > maximum
        ):
            raise ToolSchemaError("integer 最小值不能大于最大值")
        enum = node.get("enum")
        if enum is not None:
            if (
                not isinstance(enum, list)
                or not enum
                or len(enum) > 50
                or any(
                    not isinstance(item, int)
                    or isinstance(item, bool)
                    or abs(item) > _SCHEMA_INTEGER_LIMIT
                    for item in enum
                )
                or len(set(enum)) != len(enum)
            ):
                raise ToolSchemaError("integer 枚举无效")
    else:
        enum = node.get("enum")
        if enum is not None:
            if (
                not isinstance(enum, list)
                or not enum
                or len(enum) > 2
                or any(not isinstance(item, bool) for item in enum)
                or len(set(enum)) != len(enum)
            ):
                raise ToolSchemaError("boolean 枚举无效")


def _allowed_keys(node_type: str) -> frozenset[str]:
    if node_type == "object":
        return frozenset({"properties", "required", "additionalProperties"})
    if node_type == "array":
        return frozenset({"items", "minItems", "maxItems"})
    if node_type == "string":
        return frozenset({"minLength", "maxLength", "enum"})
    if node_type == "integer":
        return frozenset({"minimum", "maximum", "enum"})
    return frozenset({"enum"})


# 校验并规范化工具参数；返回深拷贝，调用方后续修改原对象不能影响已预留的输入指纹。
def validate_tool_arguments(schema: JsonObject, arguments: JsonObject) -> JsonObject:
    validate_tool_schema(schema)
    ensure_json_size(arguments, MAX_TOOL_ARGUMENT_BYTES, "工具参数")
    normalized = _validate_tool_value(schema, arguments, path="$")
    if not isinstance(normalized, dict):
        raise ToolArgumentsError("工具参数根节点必须是对象")
    return normalized


def validate_tool_result_payload(schema: JsonObject, payload: JsonObject) -> JsonObject:
    validate_tool_schema(schema)
    ensure_json_size(payload, MAX_TOOL_RESULT_BYTES, "工具结果")
    normalized = _validate_tool_value(schema, payload, path="$")
    if not isinstance(normalized, dict):
        raise ToolContractError("output_schema_mismatch", "工具结果根节点必须是对象")
    return normalized


# 递归校验值；错误只包含字段路径和类型，不回显用户参数或模型文本。
def _validate_tool_value(schema: JsonObject, value: JsonValue, *, path: str) -> JsonValue:
    node_type = schema.get("type")
    if node_type == "object":
        if not isinstance(value, dict):
            raise ToolArgumentsError(f"{path} 必须是对象")
        properties = schema.get("properties")
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise ToolSchemaError("object Schema 无效")
        if set(value) - set(properties):
            raise ToolArgumentsError(f"{path} 包含未声明字段")
        if set(required) - set(value):
            raise ToolArgumentsError(f"{path} 缺少必填字段")
        normalized: JsonObject = {}
        for key, item in value.items():
            child = properties[key]
            if not isinstance(child, dict):
                raise ToolSchemaError(f"{path}.{key} 子 Schema 无效")
            normalized[key] = _validate_tool_value(child, item, path=f"{path}.{key}")
        return normalized
    if node_type == "array":
        if not isinstance(value, list):
            raise ToolArgumentsError(f"{path} 必须是数组")
        minimum = schema.get("minItems", 0)
        maximum = schema.get("maxItems", _SCHEMA_ARRAY_LIMIT)
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or not minimum <= len(value) <= maximum
        ):
            raise ToolArgumentsError(f"{path} 数组长度超出范围")
        items = schema.get("items")
        if not isinstance(items, dict):
            raise ToolSchemaError(f"{path} items Schema 无效")
        return [
            _validate_tool_value(items, item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if node_type == "string":
        if not isinstance(value, str):
            raise ToolArgumentsError(f"{path} 必须是字符串")
        minimum = schema.get("minLength", 0)
        maximum = schema.get("maxLength", 1024)
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or not minimum <= len(value) <= maximum
        ):
            raise ToolArgumentsError(f"{path} 字符串长度超出范围")
        enum = schema.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise ToolArgumentsError(f"{path} 不在允许枚举内")
        return value
    if node_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ToolArgumentsError(f"{path} 必须是整数")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, int) and value < minimum:
            raise ToolArgumentsError(f"{path} 低于最小值")
        if isinstance(maximum, int) and value > maximum:
            raise ToolArgumentsError(f"{path} 超过最大值")
        enum = schema.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise ToolArgumentsError(f"{path} 不在允许枚举内")
        return value
    if node_type == "boolean":
        if not isinstance(value, bool):
            raise ToolArgumentsError(f"{path} 必须是布尔值")
        enum = schema.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise ToolArgumentsError(f"{path} 不在允许枚举内")
        return value
    raise ToolSchemaError(f"{path} 的类型不受支持")


# 计算稳定 UTF-8 JSON 大小并拒绝非 JSON 安全值；大小上限防止无界工具输入/结果。
def ensure_json_size(value: JsonValue | JsonObject, max_bytes: int, label: str) -> None:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ToolArgumentsError(f"{label} 必须是 JSON 安全值") from error
    if len(encoded) > max_bytes:
        raise ToolArgumentsError(f"{label} 超过大小上限")


__all__ = [
    "MAX_TOOL_ARGUMENT_BYTES",
    "MAX_TOOL_DESCRIPTION_CHARS",
    "MAX_TOOL_RESULT_BYTES",
    "MAX_TOOL_SUMMARY_BYTES",
    "TOOL_ACTION_SEQUENCE_BASE",
    "TOOL_RESULT_SCHEMA",
    "TOOL_TIMEOUT_SECONDS",
    "JsonObject",
    "RegisteredTool",
    "ToolArgumentsError",
    "ToolCapability",
    "ToolContractError",
    "ToolHandler",
    "ToolObservation",
    "ToolObservationStatus",
    "ToolQuality",
    "ToolRequest",
    "ToolResult",
    "ToolResultStatus",
    "ToolSchemaError",
    "ToolScope",
    "ensure_json_size",
    "validate_tool_arguments",
    "validate_tool_result_payload",
    "validate_tool_schema",
]
