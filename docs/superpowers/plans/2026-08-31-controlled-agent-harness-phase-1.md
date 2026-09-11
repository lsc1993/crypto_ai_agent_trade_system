# Controlled Market-Research Harness Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Route the existing manually triggered, evidence-bound market-research Agent through a policy-enforcing Harness runtime without changing the HTTP API, database schema, model tool surface, or simulation-trading behavior.

**Architecture:** Add a small app.harness control-plane package with immutable run/policy contracts, a registered-workflow runtime, and a façade compatible with the existing AnalysisReportService port. The fixed LangGraph remains in app.agent; the Harness allocates the run ID, validates declared capabilities, and passes that UUID to the Agent as its analysis_id and checkpoint thread_id.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, LangGraph, PostgreSQL checkpointing, structlog, pytest, Ruff, Pyright.

**Spec:** docs/superpowers/specs/2026-08-31-controlled-agent-harness-architecture-design.md

## Global Constraints

- Keep research manually initiated only through POST /api/v1/analysis-runs or its explicit retry endpoint. Do not add workers, queues, schedulers, automatic recovery, or automatic retries.
- Keep existing HTTP schemas. AnalysisReportService.generate(symbol) remains the API-facing interface.
- Do not add production dependencies, migrations, tables, environment variables, models, external sources, or configuration files.
- app.harness coordinates the registered research workflow only. It must not import risk, execution, paper_trading, persistence implementations, private exchanges, browser automation, shell/file tools, MCP tools, or ORM repositories.
- The only policy permits public-market reads, approved-news reads, the optional no-tools research-model call, and immutable-report persistence.
- Preserve the existing fixed LangGraph nodes, frozen evidence, Pydantic validation, prohibited-trading-language guard, UTC checks, checkpoint-payload limits, and degraded-report behavior.
- The Harness run_id is the existing analysis_id. Phase 1 creates no new persisted IDs or run tables.
- New Pydantic models are frozen and reject extra values. All datetimes are timezone-aware UTC.
- Logs contain only safe IDs, enums, counts, timestamps, durations and error types; never secrets, raw model payloads, complete external content, exception messages, or database URLs.
- Do not change TradeIntent, RiskEngine, PaperTradingEngine, simulation execution, or the real-trading prohibition.

---

## Planned file structure

| File | Responsibility |
| --- | --- |
| backend/src/app/harness/__init__.py | Package marker only; no re-exports. |
| backend/src/app/harness/contracts.py | Run/policy/capability contracts, workflow protocol and safe rejection error. |
| backend/src/app/harness/policy.py | The one Phase-1 market-research policy. |
| backend/src/app/harness/runtime.py | Pre-delegation policy checks and lifecycle logging. |
| backend/src/app/harness/market_research.py | Agent adapter and AnalysisReportService-compatible façade. |
| backend/src/app/agent/service.py | Optional preallocated analysis_id support. |
| backend/src/app/main.py | Live bootstrap through the Harness façade. |
| backend/src/app/api/errors.py | Safe 403 policy-rejection response. |
| backend/tests/harness/test_contracts.py | Contract and static-policy tests. |
| backend/tests/harness/test_runtime.py | Registration, authorization and safe-log tests. |
| backend/tests/harness/test_market_research.py | Run-ID propagation and façade tests. |
| backend/tests/agent/test_graph.py | Explicit-ID/checkpoint regression test. |
| backend/tests/api/test_agent_analysis_reports.py | Existing HTTP contract regression. |
| backend/tests/api/test_errors.py | Safe error-envelope test. |
| backend/tests/security/test_agent_dependency_boundary.py | Harness dependency isolation. |
| backend/tests/security/test_agent_source_and_secret_safety.py | Harness no-tool/no-secret static scan. |
| docs/operational-boundaries.md | Manual, policy-constrained Harness boundary. |

## Task 1: Define immutable Harness contracts and static policy

**Files:**
- Create: backend/src/app/harness/__init__.py
- Create: backend/src/app/harness/contracts.py
- Create: backend/src/app/harness/policy.py
- Create: backend/tests/harness/test_contracts.py

**Interfaces:**
- Consumes: app.market.contracts.ContractSymbol.
- Produces: HarnessRunKind, HarnessCapability, HarnessRunRequest, HarnessPolicy, HarnessWorkflow, HarnessPolicyViolation, and MARKET_RESEARCH_POLICY.

- [ ] **Step 1: Write failing contract tests**

Create backend/tests/harness/test_contracts.py with the following tests and one test that rejects duplicate policy capabilities.

    from datetime import UTC, datetime
    from uuid import UUID

    import pytest
    from pydantic import ValidationError

    from app.harness.contracts import (
        HarnessCapability,
        HarnessRunKind,
        HarnessRunRequest,
    )
    from app.harness.policy import MARKET_RESEARCH_POLICY
    from app.market.contracts import ContractSymbol

    NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)

    def test_market_research_policy_is_static_and_minimally_privileged() -> None:
        assert MARKET_RESEARCH_POLICY.run_kind is HarnessRunKind.MARKET_RESEARCH
        assert MARKET_RESEARCH_POLICY.allowed_symbols == (
            ContractSymbol.BTCUSDT,
            ContractSymbol.ETHUSDT,
        )
        assert MARKET_RESEARCH_POLICY.allowed_capabilities == (
            HarnessCapability.READ_PUBLIC_MARKET,
            HarnessCapability.READ_APPROVED_NEWS,
            HarnessCapability.CALL_RESEARCH_MODEL,
            HarnessCapability.PERSIST_IMMUTABLE_REPORT,
        )

    def test_run_request_rejects_non_utc_and_extra_payload() -> None:
        with pytest.raises(ValidationError):
            HarnessRunRequest(
                run_id=UUID("00000000-0000-0000-0000-000000000901"),
                kind=HarnessRunKind.MARKET_RESEARCH,
                symbol=ContractSymbol.BTCUSDT,
                requested_at=datetime(2026, 8, 31, 20),
            )

        with pytest.raises(ValidationError):
            HarnessRunRequest(
                run_id=UUID("00000000-0000-0000-0000-000000000901"),
                kind=HarnessRunKind.MARKET_RESEARCH,
                symbol=ContractSymbol.BTCUSDT,
                requested_at=NOW,
                raw_context="must not be accepted",
            )

- [ ] **Step 2: Run the test to verify it fails**

Run:

    Set-Location backend
    uv run pytest tests/harness/test_contracts.py -v

Expected: collection fails because app.harness does not yet exist.

- [ ] **Step 3: Implement contracts and policy**

Create contracts.py with these exact public definitions. All models use ConfigDict(frozen=True, extra="forbid"); both policy tuples are nonempty and deduplicated; requested_at rejects naïve and non-UTC datetimes.

    class HarnessRunKind(StrEnum):
        MARKET_RESEARCH = "market_research"

    class HarnessCapability(StrEnum):
        READ_PUBLIC_MARKET = "read_public_market"
        READ_APPROVED_NEWS = "read_approved_news"
        CALL_RESEARCH_MODEL = "call_research_model"
        PERSIST_IMMUTABLE_REPORT = "persist_immutable_report"

    class HarnessRunRequest(BaseModel):
        run_id: UUID
        kind: HarnessRunKind
        symbol: ContractSymbol
        requested_at: UtcDateTime

    class HarnessPolicy(BaseModel):
        run_kind: HarnessRunKind
        allowed_symbols: tuple[ContractSymbol, ...]
        allowed_capabilities: tuple[HarnessCapability, ...]

    class HarnessPolicyViolation(RuntimeError):
        """Safe rejection raised before workflow invocation."""

    class HarnessWorkflow[ResultT](Protocol):
        kind: HarnessRunKind
        required_capabilities: tuple[HarnessCapability, ...]

        async def run(self, request: HarnessRunRequest) -> ResultT: ...

Create policy.py with MARKET_RESEARCH_POLICY containing exactly the symbols and capabilities asserted by Step 1. Add only a package docstring to __init__.py. Do not add generic context, memory, tool, endpoint, payload, credential, or model fields.

- [ ] **Step 4: Run focused checks**

    Set-Location backend
    uv run pytest tests/harness/test_contracts.py -v
    uv run ruff check src/app/harness tests/harness
    uv run pyright src/app/harness tests/harness

Expected: all pass with zero lint/type errors.

- [ ] **Step 5: Commit only Task 1 paths**

    git add -- backend/src/app/harness/__init__.py backend/src/app/harness/contracts.py backend/src/app/harness/policy.py backend/tests/harness/test_contracts.py
    git commit -m "feat: define controlled harness policy contracts"

Do not stage any pre-existing working-tree changes.

## Task 2: Implement registered runtime and safe rejection response

**Files:**
- Create: backend/src/app/harness/runtime.py
- Create: backend/tests/harness/test_runtime.py
- Modify: backend/src/app/api/errors.py
- Create: backend/tests/api/test_errors.py

**Interfaces:**
- Consumes: Task 1 contracts and policy.
- Produces: HarnessRuntime.run(request) -> ResultT. It rejects before delegation.

- [ ] **Step 1: Write failing authorization and error-envelope tests**

Create a RecordingWorkflow dataclass in tests/harness/test_runtime.py with a calls list and async run method that appends the request and returns "completed". Write a successful-runtime test and an unauthorized-capability test:

    @pytest.mark.asyncio
    async def test_runtime_rejects_unknown_capability_before_delegation() -> None:
        workflow = RecordingWorkflow(
            required_capabilities=(
                HarnessCapability.READ_PUBLIC_MARKET,
                cast(HarnessCapability, "private_account"),
            )
        )
        runtime = HarnessRuntime(
            policies=(MARKET_RESEARCH_POLICY,),
            workflows=(workflow,),
        )

        with pytest.raises(HarnessPolicyViolation, match="capability_not_allowed"):
            await runtime.run(REQUEST)

        assert workflow.calls == []

Use a single UTC REQUEST constant. Also test a symbol omitted by a test-only policy, an unregistered kind, duplicate policy/workflow registration, and logging that contains run_id, kind, symbol, phase and duration_ms but no raw_context or exception message.

Create tests/api/test_errors.py: install existing exception handlers on a FastAPI app with a route that raises HarnessPolicyViolation("symbol_not_allowed"), then assert:

    assert response.status_code == 403
    assert response.json() == {
        "code": "harness_policy_rejected",
        "message": "当前运行不符合受限 Harness 策略",
        "details": {},
    }

- [ ] **Step 2: Run failing tests**

    Set-Location backend
    uv run pytest tests/harness/test_runtime.py tests/api/test_errors.py -v

Expected: collection fails because HarnessRuntime and the handler do not exist.

- [ ] **Step 3: Implement runtime and error mapping**

Implement HarnessRuntime with constructor arguments policies: tuple[HarnessPolicy, ...] and workflows: tuple[HarnessWorkflow[ResultT], ...]. Its constructor rejects duplicate run kinds with ValueError. Run in this order:

    async def run(self, request: HarnessRunRequest) -> ResultT:
        policy = self._policy_for(request.kind)
        workflow = self._workflow_for(request.kind)
        self._require_symbol_allowed(policy, request.symbol)
        self._require_capabilities_allowed(policy, workflow.required_capabilities)
        return await self._run_logged(workflow, request)

Missing policy/workflow raises HarnessPolicyViolation("run_kind_not_registered"); unknown or disallowed declared capability raises HarnessPolicyViolation("capability_not_allowed"); symbol mismatch raises HarnessPolicyViolation("symbol_not_allowed"). Use structlog.get_logger(__name__) and emit only harness_run_started, harness_run_completed, harness_run_rejected, harness_run_failed and harness_run_details. Re-raise unexpected delegate errors.

In api/errors.py, import HarnessPolicyViolation, add _harness_policy_violation_handler, and register it before the generic Exception handler. The handler returns the asserted 403 envelope and never returns str(exception).

- [ ] **Step 4: Run focused verification**

    Set-Location backend
    uv run pytest tests/harness/test_runtime.py tests/api/test_errors.py -v
    uv run ruff check src/app/harness src/app/api/errors.py tests/harness tests/api/test_errors.py
    uv run pyright src/app/harness src/app/api/errors.py tests/harness tests/api/test_errors.py

Expected: PASS with no lint/type errors.

- [ ] **Step 5: Commit only Task 2 paths**

    git add -- backend/src/app/harness/runtime.py backend/tests/harness/test_runtime.py backend/src/app/api/errors.py backend/tests/api/test_errors.py
    git commit -m "feat: add controlled harness runtime"

## Task 3: Adapt existing market-research Agent without graph changes

**Files:**
- Create: backend/src/app/harness/market_research.py
- Create: backend/tests/harness/test_market_research.py
- Modify: backend/src/app/agent/service.py
- Modify: backend/tests/agent/test_graph.py

**Interfaces:**
- Consumes: Tasks 1-2, AgentResearchService, AnalysisReportService and PersistedAnalysisReport.
- Produces: MarketResearchWorkflow, HarnessedMarketResearchService, and AgentResearchService.generate(symbol, *, analysis_id: UUID | None = None).

- [ ] **Step 1: Write failing ID-propagation tests**

In tests/harness/test_market_research.py, use a fake AgentResearchService whose async generate method records a keyword-only analysis_id. Construct the façade with a fixed UTC clock and new_run_id=lambda: RUN_ID. Assert:

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert delegate.calls == [(ContractSymbol.BTCUSDT, RUN_ID)]
    assert report.analysis_id == RUN_ID

Add a test that MarketResearchWorkflow.required_capabilities equals MARKET_RESEARCH_POLICY.allowed_capabilities, plus a test that a HarnessPolicyViolation leaves the agent delegate uncalled.

In tests/agent/test_graph.py, call service.generate(ContractSymbol.BTCUSDT, analysis_id=ANALYSIS_ID), assert report.analysis_id equals ANALYSIS_ID, and list checkpoints with thread_id equal to str(ANALYSIS_ID). Keep the existing no-research-payload checkpoint test.

- [ ] **Step 2: Run failing tests**

    Set-Location backend
    uv run pytest tests/harness/test_market_research.py tests/agent/test_graph.py -v

Expected: failure because the adapter and analysis_id keyword argument do not exist.

- [ ] **Step 3: Implement the minimal adapter**

Change only the AgentResearchService method signature and ID selection:

    async def generate(
        self,
        symbol: ContractSymbol,
        *,
        analysis_id: UUID | None = None,
    ) -> PersistedAnalysisReport:
        started_at = _require_utc(self._dependencies.clock())
        run = _AgentResearchRun(
            dependencies=self._dependencies,
            analysis_id=uuid4() if analysis_id is None else analysis_id,
            symbol=symbol,
            started_at=started_at,
        )

Do not alter the LangGraph topology, model request, evidence, validation, retry, error or checkpoint behavior.

In market_research.py implement these classes:

    class MarketResearchWorkflow(HarnessWorkflow[PersistedAnalysisReport]):
        kind = HarnessRunKind.MARKET_RESEARCH
        required_capabilities = MARKET_RESEARCH_POLICY.allowed_capabilities

        async def run(self, request: HarnessRunRequest) -> PersistedAnalysisReport:
            return await self._service.generate(
                request.symbol,
                analysis_id=request.run_id,
            )

    class HarnessedMarketResearchService:
        async def generate(self, symbol: ContractSymbol) -> PersistedAnalysisReport:
            request = HarnessRunRequest(
                run_id=self._new_run_id(),
                kind=HarnessRunKind.MARKET_RESEARCH,
                symbol=symbol,
                requested_at=_require_utc(self._clock()),
            )
            return await self._runtime.run(request)

The façade constructor accepts runtime, clock and new_run_id: Callable[[], UUID] = uuid4. It owns no network, model, market, news, risk, execution, repository, or checkpoint dependency.

- [ ] **Step 4: Run adapter and graph regression tests**

    Set-Location backend
    uv run pytest tests/harness/test_market_research.py tests/agent/test_graph.py tests/agent/test_service.py -v
    uv run ruff check src/app/harness/market_research.py src/app/agent/service.py tests/harness/test_market_research.py tests/agent/test_graph.py
    uv run pyright src/app/harness/market_research.py src/app/agent/service.py tests/harness/test_market_research.py tests/agent/test_graph.py

Expected: PASS; supplied IDs are report/checkpoint IDs; static checks are clean.

- [ ] **Step 5: Commit only Task 3 paths**

    git add -- backend/src/app/harness/market_research.py backend/tests/harness/test_market_research.py backend/src/app/agent/service.py backend/tests/agent/test_graph.py
    git commit -m "feat: route market research through harness"

## Task 4: Wire bootstrap, preserve HTTP behavior, and enforce source boundaries

**Files:**
- Modify: backend/src/app/main.py
- Modify: backend/tests/api/test_agent_analysis_reports.py
- Modify: backend/tests/security/test_agent_dependency_boundary.py
- Modify: backend/tests/security/test_agent_source_and_secret_safety.py
- Modify: docs/operational-boundaries.md

**Interfaces:**
- Consumes: HarnessRuntime, MARKET_RESEARCH_POLICY, MarketResearchWorkflow and HarnessedMarketResearchService.
- Produces: the same app.state.analysis_report_service: AnalysisReportService used by current routes.

- [ ] **Step 1: Write failing bootstrap/API/security tests**

Extend test_agent_analysis_reports.py to inject a HarnessedMarketResearchService with a fixed-ID supplier. Call create and retry endpoints. Assert both responses contain only analysisId and reportId; for retry, use a different fixed run ID and assert it becomes the new report analysis_id.

Extend test_agent_dependency_boundary.py to scan all app/harness Python files, asserting none contains app.risk, app.execution, app.paper_trading, app.infrastructure.persistence or ccxt.

Extend test_agent_source_and_secret_safety.py so the source scan includes agent, news and harness. Assert Harness source contains no subprocess, os.system, httpx.AsyncClient, requests., tools=, tool_choice, playwright, selenium, create_order, cancel_order, fetch_balance or fetch_positions.

- [ ] **Step 2: Run failing tests**

    Set-Location backend
    uv run pytest tests/api/test_agent_analysis_reports.py tests/security/test_agent_dependency_boundary.py tests/security/test_agent_source_and_secret_safety.py -v

Expected: failure until live bootstrap and boundary assertions are complete.

- [ ] **Step 3: Wire live research through the Harness**

In main.py, retain existing clients, AsyncPostgresSaver lifecycle, AgentResearchService dependencies, fallback DeterministicResearchReportService and create_app agent_research_service injection. Change the live factory annotation to Callable[[AsyncPostgresSaver], AnalysisReportService] and return:

    agent_service = AgentResearchService(
        dependencies=AgentResearchDependencies(
            market=market_capture,
            news=news_ingestion,
            model=model,
            repository=agent_report_repository,
            clock=lambda: datetime.now(UTC),
        ),
        checkpointer=checkpointer,
    )
    runtime = HarnessRuntime[PersistedAnalysisReport](
        policies=(MARKET_RESEARCH_POLICY,),
        workflows=(MarketResearchWorkflow(agent_service),),
    )
    return HarnessedMarketResearchService(
        runtime,
        clock=lambda: datetime.now(UTC),
    )

Do not expose runtime on app.state, change routes/lifespan conditions, initialize Harness without existing database/checkpoint prerequisites, or change DeepSeek settings.

Add one paragraph to docs/operational-boundaries.md: the market-research Harness is fixed, manual, policy-constrained and limited to approved public inputs plus an optional no-tools model-format call; it has no arbitrary tool router, long-term user memory, private-account access, simulated-order invocation or real-execution capability.

- [ ] **Step 4: Run API, safety and configuration checks**

    Set-Location backend
    uv run pytest tests/api/test_agent_analysis_reports.py tests/api/test_errors.py tests/security/test_agent_dependency_boundary.py tests/security/test_agent_source_and_secret_safety.py tests/shared/test_agent_settings.py -v
    uv run ruff check src/app/main.py src/app/harness src/app/api/errors.py tests/api tests/security
    uv run pyright src/app/main.py src/app/harness src/app/api/errors.py tests/api tests/security

Expected: HTTP payloads are unchanged, no restricted capability exists, settings remain allowlisted, and static checks are clean.

- [ ] **Step 5: Commit only Task 4 paths**

    git add -- backend/src/app/main.py backend/tests/api/test_agent_analysis_reports.py backend/tests/security/test_agent_dependency_boundary.py backend/tests/security/test_agent_source_and_secret_safety.py docs/operational-boundaries.md
    git commit -m "feat: bootstrap controlled research harness"

## Task 5: Full verification and phase-boundary record

**Files:**
- Modify: docs/superpowers/specs/2026-08-31-controlled-agent-harness-architecture-design.md
- Test: all backend quality gates

**Interfaces:**
- Consumes: completed Tasks 1-4.
- Produces: an exact Phase-1 implementation record. It must not imply Phase-2 audit tables or Phase-3 strategy-agent capability.

- [ ] **Step 1: Add implementation record only after all quality gates pass**

Append a Phase 1 implementation record to the design document after the full gate succeeds. State only verifiable facts: market research runs through the policy-constrained Harness; analysis_id equals the Harness run ID; no HTTP schema, dependency, database schema, source, scheduler, private API, simulation-execution or real-trading capability was added. Record the exact test count from Step 2.

- [ ] **Step 2: Run full backend verification**

    Set-Location backend
    uv run ruff check .
    uv run pyright
    uv run pytest

Expected: every command exits 0. If any fails, fix the associated task before writing the record.

- [ ] **Step 3: Inspect staging scope and whitespace**

    git diff --check
    git status --short
    git diff -- docs/superpowers/specs/2026-08-31-controlled-agent-harness-architecture-design.md

Expected: no whitespace errors and no staging of .env, credentials, production configuration, migrations, frontend, risk, execution, paper-trading or pre-existing user changes.

- [ ] **Step 4: Commit only the verification record**

    git add -- docs/superpowers/specs/2026-08-31-controlled-agent-harness-architecture-design.md
    git commit -m "docs: record controlled harness phase one"

## Spec-coverage self-review

- This plan implements the approved Phase-1 HarnessRuntime, fixed HarnessPolicy, registered workflow, safe lifecycle logging, analysis_id correlation, research integration, source isolation, manual-only behavior and tests.
- It deliberately excludes harness_runs, harness_run_events and harness_evaluations; these remain the separately gated Phase-2 decision.
- It deliberately excludes a strategy Agent, TradeIntent changes, automated simulation, private accounts and real trading; these remain separately gated Phase 3 work.
- All cross-task names are consistent: HarnessRunRequest, HarnessPolicy, HarnessRuntime, MarketResearchWorkflow, HarnessedMarketResearchService and AgentResearchService.generate with analysis_id.
