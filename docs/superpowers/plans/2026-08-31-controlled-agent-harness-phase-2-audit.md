# Controlled Harness Phase 2 Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist an immutable audit trace for every live, manually triggered market-research Harness run without changing the existing report HTTP schema or any trading boundary.

**Architecture:** Add frozen Harness audit contracts and a narrow asynchronous repository port, then implement that port with SQLAlchemy and three append-only PostgreSQL tables. The runtime writes request, policy and pre-workflow facts before delegation; an `agent_analysis_runs` database trigger appends completed/degraded terminal events in the report transaction, so those terminal facts cannot be committed independently of the report.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy async, PostgreSQL, Alembic, FastAPI, structlog, pytest, Ruff and Pyright.

**Spec:** `docs/superpowers/specs/2026-08-31-controlled-agent-harness-phase-2-audit-design.md`

## Global Constraints

- Use Python 3.12 and `uv`; do not add production dependencies, environment variables, data sources, workers, queues, schedulers or retry loops.
- Preserve the existing manual `POST /api/v1/analysis-runs` and retry API schemas and responses; do not add an audit HTTP endpoint or expose the repository on `app.state`.
- `harness` may declare Pydantic contracts and repository protocols only; it must not import SQLAlchemy, Alembic, `app.infrastructure.persistence`, `app.risk`, `app.execution`, `app.paper_trading`, CCXT, private exchanges, HTTP clients, browser, shell, file or MCP tools.
- Keep real trading disabled. Do not modify `TradeIntent`, `RiskEngine`, `PaperTradingEngine`, execution adapters, account permissions or any real-order boundary.
- `run_id` remains equal to the market-research `analysis_id`; do not backfill, update, delete or migrate existing report, evidence, checkpoint or paper-trading records.
- New Pydantic models are frozen, reject extra fields and require timezone-aware UTC times. Hashes are lowercase 64-character SHA-256 values. Prices, amounts and fees are not introduced.
- Audit details are fixed safe Pydantic count/enum facts only; never save prompts, raw model responses, news HTML, external payloads, exception messages, database URLs, secrets or private data.
- New audit tables and their rows are append-only: database triggers reject every UPDATE and DELETE; the Alembic downgrade raises `NotImplementedError` before any schema mutation.
- Audit persistence must fail closed before workflow delegation. Explicit API retry continues to create a new run ID; no automatic retry or automatic recovery is allowed.
- Preserve the fixed LangGraph, frozen evidence, current deterministic Agent validation/degraded report behavior and existing `agent_analysis_runs` immutability.

---

## Planned file structure

| File | Responsibility |
| --- | --- |
| `backend/src/app/harness/audit.py` | Frozen audit enums/models, canonical SHA-256 helpers, safe storage exception and repository protocol. |
| `backend/src/app/harness/contracts.py` | Add the immutable policy version field only. |
| `backend/src/app/harness/policy.py` | Set the only current policy version to `market_research_v1`. |
| `backend/src/app/harness/runtime.py` | Create and append audit facts at the existing authorization/delegation boundary. |
| `backend/src/app/infrastructure/persistence/models/harness.py` | SQLAlchemy records for the three audit tables. |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | Export the new record classes. |
| `backend/src/app/infrastructure/persistence/harness_audit_repository.py` | Async SQLAlchemy implementation of the narrow append/read port. |
| `backend/alembic/versions/0012_create_harness_audit.py` | Forward-only audit schema, constraints, immutable triggers and agent terminal-event trigger. |
| `backend/src/app/main.py` | Inject the live SQLAlchemy audit repository into the live Harness runtime only. |
| `backend/src/app/api/errors.py` | Map an audit-storage failure to the fixed safe 503 envelope. |
| `backend/tests/harness/test_audit.py` | Contract, hashing and safe-detail validation tests. |
| `backend/tests/harness/test_runtime.py` | In-memory audit recording, rejection, pre-delegation failure and safe failed-event tests. |
| `backend/tests/harness/test_market_research.py` | Update direct runtime construction to use an explicit audit fake. |
| `backend/tests/persistence/test_harness_audit_repository.py` | Repository round trip, trace ordering, append-only semantics and terminal-event conflict tests. |
| `backend/tests/persistence/test_migrations.py` | Schema, immutable trigger, no-history-rewrite and `agent_analysis_runs` terminal-trigger tests. |
| `backend/tests/api/test_errors.py` | Safe `harness_audit_unavailable` 503 test. |
| `backend/tests/api/test_agent_analysis_reports.py` | Existing create/retry payload regression with a recording audit fake. |
| `backend/tests/security/test_agent_dependency_boundary.py` | Keep audit contracts free of persistence/risk/execution dependencies. |
| `backend/tests/security/test_agent_source_and_secret_safety.py` | Assert audit sources have no tool, I/O or secret surface. |

## Task 1: Define immutable audit contracts and versioned policy

**Files:**
- Create: `backend/src/app/harness/audit.py`
- Modify: `backend/src/app/harness/contracts.py`
- Modify: `backend/src/app/harness/policy.py`
- Create: `backend/tests/harness/test_audit.py`
- Modify: `backend/tests/harness/test_contracts.py`

**Interfaces:**
- Consumes: `HarnessRunRequest`, `HarnessPolicy`, `HarnessRunKind`, `HarnessCapability` and `ContractSymbol`.
- Produces: `HarnessAuditRun`, `HarnessAuditEvent`, `HarnessEvaluation`, `HarnessAuditTrace`, `HarnessAuditRepository`, `HarnessAuditStorageUnavailableError`, audit enums and `policy_sha256` / `request_sha256` helpers.

- [ ] **Step 1: Write failing audit contract tests**

Create `tests/harness/test_audit.py` with fixed UUID and UTC constants. Verify canonical hashes are deterministic and do not reveal a secret-looking string; verify audit models reject a naïve time, an extra field, an invalid hash, a negative duration, a completed event with an error code, and rejected evaluation without a reason code.

```python
def test_audit_models_are_frozen_and_only_accept_safe_details() -> None:
    event = HarnessAuditEvent(
        run_id=RUN_ID,
        sequence=0,
        kind=HarnessAuditEventKind.REQUESTED,
        occurred_at=NOW,
        duration_ms=0,
        error_code=None,
        details=HarnessEventDetails(declared_capability_count=4),
    )
    assert event.details.model_dump(mode="json") == {"declared_capability_count": 4}
    with pytest.raises(ValidationError):
        HarnessAuditEvent.model_validate({**event.model_dump(), "raw_context": "secret"})

def test_policy_and_request_hashes_are_stable_and_safe() -> None:
    assert policy_sha256(MARKET_RESEARCH_POLICY) == policy_sha256(MARKET_RESEARCH_POLICY)
    assert request_sha256(REQUEST, MARKET_RESEARCH_POLICY.version) == EXPECTED_REQUEST_SHA256
```

Extend `test_contracts.py` to assert `MARKET_RESEARCH_POLICY.version == "market_research_v1"` and that a policy without `version` is rejected.

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run:

```powershell
Set-Location backend
uv run pytest tests/harness/test_audit.py tests/harness/test_contracts.py -v
```

Expected: collection fails because `app.harness.audit` and `HarnessPolicy.version` do not exist.

- [ ] **Step 3: Implement the contract surface**

In `contracts.py`, add `version: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,64}$")]` to `HarnessPolicy`; preserve frozen/extra-forbid and existing nonempty/deduplicated validators. Set the sole static policy version in `policy.py`.

In `audit.py`, define the following exact enums and models, all with `ConfigDict(frozen=True, extra="forbid")`:

```python
class HarnessAuditEventKind(StrEnum):
    REQUESTED = "requested"
    POLICY_AUTHORIZED = "policy_authorized"
    POLICY_REJECTED = "policy_rejected"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_DEGRADED = "workflow_degraded"
    WORKFLOW_FAILED = "workflow_failed"

class HarnessEvaluationDecision(StrEnum):
    PASSED = "passed"
    REJECTED = "rejected"

class HarnessInitiatorKind(StrEnum):
    MANUAL_API = "manual_api"
```

Use `HarnessEventDetails` with only optional `declared_capability_count`, `allowed_capability_count`, `workflow_kind` and `error_type`; validate counts are nonnegative, `error_type` matches `^[A-Za-z][A-Za-z0-9_]{0,99}$`, and at least one field is present except for terminal completed/degraded details, which are an explicitly allowed empty instance. Use `HarnessEvaluationDetails` with only nonnegative declared/allowed capability counts.

Model the immutable records as:

```python
class HarnessAuditRun(_AuditModel):
    run_id: UUID
    run_kind: HarnessRunKind
    policy_version: str
    policy_sha256: Sha256
    symbol: ContractSymbol
    requested_at: UtcDateTime
    initiator_kind: HarnessInitiatorKind
    request_sha256: Sha256

class HarnessAuditEvent(_AuditModel):
    run_id: UUID
    sequence: Annotated[int, Field(ge=0, le=3)]
    kind: HarnessAuditEventKind
    occurred_at: UtcDateTime
    duration_ms: Annotated[int, Field(ge=0)]
    error_code: StableErrorCode | None
    details: HarnessEventDetails

class HarnessEvaluation(_AuditModel):
    run_id: UUID
    sequence: Annotated[int, Field(ge=0)]
    evaluator_name: Literal["policy_allowlist"]
    evaluator_version: Literal["1"]
    decision: HarnessEvaluationDecision
    reason_code: StableErrorCode | None
    evaluated_at: UtcDateTime
    details: HarnessEvaluationDetails
```

Add `model_validator(mode="after")` checks: `WORKFLOW_COMPLETED`/`WORKFLOW_DEGRADED` require `sequence == 3` and `error_code is None`; `POLICY_REJECTED` and `WORKFLOW_FAILED` require a non-null error code; all other event kinds require no error code; a passed evaluation has no reason and a rejected evaluation has one. `HarnessAuditTrace` contains one run plus ordered tuples of events and evaluations.

Implement `policy_sha256(policy)` and `request_sha256(request, policy_version)` by assigning their deliberately assembled JSON-safe fields to `canonical_payload`, then calling `json.dumps(canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`, UTF-8 encoding and `hashlib.sha256(serialized.encode("utf-8")).hexdigest()`. The policy helper includes version, kind, symbols and capabilities in declaration order; the request helper includes only run ID, kind, symbol, UTC ISO timestamp and policy version. Do not accept arbitrary payload input.

Define the repository protocol exactly as specified in the design. The storage exception message is the safe literal `Harness 审计存储不可用`.

- [ ] **Step 4: Run focused verification**

Run:

```powershell
Set-Location backend
uv run pytest tests/harness/test_audit.py tests/harness/test_contracts.py -v
uv run ruff check src/app/harness tests/harness/test_audit.py tests/harness/test_contracts.py
uv run pyright src/app/harness tests/harness/test_audit.py tests/harness/test_contracts.py
```

Expected: all pass with no formatting, lint or type errors.

- [ ] **Step 5: Commit only Task 1 paths**

```powershell
git add -- backend/src/app/harness/audit.py backend/src/app/harness/contracts.py backend/src/app/harness/policy.py backend/tests/harness/test_audit.py backend/tests/harness/test_contracts.py
git commit -m "feat: define harness audit contracts"
```

## Task 2: Add forward-only immutable audit schema and atomic report terminal events

**Files:**
- Create: `backend/alembic/versions/0012_create_harness_audit.py`
- Modify: `backend/tests/persistence/test_migrations.py`

**Interfaces:**
- Consumes: the existing Alembic head `0011_agent_report_metrics`, `agent_analysis_runs` and Task 1 enum values.
- Produces: `harness_runs`, `harness_run_events`, `harness_evaluations`, immutable database enforcement and an `AFTER INSERT` agent-run terminal-event trigger.

- [ ] **Step 1: Write failing migration tests**

Extend `test_migrations.py` with a test that upgrades an isolated schema from `0011_agent_report_metrics` to `head`, checks all three table names and their column types, and verifies the existing analysis-report row remains byte-for-byte unchanged. Assert the composite keys are exactly `(run_id, sequence)` on events/evaluations.

Add helpers to seed a valid `harness_runs` envelope plus sequence 0–2 facts, and then insert an `agent_analysis_runs` row. Assert that an `agent_analysis_runs.status = 'completed'` insert creates only sequence 3 `workflow_completed`; repeat with `degraded` and an allowed `error_code`, then assert a direct agent run without a Harness envelope creates no Harness event.

```python
async def _terminal_events(database_url: SecretStr, schema: str, run_id: UUID) -> list[tuple[int, str, str | None]]:
    return await _rows_in_schema(
        database_url, schema,
        text("SELECT sequence, event_kind, error_code FROM harness_run_events "
             "WHERE run_id = :run_id ORDER BY sequence"),
        {"run_id": run_id},
    )

assert await _terminal_events(url, schema, run_id) == [
    (0, "requested", None),
    (1, "policy_authorized", None),
    (2, "workflow_started", None),
    (3, "workflow_completed", None),
]
```

Extend the immutable-record helper so every new table rejects both an UPDATE and DELETE with a message containing `immutable`. Add a migration-loader helper and a test that `downgrade()` raises `NotImplementedError` before a mocked Alembic `op` can mutate the schema.

- [ ] **Step 2: Run migration tests and confirm they fail**

Run:

```powershell
Set-Location backend
uv run pytest tests/persistence/test_migrations.py -v
```

Expected: the head has no `0012_create_harness_audit` migration and no Harness audit tables.

- [ ] **Step 3: Implement the schema migration**

Create revision `0012_harness_audit` with `down_revision = "0011_agent_report_metrics"`; keep all revision strings at or below 32 characters. Use PostgreSQL UUID and JSONB types. Create these exact tables:

```text
harness_runs(
  run_id UUID PRIMARY KEY,
  run_kind VARCHAR(64) NOT NULL CHECK (run_kind = 'market_research'),
  policy_version VARCHAR(64) NOT NULL CHECK (policy_version IN ('market_research_v1', 'unregistered')),
  policy_sha256 CHAR(64) NOT NULL CHECK (policy_sha256 ~ '^[0-9a-f]{64}$'),
  symbol VARCHAR(12) NOT NULL CHECK (symbol IN ('BTCUSDT', 'ETHUSDT')),
  requested_at TIMESTAMPTZ NOT NULL,
  initiator_kind VARCHAR(32) NOT NULL CHECK (initiator_kind = 'manual_api'),
  request_sha256 CHAR(64) NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)

harness_run_events(
  run_id UUID NOT NULL REFERENCES harness_runs(run_id),
  sequence INTEGER NOT NULL CHECK (sequence BETWEEN 0 AND 3),
  event_kind VARCHAR(32) NOT NULL CHECK (event_kind IN (
    'requested', 'policy_authorized', 'policy_rejected', 'workflow_started',
    'workflow_completed', 'workflow_degraded', 'workflow_failed'
  )),
  occurred_at TIMESTAMPTZ NOT NULL,
  duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
  error_code VARCHAR(100),
  details JSONB NOT NULL,
  PRIMARY KEY (run_id, sequence),
  CHECK (error_code IS NULL OR error_code ~ '^[a-z0-9_]+$')
)

harness_evaluations(
  run_id UUID NOT NULL REFERENCES harness_runs(run_id),
  sequence INTEGER NOT NULL CHECK (sequence >= 0),
  evaluator_name VARCHAR(64) NOT NULL CHECK (evaluator_name = 'policy_allowlist'),
  evaluator_version VARCHAR(16) NOT NULL CHECK (evaluator_version = '1'),
  decision VARCHAR(16) NOT NULL CHECK (decision IN ('passed', 'rejected')),
  reason_code VARCHAR(100),
  evaluated_at TIMESTAMPTZ NOT NULL,
  details JSONB NOT NULL,
  PRIMARY KEY (run_id, sequence),
  CHECK ((decision = 'passed' AND reason_code IS NULL) OR
         (decision = 'rejected' AND reason_code ~ '^[a-z0-9_]+$'))
)
```

Add the indexes from the specification. Install three dedicated `BEFORE UPDATE OR DELETE` trigger functions that raise `analysis records are immutable`; do not reuse a function name from an older migration.

Create `AFTER INSERT FOR EACH ROW` trigger function on `agent_analysis_runs`. It must return immediately when `NEW.analysis_id` is absent from `harness_runs`; otherwise it inserts sequence 3 only, mapping `completed` to `workflow_completed` and `degraded` to `workflow_degraded`, copying `NEW.completed_at`, using `GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (NEW.completed_at - harness_runs.requested_at)) * 1000)::integer)` for `duration_ms`, copying `NEW.error_code`, and using `'{}'::jsonb` details. It must never update an audit row or emit a record for a non-Harness Agent run.

Use `downgrade()` only to raise `NotImplementedError("Harness 审计迁移不可逆，禁止删除审计记录")`.

- [ ] **Step 4: Run migration verification**

Run:

```powershell
Set-Location backend
uv run pytest tests/persistence/test_migrations.py -v
uv run alembic heads
uv run ruff check alembic/versions/0012_create_harness_audit.py tests/persistence/test_migrations.py
uv run pyright tests/persistence/test_migrations.py
```

Expected: one Alembic head, all migration tests pass, no old report is changed, all new tables reject updates/deletes, and direct Agent runs produce no Harness event.

- [ ] **Step 5: Commit only Task 2 paths**

```powershell
git add -- backend/alembic/versions/0012_create_harness_audit.py backend/tests/persistence/test_migrations.py
git commit -m "feat: add immutable harness audit schema"
```

## Task 3: Implement the SQLAlchemy append/read adapter

**Files:**
- Create: `backend/src/app/infrastructure/persistence/models/harness.py`
- Modify: `backend/src/app/infrastructure/persistence/models/__init__.py`
- Create: `backend/src/app/infrastructure/persistence/harness_audit_repository.py`
- Create: `backend/tests/persistence/test_harness_audit_repository.py`

**Interfaces:**
- Consumes: Task 1 models/protocol, Task 2 schema, `async_sessionmaker[AsyncSession]` and the `migrated_database` test fixture.
- Produces: `SqlAlchemyHarnessAuditRepository`, which implements all `HarnessAuditRepository` methods and translates SQLAlchemy failures to `HarnessAuditStorageUnavailableError`.

- [ ] **Step 1: Write failing repository tests**

Create a `Recording` fixture factory in `test_harness_audit_repository.py` that returns a valid `HarnessAuditRun`, requested event, passed policy evaluation, policy-authorized event and workflow-started event. Use `SqlAlchemyHarnessAuditRepository(migrated_database.session_factory)`.

```python
@pytest.mark.asyncio
async def test_repository_appends_and_reads_an_ordered_trace(migrated_database: MigratedDatabase) -> None:
    repository = SqlAlchemyHarnessAuditRepository(migrated_database.session_factory)
    run, requested, evaluation, authorized, started = _admitted_run()
    await repository.create_requested_run(run, requested)
    await repository.append_policy_evaluation(evaluation, authorized)
    await repository.append_event(started)

    trace = await repository.get_trace(run.run_id)
    assert trace is not None
    assert [event.kind for event in trace.events] == [
        HarnessAuditEventKind.REQUESTED,
        HarnessAuditEventKind.POLICY_AUTHORIZED,
        HarnessAuditEventKind.WORKFLOW_STARTED,
    ]
    assert trace.evaluations == (evaluation,)
```

Add tests for absent trace returning `None`, duplicate primary-key append becoming `HarnessAuditStorageUnavailableError`, and direct UPDATE/DELETE of each mapped record failing with the migration's immutable DB error. Assert the stored details never contain a `raw_context` key.

- [ ] **Step 2: Run repository tests and confirm they fail**

Run:

```powershell
Set-Location backend
uv run pytest tests/persistence/test_harness_audit_repository.py -v
```

Expected: collection fails because the SQLAlchemy models and adapter do not exist.

- [ ] **Step 3: Implement the models and adapter**

Create three SQLAlchemy declarative records with table/column names exactly matching Task 2. Use `PostgreSQLUUID(as_uuid=True)`, timezone-aware `DateTime`, `JSONB`, `String` and composite primary keys for event/evaluation sequences. Do not define ORM relationships; the adapter performs explicit ordered selects and remains small.

Implement the adapter so `create_requested_run` adds both supplied records in one `async with session.begin()` transaction, and `append_policy_evaluation` likewise adds both supplied records in one transaction. `append_event` is one insert transaction. `get_trace` uses one session and explicit ascending `sequence` selects for events/evaluations, returning `None` only if the run row is absent.

Map SQLAlchemy values back to Task 1 Pydantic models with `ContractSymbol`, `HarnessRunKind`, `HarnessAuditEventKind`, `HarnessInitiatorKind` and `HarnessEvaluationDecision` constructors. Catch only `SQLAlchemyError` at the repository boundary and raise `HarnessAuditStorageUnavailableError` without including database errors, SQL text or connection information. Do not issue `UPDATE`, `DELETE`, `ON CONFLICT`, `merge`, `upsert` or retry logic.

- [ ] **Step 4: Run adapter verification**

Run:

```powershell
Set-Location backend
uv run pytest tests/persistence/test_harness_audit_repository.py tests/persistence/test_migrations.py -v
uv run ruff check src/app/infrastructure/persistence/models/harness.py src/app/infrastructure/persistence/harness_audit_repository.py tests/persistence/test_harness_audit_repository.py
uv run pyright src/app/infrastructure/persistence/models/harness.py src/app/infrastructure/persistence/harness_audit_repository.py tests/persistence/test_harness_audit_repository.py
```

Expected: repository traces round-trip in sequence order; all writes are inserts; storage errors are safe and no migration guarantees regress.

- [ ] **Step 5: Commit only Task 3 paths**

```powershell
git add -- backend/src/app/infrastructure/persistence/models/harness.py backend/src/app/infrastructure/persistence/models/__init__.py backend/src/app/infrastructure/persistence/harness_audit_repository.py backend/tests/persistence/test_harness_audit_repository.py
git commit -m "feat: persist harness audit traces"
```

## Task 4: Record audit facts in the runtime and wire live composition

**Files:**
- Modify: `backend/src/app/harness/runtime.py`
- Modify: `backend/src/app/main.py`
- Modify: `backend/src/app/api/errors.py`
- Modify: `backend/tests/harness/test_runtime.py`
- Modify: `backend/tests/harness/test_market_research.py`
- Modify: `backend/tests/api/test_errors.py`
- Modify: `backend/tests/api/test_agent_analysis_reports.py`
- Modify: `backend/tests/security/test_agent_dependency_boundary.py`
- Modify: `backend/tests/security/test_agent_source_and_secret_safety.py`

**Interfaces:**
- Consumes: Task 1 `HarnessAuditRepository`, Task 3 adapter, existing registered workflows and FastAPI error handlers.
- Produces: auditable live market-research Harness behavior, a fixed 503 audit-storage error envelope and unchanged report endpoints.

- [ ] **Step 1: Write failing runtime and API tests**

Add a `RecordingAuditRepository` fake to `test_runtime.py`; it stores method arguments and can raise `HarnessAuditStorageUnavailableError`. Construct every successful test runtime as `HarnessRuntime(policies=(MARKET_RESEARCH_POLICY,), workflows=(workflow,), audit_repository=audit)`. Assert the successful call records request sequence 0, passed policy evaluation plus sequence 1, and workflow-started sequence 2 before the workflow receives its request.

```python
assert [event.sequence for event in audit.events] == [0, 1, 2]
assert audit.evaluations[0].decision is HarnessEvaluationDecision.PASSED
assert workflow.calls == [REQUEST]
```

For an unauthorized symbol/capability, assert the fake contains requested plus `POLICY_REJECTED`, its evaluation reason equals the safe policy error code, and `workflow.calls == []`. For a failing workflow, assert sequence 3 `WORKFLOW_FAILED` has `error_code == "workflow_exception"`, a safe `RuntimeError` type and no exception message. For audit failure before request, evaluation or start, assert `HarnessAuditStorageUnavailableError` and zero workflow calls.

In `test_errors.py`, add a route raising `HarnessAuditStorageUnavailableError`; assert status 503 and exactly:

```python
{
    "code": "harness_audit_unavailable",
    "message": "Harness 审计存储不可用",
    "details": {},
}
```

Update the existing API create/retry test to pass the recording audit repository into its manually constructed HarnessRuntime and continue asserting the HTTP bodies contain only `analysisId` and `reportId`.

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run:

```powershell
Set-Location backend
uv run pytest tests/harness/test_runtime.py tests/api/test_errors.py tests/api/test_agent_analysis_reports.py -v
```

Expected: the runtime lacks an audit repository argument and the audit storage exception handler does not exist.

- [ ] **Step 3: Implement runtime recording and safe error handling**

Change `HarnessRuntime.__init__` to require `audit_repository: HarnessAuditRepository`; do not add a no-op default. Build a `HarnessAuditRun` before policy validation using the resolved static policy, or `policy_version="unregistered"` and the canonical sentinel hash when no policy is registered. Use `HarnessInitiatorKind.MANUAL_API` only.

Execute this exact order in `run`:

1. write `create_requested_run(run, requested sequence 0)`; if it fails, propagate the safe storage error and do not inspect/delegate the workflow;
2. resolve policy/workflow and validate symbol/capabilities;
3. on `HarnessPolicyViolation`, append rejected evaluation plus sequence 1 `POLICY_REJECTED`, log only safe IDs/enums/counts/error type, then re-raise the existing 403 exception;
4. on success, append passed evaluation plus sequence 1 `POLICY_AUTHORIZED`, then append sequence 2 `WORKFLOW_STARTED`;
5. invoke the fixed workflow exactly once; on an ordinary `Exception`, append sequence 3 `WORKFLOW_FAILED` with stable `workflow_exception` and the exception type only, then re-raise. Do not catch `asyncio.CancelledError` and do not create timeout/retry behavior;
6. return the workflow result without appending a success/degraded terminal event: Task 2's `agent_analysis_runs` trigger owns that atomic write.

Retain the existing structlog lifecycle logs, but never log audit details, raw exception messages or trace payloads. If the failure-event write itself raises a storage error, let that safe storage error replace the workflow error; do not attempt a second write.

In `errors.py`, register `HarnessAuditStorageUnavailableError` before the generic exception handler and return the exact 503 envelope. In `main.py`, instantiate `SqlAlchemyHarnessAuditRepository(session_factory)` only inside the existing live Agent factory preconditions and pass it to `HarnessRuntime`; do not create an engine, client or Harness audit repository for fallback/injected service paths.

Update security tests to include `audit.py` in the existing Harness scan and explicitly reject `sqlalchemy`, `alembic`, `app.infrastructure.persistence`, `app.risk`, `app.execution`, `app.paper_trading`, `httpx`, `subprocess`, `os.system`, browser/tool tokens and secret-key names. Assert `main.py` contains `SqlAlchemyHarnessAuditRepository(session_factory)` and does not put an audit repository on `app.state`.

- [ ] **Step 4: Run runtime, API and boundary verification**

Run:

```powershell
Set-Location backend
uv run pytest tests/harness/test_audit.py tests/harness/test_runtime.py tests/harness/test_market_research.py tests/api/test_errors.py tests/api/test_agent_analysis_reports.py tests/security/test_agent_dependency_boundary.py tests/security/test_agent_source_and_secret_safety.py -v
uv run ruff check src/app/harness src/app/main.py src/app/api/errors.py tests/harness tests/api/test_errors.py tests/api/test_agent_analysis_reports.py tests/security
uv run pyright src/app/harness src/app/main.py src/app/api/errors.py tests/harness tests/api/test_errors.py tests/api/test_agent_analysis_reports.py tests/security
```

Expected: authorized flows record the first three facts before delegation; rejected flows never delegate; audit outage returns a generic 503; no HTTP report payload or security boundary changes.

- [ ] **Step 5: Commit only Task 4 paths**

```powershell
git add -- backend/src/app/harness/runtime.py backend/src/app/main.py backend/src/app/api/errors.py backend/tests/harness/test_runtime.py backend/tests/harness/test_market_research.py backend/tests/api/test_errors.py backend/tests/api/test_agent_analysis_reports.py backend/tests/security/test_agent_dependency_boundary.py backend/tests/security/test_agent_source_and_secret_safety.py
git commit -m "feat: audit controlled harness runs"
```

## Task 5: End-to-end persistence regression and Phase 2 record

**Files:**
- Modify: `backend/tests/persistence/test_agent_research_repository.py`
- Modify: `backend/tests/persistence/test_migrations.py`
- Modify: `docs/superpowers/specs/2026-08-31-controlled-agent-harness-phase-2-audit-design.md`

**Interfaces:**
- Consumes: Tasks 1–4 and the isolated PostgreSQL test schema.
- Produces: proof that report persistence atomically creates a terminal audit event and a fact-only implementation record.

- [ ] **Step 1: Write failing end-to-end database test**

In `test_agent_research_repository.py`, use the audit repository to create an admitted run with `run_id == _agent_creation().report.analysis_id`, then call `SqlAlchemyAnalysisReportRepository.persist_agent(_agent_creation())`. Query `HarnessAuditEventRecord` and assert sequence 3 is `workflow_completed`, `error_code is None`, `details == {}`, and the prior three audit rows remain unchanged.

Add a second creation whose report status is `DEGRADED` and non-null stable error code; assert the trigger writes only `workflow_degraded` and copies that code. Add a no-envelope `persist_agent` assertion that no Harness event is created for its analysis ID.

- [ ] **Step 2: Run the end-to-end test and confirm it fails**

Run:

```powershell
Set-Location backend
uv run pytest tests/persistence/test_agent_research_repository.py::test_agent_report_persistence_appends_harness_terminal_event_atomically -v
```

Expected: it fails until the migration trigger and mapped audit models are present and correctly wired to the repository fixture schema.

- [ ] **Step 3: Make the smallest corrections required for the atomic assertion**

Do not change `SqlAlchemyAnalysisReportRepository.persist_agent` transaction structure, domain report contracts or the fixed Agent graph. Adjust only the Task 2 trigger SQL or Task 3 mappings if the trigger cannot observe the pre-existing Harness envelope or maps statuses/times/errors incorrectly. Keep terminal details as an empty JSON object and preserve the no-envelope no-op condition.

- [ ] **Step 4: Run all affected and full quality gates**

Run:

```powershell
Set-Location backend
uv run pytest tests/harness tests/api/test_errors.py tests/api/test_agent_analysis_reports.py tests/persistence/test_harness_audit_repository.py tests/persistence/test_agent_research_repository.py tests/persistence/test_migrations.py tests/security -v
uv run ruff check .
uv run pyright
uv run pytest
```

Expected: all commands exit 0. Run the full suite with the existing isolated test PostgreSQL configuration; do not print or commit its connection string.

- [ ] **Step 5: Record verified facts, inspect scope and commit**

After every Task 5 command passes, append a dated `Phase 2 实施记录` to the specification that states only verified facts: the three append-only audit tables exist; live manual market-research runs record the declared audit facts; completed/degraded terminal events are inserted with the report transaction; no report HTTP schema, automatic task, strategy Agent, simulation execution, private API or real-trading ability was added. Include the exact pytest count from the full command.

Then run:

```powershell
git diff --check
git status --short
git diff -- docs/superpowers/specs/2026-08-31-controlled-agent-harness-phase-2-audit-design.md
git add -- backend/tests/persistence/test_agent_research_repository.py backend/tests/persistence/test_migrations.py docs/superpowers/specs/2026-08-31-controlled-agent-harness-phase-2-audit-design.md
git commit -m "docs: record harness audit phase two"
```

Before staging, verify no `.env`, credentials, compose configuration, user-owned files, frontend, strategy, risk, execution or paper-trading source is included. If Task 5 requires a source correction, commit that correction with its own focused tests before the final documentation commit.

## Plan self-review

- **Spec coverage:** Task 1 implements the static policy identity and safe contracts; Task 2 implements exactly the three immutable tables and atomic terminal trigger; Task 3 supplies the infra adapter; Task 4 applies pre-delegation failure semantics, main composition, safe 503 and dependency boundaries; Task 5 proves atomic report correlation and records verified outcomes.
- **Excluded scope:** No task adds an audit HTTP route, frontend, worker, scheduler, retry loop, tool surface, strategy Agent, `TradeIntent`, risk/execution change, private account access or real trading capability.
- **Type consistency:** `HarnessAuditRepository`, `HarnessAuditRun`, `HarnessAuditEvent`, `HarnessEvaluation` and `HarnessAuditStorageUnavailableError` are introduced in Task 1 and used with the same names in Tasks 3–4. Terminal event names and fixed sequence numbers match the approved design.
- **Placeholder scan:** 未发现占位语句或未指定的错误处理步骤；每项任务均给出路径、测试命令、预期结果和提交范围。
