# 多币对研究与管理 Implementation Plan

> **For agentic workers:** Use the reviewed specification and test-first implementation; independent frontend, research adaptation, and persistence tasks can run concurrently with fixed interfaces. Track completion in this file.

**Goal:** 用户可自行添加受支持的研究币对、同步全部适用数据，并在三个研究页面一致地切换范围。

**Architecture:** PostgreSQL 目录是研究准入来源。公开适配器校验能力，数据库租约任务同步数据，前端按 URL 和目录选择币对。保留交易功能原有范围。

**Tech Stack:** Python 3.12 / FastAPI / Pydantic / SQLAlchemy / PostgreSQL / asyncio；React / TanStack Query / Zod / Vitest。

**Spec:** `docs/superpowers/specs/2026-09-07-research-symbol-management-design.md`（用户已于本会话确认）。

## Global Constraints

- 不新增生产依赖，不修改 .env、凭证、生产配置，不执行真实交易或清理用户数据。
- 数值使用 Decimal，时间使用 UTC；研究能力扩展不得扩大交易准入。
- 当前分支 `codex/report-policy-funding-etf`，包含用户既有未提交改动；按已批准方案在当前工作区逐文件保留并集成，不切换或重置分支。
- 先验证新增测试失败，再实现；基线已通过后端 83 项和前端 48 项相关测试。
- 本计划不自动提交混合工作区；实现及审核结果通过文件差异交付。

## Fixed integration interfaces

Root owns `backend/src/app/symbols/contracts.py`, `service.py`, `sync.py`, `api` integration and `main.py` wiring.

Research value: `app.market.symbols.ResearchSymbol` is a Pydantic validated string (5–32 uppercase ASCII alphanumeric chars ending USDT); legacy `ContractSymbol` stays restricted to BTC/ETH. Public research interfaces accept ResearchSymbol (a str alias), use value equality and plain string serialization.

All following Pydantic models serialize camelCase, accept snake_case in Python, freeze models, forbid extra fields:

```python
class Capability(BaseModel):
    name: Literal['market', 'candles', 'derivatives', 'funding', 'news', 'sentiment', 'etf']
    status: Literal['supported', 'unsupported', 'unverified']
    message: str
class MarketMetadata(BaseModel):
    symbol: ResearchSymbol
    base_asset: str
    quote_asset: str
    margin_asset: str
    contract_type: str
    status: str
class CheckResult(BaseModel):
    symbol: ResearchSymbol
    supported: bool
    checks: tuple[Capability, ...]
    metadata: MarketMetadata | None
class SyncSource(BaseModel):
    name: str
    status: Literal['available', 'partial', 'missing', 'failed', 'unsupported']
    message: str
    payload: dict[str, JsonValue]  # Decimal serialized as strings, UTC as ISO
    payload_sha256: str
class SyncRun(BaseModel):
    id: UUID
    symbol: ResearchSymbol
    version: int
    status: Literal['queued', 'running', 'ready', 'partial', 'failed', 'cancelled']
    stage: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    lease_token: UUID | None
    lease_until: datetime | None
    snapshot_id: UUID | None
    sources: tuple[SyncSource, ...]
    error: str | None
class ResearchSymbolEntry(BaseModel):
    symbol: ResearchSymbol
    base_asset: str
    quote_asset: str
    margin_asset: str
    contract_type: str
    enabled: bool
    keywords: tuple[str, ...]
    capabilities: tuple[Capability, ...]
    version: int
    created_at: datetime
    archived_at: datetime | None
    can_research: bool  # true if enabled and at least one core-complete sync
    last_sync: SyncRun | None
```

Repository port `app.symbols.repository.SymbolRepository` (root creates Protocol, persistence agent implements `SqlAlchemySymbolRepository`):

```python
async def list(self, *, include_archived: bool = False) -> tuple[ResearchSymbolEntry, ...]: ...
async def get(self, symbol: str) -> ResearchSymbolEntry | None: ...
async def add(self, check: CheckResult, *, keywords: tuple[str, ...], now: datetime) -> ResearchSymbolEntry: ...
async def archive(self, symbol: str, *, now: datetime) -> ResearchSymbolEntry: ...
async def enqueue(self, symbol: str, *, now: datetime) -> SyncRun: ...
async def get_run(self, run_id: UUID) -> SyncRun | None: ...
async def claim(self, *, now: datetime) -> SyncRun | None: ...
async def renew(self, run: SyncRun, *, now: datetime) -> bool: ...
async def finish(self, run: SyncRun, *, status: str, sources: tuple[SyncSource, ...], snapshot_id: UUID | None, error: str | None, now: datetime) -> bool: ...
async def record_check(self, check: CheckResult, *, now: datetime) -> None: ...
```

`SymbolError(code: str, message: str, status_code: int = 409)` is defined in contracts. Persistence errors must map to safe 503 errors. Missing symbols use code `research_symbol_not_found` (404); inactive `research_symbol_archived` (409).

HTTP interface under `/api/v1`: GET `/research-symbols?include_archived=true` -> `{items: ResearchSymbolEntry[]}`; POST `/research-symbols/check` accepts `{symbol, keywords?: string[]}` -> CheckResult; POST `/research-symbols` same input -> 202 ResearchSymbolEntry (with lastSync); POST `/{symbol}/archive` -> ResearchSymbolEntry; POST `/{symbol}/sync` -> 202 SyncRun; GET `/research-symbol-sync-runs/{id}` -> SyncRun. Archive/sync paths are relative to `/research-symbols`.

Frontend WorkbenchApi adds `listResearchSymbols(includeArchived?: boolean)`, `checkResearchSymbol(input)`, `addResearchSymbol(input)`, `archiveResearchSymbol(symbol)`, `syncResearchSymbol(symbol)`, `getResearchSymbolSyncRun(id)`; getDashboard accepts optional `{symbol: ResearchSymbol}`. Agent may use ergonomic type aliases; wire contract above is binding.

## Task 1: Dynamic research identifiers and source adaptation (research agent)

Files: create `backend/src/app/market/symbols.py`; modify research-only market/agent/news/reports/harness modules and related tests. Do not edit persistence, API routes, dashboard or main (other owners).

- [ ] Add a failing test parsing SOLUSDT market/report/Harness inputs while TradeIntent, paper account and backtest still reject it; run pytest and record expected failure.
- [ ] Introduce validated research strings, migrate research annotations and `.value`/identity comparisons; retain legacy constants for defaults.
- [ ] Add `BinanceUsdmPublicMarketGateway.get_exchange_info(symbol: str) -> dict[str, str] | None`, through the existing fixed public transport; return symbol/baseAsset/quoteAsset/marginAsset/contractType/status. Add public path, sufficient bounded response size, and TTL caching.
- [ ] Verify actual derivatives parameters (basis uses pair/contractType), and reject mismatched symbol/time scope in core metrics. Update protocol definitions consumed by root.
- [ ] Allow capture_symbol dynamic inputs; optional async admission callback receives symbol, defaults legacy BTC/ETH only. Root supplies directory-aware callback. Keep batch defaults compatible.
- [ ] News collect accepts optional `keywords: tuple[str, ...] = ()`; deterministically match new ticker/keywords and common macro context without mutating frozen evidence. Root supplies keywords through a wrapper; persistence agent adds links.
- [ ] ETF unsupported returns an explicit missing/unavailable topic with the exact limitation “当前数据源不支持”; no fabricated evidence or interpretations.
- [ ] Add an optional async policy provider to HarnessRuntime or service wrapper, freezing per-run version/allowed symbols while keeping default static policy for tests. Publish exact signature to root.
- [ ] Run related pytest/Ruff/Pyright; provide changed files and test evidence.

## Task 2: Persistent directory and job ownership (persistence agent)

Files: create models/symbols.py, symbol_repository.py, migration after current head, new persistence tests; own all files under infrastructure/persistence and alembic needed for research conversion.

- [ ] Write failing isolated-schema tests: add/check/enqueue/archive, unique active job, lease expiry and stale finish rejection, complete SOL market/report save.
- [ ] Add four tables from spec; use exact root contracts and repository signatures above.
- [ ] Add/seed BTC/ETH and queued initialization syncs, widen research columns, replace fixed research checks with format + directory FK, preserve trading checks and history.
- [ ] Serialize directory capabilities and source payloads with Pydantic JSON; lock directory rows for add/enqueue/archive. Atomic job claim uses SKIP LOCKED, 30-second lease and directory version; expired jobs become failed.
- [ ] Append audit events for directory and job transitions. Terminal jobs immutable; old lease holders cannot finish. Successful ready/partial sets canResearch only on enabled current version.
- [ ] Adapt research persistence strings without expanding trade/backtest/paper contracts; add optional keyword-independent news-link persistence based on current collect symbol and `list_for_symbol(symbol, limit=...)` for dashboard.
- [ ] Verify migrations and repository races in isolated test schema, run targeted static checks; report test evidence and signatures.

## Task 3: API and complete source synchronization (root)

Files: `app/symbols/{contracts,repository,service,sync}.py`, API routes/research_symbols.py, existing market/report/dashboard routes, dashboard/service.py, main.py, capture script, backend/tests/symbols and API tests.

- [ ] Write failing lifecycle tests with in-memory test repository and public gateway doubles; assert rejected checks create no registry item, interrupted jobs do not complete, full data source results survive.
- [ ] Implement strict models and shared contracts, check/exchange metadata/probe semantics; use structured errors and UTC/Decimal throughout.
- [ ] Implement registry admission and API methods with a per-call directory check; unavailable database fails closed for writes; legacy read-only test injections can use a static BTC/ETH catalog.
- [ ] Implement initial/manual sync collector using existing market capture, derivative gateway, funding history, governed RSS, sentiment and ETF; persist source hashes, isolate optional failures, reject core failure.
- [ ] Implement two-worker lifespan consumer with 120-second operation bound and 10-second lease heartbeat; cancel on archive/lease loss; store progress and safe failures.
- [ ] Wire source-aware sync, dynamic Harness and directory validation in main; preserve all dependency injections and resource cleanup.
- [ ] Dashboard symbol query filters market, reports and stored news. Read archive report by ID; enforce directory state for new generation/retry. Existing batch capture reads enabled directory independently per symbol.
- [ ] Run API/lifecycle tests, then integrated backend suite.

Example lifecycle assertion:

```python
entry = await service.add(SymbolInput(symbol='SOLUSDT'))
assert entry.last_sync is not None
assert entry.last_sync.status == 'queued'
assert entry.can_research is False
await worker.run_once()
entry = await repository.get('SOLUSDT')
assert entry is not None and entry.can_research
assert {s.name for s in entry.last_sync.sources} == {'market', 'candles', 'derivatives', 'funding', 'news', 'sentiment', 'etf'}
```

## Task 4: Shared selector and management UI (frontend agent)

Files: frontend research domain schemas, API implementations, feature pages, common selector/context, layout/router, tests. Own frontend only, preserve deleted frontend/.env.example.

- [ ] Write failing interaction tests for SOL add then choose on three pages, invalid/archived URL, last symbol removal, late request after switch, ETF unsupported detail.
- [ ] Add research schemas/API contract above, preserve trading type restrictions, update API/Hybrid/Mock consistently; Mock behavior visibly offline.
- [ ] Add URL-aware shared selector with remembered preference and directory authority, guards before first symbol-scoped query, selector remains visible in loading/error/empty states.
- [ ] Apply to dashboard, market, report list/detail; filter before report pagination, remount report generator by symbol and guard late market mutation callbacks; retain report identity on detail.
- [ ] Add management menu/page with input, optional keywords, capability results, source progress, retries, archive and historical report link. Archived history has no generation/retry.
- [ ] Preserve current trade/backtest/paper constraints and accurate low-price formatting; invalid explicit URLs never silently show BTC.
- [ ] Run frontend tests/lint/typecheck/build, adjust impacted existing tests to intended behavior, provide evidence.

## Task 5: Review and delivery (root + independent reviewer)

- [ ] Review each task diff and resolve integration discrepancies; check spec coverage and unchanged trading restrictions.
- [ ] Run complete backend Ruff/Pyright/pytest and frontend lint/typecheck/tests/build. Report genuine pre-existing failures separately if any, fix introduced failures.
- [ ] Verify add/sync/select/report/archive journey through local UI with controlled data or an available local server, without editing credentials.
- [ ] Update README and operational documentation for migration, supported contract scope, automatic initial/manual refresh, archived history and recoverable failures.
- [ ] Independent code review of correctness/races/security boundaries, address material findings, rerun affected checks.

## Progress

- Planning and spec approved; relevant baselines 83 backend tests, 48 frontend tests passed.
- Implementation pending.
