# 定义 C5 任务总预算的纯契约与准入规则：初始档、部署硬上限、追加授权和活动时间安全余量。
# 预算只约束模型/工具/传输调用与 Token、活动时间，不持有或改变交易资金、仓位或风险政策。
# 所有修订、片段和恢复共享同一 run 账本；追加授权只提高上限，不回写历史用量。
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from pydantic import Field, model_validator

from app.agent_runs.attempts import (
    AttemptCategory,
    AttemptRequest,
    AttemptResult,
    StepAttempt,
)
from app.agent_runs.contracts import AgentRunError
from app.agent_runs.segments import RunFence
from app.shared.agent_types import AgentModel

# 设计 §9.2 初始档；这些是保守初值，必须与审查通过的契约保持逐字一致。
INITIAL_MODEL_CALLS = 8
INITIAL_TOOL_CALLS = 12
INITIAL_CUMULATIVE_INPUT_TOKENS = 98_304
INITIAL_CUMULATIVE_OUTPUT_TOKENS = 32_768
INITIAL_ACTIVE_SECONDS = 600
INITIAL_TRANSPORT_CALLS = 64

# 部署侧硬上限；运行中的 AP-05 追加授权也不能突破，且与交易资金无关。
HARD_MODEL_CALLS = 32
HARD_TOOL_CALLS = 48
HARD_CUMULATIVE_INPUT_TOKENS = 393_216
HARD_CUMULATIVE_OUTPUT_TOKENS = 131_072
HARD_ACTIVE_SECONDS = 1800
HARD_TRANSPORT_CALLS = 256

# 单次模型边界仍由 attempts.py 固定；这里保留导入式常量用于预算契约核对。
MAX_INPUT_TOKENS_PER_CALL = 16_384
MAX_OUTPUT_TOKENS_PER_CALL = 4_096
MODEL_TIMEOUT_SECONDS = 60
# 首期工具串行；具体守卫在 T09 实现，预算模块只冻结口径。
TOOL_CONCURRENCY = 1
# 停止新调用时必须至少留下 15 秒用于保存与安全收尾。
ACTIVITY_SAFETY_MARGIN_SECONDS = 15


# 绝对预算上限；追加授权提供新的绝对值，有效上限取各授权逐维度最大值。
class BudgetLimits(AgentModel):
    model_calls: int = Field(ge=1)
    tool_calls: int = Field(ge=1)
    input_tokens: int = Field(ge=1)
    output_tokens: int = Field(ge=1)
    active_seconds: int = Field(ge=1)
    transport_calls: int = Field(ge=1)


# 预算快照：上限与已占用量分开；已占用包含实际结算值和未知调用的最坏预留。
# Token/活动时间允许如实超过上限（供应商回执或长时间运行），但新调用会被拒绝。
class BudgetStatus(AgentModel):
    model_limit: int = Field(ge=1)
    tool_limit: int = Field(ge=1)
    input_token_limit: int = Field(ge=1)
    output_token_limit: int = Field(ge=1)
    active_second_limit: int = Field(ge=1)
    transport_limit: int = Field(ge=1)
    model_calls: int = Field(ge=0)
    model_sent: int = Field(default=0, ge=0)
    tool_calls: int = Field(ge=0)
    tool_sent: int = Field(default=0, ge=0)
    transport_calls: int = Field(ge=0)
    transport_sent: int = Field(default=0, ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    active_seconds: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_watermarks(self) -> BudgetStatus:
        # 已发送不能超过已预留；调用次数也不能超过当前有效上限（次数在发送前检查）。
        if self.model_sent > self.model_calls:
            raise ValueError("模型已发送数不能超过已预留数")
        if self.tool_sent > self.tool_calls:
            raise ValueError("工具已发送数不能超过已预留数")
        if self.transport_sent > self.transport_calls:
            raise ValueError("传输已发送数不能超过已预留数")
        if self.model_calls > self.model_limit:
            raise ValueError("模型调用数不能超过有效上限")
        if self.tool_calls > self.tool_limit:
            raise ValueError("工具调用数不能超过有效上限")
        if self.transport_calls > self.transport_limit:
            raise ValueError("传输调用数不能超过有效上限")
        return self


# 预算账本端口；SQL 实现在 infrastructure/persistence，调用方不能绕过 fenced 事务。
# 除 C5 固定的 reserve/mark_sent/settle 外，T05 增加只读状态、活动时间与 AP-05 追加授权。
class BudgetLedger(Protocol):
    async def reserve(self, fence: RunFence, request: AttemptRequest) -> StepAttempt: ...

    async def mark_sent(self, fence: RunFence, attempt_id: UUID) -> None: ...

    async def settle(
        self,
        fence: RunFence,
        attempt_id: UUID,
        result: AttemptResult,
    ) -> None: ...

    async def status(self, fence: RunFence) -> BudgetStatus: ...

    async def record_activity(self, fence: RunFence, seconds: int) -> BudgetStatus: ...

    async def append_authorization(
        self,
        fence: RunFence,
        limits: BudgetLimits,
        *,
        authorization_ref: UUID,
        reason: str,
    ) -> BudgetStatus: ...


_INITIAL_LIMITS = BudgetLimits(
    model_calls=INITIAL_MODEL_CALLS,
    tool_calls=INITIAL_TOOL_CALLS,
    input_tokens=INITIAL_CUMULATIVE_INPUT_TOKENS,
    output_tokens=INITIAL_CUMULATIVE_OUTPUT_TOKENS,
    active_seconds=INITIAL_ACTIVE_SECONDS,
    transport_calls=INITIAL_TRANSPORT_CALLS,
)
_HARD_LIMITS = BudgetLimits(
    model_calls=HARD_MODEL_CALLS,
    tool_calls=HARD_TOOL_CALLS,
    input_tokens=HARD_CUMULATIVE_INPUT_TOKENS,
    output_tokens=HARD_CUMULATIVE_OUTPUT_TOKENS,
    active_seconds=HARD_ACTIVE_SECONDS,
    transport_calls=HARD_TRANSPORT_CALLS,
)
_LIMIT_FIELDS = (
    "model_calls",
    "tool_calls",
    "input_tokens",
    "output_tokens",
    "active_seconds",
    "transport_calls",
)


# 返回不可变初始档；调用方不能修改共享对象。
def initial_budget_limits() -> BudgetLimits:
    return _INITIAL_LIMITS


# 返回不可变部署硬上限；AP-05 只能在上限内追加。
def hard_budget_limits() -> BudgetLimits:
    return _HARD_LIMITS


# 计算多份追加授权的有效上限；空集合表示仍使用初始档。
def effective_budget_limits(limits: Iterable[BudgetLimits]) -> BudgetLimits:
    rows = tuple(limits)
    if not rows:
        return _INITIAL_LIMITS
    return BudgetLimits(
        **{field: max(getattr(row, field) for row in rows) for field in _LIMIT_FIELDS}
    )


# 校验 AP-05 追加授权：只能逐维度不减、至少一项增加且不超过部署硬上限。
def validate_append_limits(current: BudgetLimits, requested: BudgetLimits) -> None:
    hard = _HARD_LIMITS
    changed = False
    for field in _LIMIT_FIELDS:
        current_value = getattr(current, field)
        requested_value = getattr(requested, field)
        hard_value = getattr(hard, field)
        if requested_value < current_value or requested_value > hard_value:
            raise AgentRunError(
                "invalid_budget_authorization",
                f"预算追加维度 {field} 必须不减且不超过部署硬上限",
            )
        if requested_value > current_value:
            changed = True
    if not changed:
        raise AgentRunError(
            "invalid_budget_authorization",
            "预算追加必须至少提高一个维度",
        )


# 活动时间保留安全收尾余量；剩余不足 15 秒时停止开始任何新外部调用。
def validate_activity_start(status: BudgetStatus) -> None:
    if status.active_seconds + ACTIVITY_SAFETY_MARGIN_SECONDS >= status.active_second_limit:
        raise AgentRunError(
            "budget_exhausted",
            "活动时间不足安全收尾余量，停止新调用",
        )


# 发送前准入：prepared 的次数/Token 已计入当前累计，因此不再相加，只拒绝已越限的运行。
# 允许恰好等于上限（该次预留本来就属于上限内）；任一 Token 或活动时间越限即停止新发送。
def validate_send_fits(status: BudgetStatus) -> None:
    if status.input_tokens > status.input_token_limit:
        raise AgentRunError("budget_exhausted", "累计输入 Token 已超过有效上限")
    if status.output_tokens > status.output_token_limit:
        raise AgentRunError("budget_exhausted", "累计输出 Token 已超过有效上限")
    validate_activity_start(status)


# 预留准入：分类次数、累计 Token 与活动时间必须同时满足；返回 None，超限抛稳定错误。
def validate_reservation_fits(status: BudgetStatus, request: AttemptRequest) -> None:
    if request.category is AttemptCategory.MODEL:
        if status.model_calls + 1 > status.model_limit:
            raise AgentRunError("budget_exhausted", "模型调用次数超过有效上限")
        if status.input_tokens + request.reserved_input_tokens > status.input_token_limit:
            raise AgentRunError("budget_exhausted", "累计输入 Token 超过有效上限")
        if status.output_tokens + request.reserved_output_tokens > status.output_token_limit:
            raise AgentRunError("budget_exhausted", "累计输出 Token 超过有效上限")
    elif request.category is AttemptCategory.TOOL:
        if status.tool_calls + 1 > status.tool_limit:
            raise AgentRunError("budget_exhausted", "工具调用次数超过有效上限")
    else:
        if status.transport_calls + 1 > status.transport_limit:
            raise AgentRunError("budget_exhausted", "外部传输次数超过有效上限")
    validate_activity_start(status)


__all__ = [
    "ACTIVITY_SAFETY_MARGIN_SECONDS",
    "HARD_ACTIVE_SECONDS",
    "HARD_CUMULATIVE_INPUT_TOKENS",
    "HARD_CUMULATIVE_OUTPUT_TOKENS",
    "HARD_MODEL_CALLS",
    "HARD_TOOL_CALLS",
    "HARD_TRANSPORT_CALLS",
    "INITIAL_ACTIVE_SECONDS",
    "INITIAL_CUMULATIVE_INPUT_TOKENS",
    "INITIAL_CUMULATIVE_OUTPUT_TOKENS",
    "INITIAL_MODEL_CALLS",
    "INITIAL_TOOL_CALLS",
    "INITIAL_TRANSPORT_CALLS",
    "MAX_INPUT_TOKENS_PER_CALL",
    "MAX_OUTPUT_TOKENS_PER_CALL",
    "MODEL_TIMEOUT_SECONDS",
    "TOOL_CONCURRENCY",
    "BudgetLedger",
    "BudgetLimits",
    "BudgetStatus",
    "effective_budget_limits",
    "hard_budget_limits",
    "initial_budget_limits",
    "validate_activity_start",
    "validate_append_limits",
    "validate_reservation_fits",
    "validate_send_fits",
]
