# MCP 专用有界 HTTP 传输：在官方 SDK 之前拒绝未登记端点、3xx、超额请求与超大 JSON。
# SDK 会自行跟随同源 307/308，因此守卫必须位于 httpx2 transport 层，
# 而不是只设置 follow_redirects=False。
# 每个实际 HTTP 请求（含 SDK 后台重连/重列）都经过这里计数并受同一上限约束。
# 本模块不读取模型、业务库或凭据内容；Authorization 由调用方注入 httpx2 客户端。
from __future__ import annotations

import httpx2

from app.infrastructure.mcp.registry import McpEndpoint, McpServiceCredential


# 稳定传输错误；对外只暴露固定 code，不包含 URL、响应正文或异常链。
class McpTransportError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BoundedMcpTransport(httpx2.AsyncBaseTransport):
    # 包装真实网络 transport；不修改请求头/正文，只做目标、重定向、计数和大小检查。
    def __init__(
        self,
        *,
        inner: httpx2.AsyncBaseTransport,
        endpoint: McpEndpoint,
    ) -> None:
        self._inner = inner
        self._endpoint = endpoint
        self._request_count = 0

    @property
    def request_count(self) -> int:
        return self._request_count

    # 固定主机/端口/路径/无 query；端口未显式书写时按 http 默认 80 比较。
    def _validate_target(self, url: httpx2.URL) -> None:
        port = url.port if url.port is not None else 80
        if (
            url.scheme != "http"
            or url.host != self._endpoint.host
            or port != self._endpoint.port
            or url.path != self._endpoint.path
            or url.query
            or url.fragment
        ):
            raise McpTransportError("endpoint_not_registered")

    # 任何 3xx 都失败；即使 SDK 愿意跟随同源跳转，也不会看到可跟随的响应。
    @staticmethod
    def _reject_redirect(response: httpx2.Response) -> None:
        if 300 <= response.status_code < 400:
            raise McpTransportError("redirect_rejected")

    # JSON/普通响应增量读取并在超过上限时立即中止；SSE 保持流式。
    # 不能先无界 aread 再判断大小，否则恶意服务可用超大响应消耗内存。
    async def _bounded_response(
        self,
        response: httpx2.Response,
        request: httpx2.Request,
    ) -> httpx2.Response:
        content_type = response.headers.get("content-type", "").lower()
        if "text/event-stream" in content_type:
            return response
        declared = response.headers.get("content-length")
        if declared is not None:
            try:
                declared_bytes = int(declared)
            except ValueError as error:
                raise McpTransportError("invalid_content_length") from error
            if declared_bytes > self._endpoint.max_json_body_bytes:
                raise McpTransportError("payload_too_large")
        chunks: list[bytes] = []
        total = 0
        try:
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > self._endpoint.max_json_body_bytes:
                    raise McpTransportError("payload_too_large")
                chunks.append(chunk)
        finally:
            await response.aclose()
        # 返回已解码、已限长的内容；移除仅对原传输编码有效的头，避免重复解码。
        headers = [
            (name, value)
            for name, value in response.headers.multi_items()
            if name.lower() not in {"content-encoding", "content-length", "transfer-encoding"}
        ]
        return httpx2.Response(
            status_code=response.status_code,
            headers=headers,
            content=b"".join(chunks),
            request=request,
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self._validate_target(request.url)
        # 上限检查先于计数：被拒绝的请求没有实际发送，不能计入“已发送”证据。
        if self._request_count >= self._endpoint.max_transport_requests:
            raise McpTransportError("transport_limit_exceeded")
        self._request_count += 1

        response = await self._inner.handle_async_request(request)
        try:
            self._reject_redirect(response)
            return await self._bounded_response(response, request)
        except BaseException:
            await response.aclose()
            raise

    async def aclose(self) -> None:
        await self._inner.aclose()


# 构造固定 loopback HTTP 客户端：禁用代理环境、关闭自动跳转并注入进程内服务凭据。
# 这里不打印 URL/凭据；调用方负责在关闭时显式 await client.aclose()。
def build_http_client(
    endpoint: McpEndpoint,
    credential: McpServiceCredential,
    *,
    transport: BoundedMcpTransport | None = None,
) -> httpx2.AsyncClient:
    guarded = transport or BoundedMcpTransport(
        inner=httpx2.AsyncHTTPTransport(),
        endpoint=endpoint,
    )
    return httpx2.AsyncClient(
        transport=guarded,
        headers={
            "Authorization": credential.authorization_header(),
            "Accept": "application/json, text/event-stream",
        },
        timeout=httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        follow_redirects=False,
        trust_env=False,
        max_redirects=0,
    )


__all__ = [
    "BoundedMcpTransport",
    "McpTransportError",
    "build_http_client",
]
