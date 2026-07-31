# Hybrid 真实报告工作流 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `market-api` 模式读取真实市场数据和真实持久化报告，并在真实报告创建后自动打开对应详情页，同时保留交易、统计和资讯的 Mock 行为。

**Architecture:** `WorkbenchApi` 的报告创建结果携带可选 `reportId`。`HttpWorkbenchApi` 保留后端返回的不可变报告 ID；`HybridWorkbenchApi` 把所有报告读取/创建/SSE 调用委托给该 HTTP API，并将真实报告列表合并到原有 Mock 仪表盘。页面只有在收到 `reportId` 时才导航；Mock 实现没有该字段，因此现有 Mock 生命周期不变。

**Tech Stack:** React 19、TypeScript 5、React Router、TanStack Query、Zod、Vitest、Testing Library。

## Global Constraints

- 不修改后端 API、数据库 schema、迁移、`.env`、生产依赖或数据采集频率。
- 浏览器只访问配置的本地 HTTP API；不得加入交易所、模型、账户或交易网络请求。
- `market-api` 下市场和报告请求失败必须向 UI 传播安全错误，禁止将真实报告静默替换成 Mock 报告。
- 交易日志、交易编辑、统计和资讯继续由 `MockWorkbenchApi` 提供；不得改变其存储或生命周期行为。
- 报告 URL 只能使用 `encodeURIComponent(reportId)` 形成一个路径片段；不得在 URL 中携带正文、证据、配置或凭证。
- 每项行为先写 Vitest 失败测试，再写最小实现；最终执行 lint、typecheck、全量测试和生产构建。

---

## Target File Layout

```text
frontend/src/
├── shared/api/
│   ├── workbench-api.ts              # 报告创建结果公共契约
│   ├── http-workbench-api.ts         # 保留后端 reportId
│   ├── hybrid-workbench-api.ts       # 真实市场/报告 + Mock 其余功能
│   ├── hybrid-workbench-api.test.ts  # Hybrid 委托与错误传播
│   └── report-http.test.ts           # HTTP 创建/重试保留 reportId
└── features/
    ├── market/{MarketPage.tsx,MarketPage.test.tsx}
    └── reports/{ReportGenerator.tsx,ReportPages.test.tsx}
```

### Task 1: 冻结报告创建结果并保留真实报告 ID

**Files:**
- Modify: `frontend/src/shared/api/workbench-api.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.ts`
- Modify: `frontend/src/shared/api/report-http.test.ts`

**Interfaces:**
- Produces:

```ts
export interface ReportRunCreated {
  analysisId: string;
  reportId?: string;
}
```

- `WorkbenchApi.startReport(input)` and `WorkbenchApi.retryReport(reportId)` return `Promise<ReportRunCreated>`.
- `HttpWorkbenchApi` returns both values parsed from the existing `{ analysisId, reportId }` backend response.
- Existing `MockWorkbenchApi` results remain valid because `reportId` is optional.

- [ ] **Step 1: 更新 HTTP 失败测试，要求保留 `reportId`**

In `report-http.test.ts`, change the existing create/retry assertions to require:

```ts
await expect(api.startReport({ symbol: "BTCUSDT" })).resolves.toEqual({
  analysisId: "analysis-created-001",
  reportId: "report-created-001",
});
await expect(api.retryReport("report/id?fragment")).resolves.toEqual({
  analysisId: "analysis-created-001",
  reportId: "report-created-001",
});
```

- [ ] **Step 2: 验证测试按预期失败**

Run from `frontend`:

```powershell
npm run test -- --run src/shared/api/report-http.test.ts
```

Expected: the two assertions fail because the HTTP API currently discards `reportId`.

- [ ] **Step 3: 扩展公共契约并返回完整 HTTP 结果**

In `workbench-api.ts`, declare `ReportRunCreated` and update the two method signatures. In `http-workbench-api.ts`, import that type and return the parsed result unchanged:

```ts
async startReport(input: { symbol: Symbol }): Promise<ReportRunCreated> {
  const result = await this.transport.request(
    "/api/v1/analysis-runs",
    analysisRunResultSchema,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(parsedInput) },
  );
  return result;
}
```

Use the equivalent existing retry path and request body rules. Do not change the Zod wire schema or endpoint paths.

- [ ] **Step 4: 验证契约与 HTTP 映射**

Run:

```powershell
npm run test -- --run src/shared/api/report-http.test.ts src/shared/api/http-workbench-api.test.ts
npm run typecheck
```

Expected: the HTTP result contains both IDs; the pre-existing market HTTP tests and strict TypeScript checks pass.

- [ ] **Step 5: 提交 Task 1**

```powershell
git add -- frontend/src/shared/api/workbench-api.ts frontend/src/shared/api/http-workbench-api.ts frontend/src/shared/api/report-http.test.ts
git commit -m "feat: retain report identifiers in HTTP results"
```

### Task 2: 在 Hybrid 模式委托真实报告并合并仪表盘报告

**Files:**
- Modify: `frontend/src/shared/api/hybrid-workbench-api.ts`
- Modify: `frontend/src/shared/api/hybrid-workbench-api.test.ts`
- Modify: `frontend/src/shared/api/create-api.test.ts`

**Interfaces:**
- Replace `MarketDataApi` with `MarketAndReportApi`, which includes:

```ts
interface MarketAndReportApi {
  listMarketSummaries(): Promise<MarketSummary[]>;
  getMarket(input: { symbol: Symbol; timeframes: Timeframe[] }): Promise<MarketDetail>;
  listReports(filters: ReportFilters): Promise<Page<AnalysisReportSummary>>;
  getReport(reportId: string): Promise<AnalysisReport>;
  startReport(input: { symbol: Symbol }): Promise<ReportRunCreated>;
  retryReport(reportId: string): Promise<ReportRunCreated>;
  subscribeReport(analysisId: string, onEvent: (event: AnalysisStreamEvent) => void): () => void;
}
```

- `HybridWorkbenchApi.getDashboard()` performs `Promise.all` over Mock dashboard, real summaries and `listReports({ page: 1, pageSize: 20 })`.
- Dashboard merges `markets` and `recentReports` from the real API while preserving Mock `news`; `generatedAt` remains derived from real market freshness.
- All report methods delegate directly to the real dependency. Trades, analytics and Mock news remain delegated to `mockApi`.

- [ ] **Step 1: 写入 Hybrid 失败测试**

Replace the existing assertion that `recentReports` equal Mock reports with real report fixtures:

```ts
expect(dashboard.recentReports).toEqual([realReportSummary]);
```

Add tests that `listReports`, `getReport`, `startReport`, `retryReport` and `subscribeReport` call the remote fake, and that a rejected remote `listReports` is propagated instead of returning Mock reports.

The remote fake must throw if a method not expected by the test is called, so a fallback is detectable.

- [ ] **Step 2: 验证 Hybrid 测试按预期失败**

Run:

```powershell
npm run test -- --run src/shared/api/hybrid-workbench-api.test.ts
```

Expected: tests fail because the current Hybrid implementation returns Mock reports and does not request the remote report page.

- [ ] **Step 3: 实现窄的市场/报告远程端口与委托**

Update `HybridWorkbenchApi` to accept `MarketAndReportApi`. Implement dashboard composition as:

```ts
const [mockDashboard, markets, reports] = await Promise.all([
  this.mockApi.getDashboard(),
  this.remoteApi.listMarketSummaries(),
  this.remoteApi.listReports({ page: 1, pageSize: 20 }),
]);
return dashboardSnapshotSchema.parse({
  ...mockDashboard,
  generatedAt: latestFetchedAt(markets, mockDashboard.generatedAt),
  markets,
  recentReports: reports.items,
});
```

Delegate report methods to `remoteApi` with no catch block. Keep `listTrades`, `createTrade`, `updateTrade` and `getAnalytics` unchanged on `mockApi`.

- [ ] **Step 4: 验证 Hybrid 与入口组合**

Run:

```powershell
npm run test -- --run src/shared/api/hybrid-workbench-api.test.ts src/shared/api/create-api.test.ts
npm run lint
npm run typecheck
```

Expected: `market-api` still selects Hybrid; it now makes local backend market/report requests, preserves Mock news/trades/analytics, and propagates real report failures.

- [ ] **Step 5: 提交 Task 2**

```powershell
git add -- frontend/src/shared/api/hybrid-workbench-api.ts frontend/src/shared/api/hybrid-workbench-api.test.ts frontend/src/shared/api/create-api.test.ts
git commit -m "feat: use real reports in hybrid mode"
```

### Task 3: 真实报告创建后安全导航至详情

**Files:**
- Modify: `frontend/src/features/market/MarketPage.tsx`
- Modify: `frontend/src/features/market/MarketPage.test.tsx`
- Modify: `frontend/src/features/reports/ReportGenerator.tsx`
- Modify: `frontend/src/features/reports/ReportPages.test.tsx`

**Interfaces:**
- `MarketPage` and `ReportGenerator` use `useNavigate()`.
- When `ReportRunCreated.reportId` exists, both navigate to `/reports/${encodeURIComponent(reportId)}`.
- When `reportId` is absent, `ReportGenerator` retains the existing Mock SSE subscription behavior; `MarketPage` retains its existing Mock success message.

- [ ] **Step 1: 写入市场页自动导航失败测试**

Create a `RecordingMarketApi` subclass whose `startReport` returns:

```ts
{ analysisId: "analysis-real-001", reportId: "report/segment?fragment" }
```

Render both routes with a `useLocation()` probe. After clicking the generation button, assert the route is exactly:

```text
/reports/report%2Fsegment%3Ffragment
```

Retain the existing Mock-only test asserting the `analysis-new-*` success message.

- [ ] **Step 2: 写入报告页生成器自动导航失败测试**

Create a `ReportGenerator` fake that returns a `reportId`. Render `/reports` and `/reports/:reportId` routes with a location probe. Click the button and assert it reaches the encoded detail route without registering an SSE subscription.

- [ ] **Step 3: 验证页面测试按预期失败**

Run:

```powershell
npm run test -- --run src/features/market/MarketPage.test.tsx src/features/reports/ReportPages.test.tsx
```

Expected: both new tests fail because current pages leave the user on the creation page and do not use `reportId`.

- [ ] **Step 4: 实现最小导航分支**

In `MarketPage`, add an `onSuccess` callback to the existing mutation:

```ts
onSuccess: ({ reportId }) => {
  if (reportId !== undefined) {
    navigate(`/reports/${encodeURIComponent(reportId)}`);
  }
}
```

In `ReportGenerator.onSuccess`, preserve the existing mounted/epoch guard. After that guard and before setting lifecycle state, branch on `reportId`: navigate and return when it exists; otherwise execute the existing subscription logic unchanged. Do not add report content to navigation state or query parameters.

- [ ] **Step 5: 验证导航、Mock 生命周期和页面回归**

Run:

```powershell
npm run test -- --run src/features/market/MarketPage.test.tsx src/features/reports/ReportPages.test.tsx
npm run typecheck
```

Expected: real report creation opens the immutable detail page; all existing Mock lifecycle tests continue to subscribe and unsubscribe as before.

- [ ] **Step 6: 提交 Task 3**

```powershell
git add -- frontend/src/features/market/MarketPage.tsx frontend/src/features/market/MarketPage.test.tsx frontend/src/features/reports/ReportGenerator.tsx frontend/src/features/reports/ReportPages.test.tsx
git commit -m "feat: open newly created report details"
```

### Task 4: 完整前端质量验收与使用说明

**Files:**
- Modify only a failing test file if a Task 1-3 regression reveals an incorrect expectation.

**Interfaces:**
- No new production surface.
- `market-api` is the intended daily mode for real markets/reports plus Mock journals/statistics/news.

- [ ] **Step 1: 复查数据模式行为**

Run the existing API factory tests and verify their contracts:

```powershell
npm run test -- --run src/shared/api/create-api.test.ts src/shared/api/hybrid-workbench-api.test.ts
```

Expected: `mock` remains all Mock; `market-api` uses the Hybrid implementation; `api` remains the all-HTTP implementation and still exposes unavailable errors for unimplemented dashboard/trade/analytics endpoints.

- [ ] **Step 2: 执行全量前端质量检查**

Run:

```powershell
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

Expected: all commands exit `0`; no test makes a third-party request and no Mock-only behavior changes unintentionally.

- [ ] **Step 3: 手动验收说明**

With the local backend and frontend running in `market-api` mode:

1. Open `/`; confirm market cards and recent reports use the backend API while news remains the fixed Mock feed.
2. Open `/market/BTCUSDT`; click “生成 AI 研究报告”.
3. Confirm the browser reaches `/reports/<report-id>` without manually refreshing a list.
4. Open `/trades` and `/analytics`; confirm their existing Mock behavior remains available.
5. Stop neither database nor volumes as part of this verification.

- [ ] **Step 4: 提交 Task 4（仅当存在回归调整）**

```powershell
git add -- <only-regression-test-files>
git commit -m "test: verify hybrid real report workflow"
```

## Plan Self-Review

- **Spec coverage:** Task 1 exposes the optional immutable report ID; Task 2 redirects all Hybrid report operations and dashboard history to the local API; Task 3 consumes the ID for safe automatic navigation; Task 4 proves mode boundaries and quality gates.
- **Placeholder scan:** Every production task names exact files, contracts, failure cases, validation commands and commit scope. Task 4 permits edits only when a concrete regression test identifies an incorrect expectation.
- **Type consistency:** `ReportRunCreated` is produced by HTTP, accepted by Hybrid and consumed by both pages; `MarketAndReportApi` includes every delegated report method; `reportId` is optional only for Mock compatibility.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-31-hybrid-real-report-workflow.md`.

Use inline execution in this session with review checkpoints; the user requested direct updates on `main`, so no worktree or subagent delegation is used.
