# Backtest Response Decimal Precision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make every decimal emitted by the backtest API compatible with the frontend's 18-fraction-digit decimal contract without changing internal backtest calculations.

**Architecture:** Add a route-local Pydantic serializer for backtest API `Decimal` fields. It quantizes only JSON response values to 18 fraction digits using half-even rounding; domain models, engine results, audit events, and persistence retain their existing values.

**Tech Stack:** Python 3.12, Decimal, Pydantic, FastAPI, pytest, Ruff, Pyright.

## Global Constraints

- Do not use `float` for amounts, quantities, prices, fees, or ratios.
- Preserve immutable audit data and deterministic engine calculations.
- Do not change exchange access, risk limits, execution behaviour, credentials, or `.env` files.
- Public API responses must remain Pydantic-defined and use UTC timestamps.

---

### Task 1: Backtest response precision contract

**Files:**
- Modify: `backend/tests/api/test_backtests.py`
- Modify: `backend/src/app/api/routes/backtests.py`

**Interfaces:**
- Consumes: `BacktestRunDetailResponse`, `BacktestPageResponse`, and the fake backtest repository used by API tests.
- Produces: JSON decimal strings with no more than 18 fraction digits for every decimal field exposed by the backtest route.

- [x] **Step 1: Write the failing test**

Add a completed `PersistedBacktestRun` fixture whose summary includes `Decimal("0.09039311972615772470574350276")` and `Decimal("0.4296927291438667043301680249")`. Assert POST, list, and detail responses serialize them respectively as `"0.090393119726157725"` and `"0.429692729143866704"`.

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_backtests.py -q`

Expected: FAIL because the existing route emits the unbounded fractional strings.

- [x] **Step 3: Write minimal implementation**

In `backtests.py`, define a route-local `BacktestDecimalValue` annotated serializer that quantizes a `Decimal` to `Decimal("0.000000000000000001")` using `ROUND_HALF_EVEN` within a local context whose precision is derived from the value's digits plus the 18 response fraction digits. Replace `DecimalValue` in all backtest response models with `BacktestDecimalValue`.

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_backtests.py -q`

Expected: PASS; the test confirms the API's list, create, and detail payloads conform to the frontend decimal precision contract.

- [x] **Step 5: Run scope verification**

Run: `uv run ruff check .; uv run pyright; uv run pytest tests/api/test_backtests.py tests/research/backtests/test_engine.py`

Expected: All commands exit 0. The engine tests prove response normalization did not change deterministic replay semantics.
