# 固定 MCP 服务登记：loopback 端点、协议版本、工具 Schema 指纹与进程内服务凭据。
# 传输和客户端只接受这里登记的固定端点；模型、用户研究文本或远端响应不能追加端点。
# 本模块不发起网络、不读取数据库、不依赖交易/风控/账户实现，也不把凭据序列化给浏览器。
from __future__ import annotations

import copy
import hmac
import re
import secrets
from collections.abc import Iterable
from typing import Any, Literal, cast

from pydantic import Field, SecretStr, field_validator

from app.shared.agent_types import AgentModel, JsonValue, is_sha256, sha256_json

# 本地只读服务固定使用 2026-07-28 现代协议；握手协议仍允许登记，但客户端会拒绝不回落到旧版。
MCP_PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_MCP_PROTOCOL_VERSIONS = ("2025-06-18", "2025-11-25", "2026-07-28")
MCP_MOUNT_PATH = "/internal/agent-mcp"
MCP_TOOL_PATH = "/mcp"
MCP_SERVICE_PATH = MCP_MOUNT_PATH + MCP_TOOL_PATH
DEFAULT_MCP_SERVER_ID = "local_research"

# 原始载荷和模型摘要上限；SSE 事件单条上限与 JSON 响应上限分开登记。
MAX_MCP_JSON_BODY_BYTES = 64 * 1024
MAX_MCP_SSE_EVENT_BYTES = 64 * 1024
MAX_MCP_RESULT_BYTES = 64 * 1024
MAX_MCP_SUMMARY_BYTES = 8 * 1024
MAX_MCP_TRANSPORT_REQUESTS = 64

_SERVER_ID = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_PATH = re.compile(r"/[A-Za-z0-9._~/-]{0,255}\Z")
_CREDENTIAL_CHARS = re.compile(r"[\x21-\x7e]{32,256}\Z")


# 稳定配置错误；调用方只记录 code，不回显端点、令牌或上游异常。
class McpRegistryError(ValueError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


# 进程启动时生成的内部服务令牌；SecretStr 阻止普通 repr/序列化泄露。
class McpServiceCredential(AgentModel):
    token: SecretStr = Field(min_length=32, max_length=256)

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if _CREDENTIAL_CHARS.fullmatch(raw) is None:
            raise ValueError("MCP 内部凭据必须是有界可打印 ASCII")
        return value

    # 从外部字符串构造；仅在进程内使用，调用方不得记录原始 token。
    @classmethod
    def from_token(cls, token: str) -> McpServiceCredential:
        return cls(token=SecretStr(token))

    # 进程启动时生成内部凭据；长度满足最小要求且不由模型/用户输入决定。
    @classmethod
    def generate(cls) -> McpServiceCredential:
        return cls.from_token(secrets.token_urlsafe(32))

    # 只构造请求头；调用方不得把返回值写入日志、事件或页面投影。
    def authorization_header(self) -> str:
        return f"Bearer {self.token.get_secret_value()}"

    # 使用常量时间比较，避免服务端泄露令牌长度或前缀差异。
    def is_authorized(self, header: str | None) -> bool:
        if header is None:
            return False
        return hmac.compare_digest(header, self.authorization_header())


# 单个工具登记项：名称稳定，Schema 指纹与服务端 tools/list 投影必须一致。
class McpToolDescriptor(AgentModel):
    name: str
    schema_sha256: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if _TOOL_NAME.fullmatch(value) is None:
            raise ValueError("MCP 工具名称必须是稳定小写标识")
        return value

    @field_validator("schema_sha256")
    @classmethod
    def validate_schema_sha256(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("MCP 工具 Schema 指纹必须是 64 位小写十六进制")
        return value


# 统一工具 Schema 指纹口径：服务端 tools/list 与客户端登记必须使用同一投影。
def mcp_tool_schema_sha256(
    *,
    name: str,
    description: str | None,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any] | None = None,
) -> str:
    projection = {
        "name": name,
        "description": description or "",
        "inputSchema": cast(JsonValue, input_schema),
        "outputSchema": cast(JsonValue, output_schema),
    }
    return sha256_json(cast(JsonValue, projection))


# 公开服务描述只包含部署侧固定信息；凭据不在模型字段中，不能随 JSON 投影外泄。
class LocalMcpServiceDescriptor(AgentModel):
    server_id: str = DEFAULT_MCP_SERVER_ID
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(ge=1, le=65_535)
    path: str = MCP_SERVICE_PATH
    protocol_version: str = MCP_PROTOCOL_VERSION
    tools: tuple[McpToolDescriptor, ...] = ()

    @field_validator("server_id")
    @classmethod
    def validate_server_id(cls, value: str) -> str:
        if _SERVER_ID.fullmatch(value) is None:
            raise ValueError("MCP 服务标识必须是稳定短标识")
        return value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if (
            _PATH.fullmatch(value) is None
            or "//" in value
            or "/../" in value
            or value.endswith("/..")
            or value == "/"
        ):
            raise ValueError("MCP 路径必须是固定绝对路径且不能包含遍历")
        return value

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        if value not in SUPPORTED_MCP_PROTOCOL_VERSIONS:
            raise ValueError("MCP 协议版本不在支持集合内")
        return value

    @field_validator("tools")
    @classmethod
    def validate_tools(
        cls,
        value: tuple[McpToolDescriptor, ...],
    ) -> tuple[McpToolDescriptor, ...]:
        names = tuple(item.name for item in value)
        if len(set(names)) != len(names):
            raise ValueError("MCP 工具名称不能重复登记")
        return value

    # 固定 loopback URL；不接受用户提供的 query、fragment 或外部主机。
    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}{self.path}"

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.tools)

    # 读取登记 Schema 指纹；缺失工具明确失败，而不是退回“未校验”。
    def schema_sha256(self, tool_name: str) -> str:
        for item in self.tools:
            if item.name == tool_name:
                return item.schema_sha256
        raise McpRegistryError("tool_schema_unregistered")


# 客户端端点额外声明传输上限；上限由部署登记，模型不能调大。
class McpEndpoint(LocalMcpServiceDescriptor):
    max_json_body_bytes: int = Field(
        default=MAX_MCP_JSON_BODY_BYTES,
        ge=128,
        le=MAX_MCP_JSON_BODY_BYTES,
    )
    max_sse_event_bytes: int = Field(
        default=MAX_MCP_SSE_EVENT_BYTES,
        ge=128,
        le=MAX_MCP_SSE_EVENT_BYTES,
    )
    max_transport_requests: int = Field(
        default=MAX_MCP_TRANSPORT_REQUESTS,
        ge=1,
        le=256,
    )


# 启动时冻结的端点集合；同一工具只能属于一个端点，避免按名称模糊路由到未登记服务。
class McpEndpointRegistry:
    def __init__(
        self,
        endpoints: Iterable[McpEndpoint],
        *,
        credential: McpServiceCredential,
    ) -> None:
        isolated = tuple(
            McpEndpoint.model_validate(copy.deepcopy(item.model_dump(mode="python")))
            for item in endpoints
        )
        if not isolated:
            raise McpRegistryError("endpoint_registry_empty")
        server_ids = tuple(item.server_id for item in isolated)
        if len(set(server_ids)) != len(server_ids):
            raise McpRegistryError("duplicate_server")
        tool_owner: dict[str, str] = {}
        for endpoint in isolated:
            for tool_name in endpoint.tool_names:
                if tool_name in tool_owner:
                    raise McpRegistryError("duplicate_tool_registration")
                tool_owner[tool_name] = endpoint.server_id
        self._endpoints = isolated
        self._credential = credential
        self._catalog_sha256 = sha256_json(
            cast(
                JsonValue,
                [item.model_dump(mode="json") for item in self.descriptors()],
            )
        )

    @property
    def credential(self) -> McpServiceCredential:
        return self._credential

    @property
    def catalog_sha256(self) -> str:
        return self._catalog_sha256

    # 按固定服务标识解析；未知标识不得回退到默认端点。
    def resolve(self, server_id: str) -> McpEndpoint:
        for endpoint in self._endpoints:
            if endpoint.server_id == server_id:
                return endpoint
        raise McpRegistryError("server_not_registered")

    # 按工具名解析唯一端点；未登记工具在发送前拒绝。
    def for_tool(self, tool_name: str) -> McpEndpoint:
        for endpoint in self._endpoints:
            if tool_name in endpoint.tool_names:
                return endpoint
        raise McpRegistryError("tool_not_registered")

    # 供宿主装配/能力接口使用的安全描述；不含凭据和内部传输上限。
    def descriptors(self) -> tuple[LocalMcpServiceDescriptor, ...]:
        return tuple(
            LocalMcpServiceDescriptor(
                server_id=endpoint.server_id,
                host=endpoint.host,
                port=endpoint.port,
                path=endpoint.path,
                protocol_version=endpoint.protocol_version,
                tools=endpoint.tools,
            )
            for endpoint in self._endpoints
        )


__all__ = [
    "DEFAULT_MCP_SERVER_ID",
    "MCP_MOUNT_PATH",
    "MCP_PROTOCOL_VERSION",
    "MCP_SERVICE_PATH",
    "MCP_TOOL_PATH",
    "MAX_MCP_JSON_BODY_BYTES",
    "MAX_MCP_RESULT_BYTES",
    "MAX_MCP_SSE_EVENT_BYTES",
    "MAX_MCP_SUMMARY_BYTES",
    "MAX_MCP_TRANSPORT_REQUESTS",
    "SUPPORTED_MCP_PROTOCOL_VERSIONS",
    "LocalMcpServiceDescriptor",
    "McpEndpoint",
    "McpEndpointRegistry",
    "McpRegistryError",
    "McpServiceCredential",
    "McpToolDescriptor",
    "mcp_tool_schema_sha256",
]
