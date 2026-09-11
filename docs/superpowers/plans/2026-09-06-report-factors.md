# Report Factors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add evidence-backed US policy, funding history, and US spot BTC/ETH ETF flow topics to existing reports.

**Architecture:** Fixed-host public adapters produce typed immutable inputs. The application computes facts, freezes evidence, validates topic-specific model citations, and persists an optional JSONB factor analysis. The frontend renders three topics with their individual availability and provenance.

**Tech Stack:** Python 3.12, Pydantic, Decimal, httpx, stdlib HTMLParser, SQLAlchemy/Alembic, React/Zod.

**Spec:** docs/superpowers/specs/2026-09-06-report-factors-design.md

**Status (2026-09-07):** Implemented and reviewed. Backend: 452 tests passed;
frontend: 243 tests passed. Ruff, Pyright, frontend lint and production build passed.
The backend full run used a new workspace `--basetemp` after an existing Windows
temporary-directory permission error. See `docs/report-factors.md` for source
semantics and migration/deployment instructions. Running deployment was not changed.

## Global Constraints

- Policy: SEC, CFTC, Federal Reserve, US Treasury; rolling 7 days UTC.
- ETF: US BTC/ETH spot products, Farside public pages, USD Decimal values.
- No new production dependencies, no credentials/config edits, no trading actions.
- Preserve existing uncommitted changes. Only commit work if it can be separated safely.
- All collected facts use immutable evidence, exact Decimal, UTC aware timestamps.
- Missing data is never zero. Existing reports with no topics remain readable.

### Task 1: Public funding-history and ETF adapters

**Files:**
- Create backend/src/app/market/funding_history.py
- Modify backend/src/app/market/binance_usdm.py
- Create backend/src/app/market/etf_flows.py
- Create backend/tests/market/test_funding_history.py
- Create backend/tests/market/test_etf_flows.py

**Interfaces:**
- FundingPoint: frozen Pydantic fields funding_time: datetime, funding_rate: Decimal.
- FundingHistory: symbol: ContractSymbol, since: datetime, until: datetime, fetched_at: datetime, points: tuple[FundingPoint, ...].
- BinanceUsdmPublicMarketGateway.get_funding_history(symbol: ContractSymbol, *, since: datetime, until: datetime) -> FundingHistory.
- EtfFlowDay: trading_date: date, funds: dict[str, Decimal | None], total_net_flow_usd: Decimal | None, complete: bool.
- EtfFlowSnapshot: symbol: ContractSymbol, fetched_at: datetime, source_url: str, days: tuple[EtfFlowDay, ...].
- FarsideEtfFlowGateway(client: httpx.AsyncClient, clock: Callable[[], datetime]); async collect(symbol: ContractSymbol, *, as_of: datetime) -> EtfFlowSnapshot.
- Adapters raise MarketDataUnavailableError on invalid/unavailable input, propagate cancellation.

- [x] Write failing tests with MockTransport using real parser and public boundary. Hand-checked flows: `(12.5)` -> Decimal('-12500000'), `0.0` -> Decimal('0'), `-` -> None. A row with any undisclosed fund is incomplete even with a displayed partial total.
- [x] Run `uv run pytest tests/market/test_funding_history.py tests/market/test_etf_flows.py -q` to observe the absent behavior.
- [x] Implement bounded fixed-host readers: `/fapi/v1/fundingRate`; `https://farside.co.uk/btc/` and `/eth/`. Funding response validates symbol, finite string Decimal, window boundaries, sorted unique timestamps; use existing gateway request/retry helper. Keep a point immediately before the window only if needed internally, never include it in results.
- [x] Parse table with stdlib HTMLParser, recognize ticker/date rows independent of the number of funds, exclude non-date rows and future New York session dates. Preserve current rows as provisional in topic statistics, including fully numeric rows. Actual fixtures must mirror current public page header shape. Reject unexpected host, oversized payload, malformed/mismatched totals (allow rounding tolerance matching 0.1 million per displayed fund), conflicting dates, and empty tables. Return at most 15 recent days.
- [x] Preserve incomplete recent rows, and reject historical or future as_of timestamps rather than backfilling revised data as previously known; allow up to five minutes for live report collection. fetched_at is actual completion clock time; never invent publication time.
- [x] Run targeted tests, `uv run ruff check` and Pyright on new files; report changed paths and test evidence, do not commit shared edits.

Test examples:

```python
assert history.points[-1].funding_rate == Decimal('-0.0002')
assert snapshot.days[-1].funds['IBIT'] == Decimal('-12500000')
assert snapshot.days[-1].funds['FBTC'] is None
assert snapshot.days[-1].complete is False
```

### Task 2: Freeze and persist three report topics

**Files:** backend/src/app/reports/factors.py, backend/src/app/agent/factors.py,
backend/src/app/agent/service.py, backend/src/app/agent/model.py, backend/src/app/agent/prompt.py,
backend/src/app/news/normalization.py, backend/src/app/reports/contracts.py,
backend/src/app/main.py, backend/src/app/api/routes/analysis_reports.py,
backend/src/app/infrastructure/persistence/models/agent_research.py,
backend/src/app/infrastructure/persistence/report_repository.py,
backend/alembic/versions/0014_add_report_factors.py; tests in corresponding backend directories.

**Interfaces:** consumes Task 1 models and adapters. Produces optional `AgentAnalysis.factor_analysis`
with `policy`, `funding`, `etf` entries. Each entry has availability, facts, source times,
evidence_ids, interpretation, outlook, invalidation and limitations. `ResearchModelRequest`
carries these frozen inputs and model output supports separate topic interpretations.

- [x] Write regressions for Fed/Treasury/CFTC relevant policy without a coin name, reject unrelated government releases, and policy published 6 days ago reaches model while 8-day/future items do not.
- [x] Write integration tests for funding/ETF statistics, exact five disclosed sessions, missing/partial statuses, and same-topic evidence citation enforcement; run failing tests.
- [x] Implement independent acquisition with bounded errors, mandatory 7-day policy selection, protected evidence quota, deterministic statistics and source payload hashes. Stats present actual coverage and do not infer OI history from a snapshot.
- [x] Extend model request/prompt with topical analysis requirements and model output token budget; bound interpretation text independently of existing 1100–2500 narrative characters. Validate unknown and wrong-topic evidence. Without model topical output, show frozen facts with an explicit interpretation limitation.
- [x] Add nullable JSONB factor_analysis, persist/load it in existing immutable report transaction, expose camelCase API fields, and wire real adapters at startup with managed clients.
- [x] Run relevant agent, report, API, news and persistence tests, including legacy report null compatibility and migration round trip when the database is available.

```python
assert report.agent_analysis.factor_analysis.funding.status == 'available'
assert report.agent_analysis.factor_analysis.etf.status == 'partial'
assert six_days_old.id in {item.id for item in request.evidences}
```

### Task 3: Frontend topics, review and verification

**Files:** frontend/src/domain/report.ts, frontend/src/features/reports/ReportFactorAnalysis.tsx,
frontend/src/features/reports/AgentResearchReport.tsx,
frontend/src/features/reports/research-report.css; frontend tests; user documentation.

- [x] Write tests that parse null/absent old factors, render all three sections, show zero/negative/missing distinctly and link citations to frozen evidence; observe failure.
- [x] Add typed schemas and semantic sections using existing report components/styles and Decimal formatting. Show policy institutional provenance and publication date, funding observation range, ETF trade dates separately from fetched_at.
- [x] Run frontend report/domain tests, lint, typecheck and build.
- [x] Review cumulative task diff and fix correctness findings; run `uv run ruff check .`, `uv run pyright`, `uv run pytest` and front-end checks appropriate to all changes. Record environment-only failures explicitly.
- [x] Document migration requirement and external source limitations, update completion ledger and deliver concise result with verification evidence.
