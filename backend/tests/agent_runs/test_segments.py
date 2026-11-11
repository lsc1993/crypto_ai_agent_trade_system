# 验证 C4 纯类型：执行围栏、服务端执行上下文、片段结果、提交裁决与计划采纳提案。
# 这些类型不连接数据库、不调用模型或工具，只证明跨任务共享的字段约束和安全边界。
# 失败路径必须明确拒绝，不能用默认零值或空材料掩盖缺失的服务端身份。
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.agent_runs.segments import (
    CompletionDecision,
    CompletionDecisionKind,
    ExecutionContext,
    PlanAdoptionProposal,
    RunFence,
    SegmentOutcome,
    SegmentOutcomeKind,
)
from app.shared.agent_types import ArtifactRef, VersionRef


# 构造合法围栏；具体工作台/任务/片段标识使用合成 UUID，不涉及真实账户或资金。
def _fence(**overrides: Any) -> RunFence:
    values: dict[str, Any] = {
        "workspace_id": uuid4(),
        "run_id": uuid4(),
        "revision": 1,
        "segment_id": uuid4(),
        "owner": uuid4(),
        "lease_epoch": 3,
    }
    values.update(overrides)
    return RunFence(**values)


# 执行上下文由服务端装配；测试只提供安全版本引用，不构造任何权限扩展字段。
def _context(**overrides: Any) -> ExecutionContext:
    values: dict[str, Any] = {
        "fence": _fence(),
        "strategy_ref": VersionRef(version_id=uuid4(), sha256="a" * 64),
        "tool_catalog_sha256": "b" * 64,
        "policy_version": "interactive_planning_v1",
        "budget_authorization_id": uuid4(),
        "evidence_epoch": None,
    }
    values.update(overrides)
    return ExecutionContext(**values)


def test_run_fence_rejects_missing_server_identity_and_nonpositive_revision() -> None:
    # 围栏标识是租约写入的幂等键；零 UUID、非法修订或负代次不能被默认接受。
    fence = _fence()
    assert fence.revision == 1
    assert fence.lease_epoch == 3

    with pytest.raises(ValidationError):
        _fence(revision=0)
    with pytest.raises(ValidationError):
        _fence(lease_epoch=-1)
    with pytest.raises(ValidationError):
        _fence(owner=UUID(int=0))
    with pytest.raises(ValidationError):
        _fence(segment_id=UUID(int=0))


def test_execution_context_is_frozen_and_requires_bounded_server_versions() -> None:
    context = _context()
    # 模型和客户端不能修改已装配上下文；冻结模型会拒绝赋值。
    with pytest.raises(ValidationError):
        context.policy_version = "other"  # type: ignore[misc]

    with pytest.raises(ValidationError):
        _context(tool_catalog_sha256="not-a-sha")
    with pytest.raises(ValidationError):
        _context(policy_version="")
    with pytest.raises(ValidationError):
        _context(policy_version="x" * 65)
    with pytest.raises(ValidationError):
        _context(evidence_epoch="not-an-epoch")


def test_segment_outcome_requires_preparing_interaction_for_waiting_states() -> None:
    completed = SegmentOutcome(kind=SegmentOutcomeKind.COMPLETED)
    assert completed.preparing_interaction_id is None
    assert completed.artifact_refs == ()

    with pytest.raises(ValidationError):
        SegmentOutcome(kind=SegmentOutcomeKind.WAIT_INPUT)
    with pytest.raises(ValidationError):
        SegmentOutcome(kind=SegmentOutcomeKind.WAIT_APPROVAL)

    waiting = SegmentOutcome(
        kind=SegmentOutcomeKind.WAIT_APPROVAL,
        preparing_interaction_id=uuid4(),
        applied_message_seq=2,
    )
    assert waiting.preparing_interaction_id is not None
    assert waiting.applied_message_seq == 2

    with pytest.raises(ValidationError):
        SegmentOutcome(kind=SegmentOutcomeKind.FAILED, preparing_interaction_id=uuid4())


def test_segment_outcome_only_carries_plan_proposal_on_completion() -> None:
    proposal = PlanAdoptionProposal(
        plan_ref=ArtifactRef(artifact_id=uuid4(), sha256="c" * 64),
        interaction_id=uuid4(),
        material_hash="d" * 64,
        pool_id=uuid4(),
        pool_generation=1,
    )
    outcome = SegmentOutcome(kind=SegmentOutcomeKind.COMPLETED, plan_proposal=proposal)
    assert outcome.plan_proposal == proposal

    with pytest.raises(ValidationError):
        SegmentOutcome(kind=SegmentOutcomeKind.WAIT_INPUT, plan_proposal=proposal)
    with pytest.raises(ValidationError):
        SegmentOutcome(kind=SegmentOutcomeKind.CANCELLED, plan_proposal=proposal)

    with pytest.raises(ValidationError):
        PlanAdoptionProposal(
            plan_ref=proposal.plan_ref,
            interaction_id=proposal.interaction_id,
            material_hash="not-a-sha",
            pool_id=proposal.pool_id,
            pool_generation=1,
        )
    with pytest.raises(ValidationError):
        PlanAdoptionProposal(
            plan_ref=proposal.plan_ref,
            interaction_id=proposal.interaction_id,
            material_hash=proposal.material_hash,
            pool_id=proposal.pool_id,
            pool_generation=0,
        )


def test_completion_decision_requires_state_version_and_safe_reason_by_kind() -> None:
    committed = CompletionDecision(kind=CompletionDecisionKind.COMMITTED, state_version=4)
    assert committed.state_version == 4
    assert committed.safe_reason is None

    with pytest.raises(ValidationError):
        CompletionDecision(kind=CompletionDecisionKind.COMMITTED)
    with pytest.raises(ValidationError):
        CompletionDecision(
            kind=CompletionDecisionKind.CONFLICT,
            state_version=4,
            safe_reason="state_version_conflict",
        )
    with pytest.raises(ValidationError):
        CompletionDecision(kind=CompletionDecisionKind.LEASE_LOST)
    with pytest.raises(ValidationError):
        CompletionDecision(kind=CompletionDecisionKind.MESSAGES_PENDING)

    # 安全原因供审计与前端提示，必须是稳定短码而非自由异常文本。
    with pytest.raises(ValidationError):
        CompletionDecision(
            kind=CompletionDecisionKind.CONFLICT,
            safe_reason="包含 空格 与任意异常",
        )
