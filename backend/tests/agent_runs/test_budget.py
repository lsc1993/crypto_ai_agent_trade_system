# 验证 C5 任务总预算：初始档、部署硬上限、追加授权单调性、活动时间安全余量与快照一致性。
# 这些测试是纯函数/契约测试，不连接数据库，不发起模型、工具或交易请求。
# 预算只约束 Agent 调用次数与 Token/时间，不增加或改变交易资金与风险额度。
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.agent_runs.budget import (
    ACTIVITY_SAFETY_MARGIN_SECONDS,
    HARD_ACTIVE_SECONDS,
    HARD_CUMULATIVE_INPUT_TOKENS,
    HARD_CUMULATIVE_OUTPUT_TOKENS,
    HARD_MODEL_CALLS,
    HARD_TOOL_CALLS,
    HARD_TRANSPORT_CALLS,
    INITIAL_ACTIVE_SECONDS,
    INITIAL_CUMULATIVE_INPUT_TOKENS,
    INITIAL_CUMULATIVE_OUTPUT_TOKENS,
    INITIAL_MODEL_CALLS,
    INITIAL_TOOL_CALLS,
    INITIAL_TRANSPORT_CALLS,
    MAX_INPUT_TOKENS_PER_CALL,
    MAX_OUTPUT_TOKENS_PER_CALL,
    MODEL_TIMEOUT_SECONDS,
    TOOL_CONCURRENCY,
    BudgetLimits,
    BudgetStatus,
    effective_budget_limits,
    hard_budget_limits,
    initial_budget_limits,
    validate_activity_start,
    validate_append_limits,
)
from app.agent_runs.contracts import AgentRunError


# 构造默认初始上限；各测试按需覆盖单个维度，避免把未测维度误当作生产值。
def _limits(**overrides: Any) -> BudgetLimits:
    values: dict[str, Any] = {
        "model_calls": INITIAL_MODEL_CALLS,
        "tool_calls": INITIAL_TOOL_CALLS,
        "input_tokens": INITIAL_CUMULATIVE_INPUT_TOKENS,
        "output_tokens": INITIAL_CUMULATIVE_OUTPUT_TOKENS,
        "active_seconds": INITIAL_ACTIVE_SECONDS,
        "transport_calls": INITIAL_TRANSPORT_CALLS,
    }
    values.update(overrides)
    return BudgetLimits(**values)


# 构造预算状态；默认无消耗，只用于验证活动时间安全余量与水位一致性。
def _status(**overrides: Any) -> BudgetStatus:
    values: dict[str, Any] = {
        "model_limit": INITIAL_MODEL_CALLS,
        "tool_limit": INITIAL_TOOL_CALLS,
        "input_token_limit": INITIAL_CUMULATIVE_INPUT_TOKENS,
        "output_token_limit": INITIAL_CUMULATIVE_OUTPUT_TOKENS,
        "active_second_limit": INITIAL_ACTIVE_SECONDS,
        "transport_limit": INITIAL_TRANSPORT_CALLS,
        "model_calls": 0,
        "model_sent": 0,
        "tool_calls": 0,
        "tool_sent": 0,
        "transport_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "active_seconds": 0,
    }
    values.update(overrides)
    return BudgetStatus(**values)


def test_initial_and_hard_budget_limits_match_the_reviewed_contract() -> None:
    initial = initial_budget_limits()
    hard = hard_budget_limits()

    assert initial.model_calls == 8
    assert initial.tool_calls == 12
    assert initial.input_tokens == 98304
    assert initial.output_tokens == 32768
    assert initial.active_seconds == 600
    assert initial.transport_calls == 64

    assert hard.model_calls == 32
    assert hard.tool_calls == 48
    assert hard.input_tokens == 393216
    assert hard.output_tokens == 131072
    assert hard.active_seconds == 1800
    assert hard.transport_calls == 256

    # 单次与并发限制不在追加授权中放大；它们仍是固定的逐次守卫边界。
    assert MAX_INPUT_TOKENS_PER_CALL == 16384
    assert MAX_OUTPUT_TOKENS_PER_CALL == 4096
    assert MODEL_TIMEOUT_SECONDS == 60
    assert TOOL_CONCURRENCY == 1
    assert ACTIVITY_SAFETY_MARGIN_SECONDS == 15
    assert HARD_MODEL_CALLS == 32
    assert HARD_TOOL_CALLS == 48
    assert HARD_CUMULATIVE_INPUT_TOKENS == 393216
    assert HARD_CUMULATIVE_OUTPUT_TOKENS == 131072
    assert HARD_ACTIVE_SECONDS == 1800
    assert HARD_TRANSPORT_CALLS == 256


def test_append_authorization_is_monotonic_refuses_decrease_and_hard_limit_breach() -> None:
    current = initial_budget_limits()

    increased = _limits(model_calls=12, tool_calls=16)
    validate_append_limits(current, increased)

    with pytest.raises(AgentRunError) as decrease:
        validate_append_limits(current, _limits(model_calls=7))
    assert decrease.value.code == "invalid_budget_authorization"

    with pytest.raises(AgentRunError) as no_increase:
        validate_append_limits(current, current)
    assert no_increase.value.code == "invalid_budget_authorization"

    with pytest.raises(AgentRunError) as model_breach:
        validate_append_limits(current, _limits(model_calls=HARD_MODEL_CALLS + 1))
    assert model_breach.value.code == "invalid_budget_authorization"

    with pytest.raises(AgentRunError) as time_breach:
        validate_append_limits(current, _limits(active_seconds=HARD_ACTIVE_SECONDS + 1))
    assert time_breach.value.code == "invalid_budget_authorization"

    # 任一维度超出部署硬上限都必须整体拒绝，不能部分写入。
    with pytest.raises(AgentRunError):
        validate_append_limits(
            _limits(model_calls=20),
            _limits(model_calls=33, tool_calls=48, transport_calls=256),
        )


def test_effective_limits_take_monotonic_maximum_across_authorizations() -> None:
    initial = initial_budget_limits()
    # 追加授权是绝对值而非增量；有效上限取每个维度的最大值，避免后写覆盖前一次授权。
    first = _limits(model_calls=12, tool_calls=20)
    second = _limits(model_calls=16, active_seconds=900)

    effective = effective_budget_limits((initial, first, second))
    assert effective.model_calls == 16
    assert effective.tool_calls == 20
    assert effective.active_seconds == 900
    assert effective.input_tokens == INITIAL_CUMULATIVE_INPUT_TOKENS
    assert effective.transport_calls == INITIAL_TRANSPORT_CALLS
    assert effective_budget_limits(()) == initial


def test_activity_safety_margin_blocks_new_calls_at_the_boundary() -> None:
    # 584 秒后仍剩 16 秒，允许开始最后一个有界调用；585 秒后只剩 15 秒，必须停止新调用。
    validate_activity_start(_status(active_seconds=584))
    with pytest.raises(AgentRunError) as blocked:
        validate_activity_start(_status(active_seconds=585))
    assert blocked.value.code == "budget_exhausted"

    # 运行中追加活动时间只提高 Agent 预算上限，不触碰任何交易资金字段。
    validate_activity_start(
        _status(
            active_seconds=585,
            active_second_limit=HARD_ACTIVE_SECONDS,
        )
    )


def test_budget_status_rejects_impossible_watermarks_and_negative_values() -> None:
    status = _status(model_calls=2, model_sent=1)
    assert status.model_calls == 2

    with pytest.raises(ValidationError):
        _status(model_calls=1, model_sent=2)
    with pytest.raises(ValidationError):
        _status(model_calls=-1)
    with pytest.raises(ValidationError):
        _status(active_seconds=-1)
    # 有效上限必须至少覆盖已经发生的预留，否则状态本身就是不变量破坏。
    with pytest.raises(ValidationError):
        _status(model_limit=1, model_calls=2)
    with pytest.raises(ValidationError):
        _limits(model_calls=0)
