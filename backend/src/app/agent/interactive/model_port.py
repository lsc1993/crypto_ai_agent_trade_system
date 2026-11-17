# 定义 C6 模型端口与最终分析的纯契约：模型只能提出工具批次、控制提案或最终分析。
# 本模块不访问模型、数据库或工具实现；GraphDependencies 通过 Protocol 注入，
# 最终产物只经 AnalysisArtifactStager 协议暂存，T11 不导入 T14 的报告/规划实现。
# 所有字段只含引用、定性文本、安全摘要和元数据，不内嵌金额、仓位、杠杆或账户资料。
from __future__ import annotations

import re
from typing import Protocol
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.agent.interactive.context import ModelContext
from app.agent.interactive.tools.contracts import ToolRequest
from app.agent_runs.attempts import TokenUsage
from app.agent_runs.decisions import ControlProposal
from app.agent_runs.segments import ExecutionContext
from app.shared.agent_types import AgentModel, ArtifactRef, is_sha256

# 稳定短码/标识边界；模型自由文本不能进入权限、文件路径或供应商字段。
_SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_SAFE_TARGET = re.compile(r"[a-z][a-z0-9_.:-]{0,63}\Z")
_FACT_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_CANDIDATE_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_MODEL_NAME = re.compile(r"[A-Za-z0-9._:/-]{1,128}\Z")
_RECEIPT = re.compile(r"[\x20-\x7e\u0080-\uffff]{1,256}\Z")
_FINISH_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


# 模型适配器可抛出的稳定错误；调用方按 code 结算失败/未知，并安全降级。
class ModelCallError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        usage: TokenUsage | None = None,
        provider_request_id: str | None = None,
        returned_model: str | None = None,
    ) -> None:
        super().__init__(message or code)
        if _SAFE_CODE.fullmatch(code) is None:
            raise ValueError("模型错误码必须是稳定短码")
        self.code = code
        self.usage = usage
        self.provider_request_id = provider_request_id
        self.returned_model = returned_model


# 产物暂存失败的安全错误；T14 的生产实现可抛此类型，T11 只依赖协议。
class AnalysisStagingError(RuntimeError):
    def __init__(self, code: str = "artifact_invalid", message: str | None = None) -> None:
        super().__init__(message or code)
        if _SAFE_CODE.fullmatch(code) is None:
            raise ValueError("产物错误码必须是稳定短码")
        self.code = code


# 单次模型调用的可审计元数据；只记录供应商返回的安全标识、用量与版本指纹。
# 不保存 Prompt 原文、隐藏思考、工具参数或任何财务值；trace 由注入的记录器决定持久化方式。
class ModelCallTrace(AgentModel):
    requested_model: str
    returned_model: str
    prompt_version: str
    schema_version: str
    prompt_sha256: str
    schema_sha256: str
    tool_catalog_sha256: str
    provider_request_id: str | None = None
    finish_reason: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)

    @field_validator("requested_model", "returned_model")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        if _MODEL_NAME.fullmatch(value) is None:
            raise ValueError("模型名称必须是稳定有界标识")
        return value

    @field_validator("prompt_sha256", "schema_sha256", "tool_catalog_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("模型 trace 指纹必须是 64 位小写十六进制")
        return value

    @field_validator("prompt_version", "schema_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9_-]{1,64}", value):
            raise ValueError("Prompt/Schema 版本必须是稳定短码")
        return value

    @field_validator("provider_request_id")
    @classmethod
    def validate_provider_request_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if _RECEIPT.fullmatch(normalized) is None:
            raise ValueError("供应商标识必须有界且不含控制字符")
        return normalized

    @field_validator("finish_reason")
    @classmethod
    def validate_finish_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _FINISH_REASON.fullmatch(value) is None:
            # 未知供应商原因不保存自由文本，避免把上游内容带入 trace。
            return None
        return value


# 事实引用只保留目标角色与事实标识；价格和数值必须由程序按引用渲染。
class ClaimFactRef(AgentModel):
    target: str
    fact_id: str

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        if _SAFE_TARGET.fullmatch(value) is None:
            raise ValueError("事实引用目标必须是稳定短标识")
        return value

    @field_validator("fact_id")
    @classmethod
    def validate_fact_id(cls, value: str) -> str:
        if _FACT_ID.fullmatch(value) is None:
            raise ValueError("事实标识必须是稳定有界标识")
        return value


# 定性分析块；数字只能通过事实引用绑定程序事实，不能由模型自由填写。
class ClaimBlock(AgentModel):
    text: str = Field(min_length=1, max_length=4_000)
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=32)
    fact_refs: tuple[ClaimFactRef, ...] = Field(default=(), max_length=16)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("分析块必须有非空文本且不能包含 NUL")
        return normalized

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("同一分析块的证据标识不能重复")
        if any(item.int == 0 for item in value):
            raise ValueError("证据标识不能是全零 UUID")
        return value

    @model_validator(mode="after")
    def validate_fact_refs(self) -> ClaimBlock:
        keys = tuple((item.target, item.fact_id) for item in self.fact_refs)
        if len(set(keys)) != len(keys):
            raise ValueError("同一分析块不能重复引用同一事实")
        return self


# 最终分析是模型提案，不是业务完成；计划引用和候选仍须由产物服务与规划服务复核。
class FinalAnalysis(AgentModel):
    market_blocks: tuple[ClaimBlock, ...] = Field(default=(), max_length=12)
    decision_blocks: tuple[ClaimBlock, ...] = Field(default=(), max_length=8)
    selected_candidate_id: str | None = Field(default=None, max_length=128)
    plan_ref: ArtifactRef | None = None
    no_plan_reasons: tuple[str, ...] = Field(default=(), max_length=8)
    limitations: tuple[str, ...] = Field(default=(), max_length=16)
    safe_summary: str = Field(min_length=1, max_length=2_000)
    usage: TokenUsage | None = None
    provider_request_id: str | None = None

    @field_validator("selected_candidate_id")
    @classmethod
    def validate_candidate_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _CANDIDATE_ID.fullmatch(value) is None:
            raise ValueError("候选标识必须是稳定有界标识")
        return value

    @field_validator("safe_summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("最终分析摘要必须有界且不能包含 NUL")
        return normalized

    @field_validator("no_plan_reasons", "limitations")
    @classmethod
    def validate_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("分析原因/限制不能重复")
        if any(_SAFE_CODE.fullmatch(item) is None for item in value):
            raise ValueError("分析原因/限制必须是稳定短码")
        return value

    @field_validator("provider_request_id")
    @classmethod
    def validate_provider_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if _RECEIPT.fullmatch(normalized) is None:
            raise ValueError("供应商标识必须有界且不含控制字符")
        return normalized

    @model_validator(mode="after")
    def validate_shape(self) -> FinalAnalysis:
        if self.plan_ref is not None:
            if self.selected_candidate_id is None:
                raise ValueError("携带计划引用时必须绑定候选标识")
            if self.no_plan_reasons:
                raise ValueError("有计划的最终分析不能同时声明无计划原因")
        elif not self.no_plan_reasons:
            raise ValueError("无计划的最终分析必须说明稳定原因")
        return self


# 工具批次是模型的原生请求，最多四个调用；网关仍会逐个校验名称、参数、范围和预算。
class ToolBatch(AgentModel):
    calls: tuple[ToolRequest, ...] = Field(min_length=1, max_length=4)
    safe_summary: str = Field(min_length=1, max_length=2_000)
    usage: TokenUsage | None = None
    provider_request_id: str | None = None

    @field_validator("safe_summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("工具批次摘要必须有界且不能包含 NUL")
        return normalized

    @field_validator("provider_request_id")
    @classmethod
    def validate_provider_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if _RECEIPT.fullmatch(normalized) is None:
            raise ValueError("供应商标识必须有界且不含控制字符")
        return normalized

    @model_validator(mode="after")
    def validate_calls(self) -> ToolBatch:
        call_ids = tuple(item.call_id for item in self.calls)
        if len(set(call_ids)) != len(call_ids):
            raise ValueError("同一批次的工具调用标识不能重复")
        return self


# 控制提案的薄包装：保留 T06 的 ControlProposal 类型，同时携带本次模型用量与供应商标识。
# 不把用量写入 ControlProposal，避免审核材料与模型费用元数据混成一个契约。
class ModelControlDecision(AgentModel):
    proposal: ControlProposal
    safe_summary: str | None = Field(default=None, max_length=2_000)
    usage: TokenUsage | None = None
    provider_request_id: str | None = None

    @field_validator("safe_summary")
    @classmethod
    def validate_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("控制提案摘要必须有界且不能包含 NUL")
        return normalized

    @field_validator("provider_request_id")
    @classmethod
    def validate_provider_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if _RECEIPT.fullmatch(normalized) is None:
            raise ValueError("供应商标识必须有界且不含控制字符")
        return normalized


# 模型端口的唯一输出联合；图只按这三种决策路由，不接受自由文本动作。
type ModelDecision = ToolBatch | ModelControlDecision | FinalAnalysis


# 模型端口：真实适配器必须发送工具 Schema 并返回上述类型；不可用/失败必须显式报错。
# estimate_request 使用与真实请求相同的编码计算保守输入预留，供 C5 账本在发送前预留。
class ModelPort(Protocol):
    @property
    def requested_model(self) -> str: ...

    @property
    def available(self) -> bool: ...

    def estimate_request(self, context: ModelContext) -> int: ...

    async def decide(self, context: ModelContext) -> ModelDecision: ...


# 最终分析产物暂存协议；T14 的 ArtifactService 才提供生产实现，T11 不导入报告实现。
class AnalysisArtifactStager(Protocol):
    async def validate_and_stage(
        self,
        context: ExecutionContext,
        analysis: FinalAnalysis,
    ) -> tuple[ArtifactRef, ...]: ...


__all__ = [
    "AnalysisArtifactStager",
    "AnalysisStagingError",
    "ClaimBlock",
    "ClaimFactRef",
    "FinalAnalysis",
    "ModelCallError",
    "ModelCallTrace",
    "ModelControlDecision",
    "ModelDecision",
    "ModelPort",
    "ToolBatch",
]
