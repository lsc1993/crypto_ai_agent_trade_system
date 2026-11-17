# 定义 T11 有限 LangGraph 的轻量状态：只保存阶段、安全计数、结果类型和引用。
# 不把原始证据、工具全文、模型正文、隐藏思考或财务值写入图状态，避免 checkpoint 成为第二真相。
# 状态不携带权限或租约；真实围栏、预算和业务提交仍由 ExecutionContext/协调器持有。
from __future__ import annotations

import re
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.agent_runs.segments import SegmentOutcomeKind
from app.shared.agent_types import AgentModel, ArtifactRef

_SAFE_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


# 图当前阶段；DONE 表示已形成 SegmentOutcome，路由器据此结束本次片段。
class GraphPhase(StrEnum):
    PREPARE = "prepare"
    DECIDE = "decide"
    TOOLS = "tools"
    CONTROL = "control"
    FINALIZE = "finalize"
    DONE = "done"


# 可 checkpoint 的图状态；字段只用于路由、审计计数和提交引用，不含模型/工具原文。
class InteractiveGraphState(AgentModel):
    phase: GraphPhase = GraphPhase.PREPARE
    model_calls: int = Field(default=0, ge=0, le=64)
    tool_calls: int = Field(default=0, ge=0, le=256)
    applied_seq: int = Field(default=0, ge=0)
    outcome_kind: SegmentOutcomeKind | None = None
    safe_reason: str | None = None
    preparing_interaction_id: UUID | None = None
    artifact_refs: tuple[ArtifactRef, ...] = Field(default=(), max_length=32)

    @field_validator("safe_reason")
    @classmethod
    def validate_safe_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _SAFE_REASON.fullmatch(value) is None:
            raise ValueError("图安全原因必须是稳定短码")
        return value

    @field_validator("artifact_refs")
    @classmethod
    def validate_refs(cls, value: tuple[ArtifactRef, ...]) -> tuple[ArtifactRef, ...]:
        keys = tuple((str(item.artifact_id), item.sha256) for item in value)
        if len(set(keys)) != len(keys):
            raise ValueError("图产物引用不能重复")
        return value

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> InteractiveGraphState:
        waiting = self.outcome_kind in {
            SegmentOutcomeKind.WAIT_INPUT,
            SegmentOutcomeKind.WAIT_APPROVAL,
        }
        if waiting != (self.preparing_interaction_id is not None):
            raise ValueError("等待结果必须有 preparing 待办，其他结果不能携带")
        if self.outcome_kind is SegmentOutcomeKind.DEGRADED and self.safe_reason is None:
            raise ValueError("降级结果必须提供安全原因")
        if self.outcome_kind is None and (self.safe_reason or self.artifact_refs):
            raise ValueError("未形成结果前不能携带原因或产物引用")
        return self


__all__ = ["GraphPhase", "InteractiveGraphState"]
