# 官方 MCP SDK 客户端适配：固定端点/协议/Schema 指纹，经有界 Streamable HTTP 调用只读服务。
# 该客户端实现 T09 ToolHandler，必须由 ToolGateway 先完成预算预留/发送提交后才会被调用。
# call() 只是已绑定网关的受控入口；未绑定网关时显式失败，禁止形成绕过工具守卫的第二条路径。
# 本模块不访问私有账户、交易执行或业务库；模型参数不能选择 URL、服务、工具 Schema 或策略版本。
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast
from uuid import UUID

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent, Tool
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.interactive.tools.contracts import (
    JsonObject,
    RegisteredTool,
    ToolObservation,
    ToolQuality,
    ToolRequest,
    ToolResult,
    ToolResultStatus,
)
from app.agent_runs.contracts import RunSnapshot
from app.agent_runs.segments import ExecutionContext
from app.infrastructure.mcp.registry import (
    MAX_MCP_RESULT_BYTES,
    MAX_MCP_SUMMARY_BYTES,
    McpEndpoint,
    McpEndpointRegistry,
    McpRegistryError,
    mcp_tool_schema_sha256,
)
from app.infrastructure.mcp.transport import (
    BoundedMcpTransport,
    McpTransportError,
    build_http_client,
)
from app.shared.agent_types import ArtifactRef, UtcDateTime, is_sha256, require_utc


# 已绑定网关的最小协议；避免客户端导入网关实现并形成循环依赖。
class GuardedToolCaller(Protocol):
    async def call(
        self,
        context: ExecutionContext,
        request: ToolRequest,
    ) -> ToolObservation: ...


# MCP 服务返回的固定安全载荷；字段与服务端一致，未知字段/非法时间直接拒绝。
class _McpStrategyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok", "degraded"]
    quality: Literal["valid", "partial", "stale", "missing"]
    safe_summary: str = Field(min_length=1, max_length=MAX_MCP_SUMMARY_BYTES)
    reason_code: str | None = None
    observed_at: UtcDateTime
    expires_at: UtcDateTime | None = None
    version_id: str | None = None
    sha256: str | None = None

    @field_validator("reason_code")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value or len(value) > 64 or not value.replace("_", "").isalnum():
            raise ValueError("MCP 原因码必须是稳定短码")
        return value

    @field_validator("safe_summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("MCP 摘要必须非空且不能包含 NUL")
        if len(normalized.encode("utf-8")) > MAX_MCP_SUMMARY_BYTES:
            raise ValueError("MCP 摘要超过 8 KiB")
        return normalized

    @model_validator(mode="after")
    def validate_shape(self) -> _McpStrategyPayload:
        if self.status == "ok" and self.reason_code is not None:
            raise ValueError("正常 MCP 结果不能夹带降级原因")
        if self.status == "degraded" and self.reason_code is None:
            raise ValueError("降级 MCP 结果必须给出原因")
        if (self.version_id is None) != (self.sha256 is None):
            raise ValueError("MCP 版本引用必须同时存在")
        if self.sha256 is not None and not is_sha256(self.sha256):
            raise ValueError("MCP 版本指纹必须是 64 位小写十六进制")
        if self.expires_at is not None and self.expires_at < self.observed_at:
            raise ValueError("MCP 结果到期时间不能早于观测时间")
        return self


# 固定只读策略定义工具；客户端拒绝用于其他工具名，避免形成通用远端工具路由。
_SUPPORTED_TOOL = "read_strategy_definition"
# 传输错误到稳定安全原因的映射；不把 URL、上游正文或异常文本带给模型。
_REASON_BY_TRANSPORT = {
    "redirect_rejected": "mcp_redirect_rejected",
    "payload_too_large": "mcp_payload_too_large",
    "transport_limit_exceeded": "mcp_transport_limit",
    "invalid_content_length": "mcp_invalid_response",
    "endpoint_not_registered": "mcp_unavailable",
    "mcp_protocol_mismatch": "mcp_protocol_mismatch",
    "mcp_unavailable": "mcp_unavailable",
}


class McpToolClient:
    def __init__(
        self,
        *,
        registry: McpEndpointRegistry,
        tool: RegisteredTool,
        clock: Callable[[], datetime] | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        if tool.name != _SUPPORTED_TOOL:
            raise McpRegistryError("unsupported_mcp_tool")
        self._registry = registry
        # 公开属性满足 T09 ToolHandler 的可变属性协议；网关在绑定后不再接受目录漂移。
        self.tool = tool
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout_seconds = timeout_seconds or float(tool.timeout_seconds)
        self._gateway: GuardedToolCaller | None = None
        self._last_request_count: int | None = None

    # 最近一次 MCP 调用的实际 HTTP 请求数（含 SDK discover/list/call 与重连）；仅用于审计/测试。
    @property
    def last_request_count(self) -> int | None:
        return self._last_request_count

    # 受控公共入口：必须绑定 T09 ToolGateway 后才能调用，确保预算/目录/fence 守卫不被绕过。
    def bind_gateway(self, gateway: GuardedToolCaller) -> None:
        self._gateway = gateway

    async def call(
        self,
        context: ExecutionContext,
        request: ToolRequest,
    ) -> ToolObservation:
        if self._gateway is None:
            raise McpRegistryError("tool_gateway_required")
        return await self._gateway.call(context, request)

    # T09 处理器：网关已完成参数/范围/预算校验；这里只按当前上下文读取固定策略版本。
    async def handle(
        self,
        context: ExecutionContext,
        snapshot: RunSnapshot,
        arguments: JsonObject,
        *,
        sent_at: datetime,
    ) -> ToolResult:
        _ = (snapshot, arguments, sent_at)
        now = require_utc(self._clock())
        try:
            endpoint = self._registry.for_tool(self.tool.name)
        except McpRegistryError:
            return _degraded("mcp_unavailable", now=now)
        try:
            payload = await self._call_mcp(endpoint, context)
        except TimeoutError:
            return _degraded("mcp_timeout", now=require_utc(self._clock()))
        except McpRegistryError as error:
            return _degraded(_safe_registry_reason(error.code), now=require_utc(self._clock()))
        except McpTransportError as error:
            reason = _REASON_BY_TRANSPORT.get(error.code, "mcp_unavailable")
            return _degraded(reason, now=require_utc(self._clock()))
        except ValueError:
            return _degraded("mcp_invalid_result", now=require_utc(self._clock()))
        except BaseExceptionGroup as group:
            # anyio/SDK 会把上下文退出期间的错误包成 ExceptionGroup；先提取可识别守卫原因。
            if _contains_cancelled(group):
                raise
            reason = _group_reason(group) or "mcp_unavailable"
            return _degraded(reason, now=require_utc(self._clock()))
        except (httpx2.HTTPError, OSError, RuntimeError):
            # 连接失败、SDK 协商失败或服务不可达都降级；不重试、不切换其他供应商/端点。
            return _degraded("mcp_unavailable", now=require_utc(self._clock()))
        except Exception:
            # 未预期异常不向外抛出上游文本；工具调用已经发送，按不可用观察返回。
            return _degraded("mcp_unavailable", now=require_utc(self._clock()))
        return self._payload_to_result(payload, context, now=require_utc(self._clock()))

    # 实际 SDK 调用：固定 mode=auto 协商，随后核对协议、工具集合与 Schema 指纹，最后只调用一个工具。
    async def _call_mcp(
        self,
        endpoint: McpEndpoint,
        context: ExecutionContext,
    ) -> _McpStrategyPayload:
        transport = BoundedMcpTransport(
            inner=httpx2.AsyncHTTPTransport(),
            endpoint=endpoint,
        )
        http_client = build_http_client(
            endpoint,
            self._registry.credential,
            transport=transport,
        )
        self._last_request_count = None
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with http_client:
                    mcp_transport = streamable_http_client(
                        endpoint.url,
                        http_client=http_client,
                        terminate_on_close=True,
                        max_sse_event_size=endpoint.max_sse_event_bytes,
                    )
                    mismatch: McpRegistryError | McpTransportError = McpTransportError(
                        "mcp_unavailable"
                    )
                    async with Client(
                        mcp_transport,
                        mode="auto",
                        read_timeout_seconds=self._timeout_seconds,
                    ) as client:
                        if client.protocol_version != endpoint.protocol_version:
                            mismatch = McpTransportError("mcp_protocol_mismatch")
                        else:
                            tools = await client.list_tools()
                            try:
                                _verify_catalog(endpoint, tools.tools)
                            except McpRegistryError as error:
                                mismatch = error
                            else:
                                result = await client.call_tool(
                                    self.tool.name,
                                    {
                                        "workspace_id": str(context.fence.workspace_id),
                                        "version_id": str(context.strategy_ref.version_id),
                                        "sha256": context.strategy_ref.sha256,
                                    },
                                )
                                return _parse_tool_result(
                                    result.structured_content,
                                    result.content,
                                )
                    # 在 SDK 上下文正常退出后再抛出配置不匹配，避免被 anyio 包成 ExceptionGroup。
                    raise mismatch
        finally:
            self._last_request_count = transport.request_count

    # 将服务端安全载荷映射为 T09 ToolResult；时间/版本/摘要越界都降级，不伪装成功。
    def _payload_to_result(
        self,
        payload: _McpStrategyPayload,
        context: ExecutionContext,
        *,
        now: datetime,
    ) -> ToolResult:
        if payload.observed_at > now + timedelta(seconds=5):
            return _degraded("mcp_result_from_future", now=now)
        if payload.expires_at is not None and payload.expires_at < now:
            return ToolResult(
                status=ToolResultStatus.DEGRADED,
                safe_summary=payload.safe_summary,
                quality=ToolQuality.STALE,
                reason_code="result_expired",
                observed_at=payload.observed_at,
                expires_at=payload.expires_at,
                result_ref=_payload_ref(payload),
            )
        if payload.status == "degraded":
            return ToolResult(
                status=ToolResultStatus.DEGRADED,
                safe_summary=payload.safe_summary,
                quality=ToolQuality(payload.quality),
                reason_code=payload.reason_code or "mcp_degraded",
                observed_at=payload.observed_at,
                expires_at=payload.expires_at,
                result_ref=_payload_ref(payload),
            )
        if (
            payload.version_id != str(context.strategy_ref.version_id)
            or payload.sha256 != context.strategy_ref.sha256
        ):
            return _degraded("strategy_version_mismatch", now=now)
        if payload.quality != "valid":
            return _degraded("mcp_invalid_result", now=now)
        return ToolResult(
            status=ToolResultStatus.OK,
            safe_summary=payload.safe_summary,
            quality=ToolQuality.VALID,
            observed_at=payload.observed_at,
            expires_at=payload.expires_at,
            result_ref=_payload_ref(payload),
        )


# 校验服务端 tools/list 与登记集合/指纹完全一致；任何漂移都在调用工具前失败。
def _verify_catalog(endpoint: McpEndpoint, tools: list[Tool]) -> None:
    advertised = {tool.name: tool for tool in tools}
    if set(advertised) != set(endpoint.tool_names):
        raise McpRegistryError("mcp_tool_catalog_mismatch")
    for name in endpoint.tool_names:
        tool = advertised[name]
        actual = mcp_tool_schema_sha256(
            name=tool.name,
            description=tool.description,
            input_schema=dict(tool.input_schema),
            output_schema=None if tool.output_schema is None else dict(tool.output_schema),
        )
        if actual != endpoint.schema_sha256(name):
            raise McpRegistryError("mcp_tool_catalog_mismatch")


# 优先读取 structuredContent；兼容文本 JSON，但两者都执行 64 KiB 上限与类型检查。
def _parse_tool_result(
    structured: Any,
    content: list[Any],
) -> _McpStrategyPayload:
    if structured is None:
        text_blocks = [item.text for item in content if isinstance(item, TextContent)]
        if not text_blocks:
            raise ValueError("MCP 工具没有返回结构化结果")
        raw_text = text_blocks[0]
        if len(raw_text.encode("utf-8")) > MAX_MCP_RESULT_BYTES:
            raise ValueError("MCP 工具结果超过 64 KiB")
        decoded: Any = json.loads(raw_text)
    else:
        decoded = structured
    if not isinstance(decoded, dict):
        raise ValueError("MCP 工具结果必须是对象")
    serialized = json.dumps(decoded, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_MCP_RESULT_BYTES:
        raise ValueError("MCP 工具结果超过 64 KiB")
    return _McpStrategyPayload.model_validate(cast(dict[str, Any], decoded))


def _payload_ref(payload: _McpStrategyPayload) -> ArtifactRef | None:
    if payload.version_id is None or payload.sha256 is None:
        return None
    try:
        return ArtifactRef(
            artifact_id=UUID(payload.version_id),
            sha256=payload.sha256,
        )
    except ValueError:
        return None


def _safe_registry_reason(code: str) -> str:
    if code == "mcp_tool_catalog_mismatch":
        return code
    return "mcp_unavailable"


# 递归提取守卫错误；SDK/anyio 的异常组可能嵌套，但只映射已知安全 code。
def _group_reason(error: BaseException) -> str | None:
    if isinstance(error, TimeoutError):
        return "mcp_timeout"
    if isinstance(error, McpTransportError):
        return _REASON_BY_TRANSPORT.get(error.code)
    if isinstance(error, McpRegistryError):
        return _safe_registry_reason(error.code)
    if isinstance(error, BaseExceptionGroup):
        group = cast(BaseExceptionGroup[BaseException], error)
        for child in group.exceptions:
            reason = _group_reason(child)
            if reason is not None:
                return reason
    return None


# 取消必须继续向上传播；不能把任务取消伪装成 MCP 不可用观察。
def _contains_cancelled(error: BaseException) -> bool:
    if isinstance(error, asyncio.CancelledError):
        return True
    if isinstance(error, BaseExceptionGroup):
        group = cast(BaseExceptionGroup[BaseException], error)
        return any(_contains_cancelled(child) for child in group.exceptions)
    return False


def _degraded(reason: str, *, now: datetime) -> ToolResult:
    return ToolResult(
        status=ToolResultStatus.DEGRADED,
        safe_summary="策略定义 MCP 服务当前不可用；没有回退到其他工具、端点或策略版本。",
        quality=ToolQuality.MISSING,
        reason_code=reason,
        observed_at=now,
    )


__all__ = ["GuardedToolCaller", "McpToolClient"]
