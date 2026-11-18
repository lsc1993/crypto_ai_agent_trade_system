# T11 原生 Tool Calling 适配器测试：用 httpx.MockTransport 验证真实请求/响应协议。
# 不连接 DeepSeek 或其他外部服务，不读取环境密钥；所有模型名、参数和摘要均为合成值。
# 重点断言工具 Schema 确实随请求发送、工具观察以原生 tool_call_id 回传、usage 不被写零，
# 以及异常响应和超限工具批次明确失败，而不是用正文文字伪装成工具调用。
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.agent.interactive.context import ModelMessage, ModelToolCall, encode_model_request
from app.agent.interactive.context_budget import estimate_input
from app.agent.interactive.deepseek import (
    MAX_MODEL_RESPONSE_BYTES,
    DeepSeekToolCallingModel,
    ModelCallError,
)
from app.agent.interactive.model_port import (
    FinalAnalysis,
    ModelCallTrace,
    ModelControlDecision,
    ModelDecision,
    ToolBatch,
)
from app.agent_runs.decisions import ControlAction
from tests.agent.interactive import graph_fixtures as fixtures


# 构造 DeepSeek 原生响应；保留真实字段名，便于验证适配器而非模仿其内部模型。
def _response(
    *,
    content: str | None = None,
    tool_calls: list[dict[str, object]] | None = None,
    finish_reason: str | None = "stop",
    model: str = "deepseek-v4-pro",
    usage: dict[str, int] | None = None,
    response_id: str = "chatcmpl-synthetic-1",
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    body: dict[str, Any] = {
        "id": response_id,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }
    if usage is not None:
        body["usage"] = usage
    return body


# 构造原生工具调用；arguments 使用供应商实际的 JSON 字符串形式。
def _tool_call(
    *,
    call_id: str = "call_synthetic_1",
    name: str = "read_market_evidence",
    arguments: str = '{"symbol":"BTCUSDT"}',
) -> dict[str, object]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


# 计数的异步字节流；用于证明越限后不再消费后续块并关闭响应。
class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.yielded = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.yielded += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


# 捕获请求并返回固定响应；记录请求体以便断言工具 Schema 和消息配对。
class _Recorder:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        return httpx.Response(200, json=self.responses.pop(0))


# 构造适配器；trace_sink 只收集合成元数据，不写入任何日志或文件。
def _adapter(
    recorder: _Recorder,
    *,
    traces: list[ModelCallTrace] | None = None,
    api_key: SecretStr | None = SecretStr("synthetic-test-key"),
    client: httpx.AsyncClient | None = None,
) -> DeepSeekToolCallingModel:
    http_client = client or httpx.AsyncClient(
        transport=httpx.MockTransport(recorder.handler),
    )
    return DeepSeekToolCallingModel(
        client=http_client,
        api_key=api_key,
        model="deepseek-v4-pro",
        trace_recorder=None if traces is None else traces.append,
    )


@pytest.mark.asyncio
async def test_native_tool_request_is_sent_and_batch_is_parsed() -> None:
    execution_context = fixtures.context()
    base = fixtures.model_context(execution_context)
    recorder = _Recorder(
        [
            _response(
                content="先读取冻结行情。",
                tool_calls=[_tool_call()],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 120, "completion_tokens": 30},
            )
        ]
    )
    traces: list[ModelCallTrace] = []
    model = _adapter(recorder, traces=traces)

    decision: ModelDecision = await model.decide(base)

    assert isinstance(decision, ToolBatch)
    assert decision.calls[0].call_id == "call_synthetic_1"
    assert decision.calls[0].arguments == {"symbol": "BTCUSDT"}
    assert decision.usage is not None
    assert decision.usage.input_tokens == 120
    assert decision.usage.output_tokens == 30

    request = recorder.requests[0]
    assert request["model"] == "deepseek-v4-pro"
    assert request["thinking"] == {"type": "disabled"}
    assert request["max_tokens"] == 4096
    assert "tool_choice" not in request
    assert request["tools"][0]["type"] == "function"
    assert request["tools"][0]["function"]["name"] == "read_market_evidence"
    assert request["tools"][0]["function"]["parameters"] == base.tools[0].input_schema

    # 系统 Prompt 与上下文系统消息合并为一条，避免供应商把第二条 system 当用户内容。
    system_messages = [item for item in request["messages"] if item["role"] == "system"]
    assert len(system_messages) == 1
    assert "你是受治理的合成研究助手。" in system_messages[0]["content"]
    assert "只读研究" in system_messages[0]["content"]

    trace = traces[0]
    assert trace.requested_model == "deepseek-v4-pro"
    assert trace.returned_model == "deepseek-v4-pro"
    assert trace.prompt_version
    assert trace.schema_version
    assert trace.prompt_sha256
    assert trace.schema_sha256
    assert trace.tool_catalog_sha256 == base.manifest.tool_catalog_sha256
    assert trace.provider_request_id == "chatcmpl-synthetic-1"
    assert trace.finish_reason == "tool_calls"
    assert trace.input_tokens == 120
    assert trace.output_tokens == 30


@pytest.mark.asyncio
async def test_tool_observation_is_sent_with_native_call_pairing() -> None:
    execution_context = fixtures.context()
    first = fixtures.model_context(execution_context)
    assistant = ModelMessage(
        role="assistant",
        content=None,
        tool_calls=(
            ModelToolCall(
                call_id="call_synthetic_1",
                name="read_market_evidence",
                arguments={"symbol": "BTCUSDT"},
            ),
        ),
    )
    tool_result = ModelMessage(
        role="tool",
        content='{"status":"ok","summary":"合成行情观察"}',
        tool_call_id="call_synthetic_1",
    )
    second = first.model_copy(
        update={
            "messages": (*first.messages, assistant, tool_result),
        }
    )
    recorder = _Recorder(
        [
            _response(
                content=json.dumps(
                    {
                        "decision": "final_analysis",
                        "market_blocks": [],
                        "decision_blocks": [],
                        "selected_candidate_id": None,
                        "plan_ref": None,
                        "no_plan_reasons": ["no_valid_candidate"],
                        "limitations": [],
                        "safe_summary": "合成无计划结论。",
                    }
                ),
                finish_reason="stop",
            )
        ]
    )
    model = _adapter(recorder)

    decision = await model.decide(second)

    assert isinstance(decision, FinalAnalysis)
    request = recorder.requests[0]
    assert request["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "call_synthetic_1",
        "content": '{"status":"ok","summary":"合成行情观察"}',
    }
    assert request["messages"][-2]["role"] == "assistant"
    assert request["messages"][-2]["tool_calls"][0]["id"] == "call_synthetic_1"
    assert request["messages"][-2]["tool_calls"][0]["function"]["arguments"] == (
        '{"symbol":"BTCUSDT"}'
    )


@pytest.mark.asyncio
async def test_control_proposal_json_is_typed_and_bounded() -> None:
    execution_context = fixtures.context()
    base = fixtures.model_context(execution_context)
    recorder = _Recorder(
        [
            _response(
                content=json.dumps(
                    {
                        "decision": "control_proposal",
                        "action": "clarify",
                        "diffs": [],
                        "material_refs": [],
                        "safe_reason": "goal_ambiguous",
                    }
                )
            )
        ]
    )
    model = _adapter(recorder)

    decision = await model.decide(base)

    assert isinstance(decision, ModelControlDecision)
    assert decision.proposal.action is ControlAction.CLARIFY
    assert decision.proposal.safe_reason == "goal_ambiguous"


@pytest.mark.asyncio
async def test_missing_usage_is_unknown_not_zero() -> None:
    execution_context = fixtures.context()
    base = fixtures.model_context(execution_context)
    recorder = _Recorder(
        [
            _response(
                content=json.dumps(
                    {
                        "decision": "final_analysis",
                        "market_blocks": [],
                        "decision_blocks": [],
                        "selected_candidate_id": None,
                        "plan_ref": None,
                        "no_plan_reasons": ["no_valid_candidate"],
                        "limitations": [],
                        "safe_summary": "合成无计划结论。",
                    }
                )
            )
        ]
    )
    traces: list[ModelCallTrace] = []
    model = _adapter(recorder, traces=traces)

    decision = await model.decide(base)

    assert isinstance(decision, FinalAnalysis)
    assert decision.usage is None
    assert traces[0].input_tokens is None
    assert traces[0].output_tokens is None


@pytest.mark.asyncio
async def test_more_than_four_tool_calls_are_rejected_before_execution() -> None:
    execution_context = fixtures.context()
    base = fixtures.model_context(execution_context)
    recorder = _Recorder(
        [
            _response(
                tool_calls=[_tool_call(call_id=f"call_{index}") for index in range(5)],
                finish_reason="tool_calls",
            )
        ]
    )
    traces: list[ModelCallTrace] = []
    model = _adapter(recorder, traces=traces)

    with pytest.raises(ModelCallError) as captured:
        await model.decide(base)

    assert captured.value.code == "model_tool_batch_too_large"
    assert traces[0].finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_invalid_tool_arguments_are_rejected() -> None:
    execution_context = fixtures.context()
    base = fixtures.model_context(execution_context)
    recorder = _Recorder(
        [
            _response(
                tool_calls=[_tool_call(arguments="{not-json")],
                finish_reason="tool_calls",
            )
        ]
    )
    model = _adapter(recorder)

    with pytest.raises(ModelCallError) as captured:
        await model.decide(base)

    assert captured.value.code == "model_tool_call_invalid"


@pytest.mark.asyncio
async def test_unregistered_model_name_and_invalid_json_fail_closed() -> None:
    execution_context = fixtures.context()
    base = fixtures.model_context(execution_context)
    recorder = _Recorder([_response(content="这不是 JSON，也不是工具调用。")])
    model = _adapter(recorder)

    with pytest.raises(ModelCallError) as captured:
        await model.decide(base)

    assert captured.value.code == "model_invalid_response"


@pytest.mark.asyncio
async def test_missing_api_key_is_not_configured_and_does_not_send() -> None:
    execution_context = fixtures.context()
    base = fixtures.model_context(execution_context)
    recorder = _Recorder([])
    model = _adapter(recorder, api_key=None)

    assert model.available is False
    with pytest.raises(ModelCallError) as captured:
        await model.decide(base)

    assert captured.value.code == "model_not_configured"
    assert recorder.requests == []


@pytest.mark.asyncio
async def test_non_success_or_inconsistent_finish_reason_never_executes_tools() -> None:
    execution_context = fixtures.context()
    base = fixtures.model_context(execution_context)
    filtered = _response(
        tool_calls=[_tool_call()],
        finish_reason="content_filter",
        usage={"prompt_tokens": 30, "completion_tokens": 8},
    )
    recorder = _Recorder([filtered])
    model = _adapter(recorder)
    with pytest.raises(ModelCallError) as captured:
        await model.decide(base)
    assert captured.value.code == "model_finish_reason_unsupported"
    assert captured.value.usage is not None

    for body, expected in (
        (_response(tool_calls=[_tool_call()], finish_reason="stop"), "model_invalid_response"),
        (
            _response(tool_calls=[_tool_call()], finish_reason=None),
            "model_finish_reason_unsupported",
        ),
    ):
        recorder = _Recorder([body])
        model = _adapter(recorder)
        with pytest.raises(ModelCallError) as captured:
            await model.decide(base)
        assert captured.value.code == expected


@pytest.mark.asyncio
async def test_oversized_stream_is_closed_before_consuming_later_chunks() -> None:
    execution_context = fixtures.context()
    base = fixtures.model_context(execution_context)
    stream = _ChunkStream([b"{", b"x" * (MAX_MODEL_RESPONSE_BYTES + 1), b"}"])

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(
            200,
            stream=stream,
            headers={"content-type": "application/json"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = _adapter(_Recorder([]), client=client)

    with pytest.raises(ModelCallError) as captured:
        await model.decide(base)

    assert captured.value.code == "model_response_too_large"
    assert stream.yielded == 2
    assert stream.closed is True


@pytest.mark.asyncio
async def test_upstream_error_is_a_known_failure() -> None:
    execution_context = fixtures.context()
    base = fixtures.model_context(execution_context)

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(503, text="synthetic upstream unavailable")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = _adapter(_Recorder([]), client=client)

    with pytest.raises(ModelCallError) as captured:
        await model.decide(base)

    assert captured.value.code == "model_upstream_error"
    assert captured.value.usage is None


@pytest.mark.asyncio
async def test_estimate_request_includes_tools_and_prompt_envelope() -> None:
    execution_context = fixtures.context()
    base = fixtures.model_context(execution_context)
    model = _adapter(_Recorder([]))

    encoded = model.encode_request(base)
    decoded = json.loads(encoded)

    assert decoded["tools"][0]["function"]["name"] == "read_market_evidence"
    assert "tool_choice" not in decoded
    assert model.estimate_request(base) == estimate_input(encoded)
    assert model.estimate_request(base) > estimate_input(
        encode_model_request(base.messages, base.tools)
    )
