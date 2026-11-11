# 验证 C5 尝试契约：逻辑步骤标识、类别预留、状态迁移与终态结果语义。
# 这些测试不访问数据库或网络，证明调用方不能先发送再补步骤标识，也不能把未知结果伪装成功。
# 所有标识、指纹和用量均为合成值，不包含真实模型、账户或交易资料。
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agent_runs.attempts import (
    AttemptCategory,
    AttemptRequest,
    AttemptResult,
    AttemptStatus,
    StepAttempt,
    TokenUsage,
    attempt_transition_allowed,
    logical_step_id,
)
from app.agent_runs.segments import RunFence
from app.shared.agent_types import ArtifactRef


# 构造合法模型尝试；模型输入/输出预留必须在单次上限内并显式声明超时。
def _request(**overrides: Any) -> AttemptRequest:
    values: dict[str, Any] = {
        "action_sequence": 1,
        "input_sha256": "a" * 64,
        "category": AttemptCategory.MODEL,
        "reserved_input_tokens": 1024,
        "reserved_output_tokens": 512,
        "timeout_seconds": 60,
    }
    values.update(overrides)
    return AttemptRequest(**values)


# 合法围栏用于验证逻辑步骤在 run/revision 内稳定，跨片段不改变步骤身份。
def _fence(**overrides: Any) -> RunFence:
    values: dict[str, Any] = {
        "workspace_id": uuid4(),
        "run_id": uuid4(),
        "revision": 1,
        "segment_id": uuid4(),
        "owner": uuid4(),
        "lease_epoch": 1,
    }
    values.update(overrides)
    return RunFence(**values)


# 构造终态结果引用；成功步骤必须指向已持久化、可复用的校验结果。
def _result_ref() -> ArtifactRef:
    return ArtifactRef(artifact_id=uuid4(), sha256="f" * 64)


def test_logical_step_identity_is_stable_before_send_and_scoped_by_revision() -> None:
    fence = _fence()
    request = _request()

    first = logical_step_id(fence, request)
    # 同一片段内重入必须复用同一逻辑步骤，不能因重试生成第二个步骤。
    assert logical_step_id(fence, request) == first
    # 新片段（租约恢复）仍指向同一逻辑步骤，预算只在首次预留。
    assert logical_step_id(fence.model_copy(update={"segment_id": uuid4()}), request) == first
    # 不同修订、动作序号、输入指纹或类别是不同逻辑步骤，不能错误复用成功结果。
    assert logical_step_id(fence.model_copy(update={"revision": 2}), request) != first
    assert logical_step_id(fence, request.model_copy(update={"action_sequence": 2})) != first
    assert logical_step_id(fence, request.model_copy(update={"input_sha256": "b" * 64})) != first
    assert (
        logical_step_id(fence, request.model_copy(update={"category": AttemptCategory.TOOL}))
        != first
    )


def test_attempt_request_enforces_category_specific_reservations_and_timeout() -> None:
    model = _request()
    assert model.reserved_output_tokens == 512
    assert model.timeout_seconds == 60

    # 模型尝试必须预留输入/输出并受 60 秒单次超时约束。
    with pytest.raises(ValidationError):
        _request(reserved_input_tokens=0)
    with pytest.raises(ValidationError):
        _request(reserved_output_tokens=0)
    with pytest.raises(ValidationError):
        _request(reserved_input_tokens=16385)
    with pytest.raises(ValidationError):
        _request(reserved_output_tokens=4097)
    with pytest.raises(ValidationError):
        _request(timeout_seconds=None)
    with pytest.raises(ValidationError):
        _request(timeout_seconds=61)

    # 工具与传输不消费模型 Token，也不能借类别混入未登记令牌或模型超时。
    tool = AttemptRequest(
        action_sequence=2,
        input_sha256="c" * 64,
        category=AttemptCategory.TOOL,
    )
    assert tool.reserved_input_tokens == 0
    assert tool.reserved_output_tokens == 0
    with pytest.raises(ValidationError):
        AttemptRequest(
            action_sequence=2,
            input_sha256="c" * 64,
            category=AttemptCategory.TOOL,
            reserved_input_tokens=1,
        )
    with pytest.raises(ValidationError):
        AttemptRequest(
            action_sequence=3,
            input_sha256="d" * 64,
            category=AttemptCategory.TRANSPORT,
            timeout_seconds=10,
        )
    with pytest.raises(ValidationError):
        _request(input_sha256="not-a-sha")


def test_attempt_state_machine_allows_only_forward_recovery_transitions() -> None:
    assert attempt_transition_allowed(AttemptStatus.PREPARED, AttemptStatus.IN_FLIGHT)
    assert attempt_transition_allowed(AttemptStatus.PREPARED, AttemptStatus.FAILED)
    assert attempt_transition_allowed(AttemptStatus.IN_FLIGHT, AttemptStatus.SUCCEEDED)
    assert attempt_transition_allowed(AttemptStatus.IN_FLIGHT, AttemptStatus.FAILED)
    assert attempt_transition_allowed(AttemptStatus.IN_FLIGHT, AttemptStatus.UNKNOWN)
    # 未知尝试只允许被可验证回执结算，不能被直接重新发送。
    assert attempt_transition_allowed(AttemptStatus.UNKNOWN, AttemptStatus.SUCCEEDED)
    assert attempt_transition_allowed(AttemptStatus.UNKNOWN, AttemptStatus.FAILED)

    # 先发送后补步骤或重复成功都必须拒绝，防止绕过预算与幂等。
    assert not attempt_transition_allowed(AttemptStatus.PREPARED, AttemptStatus.SUCCEEDED)
    assert not attempt_transition_allowed(AttemptStatus.SUCCEEDED, AttemptStatus.IN_FLIGHT)
    assert not attempt_transition_allowed(AttemptStatus.FAILED, AttemptStatus.IN_FLIGHT)
    assert not attempt_transition_allowed(AttemptStatus.UNKNOWN, AttemptStatus.IN_FLIGHT)
    assert not attempt_transition_allowed(AttemptStatus.IN_FLIGHT, AttemptStatus.PREPARED)


def test_attempt_result_requires_validated_result_reason_and_unknown_usage_semantics() -> None:
    succeeded = AttemptResult(
        status=AttemptStatus.SUCCEEDED,
        result_ref=_result_ref(),
        usage=TokenUsage(input_tokens=800, output_tokens=120),
    )
    assert succeeded.usage is not None
    assert succeeded.usage.input_tokens == 800

    # 成功但缺少已校验结果引用时不能进入可复用账本。
    with pytest.raises(ValidationError):
        AttemptResult(status=AttemptStatus.SUCCEEDED)
    # 失败/未知必须给出固定原因码，不能只留下自由文本或空原因。
    with pytest.raises(ValidationError):
        AttemptResult(status=AttemptStatus.FAILED)
    with pytest.raises(ValidationError):
        AttemptResult(status=AttemptStatus.UNKNOWN)
    # 未知结果不能同时携带已结算用量，否则会把未证实调用当已知成本。
    with pytest.raises(ValidationError):
        AttemptResult(
            status=AttemptStatus.UNKNOWN,
            reason_code="provider_timeout",
            usage=TokenUsage(input_tokens=800, output_tokens=0),
        )
    # 声明已核验回执时必须提供可审计回执标识；否则不能解除未知。
    with pytest.raises(ValidationError):
        AttemptResult(
            status=AttemptStatus.SUCCEEDED,
            result_ref=_result_ref(),
            receipt_verified=True,
        )
    with pytest.raises(ValidationError):
        AttemptResult(
            status=AttemptStatus.SUCCEEDED,
            result_ref=_result_ref(),
            reason_code="自由原因",
        )

    reconciled = AttemptResult(
        status=AttemptStatus.FAILED,
        reason_code="provider_receipt_confirmed",
        provider_receipt="receipt-123",
        receipt_verified=True,
        usage=TokenUsage(input_tokens=800, output_tokens=0),
    )
    assert reconciled.receipt_verified is True
    assert reconciled.provider_receipt == "receipt-123"


def test_pre_send_failure_snapshot_allows_no_sent_at_and_no_usage() -> None:
    # prepared→failed 是发送前失败：不得伪造 sent_at，也不得携带供应商用量。
    attempt = StepAttempt(
        attempt_id=uuid4(),
        step_id=uuid4(),
        run_id=uuid4(),
        revision=1,
        segment_id=uuid4(),
        attempt_number=1,
        category=AttemptCategory.MODEL,
        action_sequence=1,
        input_sha256="a" * 64,
        status=AttemptStatus.FAILED,
        reserved_input_tokens=1024,
        reserved_output_tokens=512,
        result_ref=None,
        usage=None,
        provider_receipt=None,
        reason_code="cancelled_before_send",
        created_at=datetime(2026, 11, 11, 12, tzinfo=UTC),
        sent_at=None,
        settled_at=datetime(2026, 11, 11, 12, 1, tzinfo=UTC),
    )
    assert attempt.sent_at is None
    assert attempt.settled_at is not None

    # 发送前失败不能夹带供应商 usage 伪装成已发送/已计费调用。
    with pytest.raises(ValidationError):
        StepAttempt(
            attempt_id=uuid4(),
            step_id=uuid4(),
            run_id=uuid4(),
            revision=1,
            segment_id=uuid4(),
            attempt_number=1,
            category=AttemptCategory.MODEL,
            action_sequence=1,
            input_sha256="a" * 64,
            status=AttemptStatus.FAILED,
            reserved_input_tokens=1024,
            reserved_output_tokens=512,
            usage=TokenUsage(input_tokens=10, output_tokens=1),
            reason_code="cancelled_before_send",
            created_at=datetime(2026, 11, 11, 12, tzinfo=UTC),
            sent_at=None,
            settled_at=datetime(2026, 11, 11, 12, 1, tzinfo=UTC),
        )
