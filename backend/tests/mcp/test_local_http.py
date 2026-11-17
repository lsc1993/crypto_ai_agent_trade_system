# 验证本地只读 MCP 服务经真实 loopback TCP 与 T09 工具网关协同工作。
# 覆盖服务凭据、协议/工具 Schema 固定、真实工具执行、不可用降级与描述符不泄露令牌。
# 使用合成策略和工作台标识；不连接外部 MCP、不调用模型、不读写账户或业务库。
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx2
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

from app.agent.interactive.adapters.technical_strategy import TECHNICAL_BREAKOUT_PARAMETER_SCHEMA
from app.agent.interactive.tools.contracts import (
    ToolObservationStatus,
    ToolQuality,
    ToolRequest,
    ToolResultStatus,
)
from app.agent.interactive.tools.gateway import ToolGateway
from app.agent.interactive.tools.registry import ToolRegistry
from app.agent.interactive.tools.research_tools import strategy_definition_tool
from app.agent_runs.attempts import (
    AttemptCategory,
    AttemptRequest,
    AttemptResult,
    AttemptStatus,
    StepAttempt,
)
from app.agent_runs.budget import (
    BudgetLimits,
    BudgetStatus,
    initial_budget_limits,
)
from app.agent_runs.contracts import RunInput, RunSnapshot, RunStatus
from app.agent_runs.segments import ExecutionContext, RunFence
from app.infrastructure.mcp.client import McpToolClient
from app.infrastructure.mcp.registry import (
    MAX_MCP_JSON_BODY_BYTES,
    MAX_MCP_SSE_EVENT_BYTES,
    MAX_MCP_TRANSPORT_REQUESTS,
    McpEndpoint,
    McpEndpointRegistry,
    McpRegistryError,
    McpServiceCredential,
    McpToolDescriptor,
)
from app.infrastructure.mcp.server import build_research_mcp
from app.market.contracts import MarketTimeframe
from app.research.strategies.contracts import (
    StrategyCapability,
    StrategyDraft,
    StrategyKind,
    StrategyVersion,
)
from app.shared.agent_types import ArtifactRef, PageQuery, ProductKey, VersionPage, VersionRef
from tests.mcp.support import reserve_loopback_port, serve_loopback

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
WORKSPACE_ID = uuid4()
RUN_ID = uuid4()
SEGMENT_ID = uuid4()
OWNER_ID = uuid4()


def _strategy(*, method_text: str = "价格突破结构并回踩确认后设置结构止损。") -> StrategyVersion:
    draft = StrategyDraft(
        draft_id=uuid4(),
        strategy_id=uuid4(),
        name="合成技术突破策略",
        method_text=method_text,
        kind=StrategyKind.SINGLE,
        parameter_schema=TECHNICAL_BREAKOUT_PARAMETER_SCHEMA,
        supported_symbols=("BTCUSDT",),
        supported_timeframes=(MarketTimeframe.H1, MarketTimeframe.H4),
        warmup_candles=200,
        evaluator_id="technical_breakout_v1",
        capabilities=(
            StrategyCapability.RESEARCH,
            StrategyCapability.PRICE_CANDIDATE,
            StrategyCapability.MANUAL_PLANNING,
        ),
        risk_notes="止损触发不保证成交；计划必须经过确定性风险检查。",
    )
    return StrategyVersion.from_draft(draft, published_at=NOW, state_version=1)


class SpyCatalog:
    # 服务端只允许从冻结目录读取；其他写接口在这里明确不可用。
    def __init__(self, strategy: StrategyVersion) -> None:
        self.strategy = strategy
        self.calls: list[tuple[UUID, VersionRef]] = []

    async def get_published(self, workspace_id: UUID, ref: VersionRef) -> StrategyVersion:
        self.calls.append((workspace_id, ref))
        if ref != self.strategy.ref:
            raise AssertionError("读取了非当前策略版本")
        return self.strategy

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


class FakeRuns:
    def __init__(self, snapshot: RunSnapshot) -> None:
        self.snapshot = snapshot

    async def get(self, workspace_id: UUID, run_id: UUID) -> RunSnapshot | None:
        if workspace_id == self.snapshot.workspace_id and run_id == self.snapshot.run_id:
            return self.snapshot
        return None


class FakeBudget:
    # 只记录网关预留/发送/结算顺序；不替代真实 SQL 预算账本的并发与围栏。
    def __init__(self) -> None:
        self.requests: list[AttemptRequest] = []
        self.results: list[tuple[UUID, AttemptResult]] = []
        self._attempts: dict[UUID, StepAttempt] = {}

    async def reserve(self, fence: RunFence, request: AttemptRequest) -> StepAttempt:
        self.requests.append(request)
        attempt = StepAttempt(
            attempt_id=uuid4(),
            step_id=uuid4(),
            run_id=fence.run_id,
            revision=fence.revision,
            segment_id=fence.segment_id,
            attempt_number=1,
            category=AttemptCategory.TOOL,
            action_sequence=request.action_sequence,
            input_sha256=request.input_sha256,
            status=AttemptStatus.PREPARED,
            reserved_input_tokens=0,
            reserved_output_tokens=0,
            created_at=NOW,
        )
        self._attempts[attempt.attempt_id] = attempt
        return attempt

    async def mark_sent(self, fence: RunFence, attempt_id: UUID) -> None:
        _ = fence
        attempt = self._attempts[attempt_id]
        self._attempts[attempt_id] = attempt.model_copy(
            update={"status": AttemptStatus.IN_FLIGHT, "sent_at": NOW}
        )

    async def settle(
        self,
        fence: RunFence,
        attempt_id: UUID,
        result: AttemptResult,
    ) -> None:
        _ = fence
        self.results.append((attempt_id, result))
        attempt = self._attempts[attempt_id]
        self._attempts[attempt_id] = attempt.model_copy(
            update={
                "status": result.status,
                "result_ref": result.result_ref,
                "reason_code": result.reason_code,
                "settled_at": NOW,
            }
        )

    async def status(self, fence: RunFence) -> BudgetStatus:
        _ = fence
        limits = initial_budget_limits()
        return BudgetStatus(
            model_limit=limits.model_calls,
            tool_limit=limits.tool_calls,
            input_token_limit=limits.input_tokens,
            output_token_limit=limits.output_tokens,
            active_second_limit=limits.active_seconds,
            transport_limit=limits.transport_calls,
            model_calls=0,
            model_sent=0,
            tool_calls=len(self.requests),
            tool_sent=len(self.results),
            transport_calls=0,
            transport_sent=0,
            input_tokens=0,
            output_tokens=0,
            active_seconds=0,
        )

    async def record_activity(self, fence: RunFence, seconds: int) -> BudgetStatus:
        _ = (fence, seconds)
        raise NotImplementedError

    async def append_authorization(
        self,
        fence: RunFence,
        limits: BudgetLimits,
        *,
        authorization_ref: UUID,
        reason: str,
    ) -> BudgetStatus:
        _ = (fence, limits, authorization_ref, reason)
        raise NotImplementedError


def _run_input(strategy: StrategyVersion) -> RunInput:
    return RunInput(
        request_id=uuid4(),
        product=ProductKey(
            venue="binance_usdm",
            symbol="BTCUSDT",
            settlement="USDT",
            kind="linear_perpetual",
        ),
        timeframes=(MarketTimeframe.H1, MarketTimeframe.H4),
        goal="合成 MCP 策略定义读取",
        strategy=strategy.ref,
        parameters={},
    )


def _snapshot(strategy: StrategyVersion) -> RunSnapshot:
    return RunSnapshot(
        run_id=RUN_ID,
        workspace_id=WORKSPACE_ID,
        thread_id=uuid4(),
        revision=1,
        status=RunStatus.RUNNING,
        state_version=1,
        input=_run_input(strategy),
        received_message_seq=0,
        applied_message_seq=0,
        created_at=NOW - timedelta(minutes=1),
        updated_at=NOW - timedelta(minutes=1),
        started_at=NOW - timedelta(seconds=30),
    )


def _context(strategy: StrategyVersion, catalog_sha256: str) -> ExecutionContext:
    return ExecutionContext(
        fence=RunFence(
            workspace_id=WORKSPACE_ID,
            run_id=RUN_ID,
            revision=1,
            segment_id=SEGMENT_ID,
            owner=OWNER_ID,
            lease_epoch=1,
        ),
        strategy_ref=strategy.ref,
        tool_catalog_sha256=catalog_sha256,
        policy_version="interactive_planning_v1",
        budget_authorization_id=uuid4(),
    )


def _endpoint(
    *,
    port: int,
    tools: tuple[McpToolDescriptor, ...],
    protocol_version: str = "2026-07-28",
) -> McpEndpoint:
    return McpEndpoint(
        server_id="local_research",
        host="127.0.0.1",
        port=port,
        path="/internal/agent-mcp/mcp",
        protocol_version=protocol_version,
        tools=tools,
        max_json_body_bytes=MAX_MCP_JSON_BODY_BYTES,
        max_sse_event_bytes=MAX_MCP_SSE_EVENT_BYTES,
        max_transport_requests=MAX_MCP_TRANSPORT_REQUESTS,
    )


class _Harness:
    def __init__(
        self,
        *,
        client: McpToolClient,
        gateway: ToolGateway,
        catalog: SpyCatalog,
        budget: FakeBudget,
        context: ExecutionContext,
    ) -> None:
        self.client = client
        self.gateway = gateway
        self.catalog = catalog
        self.budget = budget
        self.context = context


def _harness(*, registry: McpEndpointRegistry, catalog: SpyCatalog) -> _Harness:
    strategy = catalog.strategy
    budget = FakeBudget()
    tool = strategy_definition_tool()
    client = McpToolClient(registry=registry, tool=tool)
    tool_registry = ToolRegistry([tool])
    gateway = ToolGateway(
        runs=FakeRuns(_snapshot(strategy)),
        budget=budget,
        catalog=tool_registry,
        handlers={tool.name: client},
    )
    client.bind_gateway(gateway)
    return _Harness(
        client=client,
        gateway=gateway,
        catalog=catalog,
        budget=budget,
        context=_context(strategy, tool_registry.catalog_sha256),
    )


def _request(call_id: str = "call-1") -> ToolRequest:
    return ToolRequest(name="read_strategy_definition", arguments={}, call_id=call_id)


@pytest.mark.asyncio
async def test_registered_tool_is_called_through_real_tcp_mcp() -> None:
    port = reserve_loopback_port()
    strategy = _strategy()
    catalog = SpyCatalog(strategy)
    runtime = build_research_mcp(catalog, port=port)
    descriptor = await runtime.describe()
    assert descriptor.tool_names == ("read_strategy_definition",)

    registry = await runtime.build_client_registry()
    harness = _harness(registry=registry, catalog=catalog)
    async with serve_loopback(runtime.app, port=port):
        observation = await harness.client.call(harness.context, _request())

    assert observation.status is ToolObservationStatus.OK
    assert observation.quality is ToolQuality.VALID
    assert observation.result_ref == ArtifactRef(
        artifact_id=strategy.ref.version_id,
        sha256=strategy.ref.sha256,
    )
    assert catalog.calls == [(WORKSPACE_ID, strategy.ref)]
    # SDK 的 discover、tools/list 与 tools/call 每个实际 POST 都被传输层计数。
    assert harness.client.last_request_count == 3
    assert "合成技术突破策略" in observation.safe_summary
    assert "价格突破结构" in observation.safe_summary
    assert len(harness.budget.results) == 1
    assert harness.budget.results[0][1].status is AttemptStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_missing_service_credential_degrades_without_reading_strategy() -> None:
    port = reserve_loopback_port()
    strategy = _strategy()
    catalog = SpyCatalog(strategy)
    runtime = build_research_mcp(catalog, port=port)
    descriptor = await runtime.describe()
    registry = McpEndpointRegistry(
        [_endpoint(port=port, tools=descriptor.tools)],
        credential=McpServiceCredential.from_token("w" * 48),
    )
    harness = _harness(registry=registry, catalog=catalog)
    async with serve_loopback(runtime.app, port=port):
        observation = await harness.client.call(harness.context, _request())

    assert observation.status is ToolObservationStatus.DEGRADED
    assert observation.reason_code == "mcp_unavailable"
    assert catalog.calls == []


@pytest.mark.asyncio
async def test_tool_schema_mismatch_is_rejected_before_service_execution() -> None:
    port = reserve_loopback_port()
    strategy = _strategy()
    catalog = SpyCatalog(strategy)
    credential = McpServiceCredential.from_token("t" * 48)
    runtime = build_research_mcp(catalog, port=port, credential=credential)
    descriptor = await runtime.describe()
    pinned = (
        McpToolDescriptor(
            name="read_strategy_definition",
            schema_sha256="b" * 64,
        ),
    )
    registry = McpEndpointRegistry(
        [_endpoint(port=port, tools=pinned)],
        credential=credential,
    )
    harness = _harness(registry=registry, catalog=catalog)
    async with serve_loopback(runtime.app, port=port):
        observation = await harness.client.call(harness.context, _request())

    assert observation.status is ToolObservationStatus.DEGRADED
    assert observation.reason_code == "mcp_tool_catalog_mismatch"
    assert catalog.calls == []
    assert descriptor.tools[0].schema_sha256 != "b" * 64


@pytest.mark.asyncio
async def test_protocol_mismatch_is_reported_without_strategy_read() -> None:
    port = reserve_loopback_port()
    strategy = _strategy()
    catalog = SpyCatalog(strategy)
    credential = McpServiceCredential.from_token("t" * 48)
    runtime = build_research_mcp(catalog, port=port, credential=credential)
    descriptor = await runtime.describe()
    registry = McpEndpointRegistry(
        [_endpoint(port=port, tools=descriptor.tools, protocol_version="2025-11-25")],
        credential=credential,
    )
    harness = _harness(registry=registry, catalog=catalog)
    async with serve_loopback(runtime.app, port=port):
        observation = await harness.client.call(harness.context, _request())

    assert observation.status is ToolObservationStatus.DEGRADED
    assert observation.reason_code == "mcp_protocol_mismatch"
    assert catalog.calls == []
    assert harness.client.last_request_count == 0


@pytest.mark.asyncio
async def test_internal_endpoint_requires_service_credential() -> None:
    port = reserve_loopback_port()
    runtime = build_research_mcp(SpyCatalog(_strategy()), port=port)
    async with serve_loopback(runtime.app, port=port):
        async with httpx2.AsyncClient(trust_env=False) as client:
            response = await client.post(
                f"http://127.0.0.1:{port}/internal/agent-mcp/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
    assert response.status_code == 401
    assert response.json() == {"code": "mcp_unauthorized"}


@pytest.mark.asyncio
async def test_internal_endpoint_rejects_unregistered_host_header() -> None:
    port = reserve_loopback_port()
    credential = McpServiceCredential.from_token("t" * 48)
    runtime = build_research_mcp(SpyCatalog(_strategy()), port=port, credential=credential)
    async with serve_loopback(runtime.app, port=port):
        async with httpx2.AsyncClient(trust_env=False) as client:
            response = await client.post(
                f"http://127.0.0.1:{port}/internal/agent-mcp/mcp",
                headers={
                    "Host": "evil.example",
                    "Authorization": credential.authorization_header(),
                },
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
    assert response.status_code == 421


@pytest.mark.asyncio
async def test_public_descriptor_never_contains_the_service_credential() -> None:
    credential = McpServiceCredential.from_token("z" * 48)
    strategy = _strategy()
    runtime = build_research_mcp(SpyCatalog(strategy), port=9_999, credential=credential)
    descriptor = await runtime.describe()
    assert credential.token.get_secret_value() not in descriptor.model_dump_json()
    assert credential.token.get_secret_value() not in repr(runtime)


# 断言策略方法文本超长时服务端仍只返回有界安全摘要；不把完整知识正文塞进传输。
@pytest.mark.asyncio
async def test_long_strategy_text_is_bounded_by_the_service() -> None:
    port = reserve_loopback_port()
    strategy = _strategy(method_text="结构突破方法。" * 2_000)
    catalog = SpyCatalog(strategy)
    runtime = build_research_mcp(catalog, port=port)
    registry = await runtime.build_client_registry()
    harness = _harness(registry=registry, catalog=catalog)
    async with serve_loopback(runtime.app, port=port):
        observation = await harness.client.call(harness.context, _request())

    assert observation.status is ToolObservationStatus.OK
    assert len(observation.safe_summary.encode("utf-8")) <= 8_192
    assert "methodTextTruncated=true" in observation.safe_summary


# 合成财务哨兵只用于断言不泄漏；服务端不应接触规划资料或返回金额/仓位字段。
@pytest.mark.asyncio
async def test_strategy_definition_summary_has_no_financial_values() -> None:
    port = reserve_loopback_port()
    strategy = _strategy()
    catalog = SpyCatalog(strategy)
    runtime = build_research_mcp(catalog, port=port)
    registry = await runtime.build_client_registry()
    harness = _harness(registry=registry, catalog=catalog)
    async with serve_loopback(runtime.app, port=port):
        observation = await harness.client.call(harness.context, _request())

    serialized = observation.model_dump_json()
    for marker in ("position_size", "notional", "leverage", "123456.78"):
        assert marker not in serialized


# 重定向必须在传输层被拒绝；客户端只返回安全降级原因，不跟随到第二个目标。
@pytest.mark.asyncio
async def test_redirect_is_reported_as_safe_degradation_without_following() -> None:
    hits: list[str] = []

    async def redirect_mcp(request: Request) -> RedirectResponse:
        _ = request
        return RedirectResponse("/redirected", status_code=307)

    async def redirected(request: Request) -> RedirectResponse:
        hits.append(str(request))
        return RedirectResponse("/elsewhere", status_code=307)

    app = Starlette(
        routes=[
            Route("/internal/agent-mcp/mcp", redirect_mcp, methods=["POST", "GET"]),
            Route("/redirected", redirected, methods=["POST", "GET"]),
        ]
    )
    tool = strategy_definition_tool()
    strategy = _strategy()
    async with serve_loopback(app) as (_, port):
        registry = McpEndpointRegistry(
            [
                _endpoint(
                    port=port,
                    tools=(McpToolDescriptor(name=tool.name, schema_sha256="a" * 64),),
                )
            ],
            credential=McpServiceCredential.from_token("t" * 48),
        )
        client = McpToolClient(registry=registry, tool=tool)
        result = await client.handle(
            _context(strategy, "a" * 64),
            _snapshot(strategy),
            {},
            sent_at=datetime.now(UTC),
        )

    assert result.status is ToolResultStatus.DEGRADED
    assert result.reason_code == "mcp_redirect_rejected"
    assert hits == []


# 适配器只允许固定策略定义工具；模型/配置不能把它变成通用远端工具路由。
def test_client_rejects_unregistered_tool_names() -> None:
    tool = strategy_definition_tool().model_copy(update={"name": "build_manual_trade_plan"})
    registry = McpEndpointRegistry(
        [_endpoint(port=9_001, tools=(McpToolDescriptor(name=tool.name, schema_sha256="a" * 64),))],
        credential=McpServiceCredential.from_token("t" * 48),
    )
    with pytest.raises(McpRegistryError):
        McpToolClient(registry=registry, tool=tool)
