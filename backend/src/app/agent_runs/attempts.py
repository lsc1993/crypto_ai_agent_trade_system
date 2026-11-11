# 定义 C5 逐步尝试账本的纯契约：逻辑步骤标识、模型/工具/传输预留、状态机与结算结果。
# 调用方必须在实际发送前经账本预留并取得 attempt_id；发送后由账本记录内外部回执。
# 本模块不访问数据库、网络、模型或工具，不知道账户、资金或交易执行。
from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, field_validator, model_validator

from app.agent_runs.segments import RunFence
from app.shared.agent_types import (
    AgentModel,
    ArtifactRef,
    UtcDateTime,
    is_sha256,
    require_utc,
)

# 单次模型输入/输出与超时的固定上限；追加授权只放大累计额度，不能放大这些逐次边界。
MAX_INPUT_TOKENS_PER_CALL = 16_384
MAX_OUTPUT_TOKENS_PER_CALL = 4_096
MODEL_TIMEOUT_SECONDS = 60
# 同一逻辑步骤最多两次已知可重试尝试；第三次必须重新评估而不是无限重试。
MAX_ATTEMPTS_PER_STEP = 2

_REASON_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_RECEIPT_PATTERN = re.compile(r"[\x20-\x7e\u0080-\uffff]{1,256}\Z")


# 尝试类别决定计数口径：模型消耗模型次数/Token，工具与传输只消耗各自请求次数。
class AttemptCategory(StrEnum):
    MODEL = "model"
    TOOL = "tool"
    TRANSPORT = "transport"


# 步骤状态至少为 prepared/in_flight/succeeded/failed/unknown；终态不由调用方任意扩展。
class AttemptStatus(StrEnum):
    PREPARED = "prepared"
    IN_FLIGHT = "in_flight"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


TERMINAL_ATTEMPT_STATUSES = frozenset({AttemptStatus.SUCCEEDED, AttemptStatus.FAILED})
# 已知已发送状态；failed 既可能是发送后失败，也可能是发送前校验失败，
# 因此外部快照必须用 sent_at 区分，不能只凭 failed 状态推断已经发送。
SENT_ATTEMPT_STATUSES = frozenset(
    {
        AttemptStatus.IN_FLIGHT,
        AttemptStatus.SUCCEEDED,
        AttemptStatus.UNKNOWN,
    }
)

# 合法状态迁移；unknown 只能被供应商可验证回执结算，不能被直接重新发送。
_ALLOWED_TRANSITIONS: dict[AttemptStatus, frozenset[AttemptStatus]] = {
    AttemptStatus.PREPARED: frozenset({AttemptStatus.IN_FLIGHT, AttemptStatus.FAILED}),
    AttemptStatus.IN_FLIGHT: frozenset(
        {AttemptStatus.SUCCEEDED, AttemptStatus.FAILED, AttemptStatus.UNKNOWN}
    ),
    AttemptStatus.UNKNOWN: frozenset({AttemptStatus.SUCCEEDED, AttemptStatus.FAILED}),
    AttemptStatus.SUCCEEDED: frozenset(),
    AttemptStatus.FAILED: frozenset(),
}


# 供应商已知用量；未知时使用 None，绝不能把缺失 usage 写成 0。
class TokenUsage(AgentModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


# 单次预留请求；逻辑步骤由 run/revision/动作序号/输入指纹/类别共同确定。
# 模型必须声明不超过单次上限的输入/输出预留和不超过 60 秒的超时。
class AttemptRequest(AgentModel):
    action_sequence: int = Field(ge=1)
    input_sha256: str
    category: AttemptCategory
    reserved_input_tokens: int = Field(default=0, ge=0)
    reserved_output_tokens: int = Field(default=0, ge=0)
    timeout_seconds: int | None = Field(default=None, ge=1)

    @field_validator("input_sha256")
    @classmethod
    def validate_input_sha256(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("尝试输入指纹必须是 64 位小写十六进制")
        return value

    @model_validator(mode="after")
    def validate_category_reservation(self) -> AttemptRequest:
        if self.category is AttemptCategory.MODEL:
            if not 1 <= self.reserved_input_tokens <= MAX_INPUT_TOKENS_PER_CALL:
                raise ValueError("模型输入预留必须在单次上限内")
            if not 1 <= self.reserved_output_tokens <= MAX_OUTPUT_TOKENS_PER_CALL:
                raise ValueError("模型输出预留必须在单次上限内")
            if self.timeout_seconds is None or self.timeout_seconds > MODEL_TIMEOUT_SECONDS:
                raise ValueError("模型尝试必须声明不超过 60 秒的超时")
        else:
            # 工具/传输不消费模型 Token，也不借用模型超时字段。
            if self.reserved_input_tokens or self.reserved_output_tokens:
                raise ValueError("工具/传输尝试不能预留模型 Token")
            if self.timeout_seconds is not None:
                raise ValueError("工具/传输超时由各自适配器守卫，不写入模型超时")
        return self


# 终态结果；成功必须引用已校验结果，失败/未知必须给出固定原因码。
# unknown 携带 usage 会把未证实调用当已知成本；解除 unknown 必须有可验证回执。
class AttemptResult(AgentModel):
    status: AttemptStatus
    result_ref: ArtifactRef | None = None
    usage: TokenUsage | None = None
    provider_receipt: str | None = None
    reason_code: str | None = None
    receipt_verified: bool = False

    @field_validator("status")
    @classmethod
    def validate_terminal_status(cls, value: AttemptStatus) -> AttemptStatus:
        if value not in {
            AttemptStatus.SUCCEEDED,
            AttemptStatus.FAILED,
            AttemptStatus.UNKNOWN,
        }:
            raise ValueError("结算状态只能是 succeeded/failed/unknown")
        return value

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _REASON_PATTERN.fullmatch(value) is None:
            raise ValueError("尝试原因必须是稳定短码")
        return value

    @field_validator("provider_receipt")
    @classmethod
    def validate_provider_receipt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if _RECEIPT_PATTERN.fullmatch(normalized) is None:
            raise ValueError("供应商回执标识必须有界且不含控制字符")
        return normalized

    @model_validator(mode="after")
    def validate_result_semantics(self) -> AttemptResult:
        if self.status is AttemptStatus.SUCCEEDED:
            if self.result_ref is None:
                raise ValueError("成功尝试必须引用已校验结果")
        else:
            if self.result_ref is not None:
                raise ValueError("失败/未知尝试不能携带成功结果引用")
            if self.reason_code is None:
                raise ValueError("失败/未知尝试必须给出原因码")
        if self.status is AttemptStatus.UNKNOWN:
            if self.usage is not None:
                raise ValueError("未知尝试不能携带已结算用量")
            if self.receipt_verified:
                raise ValueError("未知尝试不能声称已有可验证回执")
        if self.receipt_verified and self.provider_receipt is None:
            raise ValueError("已核验回执必须提供回执标识")
        return self


# 单个实际发送尝试的只读快照；result_ref/usage 来自不可变步骤与 meter 账本。
class StepAttempt(AgentModel):
    attempt_id: UUID
    step_id: UUID
    run_id: UUID
    revision: int = Field(ge=1)
    segment_id: UUID
    attempt_number: int = Field(ge=1, le=MAX_ATTEMPTS_PER_STEP)
    category: AttemptCategory
    action_sequence: int = Field(ge=1)
    input_sha256: str
    status: AttemptStatus
    reserved_input_tokens: int = Field(ge=0)
    reserved_output_tokens: int = Field(ge=0)
    result_ref: ArtifactRef | None = None
    usage: TokenUsage | None = None
    provider_receipt: str | None = None
    reason_code: str | None = None
    created_at: UtcDateTime
    sent_at: UtcDateTime | None = None
    settled_at: UtcDateTime | None = None

    @field_validator("input_sha256")
    @classmethod
    def validate_input_sha256(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("尝试输入指纹必须是 64 位小写十六进制")
        return value

    @field_validator("created_at", "sent_at", "settled_at")
    @classmethod
    def validate_times(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> StepAttempt:
        if self.category is not AttemptCategory.MODEL:
            if self.reserved_input_tokens or self.reserved_output_tokens:
                raise ValueError("工具/传输尝试不能携带模型 Token 预留")
            if self.usage is not None:
                raise ValueError("工具/传输尝试不能携带模型 Token 用量")
        if self.status is AttemptStatus.SUCCEEDED and self.result_ref is None:
            raise ValueError("成功尝试必须引用已校验结果")
        if self.status is not AttemptStatus.SUCCEEDED and self.result_ref is not None:
            raise ValueError("未成功尝试不能携带成功结果引用")
        if self.status is AttemptStatus.PREPARED and self.sent_at is not None:
            raise ValueError("未发送尝试不能有发送时刻")
        if self.status in SENT_ATTEMPT_STATUSES and self.sent_at is None:
            raise ValueError("已发送尝试必须有发送时刻")
        if self.status is AttemptStatus.FAILED and self.sent_at is None:
            # 发送前失败是明确“未发送”的终态，不能夹带供应商 usage 或回执。
            if self.usage is not None or self.provider_receipt is not None:
                raise ValueError("发送前失败不能携带供应商用量或回执")
        if self.status in TERMINAL_ATTEMPT_STATUSES | {AttemptStatus.UNKNOWN}:
            if self.settled_at is None:
                raise ValueError("终态尝试必须有结算时刻")
        elif self.settled_at is not None:
            raise ValueError("未终态尝试不能有结算时刻")
        return self


# 判断状态迁移是否合法；仓储在数据库锁内再次调用，纯测试也复用同一规则。
def attempt_transition_allowed(current: AttemptStatus, target: AttemptStatus) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


# 在发送前计算稳定逻辑步骤标识；片段变化不会改变步骤，重入不能生成第二个幂等键。
def logical_step_id(fence: RunFence, request: AttemptRequest) -> UUID:
    key = (
        f"agent-step:{fence.run_id}:{fence.revision}:{request.action_sequence}:"
        f"{request.input_sha256}:{request.category.value}"
    )
    return uuid5(NAMESPACE_URL, key)


__all__ = [
    "MAX_ATTEMPTS_PER_STEP",
    "MAX_INPUT_TOKENS_PER_CALL",
    "MAX_OUTPUT_TOKENS_PER_CALL",
    "MODEL_TIMEOUT_SECONDS",
    "SENT_ATTEMPT_STATUSES",
    "TERMINAL_ATTEMPT_STATUSES",
    "AttemptCategory",
    "AttemptRequest",
    "AttemptResult",
    "AttemptStatus",
    "StepAttempt",
    "TokenUsage",
    "attempt_transition_allowed",
    "logical_step_id",
]
