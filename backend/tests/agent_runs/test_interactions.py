# 验证 T06 人工审核纯契约：AP 动作分类、类型化响应、待办状态形状与反馈回执。
# 本文件只使用合成 UUID/指纹/引用，不连接数据库、模型或账户，不包含真实资金资料。
# 断言重点是“模型只能提案、服务端决定审核类型、记录响应不等于已采纳计划”。
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agent_runs.contracts import RunStatus
from app.agent_runs.decisions import (
    ApprovalKind,
    ControlAction,
    ControlProposal,
    DecisionPolicy,
    GuardAction,
    ProposalDiff,
)
from app.agent_runs.interactions import (
    FeedbackReceipt,
    HumanInteraction,
    InteractionChange,
    InteractionDecision,
    InteractionDraft,
    InteractionResponse,
    InteractionStatus,
)
from app.agent_runs.segments import ExecutionContext, RunFence
from app.shared.agent_types import ArtifactRef, VersionRef

NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)


# 构造服务端执行上下文；测试不授予任何额外权限或真实证据。
def _context() -> ExecutionContext:
    return ExecutionContext(
        fence=RunFence(
            workspace_id=uuid4(),
            run_id=uuid4(),
            revision=1,
            segment_id=uuid4(),
            owner=uuid4(),
            lease_epoch=1,
        ),
        strategy_ref=VersionRef(version_id=uuid4(), sha256="a" * 64),
        tool_catalog_sha256="b" * 64,
        policy_version="interactive_planning_v1",
        budget_authorization_id=uuid4(),
        evidence_epoch=None,
    )


# 构造安全材料引用；真实金额、数量或账户信息不能进入审核材料引用。
def _artifact() -> ArtifactRef:
    return ArtifactRef(artifact_id=uuid4(), sha256="c" * 64)


# 构造动作差异；只保留字段路径和引用，不内嵌自由财务 JSON。
def _diff(field: str = "strategy_parameters") -> ProposalDiff:
    return ProposalDiff(
        field=field,
        before_ref=_artifact(),
        after_ref=_artifact(),
        reason_code="material_change",
    )


# 构造控制提案；默认带差异和材料，便于验证各类 AP 分类。
def _proposal(action: ControlAction, **overrides: Any) -> ControlProposal:
    values: dict[str, Any] = {
        "action": action,
        "diffs": (_diff(),),
        "material_refs": (_artifact(),),
        "safe_reason": "agent_requested_action",
    }
    values.update(overrides)
    return ControlProposal(**values)


def test_autonomous_read_is_allowed_while_every_ap_action_requires_review() -> None:
    # 只读研究在授权范围内自主执行，不需要逐次人工确认。
    allowed = DecisionPolicy.classify(
        _proposal(ControlAction.READ_ONLY_RESEARCH, diffs=(), material_refs=()),
        _context(),
    )
    assert allowed.action is GuardAction.ALLOW
    assert allowed.reason_code == "autonomous_read"
    assert allowed.approval is None

    # AP-01 至 AP-06 的提案必须返回审核，而不是直接放行或伪造已批准。
    expected = {
        ControlAction.ADOPT_MANUAL_PLAN: ApprovalKind.AP_01,
        ControlAction.CHANGE_STRATEGY: ApprovalKind.AP_02,
        ControlAction.CHANGE_PARAMETERS: ApprovalKind.AP_03,
        ControlAction.EXPAND_SCOPE: ApprovalKind.AP_04,
        ControlAction.INCREASE_BUDGET: ApprovalKind.AP_05,
        ControlAction.ADOPT_REVISED_PLAN: ApprovalKind.AP_06,
    }
    for action, approval in expected.items():
        decision = DecisionPolicy.classify(_proposal(action), _context())
        assert decision.action is GuardAction.APPROVE
        assert decision.approval is approval

    # AP-07 只在监控能力实现后才可用；当前必须明确拒绝而不是假装可启用。
    monitoring = DecisionPolicy.classify(
        _proposal(ControlAction.ENABLE_MONITORING),
        _context(),
    )
    assert monitoring.action is GuardAction.REJECT
    assert monitoring.reason_code == "monitoring_unavailable"

    # 澄清是交互而不是审批；模型不能借澄清绕过已选策略或权限。
    clarify = DecisionPolicy.classify(
        _proposal(ControlAction.CLARIFY, diffs=(), material_refs=()),
        _context(),
    )
    assert clarify.action is GuardAction.CLARIFY
    assert clarify.reason_code == "user_input_required"


def test_model_cannot_self_approve_or_escape_research_boundary() -> None:
    # 模型自批、真实下单和私有账户访问均被服务端拒绝，不因材料完整而放行。
    cases = {
        ControlAction.SELF_APPROVE: "model_cannot_approve",
        ControlAction.EXECUTE_TRADE: "trade_execution_prohibited",
        ControlAction.ACCESS_PRIVATE_ACCOUNT: "private_account_prohibited",
    }
    for action, reason in cases.items():
        decision = DecisionPolicy.classify(_proposal(action), _context())
        assert decision.action is GuardAction.REJECT
        assert decision.reason_code == reason
        assert decision.approval is None


def test_vague_continue_cannot_replace_a_typed_ap_diff() -> None:
    # 缺少类型化差异或材料时只能请求澄清；含糊文字不能升级预算、范围或策略。
    missing_diff = DecisionPolicy.classify(
        _proposal(ControlAction.INCREASE_BUDGET, diffs=()),
        _context(),
    )
    assert missing_diff.action is GuardAction.CLARIFY
    assert missing_diff.reason_code == "typed_diff_required"

    missing_material = DecisionPolicy.classify(
        _proposal(ControlAction.ADOPT_MANUAL_PLAN, material_refs=()),
        _context(),
    )
    assert missing_material.action is GuardAction.CLARIFY
    assert missing_material.reason_code == "material_required"

    # 差异至少需要一个引用；空对象不能冒充“已经展示前后变化”。
    with pytest.raises(ValidationError):
        ProposalDiff(field="budget", reason_code="increase")
    with pytest.raises(ValidationError):
        _proposal(ControlAction.INCREASE_BUDGET, diffs=(_diff(), _diff()))


def test_guard_decision_rejects_inconsistent_approval_shape() -> None:
    decision = DecisionPolicy.classify(_proposal(ControlAction.ADOPT_MANUAL_PLAN), _context())
    assert decision.approval is ApprovalKind.AP_01

    with pytest.raises(ValidationError):
        # 审批动作必须携带 AP 类型，不能只返回“approve”让调用方猜测。
        type(decision)(action=GuardAction.APPROVE, reason_code="missing_approval")
    with pytest.raises(ValidationError):
        # 拒绝/允许/澄清不能夹带审批类型，避免前端误认为已进入待审。
        type(decision)(
            action=GuardAction.REJECT,
            reason_code="not_allowed",
            approval=ApprovalKind.AP_01,
        )


def test_interaction_response_binds_version_material_and_typed_decision() -> None:
    interaction_id = uuid4()
    response = InteractionResponse(
        request_id=uuid4(),
        interaction_id=interaction_id,
        expected_state_version=0,
        reviewed_payload_hash="d" * 64,
        decision=InteractionDecision.APPROVE,
    )
    assert response.decision is InteractionDecision.APPROVE
    assert response.message is None
    assert response.changes == ()

    # 材料指纹必须是规范 SHA-256；用户不能提交任意字符串冒充“已审阅”。
    with pytest.raises(ValidationError):
        InteractionResponse(
            request_id=uuid4(),
            interaction_id=interaction_id,
            expected_state_version=0,
            reviewed_payload_hash="stale",
            decision=InteractionDecision.APPROVE,
        )

    # 审批动作不能夹带修改项；用户应明确选择 request_changes 后重新计算。
    with pytest.raises(ValidationError):
        InteractionResponse(
            request_id=uuid4(),
            interaction_id=interaction_id,
            expected_state_version=0,
            reviewed_payload_hash="d" * 64,
            decision=InteractionDecision.APPROVE,
            changes=(InteractionChange(field="policy", after_ref=_artifact()),),
        )

    # “继续”只是 provide_input 文本，不是审批；记录后 adoption_applied 仍为 False。
    vague = InteractionResponse(
        request_id=uuid4(),
        interaction_id=interaction_id,
        expected_state_version=0,
        reviewed_payload_hash="d" * 64,
        decision=InteractionDecision.PROVIDE_INPUT,
        message="继续",
    )
    assert vague.decision is InteractionDecision.PROVIDE_INPUT
    assert vague.decision is not InteractionDecision.APPROVE


def test_interaction_state_shape_preserves_preparing_and_pending_distinction() -> None:
    # preparing 尚未可响应，必须没有发布/响应时间；pending 才允许用户提交。
    interaction = HumanInteraction(
        interaction_id=uuid4(),
        workspace_id=uuid4(),
        run_id=uuid4(),
        revision=1,
        action=ControlAction.ADOPT_MANUAL_PLAN,
        status=InteractionStatus.PREPARING,
        material_hash="e" * 64,
        state_version=0,
        expires_at=NOW + timedelta(hours=1),
        diffs=(_diff(),),
        material_refs=(_artifact(),),
        safe_reason="awaiting_atomic_publish",
        created_at=NOW,
    )
    assert interaction.status is InteractionStatus.PREPARING
    assert interaction.can_respond is False

    pending = HumanInteraction.model_validate(
        {
            **interaction.model_dump(by_alias=False),
            "status": InteractionStatus.PENDING,
            "published_at": NOW,
        }
    )
    assert pending.can_respond is True

    # 状态时间必须与状态一致，不能用 preparing 冒充可响应的 pending。
    with pytest.raises(ValidationError):
        HumanInteraction.model_validate(
            {**pending.model_dump(by_alias=False), "published_at": None}
        )
    with pytest.raises(ValidationError):
        HumanInteraction.model_validate(
            {**interaction.model_dump(by_alias=False), "published_at": NOW}
        )
    with pytest.raises(ValidationError):
        HumanInteraction.model_validate({**pending.model_dump(by_alias=False), "responded_at": NOW})
    with pytest.raises(ValidationError):
        HumanInteraction.model_validate(
            {
                **interaction.model_dump(by_alias=False),
                "status": InteractionStatus.ANSWERED,
                "published_at": NOW,
            }
        )


def test_expired_interaction_cannot_fabricate_response_without_publication() -> None:
    # 过期可以发生在发布前，但不能出现“已响应却没有发布时间”的历史形状。
    draft = HumanInteraction(
        interaction_id=uuid4(),
        workspace_id=uuid4(),
        run_id=uuid4(),
        revision=1,
        action=ControlAction.ADOPT_MANUAL_PLAN,
        status=InteractionStatus.PREPARING,
        material_hash="e" * 64,
        state_version=0,
        expires_at=NOW + timedelta(hours=1),
        diffs=(_diff(),),
        material_refs=(_artifact(),),
        safe_reason="awaiting_atomic_publish",
        created_at=NOW,
    )
    pending = HumanInteraction.model_validate(
        {
            **draft.model_dump(by_alias=False),
            "status": InteractionStatus.PENDING,
            "published_at": NOW,
        }
    )
    answered = HumanInteraction.model_validate(
        {
            **pending.model_dump(by_alias=False),
            "status": InteractionStatus.ANSWERED,
            "responded_at": NOW,
        }
    )

    # 正常取消过期保留发布/响应事实。
    expired = HumanInteraction.model_validate(
        {
            **answered.model_dump(by_alias=False),
            "status": InteractionStatus.EXPIRED,
            "expired_at": NOW,
        }
    )
    assert expired.published_at == NOW
    assert expired.responded_at == NOW

    with pytest.raises(ValidationError):
        HumanInteraction.model_validate(
            {
                **answered.model_dump(by_alias=False),
                "status": InteractionStatus.EXPIRED,
                "expired_at": NOW,
                "published_at": None,
            }
        )


def test_feedback_and_message_receipts_do_not_claim_application() -> None:
    # 回执只证明“响应已记录”；计划采纳由 T13/协调器另行原子应用。
    receipt = FeedbackReceipt(
        request_id=uuid4(),
        interaction_id=uuid4(),
        run_id=uuid4(),
        decision=InteractionDecision.APPROVE,
        receipt_state="recorded",
        adoption_applied=False,
        run_status=RunStatus.WAITING_APPROVAL,
        interaction_status=InteractionStatus.ANSWERED,
        state_version=1,
        recorded_at=NOW,
    )
    assert receipt.receipt_state == "recorded"
    assert receipt.adoption_applied is False

    with pytest.raises(ValidationError):
        FeedbackReceipt.model_validate(
            {**receipt.model_dump(by_alias=False), "adoption_applied": True}
        )

    # 草稿构造只做本模块约束；真正落库由仓储核对有效期和单待办。
    draft = InteractionDraft(
        request_id=uuid4(),
        action=ControlAction.ADOPT_MANUAL_PLAN,
        material_hash="f" * 64,
        expires_at=NOW + timedelta(hours=1),
        diffs=(_diff(),),
        material_refs=(_artifact(),),
        safe_reason="plan_ready_for_review",
    )
    assert draft.action is ControlAction.ADOPT_MANUAL_PLAN
