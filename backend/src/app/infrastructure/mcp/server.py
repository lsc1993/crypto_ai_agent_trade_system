# 同进程只读 MCP 服务：只登记 read_strategy_definition，并固定 loopback ASGI mount。
# 宿主用 lifespan 显式管理 SDK session manager；服务不主动拨号、不启动后台发现或外部连接。
# 服务凭据由进程启动时生成，只在进程内交给客户端；公开 descriptor 不含令牌或内部配置。
# 本模块不导入交易/风控/模拟执行，也不接收 URL、SQL、代码或账户信息。
from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.routing import Mount
from starlette.types import ASGIApp, Receive, Scope, Send

from app.infrastructure.mcp.registry import (
    DEFAULT_MCP_SERVER_ID,
    MAX_MCP_RESULT_BYTES,
    MAX_MCP_SUMMARY_BYTES,
    MCP_MOUNT_PATH,
    MCP_PROTOCOL_VERSION,
    MCP_TOOL_PATH,
    LocalMcpServiceDescriptor,
    McpEndpoint,
    McpEndpointRegistry,
    McpServiceCredential,
    McpToolDescriptor,
    mcp_tool_schema_sha256,
)
from app.research.strategies.contracts import (
    StrategyContractError,
    StrategyVersion,
)
from app.research.strategies.ports import StrategyCatalog
from app.shared.agent_types import VersionRef, is_sha256, require_utc

STRATEGY_DEFINITION_TOOL = "read_strategy_definition"
MAX_METHOD_TEXT_SUMMARY_BYTES = 3_500
MAX_PARAMETER_SCHEMA_SUMMARY_BYTES = 2_000


# 内部服务鉴权中间件：只接受进程启动时生成的 Bearer 令牌，未认证请求不进入 MCP 解析器。
class _InternalServiceAuth:
    def __init__(self, app: ASGIApp, credential: McpServiceCredential) -> None:
        self._app = app
        self._credential = credential

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        if not self._credential.is_authorized(Headers(scope=scope).get("authorization")):
            response = JSONResponse(
                {"code": "mcp_unauthorized"},
                status_code=401,
                headers={"cache-control": "no-store"},
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)


# 宿主可独立启动的运行时；app 自带 lifespan，mount 到 FastAPI 时应改由宿主调用 lifespan()。
class ResearchMcpRuntime:
    def __init__(
        self,
        *,
        server: MCPServer[None],
        credential: McpServiceCredential,
        server_id: str,
        port: int,
    ) -> None:
        self._server = server
        self._credential = credential
        self._server_id = server_id
        self._port = port
        mcp_app = server.streamable_http_app(
            streamable_http_path=MCP_TOOL_PATH,
            json_response=True,
            stateless_http=True,
            host="127.0.0.1",
        )
        root = Starlette(
            routes=[Mount(MCP_MOUNT_PATH, app=mcp_app)],
            lifespan=self._starlette_lifespan,
        )
        self.app: ASGIApp = _InternalServiceAuth(root, credential)

    # Starlette 自带 lifespan：uvicorn 直接运行 runtime.app 时会启动/关闭 SDK manager。
    @asynccontextmanager
    async def _starlette_lifespan(self, app: Starlette) -> AsyncGenerator[None]:
        _ = app
        async with self.lifespan():
            yield

    # 宿主 lifespan 的显式入口；SDK manager 每个实例只能运行一次，重复进入必须失败。
    @asynccontextmanager
    async def lifespan(self) -> AsyncGenerator[None]:
        async with self._server.session_manager.run():
            yield

    @property
    def server_id(self) -> str:
        return self._server_id

    @property
    def port(self) -> int:
        return self._port

    # 宿主装配用：从当前服务描述和内部凭据创建客户端端点登记，凭据不离开运行时。
    async def build_client_registry(self) -> McpEndpointRegistry:
        descriptor = await self.describe()
        return McpEndpointRegistry(
            [
                McpEndpoint(
                    server_id=descriptor.server_id,
                    host=descriptor.host,
                    port=descriptor.port,
                    path=descriptor.path,
                    protocol_version=descriptor.protocol_version,
                    tools=descriptor.tools,
                )
            ],
            credential=self._credential,
        )

    # 描述符按实际 tools/list 投影计算 Schema 指纹，确保客户端 pin 与服务端一致。
    async def describe(self) -> LocalMcpServiceDescriptor:
        tools = await self._server.list_tools()
        described = tuple(
            McpToolDescriptor(
                name=tool.name,
                schema_sha256=mcp_tool_schema_sha256(
                    name=tool.name,
                    description=tool.description,
                    input_schema=dict(tool.input_schema),
                    output_schema=None if tool.output_schema is None else dict(tool.output_schema),
                ),
            )
            for tool in sorted(tools, key=lambda item: item.name)
        )
        return LocalMcpServiceDescriptor(
            server_id=self._server_id,
            host="127.0.0.1",
            port=self._port,
            path=MCP_MOUNT_PATH + MCP_TOOL_PATH,
            protocol_version=MCP_PROTOCOL_VERSION,
            tools=described,
        )


# 构造本地只读 MCP 服务；reader 是冻结策略目录端口，不接收任意读取器/URL/命令。
def build_research_mcp(
    reader: StrategyCatalog,
    *,
    port: int = 8_000,
    credential: McpServiceCredential | None = None,
    server_id: str = DEFAULT_MCP_SERVER_ID,
    clock: Callable[[], datetime] | None = None,
) -> ResearchMcpRuntime:
    resolved_credential = credential or McpServiceCredential.generate()
    resolved_clock = clock or (lambda: datetime.now(UTC))
    server: MCPServer[None] = MCPServer(
        name=server_id,
        version="1.0",
        instructions="本地只读策略定义服务；不提供交易、账户、任意工具或外部服务发现。",
    )

    @server.tool(
        name=STRATEGY_DEFINITION_TOOL,
        description="读取当前工作台已发布策略版本的只读定义、参数约束和能力。",
        annotations=ToolAnnotations(read_only_hint=True),
        structured_output=True,
    )
    async def read_strategy_definition(
        workspace_id: str,
        version_id: str,
        sha256: str,
    ) -> dict[str, Any]:
        return await _read_strategy_payload(
            reader,
            workspace_id=workspace_id,
            version_id=version_id,
            sha256=sha256,
            now=require_utc(resolved_clock()),
        )

    _ = read_strategy_definition
    return ResearchMcpRuntime(
        server=server,
        credential=resolved_credential,
        server_id=server_id,
        port=port,
    )


# 读取并冻结一个已发布策略版本；所有失败都返回固定安全原因，不返回上游异常文本。
async def _read_strategy_payload(
    reader: StrategyCatalog,
    *,
    workspace_id: str,
    version_id: str,
    sha256: str,
    now: datetime,
) -> dict[str, Any]:
    try:
        workspace = UUID(workspace_id)
        version = UUID(version_id)
    except ValueError:
        return _degraded("invalid_strategy_reference", now=now)
    if not is_sha256(sha256):
        return _degraded("invalid_strategy_reference", now=now)
    ref = VersionRef(version_id=version, sha256=sha256)
    try:
        strategy = await reader.get_published(workspace, ref)
        strategy = strategy.validated_snapshot()
    except (StrategyContractError, ValueError):
        return _degraded("strategy_unavailable", now=now)
    if strategy.ref != ref:
        return _degraded("strategy_version_mismatch", now=now)
    if strategy.archived or strategy.archived_at is not None:
        return _degraded(
            "strategy_archived",
            now=now,
            result_ref=(str(strategy.ref.version_id), strategy.ref.sha256),
        )
    summary = _strategy_summary(strategy)
    payload: dict[str, Any] = {
        "status": "ok",
        "quality": "valid",
        "safe_summary": summary,
        "reason_code": None,
        "observed_at": now.isoformat(),
        "expires_at": None,
        "version_id": str(strategy.ref.version_id),
        "sha256": strategy.ref.sha256,
    }
    # 原始结果上限 64 KiB；当前摘要已限 8 KiB，仍保留统一检查防止未来字段增长。
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_MCP_RESULT_BYTES:
        return _degraded("result_too_large", now=now)
    return payload


# 与 T09 本地策略定义工具保持同类安全摘要；本服务不返回完整正文或参数对象。
def _strategy_summary(strategy: StrategyVersion) -> str:
    method_text, method_truncated = _truncate_utf8(
        strategy.method_text,
        MAX_METHOD_TEXT_SUMMARY_BYTES,
    )
    schema_text, schema_truncated = _truncate_utf8(
        json.dumps(
            strategy.parameter_schema,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        MAX_PARAMETER_SCHEMA_SUMMARY_BYTES,
    )
    header = f"策略定义（只读版本）：strategyRef={strategy.ref.version_id}"
    blocks = (
        f"strategyId={strategy.strategy_id} name={strategy.name} kind={strategy.kind.value}",
        f"evaluatorId={strategy.evaluator_id} warmupCandles={strategy.warmup_candles}",
        "capabilities=" + ",".join(item.value for item in strategy.capabilities),
        "supportedSymbols=" + ",".join(strategy.supported_symbols),
        "supportedTimeframes=" + ",".join(item.value for item in strategy.supported_timeframes),
        f"methodTextTruncated={str(method_truncated).lower()}",
        "methodText:\n" + method_text,
        f"parameterSchemaTruncated={str(schema_truncated).lower()}",
        "parameterSchema=" + schema_text,
        "riskNotes=" + strategy.risk_notes,
    )
    included: list[str] = []
    for block in blocks:
        candidate = "\n".join((header, *included, block))
        if len(candidate.encode("utf-8")) <= MAX_MCP_SUMMARY_BYTES:
            included.append(block)
    text = "\n".join((header, *included))
    if len(included) < len(blocks):
        text = _append_note(
            text,
            "限制：策略定义摘要超出大小上限，完整版本应按引用读取。",
        )
    return _finalize_summary(text)


# 降级载荷保持与成功载荷相同的字段集合，客户端无需猜测缺失字段。
def _degraded(
    reason: str,
    *,
    now: datetime,
    result_ref: tuple[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "status": "degraded",
        "quality": "missing",
        "safe_summary": "策略定义不可用；没有回退到其他策略版本。",
        "reason_code": reason,
        "observed_at": now.isoformat(),
        "expires_at": None,
        "version_id": None if result_ref is None else result_ref[0],
        "sha256": None if result_ref is None else result_ref[1],
    }


def _truncate_utf8(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    return encoded[: max(0, max_bytes)].decode("utf-8", errors="ignore"), True


def _append_note(text: str, note: str) -> str:
    note_bytes = len(note.encode("utf-8"))
    base_limit = max(0, MAX_MCP_SUMMARY_BYTES - note_bytes)
    return _finalize_summary(_finalize_summary(text, limit=base_limit) + note)


def _finalize_summary(text: str, *, limit: int = MAX_MCP_SUMMARY_BYTES) -> str:
    if len(text.encode("utf-8")) <= limit:
        return text
    marker = "\n[摘要已截断]"
    marker_bytes = len(marker.encode("utf-8"))
    return _truncate_utf8(text, max(0, limit - marker_bytes))[0] + marker


__all__ = [
    "MAX_METHOD_TEXT_SUMMARY_BYTES",
    "MAX_PARAMETER_SCHEMA_SUMMARY_BYTES",
    "STRATEGY_DEFINITION_TOOL",
    "ResearchMcpRuntime",
    "build_research_mcp",
]
