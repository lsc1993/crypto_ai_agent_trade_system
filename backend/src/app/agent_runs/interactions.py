# 定义 C5 人工审核契约：待办状态、材料指纹、类型化响应、反馈回执与幂等指纹。
# 本模块只描述“用户提交了什么审核决定”，不执行计划采纳、预算追加或交易操作。
# 响应回执固定为 recorded；是否应用、采纳和可实施由后续 worker/规划协调器原子判定。
from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from app.agent_runs.contracts import RunStatus
from app.agent_runs.decisions import ControlAction, ProposalDiff
from app.agent_runs.segments import RunFence
from app.shared.agent_types import (
    AgentModel,
    ArtifactRef,
    UtcDateTime,
    is_sha256,
    require_utc,
    sha256_json,
)

_SAFE_REASON_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_FIELD_PATTERN = r"^[a-z][a-z0-9_.]{0,63}$"

# 单个审核材料可列出的差异/引用上限，避免无界载荷进入本地审核记录。
MAX_INTERACTION_DIFFS = 16
MAX_INTERACTION_REFS = 32
MAX_INTERACTION_CHANGES = 16
MAX_INTERACTION_MESSAGE = 4_000
# 审核默认 24 小时；任务最长等待 7 天。T06 只固定绝对上限，具体有效期由调用方选择。
MAX_INTERACTION_LIFETIME_SECONDS = 7 * 24 * 60 * 60

# 只有这些动作可以形成人工待办；研究只读动作不应生成无意义确认。
_REVIEWABLE_ACTIONS = frozenset(
    {
        ControlAction.CLARIFY,
        ControlAction.ADOPT_MANUAL_PLAN,
        ControlAction.CHANGE_STRATEGY,
        ControlAction.CHANGE_PARAMETERS,
        ControlAction.EXPAND_SCOPE,
        ControlAction.INCREASE_BUDGET,
        ControlAction.ADOPT_REVISED_PLAN,
        ControlAction.ENABLE_MONITORING,
    }
)


# 待办状态；preparing 只在协调器事务内准备，pending 才可由用户响应。
class InteractionStatus(StrEnum):
    PREPARING = "preparing"
    PENDING = "pending"
    ANSWERED = "answered"
    APPLIED = "applied"
    EXPIRED = "expired"


# 用户响应类型；approve 只表示“已记录用户同意”，不等于计划已采纳。
class InteractionDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    PROVIDE_INPUT = "provide_input"


# 用户提出的结构化修改仍以不可变材料引用表达，不把自由金额/数量写入通用审核 JSON。
class InteractionChange(AgentModel):
    field: str = Field(pattern=_FIELD_PATTERN)
    before_ref: ArtifactRef | None = None
    after_ref: ArtifactRef

    @model_validator(mode="after")
    def validate_change(self) -> InteractionChange:
        if self.before_ref is not None and self.before_ref == self.after_ref:
            raise ValueError("修改前后的材料引用不能相同")
        return self


# 用户提交的审核响应；材料指纹和状态号共同绑定其实际审阅版本。
class InteractionResponse(AgentModel):
    request_id: UUID
    interaction_id: UUID
    expected_state_version: int = Field(ge=0)
    reviewed_payload_hash: str
    decision: InteractionDecision
    message: str | None = Field(default=None, max_length=MAX_INTERACTION_MESSAGE)
    changes: tuple[InteractionChange, ...] = Field(
        default=(),
        max_length=MAX_INTERACTION_CHANGES,
    )

    @model_validator(mode="after")
    def validate_response(self) -> InteractionResponse:
        if not is_sha256(self.reviewed_payload_hash):
            raise ValueError("已审阅材料指纹必须是 64 位小写十六进制")
        if self.message is not None and "\x00" in self.message:
            raise ValueError("审核补充文本不能包含 NUL 字符")
        fields = [item.field for item in self.changes]
        if len(set(fields)) != len(fields):
            raise ValueError("同一字段不能重复修改")
        if self.decision in {InteractionDecision.APPROVE, InteractionDecision.REJECT}:
            if self.changes:
                raise ValueError("同意或拒绝不能夹带修改项，请使用 request_changes")
        if self.decision in {
            InteractionDecision.REQUEST_CHANGES,
            InteractionDecision.PROVIDE_INPUT,
        }:
            has_text = self.message is not None and bool(self.message.strip())
            if not has_text and not self.changes:
                raise ValueError("请求修改或补充输入必须提供文本或类型化修改")
        return self


# 待办创建草稿；request_id 只用于准备阶段幂等，不进入材料指纹。
class InteractionDraft(AgentModel):
    request_id: UUID
    action: ControlAction
    material_hash: str
    expires_at: UtcDateTime
    diffs: tuple[ProposalDiff, ...] = Field(default=(), max_length=MAX_INTERACTION_DIFFS)
    material_refs: tuple[ArtifactRef, ...] = Field(
        default=(),
        max_length=MAX_INTERACTION_REFS,
    )
    safe_reason: str = Field(pattern=_SAFE_REASON_PATTERN)

    @model_validator(mode="after")
    def validate_draft(self) -> InteractionDraft:
        if not is_sha256(self.material_hash):
            raise ValueError("审核材料指纹必须是 64 位小写十六进制")
        if self.action not in _REVIEWABLE_ACTIONS:
            raise ValueError("该动作不能形成人工待办")
        require_utc(self.expires_at)
        fields = [item.field for item in self.diffs]
        if len(set(fields)) != len(fields):
            raise ValueError("同一字段不能在待办差异中重复")
        return self


# 待办快照；业务时间和材料指纹均不可变，状态与状态号由仓储 CAS 维护。
class HumanInteraction(AgentModel):
    interaction_id: UUID
    workspace_id: UUID
    run_id: UUID
    revision: int = Field(ge=1)
    action: ControlAction
    status: InteractionStatus
    material_hash: str
    state_version: int = Field(ge=0)
    expires_at: UtcDateTime
    diffs: tuple[ProposalDiff, ...] = Field(default=(), max_length=MAX_INTERACTION_DIFFS)
    material_refs: tuple[ArtifactRef, ...] = Field(
        default=(),
        max_length=MAX_INTERACTION_REFS,
    )
    safe_reason: str = Field(pattern=_SAFE_REASON_PATTERN)
    created_at: UtcDateTime
    published_at: UtcDateTime | None = None
    responded_at: UtcDateTime | None = None
    applied_at: UtcDateTime | None = None
    expired_at: UtcDateTime | None = None

    @property
    def can_respond(self) -> bool:
        # 只有已原子发布且仍待处理的项才可由用户响应；preparing 不能提前批准。
        return self.status is InteractionStatus.PENDING

    @model_validator(mode="after")
    def validate_state_shape(self) -> HumanInteraction:
        if not is_sha256(self.material_hash):
            raise ValueError("审核材料指纹必须是 64 位小写十六进制")
        if self.action not in _REVIEWABLE_ACTIONS:
            raise ValueError("该动作不能形成人工待办")
        for field in (
            "expires_at",
            "created_at",
            "published_at",
            "responded_at",
            "applied_at",
            "expired_at",
        ):
            value = getattr(self, field)
            if value is not None:
                require_utc(value)
        if self.expires_at <= self.created_at:
            raise ValueError("待办有效期必须晚于创建时间")

        if self.status is InteractionStatus.PREPARING:
            expected = (None, None, None, None)
        elif self.status is InteractionStatus.PENDING:
            expected = (self.published_at, None, None, None)
            if self.published_at is None:
                raise ValueError("待发布待办必须已有发布时间")
        elif self.status is InteractionStatus.ANSWERED:
            expected = (self.published_at, self.responded_at, None, None)
            if self.published_at is None or self.responded_at is None:
                raise ValueError("已响应待办必须已有发布和响应时间")
        elif self.status is InteractionStatus.APPLIED:
            expected = (self.published_at, self.responded_at, self.applied_at, None)
            if self.published_at is None or self.responded_at is None or self.applied_at is None:
                raise ValueError("已应用待办必须已有发布、响应和应用时间")
        else:
            expected = (self.published_at, self.responded_at, None, self.expired_at)
            if self.expired_at is None:
                raise ValueError("过期待办必须已有过期时间")
        if (self.published_at, self.responded_at, self.applied_at, self.expired_at) != expected:
            raise ValueError("待办状态与发布/响应/应用/过期时间不一致")
        return self


# 反馈回执；recorded 只证明审核决定已落库，后续 worker 仍需重验并应用。
class FeedbackReceipt(AgentModel):
    request_id: UUID
    interaction_id: UUID
    run_id: UUID
    decision: InteractionDecision
    receipt_state: Literal["recorded"] = "recorded"
    adoption_applied: Literal[False] = False
    run_status: RunStatus
    interaction_status: InteractionStatus
    state_version: int = Field(ge=0)
    recorded_at: UtcDateTime


# 准备阶段幂等指纹：绑定工作台/任务/修订与草稿内容，不包含 request_id。
def interaction_open_sha256(fence: RunFence, draft: InteractionDraft) -> str:
    payload = {
        "workspaceId": str(fence.workspace_id),
        "runId": str(fence.run_id),
        "revision": fence.revision,
        "draft": draft.model_dump(mode="json", exclude={"request_id"}),
    }
    return sha256_json(payload)  # type: ignore[arg-type]


# 响应幂等指纹：绑定任务与全部审核决定；同请求键不同决定必须冲突。
def interaction_response_sha256(run_id: UUID, response: InteractionResponse) -> str:
    payload = {
        "runId": str(run_id),
        "response": response.model_dump(mode="json", exclude={"request_id"}),
    }
    return sha256_json(payload)  # type: ignore[arg-type]


__all__ = [
    "MAX_INTERACTION_CHANGES",
    "MAX_INTERACTION_DIFFS",
    "MAX_INTERACTION_LIFETIME_SECONDS",
    "MAX_INTERACTION_MESSAGE",
    "MAX_INTERACTION_REFS",
    "FeedbackReceipt",
    "HumanInteraction",
    "InteractionChange",
    "InteractionDecision",
    "InteractionDraft",
    "InteractionResponse",
    "InteractionStatus",
    "interaction_open_sha256",
    "interaction_response_sha256",
]


# 交互仓储端口；SQL 实现在 infrastructure/persistence，服务层只依赖该协议。
class InteractionRepository(Protocol):
    async def prepare(self, fence: RunFence, draft: InteractionDraft) -> HumanInteraction: ...

    async def respond(
        self,
        workspace_id: UUID,
        run_id: UUID,
        response: InteractionResponse,
    ) -> FeedbackReceipt: ...

    async def list_interactions(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> tuple[HumanInteraction, ...]: ...

    async def expire_due(self, workspace_id: UUID, run_id: UUID) -> int: ...


# 交互应用服务只做委托；不在此执行模型、计划采纳、预算追加或交易操作。
class InteractionService:
    def __init__(self, repository: InteractionRepository) -> None:
        self._repository = repository

    async def prepare(self, fence: RunFence, draft: InteractionDraft) -> HumanInteraction:
        return await self._repository.prepare(fence, draft)

    async def respond(
        self,
        workspace_id: UUID,
        run_id: UUID,
        response: InteractionResponse,
    ) -> FeedbackReceipt:
        return await self._repository.respond(workspace_id, run_id, response)

    async def list_interactions(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> tuple[HumanInteraction, ...]:
        return await self._repository.list_interactions(workspace_id, run_id)

    async def expire_due(self, workspace_id: UUID, run_id: UUID) -> int:
        return await self._repository.expire_due(workspace_id, run_id)


__all__ += ["InteractionRepository", "InteractionService"]
