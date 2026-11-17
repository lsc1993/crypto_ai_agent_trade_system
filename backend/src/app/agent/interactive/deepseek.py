# DeepSeek 原生 Tool Calling 适配器：发送供应商协议消息与工具 Schema，解析工具请求/最终分析。
# 只通过注入的 httpx.AsyncClient 访问固定公开端点；不读取环境密钥、不访问账户或执行交易。
# 所有模型输出仍是提案：工具必须回到 T09 网关，最终分析必须回到产物暂存和人工审核。
# 请求/响应中的 usage 缺失保持 None；不把未知用量写成零，也不依赖隐藏 reasoning_content。
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal, cast

import httpx
from pydantic import SecretStr, ValidationError

from app.agent.interactive.context import ModelContext, ModelMessage
from app.agent.interactive.context_budget import estimate_input
from app.agent.interactive.model_port import (
    FinalAnalysis,
    ModelCallError,
    ModelCallTrace,
    ModelControlDecision,
    ModelDecision,
    ToolBatch,
)
from app.agent.interactive.prompt import (
    PROMPT_SHA256,
    PROMPT_VERSION,
    SCHEMA_SHA256,
    SCHEMA_VERSION,
    SYSTEM_PROMPT,
)
from app.agent.interactive.tools.contracts import ToolRequest
from app.agent_runs.attempts import MAX_OUTPUT_TOKENS_PER_CALL, TokenUsage
from app.agent_runs.decisions import ControlProposal
from app.shared.agent_types import JsonObject, JsonValue

# 供应商端点固定；不接受模型或用户传入的 URL、命令或服务发现。
_DEEPSEEK_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
# 响应上限防止异常上游把无界正文读进模型循环；正常 4096 输出远低于该值。
MAX_MODEL_RESPONSE_BYTES = 262_144
# 与 C5 模型超时一致；适配器只把超时映射为稳定错误，不自行重试。
_DEFAULT_TIMEOUT_SECONDS = 60.0


# 把供应商中立消息转换为原生协议；系统 Prompt 与上下文系统消息合并为唯一 system 消息。
def _wire_message(message: ModelMessage) -> dict[str, object]:
    if message.role == "assistant":
        value: dict[str, object] = {
            "role": "assistant",
            "content": message.content,
        }
        if message.tool_calls:
            value["tool_calls"] = [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            cast(JsonValue, call.arguments),
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    },
                }
                for call in message.tool_calls
            ]
        return value
    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": message.content,
        }
    return {"role": message.role, "content": message.content}


# 把上下文消息转换为固定顺序的 wire 消息；系统消息统一前置且只保留一条。
def _wire_messages(context: ModelContext) -> list[dict[str, object]]:
    system_parts = [SYSTEM_PROMPT]
    body: list[dict[str, object]] = []
    for message in context.messages:
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
            continue
        body.append(_wire_message(message))
    return [{"role": "system", "content": "\n\n".join(system_parts)}, *body]


# 工具 Schema 只来自服务端已授权投影；描述与参数由目录冻结，模型不能追加字段。
def _wire_tools(context: ModelContext) -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in context.tools
    ]


# 解析供应商 usage；缺失任一字段保持 None，不能把未知用量写成 0。
def _usage(value: object) -> TokenUsage | None:
    if not isinstance(value, dict):
        return None
    data = cast(dict[str, object], value)
    input_tokens = data.get("prompt_tokens")
    output_tokens = data.get("completion_tokens")
    if (
        isinstance(input_tokens, int)
        and not isinstance(input_tokens, bool)
        and input_tokens >= 0
        and isinstance(output_tokens, int)
        and not isinstance(output_tokens, bool)
        and output_tokens >= 0
    ):
        return TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)
    return None


# 供应商标识只保留有界可打印文本；异常值不写 trace，也不影响安全解析。
def _provider_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 256:
        return None
    if any(ord(character) < 0x20 for character in normalized):
        return None
    return normalized


# 将工具参数解析为 JSON object；只接受对象，数组/标量/无效 JSON 全部 fail-closed。
def _tool_arguments(value: object) -> JsonObject:
    loaded: object
    if isinstance(value, str):
        try:
            loaded = cast(object, json.loads(value))
        except (TypeError, ValueError) as error:
            raise ModelCallError("model_tool_call_invalid") from error
    elif isinstance(value, dict):
        loaded = cast(object, value)
    else:
        raise ModelCallError("model_tool_call_invalid")
    if not isinstance(loaded, dict):
        raise ModelCallError("model_tool_call_invalid")
    return cast(JsonObject, cast(dict[str, object], loaded))


# 把单个原生 tool_call 转为 T09 ToolRequest；未登记工具留给网关拒绝并留下观察。
def _tool_request(value: object) -> ToolRequest:
    if not isinstance(value, dict):
        raise ModelCallError("model_tool_call_invalid")
    data = cast(dict[str, object], value)
    call_id = data.get("id")
    function = data.get("function")
    if not isinstance(call_id, str) or not isinstance(function, dict):
        raise ModelCallError("model_tool_call_invalid")
    function_data = cast(dict[str, object], function)
    name = function_data.get("name")
    if not isinstance(name, str):
        raise ModelCallError("model_tool_call_invalid")
    arguments = _tool_arguments(function_data.get("arguments"))
    try:
        return ToolRequest(name=name, arguments=arguments, call_id=call_id)
    except (ValidationError, ValueError) as error:
        raise ModelCallError("model_tool_call_invalid") from error


# 解析最终分析或控制提案 JSON；只接受单个对象，不执行 Markdown/自由文本猜测。
def _parse_decision(
    content: str,
    *,
    usage: TokenUsage | None,
    provider_request_id: str | None,
) -> ModelDecision:
    normalized = content.strip()
    if normalized.startswith("```"):
        # 只接受明确的 JSON 围栏，不允许在正文前后携带解释性文本。
        lines = normalized.splitlines()
        if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"}:
            if lines[-1].strip() == "```":
                normalized = "\n".join(lines[1:-1]).strip()
    try:
        loaded: object = json.loads(normalized)
    except (TypeError, ValueError) as error:
        raise ModelCallError("model_invalid_response") from error
    if not isinstance(loaded, dict):
        raise ModelCallError("model_invalid_response")
    value = cast(dict[str, object], loaded)
    decision = value.get("decision")
    if not isinstance(decision, str):
        raise ModelCallError("model_invalid_response")
    values: dict[str, object] = dict(value)
    values.pop("decision", None)
    if decision == "final_analysis":
        values["usage"] = usage
        values["provider_request_id"] = provider_request_id
        try:
            return FinalAnalysis.model_validate(values)
        except (ValidationError, ValueError) as error:
            raise ModelCallError("model_invalid_response") from error
    if decision == "control_proposal":
        try:
            proposal = ControlProposal.model_validate(values)
        except (ValidationError, ValueError) as error:
            raise ModelCallError("model_invalid_response") from error
        return ModelControlDecision(
            proposal=proposal,
            safe_summary="模型提出需要用户处理的受控动作。",
            usage=usage,
            provider_request_id=provider_request_id,
        )
    raise ModelCallError("model_invalid_response")


# 原生工具调用适配器；构造时只接收已授权客户端、模型名和可选 trace 记录器。
class DeepSeekToolCallingModel:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: SecretStr | None,
        model: Literal["deepseek-v4-flash", "deepseek-v4-pro"],
        trace_recorder: Callable[[ModelCallTrace], None] | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not 1 <= timeout_seconds <= _DEFAULT_TIMEOUT_SECONDS:
            raise ValueError("模型超时必须在 1 到 60 秒之间")
        self._client = client
        self._api_key = api_key
        self._model = model
        self._trace_recorder = trace_recorder
        self._timeout_seconds = timeout_seconds

    @property
    def requested_model(self) -> str:
        return self._model

    @property
    def available(self) -> bool:
        if self._api_key is None:
            return False
        return bool(self._api_key.get_secret_value().strip())

    # 与 decide 使用同一 wire payload 计算预留；调用方在预算预留前使用该值。
    def _payload(self, context: ModelContext) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": _wire_messages(context),
            "thinking": {"type": "disabled"},
            "max_tokens": MAX_OUTPUT_TOKENS_PER_CALL,
        }
        if context.tools:
            payload["tools"] = _wire_tools(context)
        return payload

    def encode_request(self, context: ModelContext) -> bytes:
        return json.dumps(
            self._payload(context),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def estimate_request(self, context: ModelContext) -> int:
        return estimate_input(self.encode_request(context))

    async def decide(self, context: ModelContext) -> ModelDecision:
        if not self.available:
            raise ModelCallError("model_not_configured")
        assert self._api_key is not None
        secret_value = self._api_key.get_secret_value().strip()
        payload = self._payload(context)
        try:
            response = await self._client.post(
                _DEEPSEEK_COMPLETIONS_URL,
                headers={"Authorization": f"Bearer {secret_value}"},
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as error:
            raise ModelCallError("model_timeout") from error
        except httpx.HTTPError as error:
            raise ModelCallError("model_transport_error") from error
        if response.is_redirect:
            raise ModelCallError("model_upstream_error")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise ModelCallError("model_upstream_error") from error
        if len(response.content) > MAX_MODEL_RESPONSE_BYTES:
            raise ModelCallError("model_response_too_large")
        try:
            body = response.json()
        except (TypeError, ValueError) as error:
            raise ModelCallError("model_invalid_response") from error
        return self._parse_body(context, body)

    # 解析固定原生响应形状；所有错误都转成稳定 ModelCallError，并保留已观察用量。
    def _parse_body(self, context: ModelContext, body: object) -> ModelDecision:
        if not isinstance(body, dict):
            raise ModelCallError("model_invalid_response")
        data = cast(dict[str, object], body)
        returned_model = data.get("model")
        if not isinstance(returned_model, str) or not returned_model.strip():
            raise ModelCallError("model_invalid_response")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelCallError("model_invalid_response")
        choices_list = cast(list[object], choices)
        choice = choices_list[0]
        if not isinstance(choice, dict):
            raise ModelCallError("model_invalid_response")
        choice_data = cast(dict[str, object], choice)
        message = choice_data.get("message")
        if not isinstance(message, dict):
            raise ModelCallError("model_invalid_response")
        message_data = cast(dict[str, object], message)
        finish_reason = choice_data.get("finish_reason")
        finish_value = finish_reason if isinstance(finish_reason, str) else None
        usage = _usage(data.get("usage"))
        provider_id = _provider_id(data.get("id"))
        self._record_trace(
            context,
            returned_model=returned_model,
            finish_reason=finish_value,
            usage=usage,
            provider_request_id=provider_id,
        )
        if finish_value == "length":
            raise ModelCallError(
                "model_output_truncated",
                usage=usage,
                provider_request_id=provider_id,
                returned_model=returned_model,
            )
        raw_calls = message_data.get("tool_calls")
        if isinstance(raw_calls, list) and raw_calls:
            raw_values = cast(list[object], raw_calls)
            if len(raw_values) > 4:
                raise ModelCallError(
                    "model_tool_batch_too_large",
                    usage=usage,
                    provider_request_id=provider_id,
                    returned_model=returned_model,
                )
            try:
                calls = tuple(_tool_request(item) for item in raw_values)
            except ModelCallError as error:
                raise ModelCallError(
                    error.code,
                    usage=usage,
                    provider_request_id=provider_id,
                    returned_model=returned_model,
                ) from error
            summary = message_data.get("content")
            safe_summary = (
                summary.strip()
                if isinstance(summary, str) and summary.strip()
                else "已请求只读研究工具。"
            )
            return ToolBatch(
                calls=calls,
                safe_summary=safe_summary[:2_000],
                usage=usage,
                provider_request_id=provider_id,
            )
        if finish_value == "tool_calls":
            raise ModelCallError(
                "model_invalid_response",
                usage=usage,
                provider_request_id=provider_id,
                returned_model=returned_model,
            )
        content = message_data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelCallError(
                "model_invalid_response",
                usage=usage,
                provider_request_id=provider_id,
                returned_model=returned_model,
            )
        try:
            return _parse_decision(
                content,
                usage=usage,
                provider_request_id=provider_id,
            )
        except ModelCallError as error:
            raise ModelCallError(
                error.code,
                usage=usage,
                provider_request_id=provider_id,
                returned_model=returned_model,
            ) from error

    # trace 只包含版本/指纹/模型名/用量；记录器失败按适配器内部错误向上传递。
    def _record_trace(
        self,
        context: ModelContext,
        *,
        returned_model: str,
        finish_reason: str | None,
        usage: TokenUsage | None,
        provider_request_id: str | None,
    ) -> None:
        if self._trace_recorder is None:
            return
        self._trace_recorder(
            ModelCallTrace(
                requested_model=self._model,
                returned_model=returned_model,
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
                prompt_sha256=PROMPT_SHA256,
                schema_sha256=SCHEMA_SHA256,
                tool_catalog_sha256=context.manifest.tool_catalog_sha256,
                provider_request_id=provider_request_id,
                finish_reason=finish_reason,
                input_tokens=None if usage is None else usage.input_tokens,
                output_tokens=None if usage is None else usage.output_tokens,
            )
        )


__all__ = [
    "MAX_MODEL_RESPONSE_BYTES",
    "DeepSeekToolCallingModel",
    "ModelCallError",
]
