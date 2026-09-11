# Agent Report Validation Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve and display a sanitized format-validation failure summary for degraded AI research reports, while using it to make subsequent format retries specific.

**Architecture:** `ModelOutputError` already carries bounded field paths, categories, and issue counts. The agent run will retain this metadata plus its final format-attempt count, pass it into report persistence, and return it from the report-detail endpoint. A migration adds nullable columns to preserve existing records. The frontend maps the optional detail to concise Chinese copy.

**Tech Stack:** Python 3.12, Pydantic, SQLAlchemy/Alembic, FastAPI, React, TypeScript, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-agent-report-validation-observability-design.md`

## Global Constraints

- Never persist or return model raw output, prompt text, news content, evidence payloads, credentials, or any unbounded model-controlled text.
- Store only a bounded attempt count, issue count, field paths, and controlled local error categories.
- Keep completed reports, legacy rows, and non-format failures backward compatible.
- Use pytest tests before production code, then run Ruff, Pyright, backend pytest, and affected frontend tests.

---

### Task 1: Persist the sanitized failure summary

**Files:**
- Create: `backend/alembic/versions/0016_add_agent_validation_failure_details.py`
- Modify: `backend/src/app/agent/model.py`
- Modify: `backend/src/app/agent/service.py`
- Modify: `backend/src/app/reports/contracts.py`
- Modify: `backend/src/app/infrastructure/persistence/models/agent_research.py`
- Modify: `backend/src/app/infrastructure/persistence/report_repository.py`
- Test: `backend/tests/agent/test_model.py`
- Test: `backend/tests/persistence/test_agent_research_repository.py`

**Interfaces:**
- Produces a bounded validation-failure value object consumed by report persistence and API responses.
- Accepts a format failure only when `error_code == "model_invalid_response"`.

- [ ] **Step 1: Write failing unit and repository tests** for retry metadata and a persisted degraded run.
- [ ] **Step 2: Run the focused tests** and confirm they fail because the metadata is absent.
- [ ] **Step 3: Add the bounded domain value, final-attempt tracking, nullable model columns, migration, and repository mapping.**
- [ ] **Step 4: Re-run focused tests** and confirm they pass.

### Task 2: Make retries react to the rejected schema fields

**Files:**
- Modify: `backend/src/app/agent/model.py`
- Test: `backend/tests/agent/test_model.py`

**Interfaces:**
- Consumes `ModelOutputError.validation_field_paths` and `.validation_error_categories`.
- Produces a retry message containing only those bounded values and the existing base requirements.

- [ ] **Step 1: Write a failing request-capture test** that requires an invalid first response to produce a sanitized, targeted second request.
- [ ] **Step 2: Run the focused test** and confirm it fails for the generic retry instruction.
- [ ] **Step 3: Generate the retry instruction from the bounded error summary.**
- [ ] **Step 4: Re-run focused model tests** and confirm they pass.

### Task 3: Return and display failure details

**Files:**
- Modify: `backend/src/app/api/routes/analysis_reports.py`
- Modify: `frontend/src/domain/report.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.ts`
- Modify: `frontend/src/features/reports/AgentResearchReport.tsx`
- Test: `backend/tests/api/test_agent_analysis_reports.py`
- Test: `frontend/src/features/reports/ReportPages.test.tsx`

**Interfaces:**
- API returns optional `validationFailure` with only `attemptCount`, `issueCount`, `fieldPaths`, and `errorCategories`.
- The UI renders the summary only for a degraded report with this value.

- [ ] **Step 1: Write failing API and UI tests** for a sanitized validation failure response and its Chinese display.
- [ ] **Step 2: Run both focused tests** and confirm they fail because the field is not mapped/rendered.
- [ ] **Step 3: Implement API mapping, client decoding, and accessible UI text.**
- [ ] **Step 4: Re-run focused tests** and confirm they pass.

### Task 4: Verify the complete change

**Files:**
- Verify all files above.

- [ ] **Step 1: Run `uv run ruff check .` from `backend`.**
- [ ] **Step 2: Run `uv run pyright` from `backend`.**
- [ ] **Step 3: Run `uv run pytest` from `backend`.**
- [ ] **Step 4: Run the affected frontend test suite.**
- [ ] **Step 5: Inspect the final diff and check it contains no sensitive data.**
