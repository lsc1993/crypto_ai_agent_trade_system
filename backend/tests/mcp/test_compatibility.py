# 锁定 MCP SDK/协议/依赖兼容性，并核对本地只读服务只登记一个工具。
# 直接读取已安装包元数据和 uv.lock；不联网、不安装依赖、不调用模型或账户。
from __future__ import annotations

import sys
import tomllib
from importlib.metadata import version
from pathlib import Path
from uuid import UUID

import pytest
from packaging.requirements import Requirement

from app.infrastructure.mcp.registry import (
    MAX_MCP_JSON_BODY_BYTES,
    MAX_MCP_SSE_EVENT_BYTES,
    MAX_MCP_SUMMARY_BYTES,
    MAX_MCP_TRANSPORT_REQUESTS,
    MCP_PROTOCOL_VERSION,
)
from app.infrastructure.mcp.server import build_research_mcp
from app.research.strategies.contracts import StrategyDraft, StrategyVersion
from app.shared.agent_types import PageQuery, VersionPage, VersionRef

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class _UnavailableCatalog:
    # describe() 不读取策略；任何实际读取都应显式失败，避免测试意外依赖业务目录。
    async def get_published(self, workspace_id: UUID, ref: VersionRef) -> StrategyVersion:
        _ = (workspace_id, ref)
        raise AssertionError("兼容性测试不应读取策略")

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


def _locked_versions() -> dict[str, str]:
    lock = tomllib.loads((BACKEND_ROOT / "uv.lock").read_text(encoding="utf-8"))
    return {str(package["name"]): str(package["version"]) for package in lock["package"]}


def test_mcp_sdk_and_protocol_are_locked_to_the_reviewed_versions() -> None:
    assert sys.version_info[:2] == (3, 12)
    assert version("mcp") == "2.3.0"
    assert version("mcp-types") == "2.3.0"
    assert version("httpx2").split(".")[0] == "2"
    assert MCP_PROTOCOL_VERSION == "2026-07-28"

    # 协议版本必须来自 SDK 实际支持集合，不能只靠项目常量宣称可用。
    from mcp_types.version import MODERN_PROTOCOL_VERSIONS

    assert MCP_PROTOCOL_VERSION in MODERN_PROTOCOL_VERSIONS


def test_dependency_declarations_add_only_the_mcp_adapter() -> None:
    pyproject = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = tuple(str(item) for item in pyproject["project"]["dependencies"])
    requirements = {Requirement(item).name: item for item in dependencies}

    assert requirements["mcp"].startswith("mcp==")
    assert requirements["httpx2"].startswith("httpx2")
    assert "[" not in requirements["mcp"]
    assert not any(
        item.startswith(("ccxt", "binance", "coinbase", "okra")) for item in dependencies
    )

    locked = _locked_versions()
    assert locked["mcp"] == "2.3.0"
    assert locked["httpx2"].startswith("2.")
    # 既有框架版本不能因 MCP 依赖求解而被顺手升级。
    assert locked["langgraph"] == "1.2.10"
    assert locked["langgraph-checkpoint-postgres"] == "3.1.2"
    assert locked["langchain-core"] == "1.5.3"


@pytest.mark.asyncio
async def test_research_service_exposes_only_the_strategy_definition_tool() -> None:
    runtime = build_research_mcp(_UnavailableCatalog(), port=9_998)
    descriptor = await runtime.describe()

    assert descriptor.server_id == "local_research"
    assert descriptor.protocol_version == MCP_PROTOCOL_VERSION
    assert descriptor.tool_names == ("read_strategy_definition",)
    assert descriptor.path == "/internal/agent-mcp/mcp"
    assert len(descriptor.tools[0].schema_sha256) == 64
    assert "bearer" not in descriptor.model_dump_json().lower()


def test_mcp_limits_are_fixed_to_the_reviewed_values() -> None:
    assert MAX_MCP_JSON_BODY_BYTES == 64 * 1024
    assert MAX_MCP_SSE_EVENT_BYTES == 64 * 1024
    assert MAX_MCP_SUMMARY_BYTES == 8 * 1024
    assert MAX_MCP_TRANSPORT_REQUESTS == 64
