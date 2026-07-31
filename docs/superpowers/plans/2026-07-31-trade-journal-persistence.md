# 手工交易日志与复盘持久化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 BTCUSDT/ETHUSDT 的手工交易日志、审计事件和已实现盈亏统计持久化到 PostgreSQL，并让 `market-api` 使用真实交易与统计数据。

**Architecture:** 后端先建立独立于 HTTP/SQL 的 `Decimal` FIFO 交易核心，再以 Alembic `0004` 和 SQLAlchemy 仓储保存原始成交腿、资金现金流、标签及不可变审计事件。交易服务在一个事务中重算派生 PnL 并追加审计；FastAPI 只负责安全的请求/响应边界。前端继续仅依赖 `WorkbenchApi`，由 HTTP/Hybrid 适配器接通真实交易和统计，Mock 模式保持不变。

**Tech Stack:** Python 3.12、Pydantic v2、SQLAlchemy 2.x Async、asyncpg、Alembic、FastAPI、pytest；React 19、TypeScript 5、Zod、TanStack Query、Vitest、Testing Library。

## Global Constraints

- 只支持 `BTCUSDT`、`ETHUSDT`、`long`、`short`，且所有交易均为用户手工录入；不得接入任何账户、订单、私有交易所 API、API Key、Secret、Passphrase、下单、撤单、资金划转或提现能力。
- Python 金额、价格、数量、手续费、资金现金流和盈亏必须使用 `Decimal`；数据库使用 `NUMERIC(38,18)`；HTTP 与前端传输规范十进制字符串；禁止将 `float` 静默转换为领域值。
- 所有时间必须是 UTC 且带时区。交易腿稳定排序键是 `(executed_at, sequence, id)`。
- 资金现金流是有符号值：收取为正、支付为负；手续费永远非负；杠杆不能放大 PnL。
- 交易、成交腿、资金现金流和审计事件均不得物理删除。更新通过替换活动事实、作废旧事实并追加审计事件实现；审计事件表在数据库层拒绝更新和删除。
- 统计只使用完整平仓、未归档交易；不计算未实现盈亏；没有亏损样本时 `profit_factor` 返回 `null`，前端显示“不适用”。
- 新 schema 只通过 `0004_create_trade_journal.py` 引入；不修改 `.env`、既有迁移、公开市场采集频率或生产依赖。数据库集成测试只用 `TEST_DATABASE_URL` 创建的临时 schema。
- `market-api` 下真实交易/统计请求失败必须向 UI 传播安全错误，禁止回退为 Mock；`mock` 模式保持现有离线演示和重置行为。
- 每项行为先写失败测试、确认失败原因后写最小实现。后端改动后执行 Ruff、Pyright、pytest；前端改动后执行 lint、typecheck、Vitest 与生产构建。

---

## Target File Layout

```text
backend/
├── alembic/versions/0004_create_trade_journal.py
├── src/app/
│   ├── api/routes/{trades.py,analytics.py}
│   ├── infrastructure/persistence/{models/trades.py,trade_repository.py}
│   └── trades/{contracts.py,calculator.py,repository.py,service.py,analytics.py}
└── tests/{trades,api,persistence}/
    ├── test_calculator.py
    ├── test_service.py
    ├── test_analytics.py
    ├── test_trade_repository.py
    └── test_trade_routes.py
frontend/src/
├── domain/{trade.ts,analytics.ts}
├── features/{trades,analytics}/
│   ├── CashflowEditor.tsx
│   ├── TradeForm.tsx
│   └── *.test.tsx
└── shared/api/
    ├── {workbench-api.ts,http-workbench-api.ts,hybrid-workbench-api.ts}
    └── *.test.ts
```

### Task 1: 冻结交易领域契约并实现纯 Decimal FIFO 计算

**Files:**
- Create: `backend/src/app/trades/__init__.py`
- Create: `backend/src/app/trades/contracts.py`
- Create: `backend/src/app/trades/calculator.py`
- Test: `backend/tests/trades/test_calculator.py`

**Interfaces:**
- Produces `TradeDirection`, `TradeHorizon`, `TradeLegAction`, `TradeStatus`, `TradeAuditAction` as `StrEnum` values.
- Produces immutable Pydantic contracts `TradeLegDraft`, `TradeCashflowDraft`, `TradeDraft`, `PersistedTrade`, `TradePage`, `TradeFilters`, `AnalyticsFilters`, `AnalyticsSnapshot` and `TradeValidationError`.
- Produces `TradeCalculator.calculate(direction: TradeDirection, legs: tuple[TradeLegDraft, ...], cashflows: tuple[TradeCashflowDraft, ...]) -> TradePnl` where `TradePnl` contains `gross_realized_pnl`, `total_fees`, `total_funding_cashflow`, `net_pnl`, `remaining_quantity`, `is_fully_closed` and ordered match details.

- [ ] **Step 1: 写入 FIFO 失败测试**

In `backend/tests/trades/test_calculator.py`, define UTC helpers and use `Decimal` literals. Cover a fully closed long with two opening legs, a partial-close short, both positive and negative funding cashflows, and a same-timestamp sequence:

```python
result = TradeCalculator().calculate(
    direction=TradeDirection.LONG,
    legs=(
        leg("open-1", "open", "2026-07-31T00:00:00Z", 0, "100", "2", "0.2"),
        leg("open-2", "open", "2026-07-31T00:00:00Z", 1, "110", "1", "0.1"),
        leg("close-1", "close", "2026-07-31T01:00:00Z", 0, "120", "3", "0.3"),
    ),
    cashflows=(cashflow("funding-paid", "-0.4"), cashflow("funding-earned", "0.1")),
)

assert result.gross_realized_pnl == Decimal("50")
assert result.total_fees == Decimal("0.6")
assert result.total_funding_cashflow == Decimal("-0.3")
assert result.net_pnl == Decimal("49.1")
assert result.is_fully_closed is True
```

Add focused rejection tests for an over-close, a `reduce` that clears all remaining quantity, an action after `close`, non-UTC execution time, negative fee, zero quantity, and a float supplied to a Pydantic contract.

- [ ] **Step 2: 运行测试并确认失败原因**

Run from `backend`:

```powershell
uv run pytest tests/trades/test_calculator.py -v
```

Expected: collection fails because `app.trades` does not yet exist.

- [ ] **Step 3: 实现不可变契约与最小计算器**

In `contracts.py`, reject timezone-naive/non-UTC datetimes, `float` inputs, empty/duplicate IDs, unsupported symbols and decimal values outside the stated signs. In `calculator.py`, sort legs by `(executed_at, sequence, id)`, maintain FIFO opening lots, allocate each opening fee proportionally to matched quantity, include every realized exit fee, and calculate:

```python
net_pnl = gross_realized_pnl - total_fees + total_funding_cashflow
```

Treat `close` as valid only when it exactly consumes remaining quantity; treat `reduce` as valid only when it leaves a positive remainder. Do not import FastAPI, SQLAlchemy or HTTP clients in either file.

- [ ] **Step 4: 验证领域核心**

Run:

```powershell
uv run pytest tests/trades/test_calculator.py -v
uv run ruff check src/app/trades tests/trades/test_calculator.py
uv run pyright
```

Expected: all matching, fee/funding, precision and invalid-input cases pass without a database connection.

- [ ] **Step 5: 提交 Task 1**

```powershell
git add -- backend/src/app/trades backend/tests/trades/test_calculator.py
git commit -m "feat: add auditable trade calculation core"
```

### Task 2: 创建不可变审计交易 schema 和 PostgreSQL 仓储

**Files:**
- Create: `backend/alembic/versions/0004_create_trade_journal.py`
- Create: `backend/src/app/infrastructure/persistence/models/trades.py`
- Create: `backend/src/app/trades/repository.py`
- Create: `backend/src/app/infrastructure/persistence/trade_repository.py`
- Test: `backend/tests/persistence/test_trade_repository.py`

**Interfaces:**
- Consumes Task 1 contracts and existing `MigratedDatabase` fixture.
- Produces `TradeRepository` with `create`, `replace`, `archive`, `get_by_id`, `list` and `list_closed` async methods returning Task 1 DTOs only.
- `replace` receives a complete validated `TradeDraft`, a `TradePnl`, `occurred_at` and `correlation_id`; it marks superseded active legs/cashflows as voided, inserts new activity facts and appends exactly one audit event in the same transaction.

- [ ] **Step 1: 写入迁移和仓储失败测试**

In `backend/tests/persistence/test_trade_repository.py`, use only `migrated_database`. Add tests that:

```python
created = await repository.create(
    draft=closed_trade_draft(),
    pnl=closed_trade_pnl(),
    occurred_at=NOW,
    correlation_id=uuid4(),
)
listed = await repository.list(TradeFilters(page=1, page_size=20))

assert listed.items == (created,)
assert created.net_pnl == Decimal("49.1")
```

Also assert an update preserves the original audit row and appends one new row, archive removes the trade from default list and `list_closed`, an invalid foreign report ID is rejected, a duplicate active `(trade_id, executed_at, sequence)` is rejected, and direct SQL `UPDATE` / `DELETE` against `trade_audit_events` raises a database error.

- [ ] **Step 2: 运行测试并确认缺少迁移/仓储**

Run:

```powershell
uv run pytest tests/persistence/test_trade_repository.py -v
```

Expected: collection fails because the repository module and migration revision do not exist.

- [ ] **Step 3: 编写 0004 迁移和 ORM 边界**

Create `0004_create_trade_journal.py` with `down_revision = "0003_create_analysis_reports"`. Create `trades`, `trade_legs`, `trade_cashflows`, `tags`, `trade_tags` and `trade_audit_events`; use PostgreSQL UUID, JSONB and `NUMERIC(38,18)`. Add check constraints for two supported symbols, direction, horizon, status, leg action, positive price/quantity/leverage, nonnegative fee, nonnegative sequence, and valid `closed_at` / `archived_at` ordering.

Use a nullable foreign key from `trades.analysis_report_id` to `analysis_reports.id`. Add a partial unique index for non-voided legs on `(trade_id, executed_at, sequence)`, indexes for active trade filtering and audit lookup, and a trigger that rejects `UPDATE` and `DELETE` on `trade_audit_events`.

Map those tables in `models/trades.py`. In `trade_repository.py`, use `async with session_factory.begin()` for every write and serialize `Decimal` / UTC fields through Task 1 contracts rather than returning ORM records.

- [ ] **Step 4: 验证持久化与审计不变性**

Run:

```powershell
uv run alembic upgrade head
uv run pytest tests/persistence/test_trade_repository.py -v
uv run ruff check alembic/versions/0004_create_trade_journal.py src/app/infrastructure/persistence tests/persistence/test_trade_repository.py
uv run pyright
```

Expected: the isolated test schema contains `0004`; repository writes are atomic; audit rows cannot mutate; no test uses the local user database.

- [ ] **Step 5: 提交 Task 2**

```powershell
git add -- backend/alembic/versions/0004_create_trade_journal.py backend/src/app/infrastructure/persistence/models/trades.py backend/src/app/infrastructure/persistence/trade_repository.py backend/src/app/trades/repository.py backend/tests/persistence/test_trade_repository.py
git commit -m "feat: persist auditable trade journals"
```

### Task 3: 添加交易用例服务和按需复盘统计

**Files:**
- Create: `backend/src/app/trades/service.py`
- Create: `backend/src/app/trades/analytics.py`
- Test: `backend/tests/trades/test_service.py`
- Test: `backend/tests/trades/test_analytics.py`

**Interfaces:**
- Produces `TradeService.create_trade(draft: TradeDraft) -> PersistedTrade`, `update_trade(trade_id: UUID, draft: TradeDraft) -> PersistedTrade`, and `archive_trade(trade_id: UUID) -> None`.
- Produces `PerformanceAnalyticsService.get_snapshot(filters: AnalyticsFilters) -> AnalyticsSnapshot`.
- Consumes the Task 2 repository and Task 1 calculator; services have injected UTC `clock` and UUID `correlation_id_factory` dependencies for deterministic tests.

- [ ] **Step 1: 写入服务层失败测试**

In `test_service.py`, use a fake repository that records complete write requests. Assert `TradeService.create_trade` calls the calculator and repository with one shared UTC event time/correlation ID. Assert `update_trade` raises a typed not-found error without recording a write when the repository returns no active trade, and that a calculator rejection records no write.

In `test_analytics.py`, construct completed, open and archived `PersistedTrade` fixtures. Assert only completed/unarchived items are read; verify ordering by `(closed_at, id)`, cumulative equity, maximum absolute drawdown, profit/loss/breakeven win-rate denominator, nullable profit factor with no losses, and signed decimal expectancy:

```python
assert snapshot.win_rate == Decimal("0.5")
assert snapshot.profit_factor is None
assert snapshot.max_drawdown == Decimal("-4")
```

- [ ] **Step 2: 运行服务测试并确认失败原因**

Run:

```powershell
uv run pytest tests/trades/test_service.py tests/trades/test_analytics.py -v
```

Expected: collection fails because the service and analytics modules are absent.

- [ ] **Step 3: 实现交易服务和统计服务**

`TradeService` must resolve `opened_at` from the first ordered active opening leg and `closed_at` only when `TradePnl.is_fully_closed` is true. It must pass calculated PnL and one correlation ID to the repository, never trust browser-computed PnL.

`PerformanceAnalyticsService` must aggregate only repository `list_closed(filters)` results. Compute gross profit/loss from persisted `net_pnl`, return `None` for profit factor when gross loss is zero, make breakeven trades excluded from the win-rate denominator, and group calendar points by UTC closed date. Do not write a snapshot table or cache computed analytics.

- [ ] **Step 4: 验证应用层**

Run:

```powershell
uv run pytest tests/trades/test_service.py tests/trades/test_analytics.py -v
uv run ruff check src/app/trades tests/trades/test_service.py tests/trades/test_analytics.py
uv run pyright
```

Expected: calculator/repository composition is deterministic; statistical definitions match the confirmed data semantics.

- [ ] **Step 5: 提交 Task 3**

```powershell
git add -- backend/src/app/trades/service.py backend/src/app/trades/analytics.py backend/tests/trades/test_service.py backend/tests/trades/test_analytics.py
git commit -m "feat: add trade journal services and analytics"
```

### Task 4: 暴露安全交易和统计 HTTP API

**Files:**
- Create: `backend/src/app/api/routes/trades.py`
- Create: `backend/src/app/api/routes/analytics.py`
- Modify: `backend/src/app/api/router.py`
- Modify: `backend/src/app/api/errors.py`
- Modify: `backend/src/app/main.py`
- Test: `backend/tests/api/test_trades.py`
- Test: `backend/tests/api/test_analytics.py`

**Interfaces:**
- Produces `GET /api/v1/trades`, `POST /api/v1/trades`, `PUT /api/v1/trades/{trade_id}`, `POST /api/v1/trades/{trade_id}/archive`, and `GET /api/v1/analytics`.
- All list responses serialize as `{items, page, page_size, total}`; domain fields serialize camelCase, including decimal strings and `profitFactor: string | null`.
- `create_app` accepts optional `TradeRepository`; when a database is unavailable it installs a typed unavailable repository/service that returns a safe 503 error without making a network call.

- [ ] **Step 1: 写入路由失败测试**

In `backend/tests/api/test_trades.py`, compose `create_app` with a fake trade repository/service. Assert a create request returns `201` and camelCase fields, a list query sends page/page_size and filters to the service, an update is audit-backed, archive returns `204`, unknown UUID returns the standard `{code: "not_found"}` envelope, and malformed decimal input returns the existing safe validation envelope without echoing the value.

In `backend/tests/api/test_analytics.py`, assert decimal strings remain strings, `profitFactor` is JSON `null` when no losses exist, supported filters are forwarded, and unavailable storage returns a stable 503 envelope rather than calling a market gateway.

- [ ] **Step 2: 运行 API 测试并确认缺少端点**

Run:

```powershell
uv run pytest tests/api/test_trades.py tests/api/test_analytics.py -v
```

Expected: requests return 404 until the routers and composition exist.

- [ ] **Step 3: 实现 Pydantic 路由边界和应用组合**

Define frozen API models in each route with the same alias rules used by `analysis_reports.py`. Parse UUID paths, pagination, UTC filters and decimal strings through Task 1 contracts; derive `TradeDraft` only from request fields. Register routes in `api/router.py` and add a narrow exception handler for typed trade-storage failures that emits `503` with no exception text.

In `main.py`, build `SqlAlchemyTradeRepository` only when `DATABASE_URL` is configured and assign `TradeService` / `PerformanceAnalyticsService` to app state. Keep public market gateway construction, reports and manual capture behavior unchanged.

- [ ] **Step 4: 验证 HTTP 契约和后端质量**

Run:

```powershell
uv run pytest tests/api/test_trades.py tests/api/test_analytics.py -v
uv run ruff check .
uv run pyright
uv run pytest
```

Expected: route responses preserve decimal strings, unavailable storage is safe, and all backend tests pass.

- [ ] **Step 5: 提交 Task 4**

```powershell
git add -- backend/src/app/api/routes/trades.py backend/src/app/api/routes/analytics.py backend/src/app/api/router.py backend/src/app/api/errors.py backend/src/app/main.py backend/tests/api/test_trades.py backend/tests/api/test_analytics.py
git commit -m "feat: expose persisted trade journal API"
```

### Task 5: 扩展前端领域契约、HTTP 映射和 Hybrid 委托

**Files:**
- Modify: `frontend/src/domain/trade.ts`
- Modify: `frontend/src/domain/analytics.ts`
- Modify: `frontend/src/shared/api/workbench-api.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.ts`
- Modify: `frontend/src/shared/api/hybrid-workbench-api.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.test.ts`
- Modify: `frontend/src/shared/api/hybrid-workbench-api.test.ts`
- Modify: `frontend/src/shared/api/create-api.test.ts`

**Interfaces:**
- Replaces `fundingFee` with `fundingCashflows: TradeCashflow[]`, where each item has an immutable client ID, UTC `occurredAt`, signed decimal-string `amount` and `reason`.
- `analyticsSnapshotSchema.profitFactor` becomes `decimalStringSchema.nullable()`.
- `HttpWorkbenchApi` implements list/create/update trades and analytics through the new endpoints; its wire schemas map only `page_size` at the HTTP boundary.
- `HybridWorkbenchApi` remote port includes the existing market/report methods plus `listTrades`, `createTrade`, `updateTrade` and `getAnalytics`, all delegated without a catch/fallback block.

- [ ] **Step 1: 写入前端 API 失败测试**

In `http-workbench-api.test.ts`, add responses for trade pages, a created trade and nullable `profitFactor`. Assert that `createTrade` posts decimal strings/cashflows in the JSON body, `updateTrade` uses one encoded UUID path, `getAnalytics` maps query filters, and response `profitFactor: null` remains `null`.

In `hybrid-workbench-api.test.ts`, make the remote fake throw for unconfigured methods. Assert `listTrades`, `createTrade`, `updateTrade` and `getAnalytics` delegate to remote and a rejected remote trade/analytics request rejects unchanged rather than returning Mock content. Update `create-api.test.ts` to provide all dashboard and journal/analytics HTTP fixture responses required by `market-api`.

- [ ] **Step 2: 运行前端测试并确认当前 HTTP 端点不可用**

Run from `frontend`:

```powershell
npm run test -- --run src/shared/api/http-workbench-api.test.ts src/shared/api/hybrid-workbench-api.test.ts src/shared/api/create-api.test.ts
```

Expected: trade/analytics tests fail because `HttpWorkbenchApi` currently raises `WorkbenchEndpointUnavailableError` and Hybrid delegates them to Mock.

- [ ] **Step 3: 实现 Zod 契约和窄适配器委托**

Update `trade.ts` to validate signed cashflow amounts and ensure client IDs are unique. Preserve all leg accounting checks. Update HTTP request/response schemas to parse local API output, use `encodeURIComponent(tradeId)` for paths, and return parsed Zod data directly.

Rename the Hybrid dependency to a port that includes all real market/report/journal operations. Keep dashboard news from Mock, and leave no `catch` block around real reports, trades or analytics. `MockWorkbenchApi` remains structurally valid for `mock` mode and may retain its Mock-only data flow.

- [ ] **Step 4: 验证适配器边界**

Run:

```powershell
npm run test -- --run src/shared/api/http-workbench-api.test.ts src/shared/api/hybrid-workbench-api.test.ts src/shared/api/create-api.test.ts
npm run lint
npm run typecheck
```

Expected: `mock` remains offline; `market-api` calls only the configured local backend for market/report/journal data; real request failures surface as errors.

- [ ] **Step 5: 提交 Task 5**

```powershell
git add -- frontend/src/domain/trade.ts frontend/src/domain/analytics.ts frontend/src/shared/api/workbench-api.ts frontend/src/shared/api/http-workbench-api.ts frontend/src/shared/api/hybrid-workbench-api.ts frontend/src/shared/api/http-workbench-api.test.ts frontend/src/shared/api/hybrid-workbench-api.test.ts frontend/src/shared/api/create-api.test.ts
git commit -m "feat: connect real trade journal API"
```

### Task 6: 更新手工表单与复盘页面以显示真实数据

**Files:**
- Create: `frontend/src/features/trades/CashflowEditor.tsx`
- Modify: `frontend/src/features/trades/{trade-form-schema.ts,TradeForm.tsx,TradeEditorPage.tsx,TradeEditorPage.test.tsx,TradeForm.test.tsx}`
- Modify: `frontend/src/features/trades/TradeTable.tsx`
- Modify: `frontend/src/features/analytics/{AnalyticsPage.tsx,KpiCards.tsx,AnalyticsPage.test.tsx,KpiCards.test.tsx}`
- Modify: `frontend/src/shared/mocks/{fixtures.ts,mock-workbench-api.test.ts}`

**Interfaces:**
- `CashflowEditor` consumes one `TradeCashflow` plus `onChange` / `onRemove` callbacks and produces an accessible group containing UTC time, signed amount and reason inputs.
- `TradeForm` owns `fundingCashflows`, permits add/remove rows, and passes the complete validated draft to the existing create/update page mutation.
- `KpiCards` accepts a nullable `profitFactor` and renders `不适用` for `null`; charts continue to receive decimal strings only.

- [ ] **Step 1: 写入表单与复盘页面失败测试**

In `TradeForm.test.tsx`, start with a draft containing no cashflows. Add a cashflow row, enter `-0.25`, a UTC time and a reason, submit, and assert the submitted draft contains:

```ts
fundingCashflows: [{
  id: expect.any(String),
  occurredAt: "2026-07-31T01:00:00Z",
  amount: "-0.25",
  reason: "funding payment",
}]
```

Add a validation test for a non-UTC cashflow time and confirm the positive `0.10` entry is accepted. In `KpiCards.test.tsx`, assert `profitFactor: null` produces `不适用`, not `0`, `Infinity` or an empty value. Update Mock fixtures and unit tests to use cashflow rows while preserving offline tests.

- [ ] **Step 2: 运行页面测试并确认旧字段不支持新交互**

Run:

```powershell
npm run test -- --run src/features/trades/TradeForm.test.tsx src/features/trades/TradeEditorPage.test.tsx src/features/analytics/KpiCards.test.tsx src/features/analytics/AnalyticsPage.test.tsx
```

Expected: tests fail because the current form only has a nonnegative `fundingFee` field and KPI code assumes a decimal profit factor.

- [ ] **Step 3: 实现可访问现金流编辑和空利润因子显示**

Create `CashflowEditor` with labelled inputs for “发生时间（UTC）”, “资金现金流” and “说明”, plus a remove button named by row position. Make `TradeForm` generate unique client IDs, add/reduce rows without modifying legs, and use `parseTradeFormDraft` before submission. Extend error mapping so invalid cashflow amount/time produces Chinese safe validation text.

Update `TradeTable` and editor data setup to consume `fundingCashflows`. Change `KpiCards` so only a `null` profit factor displays `不适用`; valid decimal strings continue through the existing formatter unchanged. Do not add a browser-side PnL calculation.

- [ ] **Step 4: 验证表单、页面与 Mock 回归**

Run:

```powershell
npm run test -- --run src/features/trades src/features/analytics src/shared/mocks/mock-workbench-api.test.ts
npm run lint
npm run typecheck
```

Expected: manual form mutations submit one complete draft; frontend never computes authoritative PnL; Mock mode remains resettable and usable.

- [ ] **Step 5: 提交 Task 6**

```powershell
git add -- frontend/src/features/trades frontend/src/features/analytics frontend/src/shared/mocks/fixtures.ts frontend/src/shared/mocks/mock-workbench-api.test.ts
git commit -m "feat: support auditable funding cashflows in journal UI"
```

### Task 7: 执行跨层质量验收与本地手动检查

**Files:**
- Modify only a concrete failing regression test identified by this task.

**Interfaces:**
- No new production surface.
- The completed system uses `market-api` for real markets, reports, trade journals and analytics, while Mock mode remains a separate offline experience.

- [ ] **Step 1: 执行后端完整质量门禁**

Run from `backend`:

```powershell
uv run ruff check .
uv run pyright
uv run pytest
```

Expected: all backend checks pass. Database integration tests use `TEST_DATABASE_URL` temporary schemas only; no command invokes a private exchange endpoint.

- [ ] **Step 2: 执行前端完整质量门禁**

Run from `frontend`:

```powershell
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

Expected: all commands exit `0`; no front-end test makes a third-party network request.

- [ ] **Step 3: 进行本地手动验收**

With PostgreSQL migrated, backend and frontend running in `VITE_DATA_MODE=market-api`:

1. Open `/trades`, create a complete BTCUSDT manual trade with an opening leg, closing leg and a negative funding cashflow.
2. Reload `/trades`; confirm the created trade and its decimal PnL remain visible.
3. Open `/analytics`; confirm its KPI/chart/calendar reflect the persisted closed trade and use “不适用” if there is no loss sample.
4. Edit the trade; confirm its list data changes without exposing a delete action.
5. Switch to `VITE_DATA_MODE=mock`; confirm its seeded trade and reset control still behave independently.
6. Do not run a trading client, provide keys or stop/delete any PostgreSQL volume during this check.

- [ ] **Step 4: 提交 Task 7（仅当具体回归测试需要调整）**

```powershell
git add -- backend/tests/trades/test_calculator.py backend/tests/trades/test_service.py backend/tests/trades/test_analytics.py backend/tests/persistence/test_trade_repository.py backend/tests/api/test_trades.py backend/tests/api/test_analytics.py frontend/src/shared/api/http-workbench-api.test.ts frontend/src/shared/api/hybrid-workbench-api.test.ts frontend/src/shared/api/create-api.test.ts frontend/src/features/trades/TradeForm.test.tsx frontend/src/features/trades/TradeEditorPage.test.tsx frontend/src/features/analytics/AnalyticsPage.test.tsx frontend/src/features/analytics/KpiCards.test.tsx frontend/src/shared/mocks/mock-workbench-api.test.ts
git commit -m "test: verify persisted trade journal workflow"
```

## Plan Self-Review

- **Spec coverage:** Task 1 fixes Decimal/FIFO semantics; Task 2 supplies `0004`, original facts and immutable audit persistence; Task 3 supplies authoritative commands and on-demand analytics; Task 4 exposes safe HTTP composition; Task 5 routes real journal data through adapters; Task 6 adapts user input and nullable profit factor; Task 7 proves all boundaries and mode behavior.
- **Placeholder scan:** Every production task names files, contracts, failure cases, implementation behavior, verification commands and commit scope. Task 7 permits edits only after a named regression test fails.
- **Type consistency:** `TradeDraft` carries `fundingCashflows` from frontend through HTTP to `TradeService`; `TradeCalculator` returns `TradePnl` consumed by repository/service; `AnalyticsSnapshot.profitFactor` is nullable in backend response, Zod contract and KPI UI.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-31-trade-journal-persistence.md`.

The user has explicitly authorized direct work on `main`; use inline execution in this session with review checkpoints and do not create a worktree or dispatch subagents.
