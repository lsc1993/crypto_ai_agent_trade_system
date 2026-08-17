from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app import server


def test_windows_server_uses_selector_policy_before_creating_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_policy = asyncio.DefaultEventLoopPolicy()
    installed_policies: list[asyncio.AbstractEventLoopPolicy | None] = []
    monkeypatch.setattr(asyncio, "set_event_loop_policy", installed_policies.append)

    configured = server.configure_windows_selector_event_loop_policy(
        platform="win32",
        policy_factory=lambda: selected_policy,
    )

    assert configured is True
    assert installed_policies == [selected_policy]


def test_non_windows_server_does_not_replace_the_event_loop_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed_policies: list[asyncio.AbstractEventLoopPolicy | None] = []
    monkeypatch.setattr(asyncio, "set_event_loop_policy", installed_policies.append)

    configured = server.configure_windows_selector_event_loop_policy(
        platform="linux",
        policy_factory=asyncio.DefaultEventLoopPolicy,
    )

    assert configured is False
    assert installed_policies == []


def test_windows_run_api_creates_selector_event_loop_for_psycopg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def record_run(app: str, **kwargs: Any) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(server.sys, "platform", "win32")
    monkeypatch.setattr(server.uvicorn, "run", record_run)

    server.run_api()

    config = server.uvicorn.Config(captured["app"], loop=captured["loop"])
    loop_factory = config.get_loop_factory()
    assert loop_factory is not None
    loop = loop_factory()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()
