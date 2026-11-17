# MCP 传输测试共用辅助：在真实 loopback TCP 端口上启动最小 ASGI 应用。
# 测试必须经过实际 socket 证明 Streamable HTTP 路径，不能用内存 transport 代替。
# 辅助代码不读取业务配置、.env、模型或账户，也不发起真实外部网络请求。
from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

import uvicorn
from starlette.types import ASGIApp


# 先占用再释放一个 loopback 端口；测试只用于本机短生命周期服务。
def reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# 在后台运行 uvicorn 并等待 ready；退出时请求关闭并等待任务完成，避免泄漏任务。
@asynccontextmanager
async def serve_loopback(
    app: ASGIApp,
    *,
    port: int | None = None,
) -> AsyncGenerator[tuple[uvicorn.Server, int]]:
    resolved_port = reserve_loopback_port() if port is None else port
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=resolved_port,
        lifespan="on",
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(300):
            if server.started:
                break
            if task.done():
                task.result()
            await asyncio.sleep(0.01)
        else:  # pragma: no cover - 仅在环境异常时触发
            raise RuntimeError("uvicorn 未在限定时间内启动")
        yield server, resolved_port
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=15)
        except TimeoutError:  # pragma: no cover - 仅在关闭异常时触发
            task.cancel()
            with suppress(BaseException):
                await task
