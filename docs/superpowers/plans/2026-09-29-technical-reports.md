# Skill Technical Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Add an independent Skill-based technical report and conditional flat-position plans.
**Architecture:** Deterministic facts/plans, approved method bundle, bounded model narrative, separate immutable persistence and API through Harness.
**Tech Stack:** Existing Python/FastAPI/SQLAlchemy/PostgreSQL, React/TypeScript/Zod.
**Spec:** ../specs/2026-09-29-technical-reports-design.md

## Global Constraints

- No production dependencies, private APIs, credentials, execution, TradeIntent generation, positions or leverage.
- Preserve original report behavior; all new financial values Decimal / decimal strings and all times UTC.
- New migration is forward-only; frozen report and evidence are immutable; terminal audit is atomic.
- Existing working-copy edits are excluded; implementation uses isolated checkout.

## Review Focus

- Gap, duplicate, stale or wrong-symbol candles must not produce valid plans (Task 1).
- Target cannot be invented to meet minimum reward/risk; most adverse entry and costs are used (Task 1).
- Model injection or ungrounded prices cannot change deterministic facts/plans (Task 2).
- Archived symbols retain readable historical reports but cannot generate anew (Tasks 2, 3).
- Late generation/list responses during symbol changes must not relabel or navigate results (Task 3).

### Task 1: Technical contracts, curated methods and deterministic engine

**Files:** Create backend/src/app/reports/technical.py, backend/src/app/agent/technical/{__init__,methods,engine}.py and methods markdown, backend/tests/agent/test_technical_engine.py.
**Interfaces:** calculate_technical_analysis(detail: MarketDetail, *, captured_at: datetime) -> TechnicalAnalysis; TechnicalAnalysis contains quality, facts, plans, no_plan_reasons, methods, evidence_id. TechnicalReport contains id, analysis_id, symbol, status, created_at, data_cutoff_at, analysis, narrative, error_code. Public JSON camelCase, no raw payload.
- [ ] Write tests for long/short/none, thresholds, closed-only data, duplicates/gaps/freshness, costs, adverse entry and targets.
- [ ] Run pytest tests/agent/test_technical_engine.py; establish expected failure.
- [ ] Implement versioned method adaptation, hashed attribution and pure Decimal engine according to spec. Publish concrete DTO shape for consumers.
- [ ] Run focused pytest and static checks, review spec/numeric behavior.

### Task 2: Fixed research workflow, bounded AI, storage and API

**Files:** Create agent/technical/{model,service}.py, reports/technical_repository.py, harness/technical_research.py, infrastructure/persistence/{technical_report_repository,models/technical_reports}.py, api/routes/technical_reports.py, alembic/versions/0017_create_technical_reports.py and associated tests. Modify main.py, api/router.py, harness/contracts.py, model registration.
**Interfaces:** Separate repository persist(report, frozen_evidence), get(id), list(symbol,page,page_size). Service generate(symbol)->TechnicalReport. POST /technical-reports -> report; GET collection -> {items,page,pageSize,total}; GET id -> report.
- [ ] Write model tests for legitimate references, unknown IDs, numeric/model trade instructions, missing credentials/timeouts, no tools.
- [ ] Implement bounded narrative adapter, strict schema and safe degradation.
- [ ] Write service/API/storage tests for admission, incomplete inputs, missing model, old endpoint compatibility, immutable evidence and atomic terminal events.
- [ ] Implement fixed workflow and Harness-specific policy, dedicated table/migration and application wiring.
- [ ] Run backend checks and migration heads; run database tests only with dedicated test database.

### Task 3: Independent report UI and adapters

**Files:** Create frontend/src/domain/technical-report.ts, features/technical-reports/*, tests; modify WorkbenchApi, HTTP/Mock/Hybrid adapters, router and report entry.
**Interfaces:** startTechnicalReport({symbol})->TechnicalReport; listTechnicalReports({symbol,page,pageSize})->Page<TechnicalReport>; getTechnicalReport(id)->TechnicalReport. The v1 page reuses the bounded report DTO; raw evidence remains internal.
- [ ] Write tests for report selection, rendering conditional plan/degraded/no-plan, late requests and decoders.
- [ ] Implement safe separate routes, history and report detail, financial strings and explicit research assumptions.
- [ ] Run npm lint/typecheck/test/build and old report regressions.

### Task 4: Integration, independent review and documentation

**Files:** README, frontend/README, docs/technical-reports.md, docs/project-status.md, docs/operational-boundaries.md and security doc tests if necessary.
- [ ] Review full change for project boundaries, evidence integrity and old-flow compatibility; fix actionable issues.
- [ ] Document methods, limitations, new migration and run commands without personal paths.
- [ ] Execute full permitted backend/frontend checks and report directories, outcomes and unverified checks.
- [ ] Commit only task-owned files on feature branch; preserve checkout for user review.
