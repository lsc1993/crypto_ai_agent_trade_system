# 验证本地只读 MCP 服务的宿主生命周期：显式启动/关闭 session manager，且不泄漏任务。
# 同时核对未认证请求在 lifespan 生效后返回安全 401，不进入 MCP 工具处理器。
# 仅使用本机 loopback 临时端口；不访问外部服务、模型、账户或业务库。
from __future__ import annotations

import asyncio
from uuid import UUID

import httpx2
import pytest

from app.infrastructure.mcp.server import build_research_mcp
from app.research.strategies.contracts import StrategyDraft, StrategyVersion
from app.shared.agent_types import PageQuery, VersionPage, VersionRef
from tests.mcp.support import reserve_loopback_port, serve_loopback


class _UnavailableCatalog:
    async def get_published(self, workspace_id: UUID, ref: VersionRef) -> StrategyVersion:
        _ = (workspace_id, ref)
        raise AssertionError("生命周期测试不应读取策略")

    async def publish(
        self,
        workspace_id: UUID,
        draft_id: UUID,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> StrategyVersion:
        _ = (workspace_id, draft_id, expected_version, request_id)
        raise NotImplementedError

    async def create_draft(
        self,
        workspace_id: UUID,
        draft: StrategyDraft,
        *,
        request_id: UUID,
    ) -> StrategyDraft:
        _ = (workspace_id, draft, request_id)
        raise NotImplementedError

    async def update_draft(
        self,
        workspace_id: UUID,
        draft_id: UUID,
        draft: StrategyDraft,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> StrategyDraft:
        _ = (workspace_id, draft_id, draft, expected_version, request_id)
        raise NotImplementedError

    async def list_versions(
        self,
        workspace_id: UUID,
        query: PageQuery,
    ) -> VersionPage[StrategyVersion]:
        _ = (workspace_id, query)
        raise NotImplementedError

    async def archive(
        self,
        workspace_id: UUID,
        strategy_id: UUID,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> None:
        _ = (workspace_id, strategy_id, expected_version, request_id)
        raise NotImplementedError


@pytest.mark.asyncio
async def test_runtime_lifespan_manages_session_manager_exactly_once() -> None:
    runtime = build_research_mcp(_UnavailableCatalog(), port=9_997)
    async with runtime.lifespan():
        descriptor = await runtime.describe()
        assert descriptor.tool_names == ("read_strategy_definition",)

    # SDK manager 只允许启动一次；重复进入必须显式失败，不能静默复用旧任务组。
    with pytest.raises(RuntimeError):
        async with runtime.lifespan():
            pass


@pytest.mark.asyncio
async def test_uvicorn_lifespan_serves_and_shuts_down_cleanly() -> None:
    port = reserve_loopback_port()
    runtime = build_research_mcp(_UnavailableCatalog(), port=port)
    async with serve_loopback(runtime.app, port=port) as (server, actual_port):
        assert actual_port == port
        assert server.started is True
        async with httpx2.AsyncClient() as client:
            response = await client.post(
                f"http://127.0.0.1:{port}/internal/agent-mcp/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
        assert response.status_code == 401

    assert server.should_exit is True
    # uvicorn 退出后同一 manager 不得再次启动成功；证明关闭路径真实执行过。
    with pytest.raises(RuntimeError):
        async with runtime.lifespan():
            pass


@pytest.mark.asyncio
async def test_shutdown_does_not_leave_mcp_tasks_running() -> None:
    port = reserve_loopback_port()
    runtime = build_research_mcp(_UnavailableCatalog(), port=port)
    baseline = {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}
    async with serve_loopback(runtime.app, port=port):
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.05)
    remaining = {
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and task not in baseline and not task.done()
    }
    assert remaining == set()
