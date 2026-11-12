# 定义 T06 的受控决策分类：把模型/Agent 的类型化控制提案映射为自主、澄清、审核或拒绝。
# 该模块是纯函数边界，不访问数据库、模型、工具、账户或交易执行；模型不能在这里自批。
# 审核类型沿用需求 AP-01 至 AP-07；监控未实现时 AP-07 明确拒绝，不伪装为可用能力。
from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from app.agent_runs.segments import ExecutionContext
from app.shared.agent_types import AgentModel, ArtifactRef

_SAFE_REASON_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_FIELD_PATTERN = r"^[a-z][a-z0-9_.]{0,63}$"


# 控制提案动作类别；只包含研究 Agent 可提出的类型，不含任何真实下单或账户操作。
class ControlAction(StrEnum):
    READ_ONLY_RESEARCH = "read_only_research"
    CLARIFY = "clarify"
    ADOPT_MANUAL_PLAN = "adopt_manual_plan"
    CHANGE_STRATEGY = "change_strategy"
    CHANGE_PARAMETERS = "change_parameters"
    EXPAND_SCOPE = "expand_scope"
    INCREASE_BUDGET = "increase_budget"
    ADOPT_REVISED_PLAN = "adopt_revised_plan"
    ENABLE_MONITORING = "enable_monitoring"
    SELF_APPROVE = "self_approve"
    EXECUTE_TRADE = "execute_trade"
    ACCESS_PRIVATE_ACCOUNT = "access_private_account"


# 守卫裁决只允许四种结果；审核同意也不会自动启用禁止能力或绕过确定性校验。
class GuardAction(StrEnum):
    ALLOW = "allow"
    CLARIFY = "clarify"
    APPROVE = "approve"
    REJECT = "reject"


# 需求 AP-01 至 AP-07；AP-07 仅在可选监控实现后才可启用。
class ApprovalKind(StrEnum):
    AP_01 = "AP-01"
    AP_02 = "AP-02"
    AP_03 = "AP-03"
    AP_04 = "AP-04"
    AP_05 = "AP-05"
    AP_06 = "AP-06"
    AP_07 = "AP-07"


# 差异项只暴露字段路径与不可变材料引用；不在这里内嵌金额、数量或账户资料。
class ProposalDiff(AgentModel):
    field: str = Field(pattern=_FIELD_PATTERN)
    before_ref: ArtifactRef | None = None
    after_ref: ArtifactRef | None = None
    reason_code: str = Field(pattern=_SAFE_REASON_PATTERN)

    @model_validator(mode="after")
    def validate_refs(self) -> ProposalDiff:
        if self.before_ref is None and self.after_ref is None:
            raise ValueError("差异项至少需要一个材料引用")
        return self


# 模型或 Agent 提出的控制动作；材料引用和差异用于审核展示，不构成权限。
class ControlProposal(AgentModel):
    action: ControlAction
    diffs: tuple[ProposalDiff, ...] = Field(default=(), max_length=16)
    material_refs: tuple[ArtifactRef, ...] = Field(default=(), max_length=32)
    safe_reason: str = Field(pattern=_SAFE_REASON_PATTERN)

    @model_validator(mode="after")
    def validate_unique_diff_fields(self) -> ControlProposal:
        fields = [item.field for item in self.diffs]
        if len(set(fields)) != len(fields):
            raise ValueError("同一字段不能在提案差异中重复")
        return self


# 纯裁决结果；approve 必须带 AP 类型，其余结果不能夹带审批类型。
class GuardDecision(AgentModel):
    action: GuardAction
    reason_code: str = Field(pattern=_SAFE_REASON_PATTERN)
    approval: ApprovalKind | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> GuardDecision:
        if self.action is GuardAction.APPROVE:
            if self.approval is None:
                raise ValueError("审核动作必须携带 AP 类型")
        elif self.approval is not None:
            raise ValueError("非审核动作不能携带 AP 类型")
        return self


# 每个 AP 只映射到一种审核类型；新增动作必须显式登记，不能落入默认放行。
_APPROVAL_BY_ACTION: dict[ControlAction, ApprovalKind] = {
    ControlAction.ADOPT_MANUAL_PLAN: ApprovalKind.AP_01,
    ControlAction.CHANGE_STRATEGY: ApprovalKind.AP_02,
    ControlAction.CHANGE_PARAMETERS: ApprovalKind.AP_03,
    ControlAction.EXPAND_SCOPE: ApprovalKind.AP_04,
    ControlAction.INCREASE_BUDGET: ApprovalKind.AP_05,
    ControlAction.ADOPT_REVISED_PLAN: ApprovalKind.AP_06,
}

# 需要明确差异的变更动作；含糊“继续”没有类型化差异时必须回到澄清。
_DIFF_REQUIRED = frozenset(
    {
        ControlAction.CHANGE_STRATEGY,
        ControlAction.CHANGE_PARAMETERS,
        ControlAction.EXPAND_SCOPE,
        ControlAction.INCREASE_BUDGET,
        ControlAction.ADOPT_REVISED_PLAN,
    }
)

# 需要不可变审核材料的动作；没有材料不能进入“待审批”。
_MATERIAL_REQUIRED = frozenset(
    {
        ControlAction.ADOPT_MANUAL_PLAN,
        ControlAction.ADOPT_REVISED_PLAN,
    }
)

# 禁止动作的稳定原因码；拒绝不会授予任何替代权限。
_PROHIBITED = {
    ControlAction.SELF_APPROVE: "model_cannot_approve",
    ControlAction.EXECUTE_TRADE: "trade_execution_prohibited",
    ControlAction.ACCESS_PRIVATE_ACCOUNT: "private_account_prohibited",
}


# 纯决策策略；不读取数据库，也不把 context 当作客户端可覆盖的权限来源。
class DecisionPolicy:
    @staticmethod
    def classify(proposal: ControlProposal, context: ExecutionContext) -> GuardDecision:
        # context 由服务端构造；当前分类不依赖其财务值，只表明调用方已具备执行上下文。
        _ = context
        if proposal.action is ControlAction.READ_ONLY_RESEARCH:
            return GuardDecision(action=GuardAction.ALLOW, reason_code="autonomous_read")
        if proposal.action is ControlAction.CLARIFY:
            return GuardDecision(action=GuardAction.CLARIFY, reason_code="user_input_required")

        prohibited_reason = _PROHIBITED.get(proposal.action)
        if prohibited_reason is not None:
            return GuardDecision(action=GuardAction.REJECT, reason_code=prohibited_reason)
        if proposal.action is ControlAction.ENABLE_MONITORING:
            # 监控模块尚未交付；不能把 AP-07 分类成可审核并让用户误以为能启用。
            return GuardDecision(action=GuardAction.REJECT, reason_code="monitoring_unavailable")

        if proposal.action in _DIFF_REQUIRED and not proposal.diffs:
            return GuardDecision(
                action=GuardAction.CLARIFY,
                reason_code="typed_diff_required",
            )
        if proposal.action in _MATERIAL_REQUIRED and not proposal.material_refs:
            return GuardDecision(
                action=GuardAction.CLARIFY,
                reason_code="material_required",
            )

        approval = _APPROVAL_BY_ACTION.get(proposal.action)
        if approval is None:
            # 未知新动作 fail-closed，不能通过添加枚举值自动获得自主或审核权限。
            return GuardDecision(action=GuardAction.REJECT, reason_code="unsupported_action")
        return GuardDecision(
            action=GuardAction.APPROVE,
            reason_code="human_review_required",
            approval=approval,
        )


__all__ = [
    "ApprovalKind",
    "ControlAction",
    "ControlProposal",
    "DecisionPolicy",
    "GuardAction",
    "GuardDecision",
    "ProposalDiff",
]
