# 定义 C4 的片段执行纯类型：租约围栏、服务端执行上下文、片段结果、提交裁决与计划采纳提案。
# 这些类型只描述 worker/协调器之间的事实，不访问数据库、模型、工具、风险或交易执行。
# ExecutionContext 与 PlanAdoptionProposal 只能由服务端构造；前端/模型不能填充权限或财务字段。
from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.research.evidence import EvidenceEpoch
from app.shared.agent_types import (
    AgentModel,
    ArtifactRef,
    VersionRef,
    is_sha256,
)


# 片段结束原因；等待状态必须已有 preparing 待办，完成状态才可以携带计划采纳提案。
class SegmentOutcomeKind(StrEnum):
    WAIT_INPUT = "wait_input"
    WAIT_APPROVAL = "wait_approval"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 统一提交裁决不接受模型自报成功；冲突、失租和待处理消息都返回固定结果。
class CompletionDecisionKind(StrEnum):
    COMMITTED = "committed"
    CONFLICT = "conflict"
    LEASE_LOST = "lease_lost"
    MESSAGES_PENDING = "messages_pending"


# 稳定安全原因码；自由文本、异常消息或用户财务内容不能写入公共事件/裁决。
_SAFE_REASON_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_POLICY_VERSION_PATTERN = r"^[a-z0-9_]{1,64}$"


# 标识一次具体片段写入权限；owner 与 lease_epoch 必须来自服务端租约，model 不能覆盖。
class RunFence(AgentModel):
    workspace_id: UUID
    run_id: UUID
    revision: int = Field(ge=1)
    segment_id: UUID
    owner: UUID
    lease_epoch: int = Field(ge=0)

    # 围栏 UUID 是幂等和越权边界；全零 UUID 不是有效身份。
    @field_validator("workspace_id", "run_id", "segment_id", "owner")
    @classmethod
    def validate_identifiers(cls, value: UUID) -> UUID:
        if value.int == 0:
            raise ValueError("围栏标识不能是全零 UUID")
        return value


# 计划采纳提案只携带引用和材料指纹；T13 才由协调器核对并应用，不在此导入规划服务。
class PlanAdoptionProposal(AgentModel):
    plan_ref: ArtifactRef
    interaction_id: UUID
    material_hash: str
    pool_id: UUID
    pool_generation: int = Field(ge=1)

    @field_validator("material_hash")
    @classmethod
    def validate_material_hash(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("计划材料指纹必须是 64 位小写十六进制")
        return value


# 服务端构造的片段执行上下文；模型只能读取冻结版本，不能覆盖 fence、预算或证据。
# evidence_epoch 在 T08 证据冻结后才产生；T05/T07 允许为 None，表示尚未冻结。
class ExecutionContext(AgentModel):
    fence: RunFence
    strategy_ref: VersionRef
    tool_catalog_sha256: str
    policy_version: str
    budget_authorization_id: UUID
    evidence_epoch: EvidenceEpoch | None = None

    @field_validator("tool_catalog_sha256")
    @classmethod
    def validate_tool_catalog_sha256(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("工具目录指纹必须是 64 位小写十六进制")
        return value

    @field_validator("policy_version")
    @classmethod
    def validate_policy_version(cls, value: str) -> str:
        import re

        if re.fullmatch(_POLICY_VERSION_PATTERN, value) is None:
            raise ValueError("策略版本必须是稳定短标识")
        return value


# 单个执行片段的结果；wait_* 必须先有 preparing 待办，完成时才允许计划采纳提案。
class SegmentOutcome(AgentModel):
    kind: SegmentOutcomeKind
    artifact_refs: tuple[ArtifactRef, ...] = ()
    preparing_interaction_id: UUID | None = None
    safe_reason: str | None = None
    applied_message_seq: int = Field(default=0, ge=0)
    plan_proposal: PlanAdoptionProposal | None = None

    @field_validator("safe_reason")
    @classmethod
    def validate_safe_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        import re

        if re.fullmatch(_SAFE_REASON_PATTERN, value) is None:
            raise ValueError("安全原因必须是稳定短码")
        return value

    @model_validator(mode="after")
    def validate_outcome(self) -> SegmentOutcome:
        waiting = self.kind in {
            SegmentOutcomeKind.WAIT_INPUT,
            SegmentOutcomeKind.WAIT_APPROVAL,
        }
        if waiting != (self.preparing_interaction_id is not None):
            raise ValueError("等待片段必须有 preparing 待办，非等待片段不能携带")
        if self.plan_proposal is not None and self.kind is not SegmentOutcomeKind.COMPLETED:
            raise ValueError("只有完成片段可以携带计划采纳提案")
        return self


# 片段原子提交后的裁决；committed 必须带回已提交状态号，其余结果必须带安全原因。
class CompletionDecision(AgentModel):
    kind: CompletionDecisionKind
    state_version: int | None = Field(default=None, ge=0)
    safe_reason: str | None = None

    @field_validator("safe_reason")
    @classmethod
    def validate_safe_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        import re

        if re.fullmatch(_SAFE_REASON_PATTERN, value) is None:
            raise ValueError("安全原因必须是稳定短码")
        return value

    @model_validator(mode="after")
    def validate_decision(self) -> CompletionDecision:
        if self.kind is CompletionDecisionKind.COMMITTED:
            if self.state_version is None:
                raise ValueError("已提交裁决必须携带状态号")
            if self.safe_reason is not None:
                raise ValueError("已提交裁决不能伪造安全原因")
        else:
            if self.state_version is not None:
                raise ValueError("未提交裁决不能携带已提交状态号")
            if self.safe_reason is None:
                raise ValueError("未提交裁决必须携带安全原因")
        return self


__all__ = [
    "CompletionDecision",
    "CompletionDecisionKind",
    "ExecutionContext",
    "PlanAdoptionProposal",
    "RunFence",
    "SegmentOutcome",
    "SegmentOutcomeKind",
]
