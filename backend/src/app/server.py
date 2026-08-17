"""应用进程入口及平台级 asyncio 兼容配置。"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from typing import cast

import uvicorn


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


def run_api() -> None:
    """Configure platform prerequisites before Uvicorn creates an event loop."""
    configure_windows_selector_event_loop_policy()
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)


def _windows_selector_policy_factory() -> Callable[[], asyncio.AbstractEventLoopPolicy] | None:
    policy_factory = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_factory is None:
        return None
    return cast(Callable[[], asyncio.AbstractEventLoopPolicy], policy_factory)
