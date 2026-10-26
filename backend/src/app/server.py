# 提供 Uvicorn 进程入口以及 Windows 异步事件循环兼容配置。
# 启动服务器之前设置 Selector 策略，并为 Windows 显式提供 loop 工厂。
# 这里只解决 Psycopg 的平台兼容性，不负责创建数据库 schema 或执行业务任务。
"""应用进程入口及平台级 asyncio 兼容配置。"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from typing import cast

import uvicorn


# 只在 win32 设置 Selector 策略并返回是否设置；工厂可注入以验证兼容分支。
def configure_windows_selector_event_loop_policy(
    *,
    platform: str | None = None,
    policy_factory: Callable[[], asyncio.AbstractEventLoopPolicy] | None = None,
) -> bool:
    """Use SelectorEventLoop for Psycopg async connections on Windows."""
    if (sys.platform if platform is None else platform) != "win32":
        return False
    factory = policy_factory or _windows_selector_policy_factory()
    if factory is None:
        raise RuntimeError("当前 Python 运行时不支持 Windows SelectorEventLoop")
    asyncio.set_event_loop_policy(factory())  # pyright: ignore[reportDeprecated]
    return True


# 先处理平台事件循环前提，再监听 8000 并加载 app.main:app；调用产生进程级监听副作用。
def run_api() -> None:
    """Configure platform prerequisites before Uvicorn creates an event loop."""
    configure_windows_selector_event_loop_policy()
    loop = "app.server:windows_selector_event_loop_factory" if sys.platform == "win32" else "auto"
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, loop=loop)


# 返回 Uvicorn 在 Windows 使用的 SelectorEventLoop，确保异步 PostgreSQL 驱动可运行。
def windows_selector_event_loop_factory() -> asyncio.AbstractEventLoop:
    """Create the loop Uvicorn must use with Psycopg on Windows."""
    return asyncio.SelectorEventLoop()


def _windows_selector_policy_factory() -> Callable[[], asyncio.AbstractEventLoopPolicy] | None:
    policy_factory = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_factory is None:
        return None
    return cast(Callable[[], asyncio.AbstractEventLoopPolicy], policy_factory)
