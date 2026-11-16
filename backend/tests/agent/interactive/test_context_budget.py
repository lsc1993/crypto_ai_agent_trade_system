# 验证 C5 上下文输入控长的保守估算：UTF-8 字节数加固定协议包络，不冒充真实 Token。
# 该口径用于没有可信供应商计数器时的预留；追加授权只放大累计额度，不能放大单次边界。
from __future__ import annotations

import pytest

from app.agent.interactive.context_budget import (
    CONSERVATIVE_PROTOCOL_ENVELOPE,
    MAX_INPUT_UNITS_PER_CALL,
    estimate_input,
)
from app.agent_runs.attempts import MAX_INPUT_TOKENS_PER_CALL


# 保守估算必须是纯函数：同一字节载荷得到相同结果，且显式包含协议/工具 Schema 包络。
def test_conservative_estimate_adds_fixed_protocol_envelope() -> None:
    payload = b'{"messages":[],"tools":[]}'

    assert estimate_input(payload) == len(payload) + CONSERVATIVE_PROTOCOL_ENVELOPE
    assert estimate_input(payload) == estimate_input(bytes(payload))


# UTF-8 多字节字符按真实字节数而不是 Python 字符数计算，避免中文上下文被低估。
def test_estimate_counts_utf8_bytes_not_characters() -> None:
    payload = "中文证据".encode()

    assert len(payload) > len("中文证据")
    assert estimate_input(payload) == len(payload) + 4096


# 单次上下文上限必须与 T05 模型尝试契约一致，不能在 T08 另造一个更宽窗口。
def test_single_call_ceiling_matches_attempt_contract() -> None:
    assert MAX_INPUT_UNITS_PER_CALL == MAX_INPUT_TOKENS_PER_CALL == 16_384


# 非 bytes 输入说明调用方没有先编码请求；直接拒绝而不是猜测文本编码或默默转换。
def test_rejects_non_bytes_payload() -> None:
    with pytest.raises(TypeError):
        estimate_input("already-text")  # type: ignore[arg-type]
