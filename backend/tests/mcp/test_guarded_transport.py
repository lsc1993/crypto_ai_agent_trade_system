# 验证 MCP 传输层守卫：固定端点、逐请求记账、拒绝 3xx、JSON/SSE 载荷上限。
# 同时用官方 SDK 证明 redirect 不会由 SDK 自行跟随，超限 JSON/SSE 在解析前失败。
# 测试只连接本机临时 stub 服务；不访问外部 MCP、不调用模型、不读写账户或业务库。
from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from app.infrastructure.mcp.registry import (
    MAX_MCP_JSON_BODY_BYTES,
    MAX_MCP_SSE_EVENT_BYTES,
    McpEndpoint,
    McpServiceCredential,
)
from app.infrastructure.mcp.transport import (
    BoundedMcpTransport,
    McpTransportError,
    build_http_client,
)
from tests.mcp.support import serve_loopback


def _credential() -> McpServiceCredential:
    return McpServiceCredential.from_token("t" * 48)


# 固定端点；测试显式覆盖端口/路径/上限，避免真实部署值被测试默认值掩盖。
def _endpoint(
    *,
    port: int = 9_000,
    path: str = "/mcp",
    max_json_body_bytes: int = MAX_MCP_JSON_BODY_BYTES,
    max_sse_event_bytes: int = MAX_MCP_SSE_EVENT_BYTES,
    max_transport_requests: int = 8,
) -> McpEndpoint:
    return McpEndpoint(
        server_id="test_mcp",
        host="127.0.0.1",
        port=port,
        path=path,
        protocol_version="2026-07-28",
        tools=(),
        max_json_body_bytes=max_json_body_bytes,
        max_sse_event_bytes=max_sse_event_bytes,
        max_transport_requests=max_transport_requests,
    )


class _RecordingTransport(httpx2.AsyncBaseTransport):
    # 返回固定响应并记录真实进入内层传输的请求；用于证明守卫在发送前生效。
    def __init__(self, factory: Callable[[httpx2.Request], httpx2.Response]) -> None:
        self._factory = factory
        self.requests: list[httpx2.Request] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self._factory(request)


def _json_response(
    request: httpx2.Request,
    body: bytes,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx2.Response:
    merged = {"content-type": "application/json"}
    if headers:
        merged.update(headers)
    return httpx2.Response(status_code, headers=merged, content=body, request=request)


@pytest.mark.asyncio
async def test_unregistered_origin_and_path_are_rejected_before_inner_send() -> None:
    inner = _RecordingTransport(lambda request: _json_response(request, b"{}"))
    guarded = BoundedMcpTransport(inner=inner, endpoint=_endpoint())
    async with httpx2.AsyncClient(transport=guarded) as client:
        with pytest.raises(McpTransportError) as origin_error:
            await client.get("http://127.0.0.1:9001/mcp")
        assert origin_error.value.code == "endpoint_not_registered"
        with pytest.raises(McpTransportError) as path_error:
            await client.get("http://127.0.0.1:9000/other")
        assert path_error.value.code == "endpoint_not_registered"
    assert inner.requests == []


@pytest.mark.asyncio
async def test_transport_counts_each_request_and_caps_hidden_retries() -> None:
    inner = _RecordingTransport(lambda request: _json_response(request, b"{}"))
    guarded = BoundedMcpTransport(inner=inner, endpoint=_endpoint(max_transport_requests=2))
    async with httpx2.AsyncClient(transport=guarded) as client:
        assert (await client.get("http://127.0.0.1:9000/mcp")).status_code == 200
        assert (await client.get("http://127.0.0.1:9000/mcp")).status_code == 200
        with pytest.raises(McpTransportError) as error:
            await client.get("http://127.0.0.1:9000/mcp")
        assert error.value.code == "transport_limit_exceeded"
    assert guarded.request_count == 2
    assert len(inner.requests) == 2


@pytest.mark.asyncio
async def test_redirects_are_rejected_before_sdk_can_follow() -> None:
    inner = _RecordingTransport(
        lambda request: httpx2.Response(
            307,
            headers={"location": "http://127.0.0.1:9000/redirected"},
            request=request,
        )
    )
    guarded = BoundedMcpTransport(inner=inner, endpoint=_endpoint())
    async with httpx2.AsyncClient(transport=guarded) as client:
        with pytest.raises(McpTransportError) as error:
            await client.post("http://127.0.0.1:9000/mcp", json={})
        assert error.value.code == "redirect_rejected"
    assert len(inner.requests) == 1


@pytest.mark.asyncio
async def test_json_body_limit_is_enforced_exactly() -> None:
    bodies = iter((b"x" * 1_024, b"y" * 1_025))
    inner = _RecordingTransport(lambda request: _json_response(request, next(bodies)))
    guarded = BoundedMcpTransport(inner=inner, endpoint=_endpoint(max_json_body_bytes=1_024))
    async with httpx2.AsyncClient(transport=guarded) as client:
        accepted = await client.get("http://127.0.0.1:9000/mcp")
        assert accepted.content == b"x" * 1_024
        with pytest.raises(McpTransportError) as error:
            await client.get("http://127.0.0.1:9000/mcp")
        assert error.value.code == "payload_too_large"


# 默认上限必须精确为 64 KiB；多 1 字节也不能送入 SDK 解析。
@pytest.mark.asyncio
async def test_default_json_limit_is_exactly_64_kib() -> None:
    bodies = iter((b"x" * MAX_MCP_JSON_BODY_BYTES, b"y" * (MAX_MCP_JSON_BODY_BYTES + 1)))
    inner = _RecordingTransport(lambda request: _json_response(request, next(bodies)))
    guarded = BoundedMcpTransport(inner=inner, endpoint=_endpoint())
    async with httpx2.AsyncClient(transport=guarded) as client:
        accepted = await client.get("http://127.0.0.1:9000/mcp")
        assert len(accepted.content) == MAX_MCP_JSON_BODY_BYTES
        with pytest.raises(McpTransportError) as error:
            await client.get("http://127.0.0.1:9000/mcp")
        assert error.value.code == "payload_too_large"


# 真实 SDK 路径：同源 307 不会被 SDK 跟随；超限 JSON 在结果解析前失败。
# 每次失败都只产生一个实际 HTTP 请求，证明没有隐藏的重发或跳转后调用。
@pytest.mark.asyncio
async def test_sdk_redirect_retry_and_json_body_are_guarded() -> None:
    redirected_hits: list[str] = []

    async def redirect_mcp(request: Request) -> Response:
        _ = request
        return RedirectResponse("/redirected", status_code=307)

    async def redirected(request: Request) -> Response:
        redirected_hits.append(str(request.url))
        return JSONResponse({"jsonrpc": "2.0", "id": 1, "result": {}})

    redirect_app = Starlette(
        routes=[
            Route("/mcp", redirect_mcp, methods=["POST", "GET"]),
            Route("/redirected", redirected, methods=["POST", "GET"]),
        ]
    )
    async with serve_loopback(redirect_app) as (_, redirect_port):
        endpoint = _endpoint(port=redirect_port)
        transport = BoundedMcpTransport(
            inner=httpx2.AsyncHTTPTransport(),
            endpoint=endpoint,
        )
        http_client = build_http_client(endpoint, _credential(), transport=transport)
        mcp_transport = streamable_http_client(
            endpoint.url,
            http_client=http_client,
            max_sse_event_size=endpoint.max_sse_event_bytes,
        )
        client = Client(mcp_transport, mode="2026-07-28")
        with pytest.raises((McpTransportError, BaseExceptionGroup)):
            async with client:
                await client.list_tools()
        await http_client.aclose()
        assert redirected_hits == []
        assert transport.request_count == 1

    async def oversized_json(request: Request) -> Response:
        _ = request
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"tools": [], "padding": "x" * 5_000},
            }
        )

    oversized_app = Starlette(routes=[Route("/mcp", oversized_json, methods=["POST", "GET"])])
    async with serve_loopback(oversized_app) as (_, oversized_port):
        endpoint = _endpoint(port=oversized_port, max_json_body_bytes=1_024)
        transport = BoundedMcpTransport(
            inner=httpx2.AsyncHTTPTransport(),
            endpoint=endpoint,
        )
        http_client = build_http_client(endpoint, _credential(), transport=transport)
        mcp_transport = streamable_http_client(
            endpoint.url,
            http_client=http_client,
            max_sse_event_size=endpoint.max_sse_event_bytes,
        )
        client = Client(mcp_transport, mode="2026-07-28")
        with pytest.raises((McpTransportError, BaseExceptionGroup)):
            async with client:
                await client.list_tools()
        await http_client.aclose()
        assert transport.request_count == 1


# SSE 事件上限由 SDK 解析器执行；传输层用同一登记值配置 SDK，不允许无限缓冲。
@pytest.mark.asyncio
async def test_sdk_sse_event_limit_is_enforced() -> None:
    async def oversized_sse(request: Request) -> Response:
        _ = request
        event = b"event: message\ndata: " + b"x" * 2_048 + b"\n\n"
        return Response(event, media_type="text/event-stream")

    app = Starlette(routes=[Route("/mcp", oversized_sse, methods=["POST", "GET"])])
    async with serve_loopback(app) as (_, port):
        endpoint = _endpoint(port=port, max_sse_event_bytes=512)
        transport = BoundedMcpTransport(inner=httpx2.AsyncHTTPTransport(), endpoint=endpoint)
        http_client = build_http_client(endpoint, _credential(), transport=transport)
        mcp_transport = streamable_http_client(
            endpoint.url,
            http_client=http_client,
            max_sse_event_size=endpoint.max_sse_event_bytes,
        )
        client = Client(mcp_transport, mode="2026-07-28")
        with pytest.raises((McpTransportError, BaseExceptionGroup)):
            async with client:
                await client.list_tools()
        await http_client.aclose()
        assert transport.request_count == 1


# 未登记工具/协议版本属于配置错误；这里只证明端点模型拒绝非 loopback 主机。
def test_endpoint_rejects_non_loopback_host() -> None:
    with pytest.raises(ValueError):
        McpEndpoint.model_validate(
            {
                "server_id": "test_mcp",
                "host": "example.com",
                "port": 443,
                "path": "/mcp",
                "protocol_version": "2026-07-28",
                "tools": [],
            }
        )


def test_internal_credential_is_not_serialized_in_public_descriptor() -> None:
    credential = McpServiceCredential.from_token(f"secret-{uuid4().hex}")
    endpoint = _endpoint()
    assert credential.token.get_secret_value() not in endpoint.model_dump_json()
    assert endpoint.url == "http://127.0.0.1:9000/mcp"
