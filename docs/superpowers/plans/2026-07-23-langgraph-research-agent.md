# LangGraph Research Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现单一、可恢复、只读的 `MarketResearchAgent`：用户手动触发后，系统基于冻结的市场、衍生品、资讯和个人聚合统计生成带证据、风险、不确定性与限制说明的结构化研究报告。

**Architecture:** FastAPI 创建持久化分析运行记录并在单 API 进程内启动后台执行；LangGraph 用 `analysis_id` 作为 `thread_id`，图节点只调用 application 层的只读服务；PostgreSQL 保存业务报告/证据和 LangGraph checkpointer。模型节点只得到受控、带 ID 的证据上下文；没有任意工具调用、数据库直连、交易动作或配置写入能力。

**Tech Stack:** LangGraph、langchain-core、langchain-openai、langgraph-checkpoint-postgres、Pydantic v2、FastAPI SSE、SQLAlchemy 2.x、PostgreSQL、structlog、OpenTelemetry、pytest、httpx；计划 02/03 的交易、市场和资讯读模型。

## Global Constraints

- 这是研究 Agent，不是交易 Agent：不得生成 `TradeIntent`、下单参数、仓位比例、保证收益或自动执行指令。
- LLM 没有网络、数据库、文件、交易所、设置或账户工具；图中所有读取由确定性 Python 节点通过 application 端口完成。
- 新闻正文放入显式 `UNTRUSTED_NEWS_CONTENT` 边界，限制长度，只作为引文，永不解释为指令。
- `analysis_evidences` 在报告创建后不可被后续行情/资讯改写；LangGraph checkpoint 仅保存运行 ID、节点状态、证据 ID 和最小错误元数据。
- 模型供应商密钥仅来自运行时环境变量，不能提交、显示、记录、存入报告、证据、checkpoint 或 OpenTelemetry attributes。
- 关键数据缺失、过期或模型不可用时，系统产生确定性降级报告，不让模型猜测数值。

---

## Target file layout

```text
backend/
├── alembic/versions/{0005_create_analysis_reports.py,0006_link_trades_to_analysis_reports.py}
├── src/app/
│   ├── api/{schemas/analysis.py,routes/analysis.py}
│   ├── application/
│   │   ├── ports/research_reader.py
│   │   └── analysis/{commands.py,events.py,run_research.py,service.py}
│   ├── domain/analysis/{models.py,validators.py}
│   ├── infrastructure/
│   │   ├── langgraph/{checkpointer.py,model_factory.py}
│   │   └── persistence/{models/analysis.py,repositories/analysis.py}
│   ├── repositories/analysis.py
│   ├── agent/{graph.py,prompts.py,schemas.py,state.py,tools.py,validators.py}
│   └── shared/{observability.py,redaction.py}
└── tests/
    ├── unit/{agent/test_validators.py,agent/test_prompts.py,application/test_research_context.py}
    ├── integration/{agent/test_market_research_graph.py,persistence/test_analysis_repository.py}
    └── integration/api/test_analysis_api.py
```

## Task 1: Introduce report/evidence persistence and read-only research boundary

**Files:**
- Modify: `backend/pyproject.toml`, `backend/src/app/shared/config.py`
- Create: `backend/alembic/versions/0005_create_analysis_reports.py`
- Create: `backend/src/app/domain/analysis/models.py`, `backend/src/app/application/ports/research_reader.py`
- Create: `backend/src/app/infrastructure/persistence/models/analysis.py`, `backend/src/app/repositories/analysis.py`, `backend/src/app/infrastructure/persistence/repositories/analysis.py`
- Create: `backend/tests/integration/persistence/test_analysis_repository.py`, `backend/tests/unit/application/test_research_context.py`

- [ ] Write tests first for creating a queued analysis, freezing an immutable evidence set, report/evidence ID linkage, attempted evidence overwrite rejection, and aggregation-only personal performance access.
- [ ] Add production dependencies `langgraph`, `langchain-core`, `langchain-openai`, `langgraph-checkpoint-postgres`, `opentelemetry-api` and `opentelemetry-sdk`; update `uv.lock`. These packages add research orchestration/observability only. `langchain-openai` is inactive without a runtime key.
- [ ] Add optional `openai_api_key` and `openai_model` settings. Missing key is valid and must lead to model-unavailable degradation; do not mark the whole API unhealthy merely because a model is unconfigured.
- [ ] Migration `0005_create_analysis_reports.py` creates:

| Table | Required fields |
|---|---|
| `analysis_reports` | UUID `id`, symbol, `status`, `generated_at`, `data_cutoff_at`, uncertainty, structured report JSON, error category, immutable creation timestamps. |
| `analysis_evidences` | UUID `id`, `analysis_report_id`, evidence type, source, observed/fetched times, content hash, bounded immutable JSON snapshot, creation timestamp. |

- [ ] Allow report statuses only `queued`, `running`, `completed`, `degraded`, `failed`, `interrupted`. Index `(symbol, created_at DESC)` and status. Evidence repository exposes insertion and retrieval only; there is no update/delete method.
- [ ] Define a narrow application port. It may return market snapshots, derivative context, news timeline, personal **aggregated** statistics and previous report summaries, but never raw trade notes/attachments or ORM objects:

```python
class ResearchReadService(Protocol):
    async def get_market_snapshot(self, symbol: ContractSymbol, timeframes: tuple[Timeframe, ...]) -> MarketContext: ...
    async def get_derivatives_context(self, symbol: ContractSymbol) -> DerivativesContext: ...
    async def get_news_timeline(self, symbol: ContractSymbol, since: datetime, until: datetime) -> NewsContext: ...
    async def get_personal_trading_statistics(self, filters: ResearchStatisticsFilter) -> PersonalStatisticsContext: ...
    async def get_previous_analysis(self, symbol: ContractSymbol) -> PreviousAnalysisContext | None: ...
```

- [ ] Implement `ResearchContextAssembler` in application code. It concurrently invokes the five read methods, converts results to bounded, typed evidence snapshots, persists those snapshots once, and returns only evidence IDs plus deterministic freshness/completeness results to the graph.

**Verification:**

```powershell
Set-Location backend
uv run alembic upgrade head
uv run pytest tests/integration/persistence/test_analysis_repository.py tests/unit/application/test_research_context.py
uv run ruff check .
uv run pyright
```

Expected result: evidence is durable and immutable before any model invocation; an Agent cannot receive free-form database access or raw personal journal content.

## Task 2: Define safe structured report contract and deterministic validators

**Files:**
- Create: `backend/src/app/agent/{schemas.py,prompts.py,validators.py}`
- Create: `backend/src/app/domain/analysis/validators.py`
- Create: `backend/tests/unit/agent/{test_validators.py,test_prompts.py}`

- [ ] Write failing tests for missing evidence ID, observation without source time, invalid timeframe, unrecognized uncertainty, prohibited certainty/trading language, external instruction injection text, and valid structured report output.
- [ ] Define `AnalysisReportDraft` as the only model output schema. It must distinguish factual observations from inferences and include evidence IDs for every fact:

```python
class EvidenceReference(BaseModel):
    evidence_id: UUID
    claim: str

class MarketObservation(BaseModel):
    timeframe: Timeframe
    statement: str
    evidence: list[EvidenceReference]

class RiskFlag(BaseModel):
    code: Literal["STALE_DATA", "MISSING_DATA", "HIGH_VOLATILITY", "EVENT_RISK", "MODEL_UNAVAILABLE"]
    severity: Literal["low", "medium", "high"]
    explanation: str

class AnalysisReportDraft(BaseModel):
    symbol: ContractSymbol
    summary: str
    market_observations: list[MarketObservation]
    news_context: list[NewsObservation]
    personal_statistics_context: PersonalStatisticsSummary | None
    risk_flags: list[RiskFlag]
    uncertainty: Literal["low", "medium", "high"]
    limitations: list[str]
```

- [ ] Require all claims about market/news values to resolve to evidence owned by the current report. Validate source timestamps, max list lengths and bounded string lengths. Reject report output instead of repairing it silently.
- [ ] Write a fixed Chinese research system prompt that: identifies the role as research assistant; asks for evidence-backed observations rather than instructions; requires uncertainty/limitations; marks external news as untrusted; forbids profit promises, certainty, position sizing, leverage advice, full-position language, order placement and automation. Keep it in code, versioned and unit-tested.
- [ ] Implement deterministic phrase/rule validation with normalized case/Unicode matching. It is a guardrail, not a claim of linguistic completeness; any validation failure results in a failed/degraded report with a traceable error category.

**Verification:**

```powershell
Set-Location backend
uv run pytest tests/unit/agent/test_validators.py tests/unit/agent/test_prompts.py
uv run ruff check src/app/agent src/app/domain/analysis tests/unit/agent
uv run pyright
```

Expected result: only a structured, evidence-linked research report can proceed; prompts and validators cannot produce or approve a trading action.

## Task 3: Build the LangGraph state machine with PostgreSQL checkpointing

**Files:**
- Create: `backend/src/app/agent/{state.py,tools.py,graph.py}`
- Create: `backend/src/app/infrastructure/langgraph/{checkpointer.py,model_factory.py}`
- Create: `backend/tests/integration/agent/test_market_research_graph.py`

- [ ] Write graph tests first with a fake deterministic structured-output model. Cover fresh success, stale data, missing data, model unavailable, invalid model schema, validator rejection, checkpoint recovery and duplicate run rejection.
- [ ] Make the persisted graph state minimal. It contains only `analysis_id`, `symbol`, `status`, `evidence_ids`, freshness/completeness summary, error category, attempt count and report ID. It must not contain news text, user notes, full prompt, raw model output or credentials.
- [ ] Configure `AsyncPostgresSaver` via `langgraph-checkpoint-postgres`; call its setup migration during controlled application startup after PostgreSQL is reachable. Use `analysis_id` exactly as LangGraph `thread_id`.
- [ ] Build this deterministic graph. `load_and_freeze_context` performs bounded application reads; `generate_report` is the only model node:

```text
START
  -> load_and_freeze_context
  -> evaluate_freshness
       -> [stale_or_missing] build_degraded_report -> persist_report -> END
       -> [complete] assemble_model_context -> generate_structured_report
                         -> validate_report -> persist_report -> END
```

- [ ] `assemble_model_context` calls the application evidence reader by ID and formats it into a length-bounded prompt. It wraps every news item in an explicit `UNTRUSTED_NEWS_CONTENT` delimiter and does not carry instructions from news into the system/developer context.
- [ ] Model factory returns a `ChatOpenAI` configured for `with_structured_output(AnalysisReportDraft)` only when a key is present. In tests inject `FakeStructuredResearchModel`; no test makes a live model call.
- [ ] Use a deterministic degraded report for stale/missing data or unavailable model. It lists the missing/failing sources, data cutoff time, `MODEL_UNAVAILABLE` where applicable, and no invented market conclusion.
- [ ] Agent `tools.py` may contain narrowly typed wrappers around `ResearchReadService`, but graph execution must never permit model-selected arbitrary tool calls. The model receives assembled evidence, not a toolbox.

**Verification:**

```powershell
Set-Location backend
uv run pytest tests/integration/agent/test_market_research_graph.py
uv run ruff check .
uv run pyright
```

Expected result: test runs are reproducible offline, checkpoint state is minimal, and stale/missing inputs never reach a speculative LLM call.

## Task 4: Expose manual trigger, status and SSE progress safely

**Files:**
- Create: `backend/src/app/application/analysis/{commands.py,events.py,run_research.py,service.py}`
- Create: `backend/src/app/api/{schemas/analysis.py,routes/analysis.py}`
- Create: `backend/tests/integration/api/test_analysis_api.py`
- Modify: `backend/src/app/api/router.py`, `frontend/src/shared/api/{http-workbench-api.ts,report-stream.ts}`

- [ ] Write API tests first for create (202), live progress event sequence, completed report retrieval, degraded report, validation failure, client reconnect, stale runner reconciliation and retry with a new analysis ID.
- [ ] Implement exactly these endpoints:

```text
POST /api/v1/analysis-runs
GET  /api/v1/analysis-runs/{analysis_id}
GET  /api/v1/analysis-runs/{analysis_id}/events
```

- [ ] `POST` accepts only an allowed symbol, persists a `queued` report row and starts an in-process background runner after the response is committed. It returns `{ "analysis_id": "...", "status": "queued" }` with HTTP 202. It does not block the request on LLM completion.
- [ ] Implement `AnalysisEventHub` as an in-memory async subscriber registry for a **single API replica**. SSE sends `status`, `node`, `completed` or `failed` events, each with `analysis_id`, timestamp and safe metadata. It cannot be a source of business truth.
- [ ] On SSE reconnect, send a persisted status snapshot first; attach to the local event hub only if the run is active in the same process. Final reports are always retrieved from PostgreSQL. At startup, mark stale `running` rows as `interrupted` so a user can create a new retry run; do not falsely resume a lost in-process task.
- [ ] `GET` returns the persisted structured report with evidence references and status. It must never include a raw model prompt, untrusted full news body, exception stack, database URL or key.
- [ ] Implement `HttpWorkbenchApi.startReport`, `subscribeReport`, `listReports` and `getReport` against these routes with Zod parsing. Browser SSE must not send sensitive query parameters or authorization tokens in this local single-user release.

**Verification:**

```powershell
Set-Location backend
uv run pytest tests/integration/api/test_analysis_api.py
Set-Location ../frontend
npm run test -- --run src/features/reports src/shared/api
```

Expected result: a user can observe an explicitly labeled research workflow, reconnect after browser interruption, and retrieve a durable final/degraded report without any automation control.

## Task 5: Link reports to journal entries and add safe observability

**Files:**
- Create: `backend/alembic/versions/0006_link_trades_to_analysis_reports.py`
- Create: `backend/src/app/shared/{observability.py,redaction.py}`
- Modify: `backend/src/app/api/schemas/trades.py`, `backend/src/app/application/trades/{commands.py,service.py}`
- Modify: `frontend/src/features/{reports,trades}/*`
- Create: `backend/tests/integration/{test_trade_report_link.py,test_observability_redaction.py}`

- [ ] Write migration/service tests first: a valid report can link to a new or edited journal trade; nonexistent report ID is rejected; archived/incompatible report association follows a documented 422 rule; linking never copies or mutates report/evidence rows.
- [ ] Add nullable `analysis_report_id` to `trades` only now, with a foreign key to `analysis_reports` and an index. The API extension is optional and backward-compatible with journal clients from plan 02.
- [ ] Create a trace correlation ID for analysis and journal mutations. Logs/traces include ID, status, node name and duration only; `redaction.py` removes `OPENAI_API_KEY`, database URLs, prompt bodies, raw model output, raw news content and user journal notes before emission.
- [ ] Add unit/integration tests that deliberately place secret-shaped strings in settings/errors and prove emitted structured events do not contain them.
- [ ] In the UI, `基于此分析创建交易日志` provides only `analysis_report_id` and a compact report metadata reference. It does not turn the report into an entry/exit recommendation and it does not expose a “trade now” call-to-action.

**Verification:**

```powershell
Set-Location backend
uv run alembic upgrade head
uv run pytest tests/integration/test_trade_report_link.py tests/integration/test_observability_redaction.py
uv run ruff check .
uv run pyright
```

Expected result: report-to-journal traceability works through a real FK, while reports remain immutable and telemetry remains minimal/redacted.
