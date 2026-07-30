# Foundation and Frontend Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可复现的 Python/React 工程基础，并交付使用类型化 Mock 数据的深色研究工作台，使页面、API 边界和无交易安全边界在接入真实数据前稳定下来。

**Architecture:** `backend/` 采用 FastAPI application factory 与 `src` 布局；`frontend/` 是独立 Vite SPA。页面只能通过 `WorkbenchApi` 读取/写入数据，启动时通过环境变量选择 Mock 或 HTTP 实现。第一阶段 Mock 的可变状态仅用于界面演示，不能被表述为真实持久化。

**Tech Stack:** Python 3.12、uv、FastAPI、Pydantic v2、structlog、pytest；React、TypeScript、Vite、Tailwind CSS、shadcn/ui、React Router、TanStack Query、React Hook Form、Zod、decimal.js、Lightweight Charts、Recharts、Vitest、React Testing Library、MSW、Playwright。

## Global Constraints

- 本计划不创建数据库表、不接入交易所、不调用 LLM，也不包含任何下单入口。
- 浏览器不得持有币安或模型供应商密钥，前端不得直接请求币安、OpenAI 或其他 LLM 服务。
- 业务金额在 TypeScript 契约中表示为 `DecimalString`；`number` 只可在图表显示适配层临时使用。
- 主题、显示时区和刷新偏好属于前端偏好；交易、报告和市场事实不允许仅靠浏览器存储持久化。

---

## 依赖变更与影响确认

首次 `uv add` / `npm install` 前，执行者应按下表核对。这些依赖均服务于已确认的本地研究工作台，不会增加账户访问或交易执行权限。

| 范围 | 依赖 | 影响与用途 |
|---|---|---|
| 后端运行时 | `fastapi`、`uvicorn[standard]`、`pydantic-settings`、`structlog`、`httpx` | 提供 HTTP API、配置、公开数据 HTTP 适配基础与不含敏感正文的结构化日志。 |
| 后端开发 | `pytest`、`pytest-asyncio`、`ruff`、`pyright` | 提供测试、静态检查和类型检查，不随生产镜像运行。 |
| 前端运行时 | `react`、`react-router-dom`、`@tanstack/react-query`、`zod`、`react-hook-form`、`@hookform/resolvers`、`decimal.js` | 提供路由、类型化数据、表单与十进制显示。 |
| 前端可视化 | `lightweight-charts`、`recharts` | 只在浏览器渲染行情和复盘图表，不能作为计算或数据源。 |
| 前端 UI/测试 | `tailwindcss`、`@tailwindcss/vite`、shadcn/ui 所需组件、`vitest`、`@testing-library/react`、`msw`、`playwright` | 提供界面一致性与自动化回归。 |

## 目标文件布局

```text
backend/
├── pyproject.toml
├── uv.lock
├── .python-version
├── src/app/
│   ├── __init__.py
│   ├── main.py
│   ├── api/{__init__.py,errors.py,router.py}
│   ├── api/routes/{__init__.py,health.py}
│   └── shared/{__init__.py,config.py,logging.py}
└── tests/api/test_health.py

frontend/
├── .env.example
├── package.json
├── vite.config.ts
├── tsconfig.json
├── components.json
├── src/
│   ├── main.tsx
│   ├── app/{App.tsx,router.tsx,providers.tsx,query-client.ts}
│   ├── styles/{index.css,theme.css}
│   ├── domain/{primitives.ts,market.ts,news.ts,report.ts,trade.ts,analytics.ts,settings.ts}
│   ├── shared/config/env.ts
│   ├── shared/api/{workbench-api.ts,create-api.ts,mock-workbench-api.ts,http-workbench-api.ts,report-stream.ts}
│   ├── shared/lib/{cn.ts,decimal.ts,format.ts,time.ts}
│   ├── shared/mocks/{fixtures.ts,seed.ts,reset.ts}
│   ├── components/layout/{AppShell.tsx,Sidebar.tsx,Topbar.tsx}
│   ├── components/common/{DataFreshnessBadge.tsx,PageState.tsx}
│   ├── components/ui/
│   ├── features/dashboard/
│   ├── features/market/
│   ├── features/reports/
│   ├── features/trades/
│   ├── features/analytics/
│   ├── features/settings/
│   └── test/{setup.tsx,msw/{handlers.ts,server.ts}}
└── e2e/{navigation.spec.ts,trade-journal.spec.ts,report-to-trade.spec.ts,analytics.spec.ts}

.env.example
compose.yaml
```

## Task 1: Create reproducible repository scaffolding and health contract

**Files:**
- Create: `backend/pyproject.toml`, `backend/.python-version`, `backend/src/app/main.py`
- Create: `backend/src/app/shared/config.py`, `backend/src/app/shared/logging.py`
- Create: `backend/src/app/api/router.py`, `backend/src/app/api/errors.py`, `backend/src/app/api/routes/health.py`
- Create: `backend/tests/api/test_health.py`, `.env.example`, `frontend/.env.example`

- [ ] Write `backend/tests/api/test_health.py` first. It must construct the app with `create_app()` and assert that `GET /healthz` returns HTTP 200 and exactly `{ "status": "ok" }`.
- [ ] Add `backend/pyproject.toml` with Python requirement `>=3.12,<3.13`, a `src` package layout, Ruff and Pyright configuration, and the runtime/dev dependencies listed above. Keep tool configuration in this file rather than an untracked local config.
- [ ] Run `uv python install 3.12`, create the project environment with `uv sync --all-groups`, and commit the generated `backend/uv.lock`. Do not install a global Python or copy a virtual environment into the repository.
- [ ] Implement `create_app()` in `backend/src/app/main.py`; it must install a global error handler, include the API router, and return a FastAPI app named `AI 加密合约研究工作台`.
- [ ] Implement immutable settings using `pydantic-settings`. `AppSettings` must provide `app_env`, `log_level`, `cors_allowed_origins`, and a future `database_url`; its default `database_url` may be absent in this phase. Values are loaded only from process environment and `.env` when present locally, never logged.
- [ ] Implement `GET /healthz` outside `/api/v1`. Implement `GET /api/v1` as a small version document rather than a data endpoint. Return errors through `{code, message, details}`.
- [ ] Add root `.env.example` with empty variable values only: `APP_ENV=development`, `LOG_LEVEL=INFO`, `DATABASE_URL=`, `OPENAI_API_KEY=`, `VITE_API_BASE_URL=http://localhost:8000`, `VITE_DATA_MODE=mock`. Include a Chinese warning that it is a template and must not contain real credentials.

**Required interfaces:**

```python
# backend/src/app/main.py
def create_app() -> FastAPI: ...

# backend/src/app/shared/config.py
class AppSettings(BaseSettings):
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    cors_allowed_origins: tuple[str, ...] = ("http://localhost:5173",)
    database_url: SecretStr | None = None
```

`SecretStr` is only a redaction boundary; no code may print `database_url.get_secret_value()`.

**Verification:**

```powershell
Set-Location backend
uv run pytest tests/api/test_health.py
uv run ruff check .
uv run pyright
```

Expected result: all commands exit `0`; the test proves the application factory works without PostgreSQL, exchange network access, or model configuration.

## Task 2: Establish the typed workbench API and deterministic Mock implementation

**Files:**
- Create: `frontend/src/domain/primitives.ts`, `frontend/src/domain/{market,news,report,trade,analytics,settings}.ts`
- Create: `frontend/src/shared/api/{workbench-api,create-api,mock-workbench-api,http-workbench-api,report-stream}.ts`
- Create: `frontend/src/shared/config/env.ts`, `frontend/src/shared/mocks/{fixtures,seed,reset}.ts`
- Create: `frontend/src/shared/api/create-api.test.ts`, `frontend/src/shared/mocks/mock-workbench-api.test.ts`

- [ ] Bootstrap `frontend/` with Vite React TypeScript, strict TypeScript settings, Tailwind CSS and shadcn/ui. Confirm the installed Vite version supports the available Node version before writing application code.
- [ ] Write tests first for `createWorkbenchApi()`: `VITE_DATA_MODE=mock` returns `MockWorkbenchApi`; `VITE_DATA_MODE=api` returns `HttpWorkbenchApi`; every other value throws a configuration error rendered by `PageState`.
- [ ] Define `DecimalString = string`, `UtcIsoString = string`, `Symbol = "BTCUSDT" | "ETHUSDT"`, and `Timeframe = "15m" | "1h" | "4h" | "1d"`. Add Zod parsing at API boundaries; do not trust `localStorage`, HTTP JSON, or query strings without validation.
- [ ] Define the following stable interface. Both Mock and HTTP implementations must conform without type casts:

```ts
export interface WorkbenchApi {
  getDashboard(): Promise<DashboardSnapshot>;
  getMarket(input: { symbol: Symbol; timeframes: Timeframe[] }): Promise<MarketDetail>;
  listReports(filters: ReportFilters): Promise<Page<AnalysisReportSummary>>;
  getReport(reportId: string): Promise<AnalysisReport>;
  startReport(input: { symbol: Symbol }): Promise<{ analysisId: string }>;
  subscribeReport(analysisId: string, onEvent: (event: AnalysisStreamEvent) => void): () => void;
  listTrades(filters: TradeFilters): Promise<Page<Trade>>;
  createTrade(draft: TradeDraft): Promise<Trade>;
  updateTrade(tradeId: string, draft: TradeDraft): Promise<Trade>;
  getAnalytics(filters: AnalyticsFilters): Promise<AnalyticsSnapshot>;
}
```

- [ ] Create deterministic fixtures dated in the past and a resettable in-memory Mock store. It may mirror changes into `localStorage` only to survive a browser refresh during Mock development; add a visible `Mock 数据模式` badge and a reset action. No real persistence claim is allowed.
- [ ] Implement `HttpWorkbenchApi` as a contract shell: base URL parsing, JSON/error-envelope parsing, `AbortSignal` propagation, and no endpoint-specific business mapping until plans 02–04 expose the routes. Its tests must prove it refuses invalid responses.
- [ ] Implement `subscribeReport` in Mock using a timed sequence of `queued`, `running`, `completed` events. The HTTP implementation stays an `EventSource` adapter and must not embed an API token or model key.

**Verification:**

```powershell
Set-Location frontend
npm run typecheck
npm run test -- --run src/shared/api src/shared/mocks
```

Expected result: Mock and HTTP implementations compile against one interface, and malformed wire data is surfaced as an error state rather than silently coerced.

## Task 3: Build the navigable desktop-first application shell

**Files:**
- Create: `frontend/src/app/{App,router,providers,query-client}.tsx`
- Create: `frontend/src/components/layout/{AppShell,Sidebar,Topbar}.tsx`
- Create: `frontend/src/components/common/{DataFreshnessBadge,PageState}.tsx`
- Create: `frontend/src/styles/{index,theme}.css`, `frontend/src/app/App.test.tsx`
- Modify: `frontend/src/main.tsx`

- [ ] Write a route test before the shell. It must render the dashboard and navigate using keyboard-accessible sidebar links to `/market/BTCUSDT`, `/reports`, `/trades`, `/analytics`, and `/settings`.
- [ ] Add `QueryClientProvider`, a single `WorkbenchApi` context, `BrowserRouter`, global error fallback and global loading fallback in `providers.tsx`.
- [ ] Implement routes: `/`, `/market/:symbol`, `/reports`, `/reports/:reportId`, `/trades`, `/trades/new`, `/trades/:tradeId/edit`, `/analytics`, `/settings`. Unknown paths render a clear 404 page with a dashboard link.
- [ ] Implement dark theme by default with sufficient contrast, desktop-first sidebar, responsive collapse behavior, focus-visible outlines, skip-to-content link and semantic landmarks.
- [ ] `DataFreshnessBadge` receives `observedAt`, `fetchedAt`, `status` and renders normal, stale, missing or failed state with visible text; it cannot infer freshness from a display string.
- [ ] `PageState` standardizes loading, empty, error and unavailable state so every data page handles all four states consistently.

**Verification:**

```powershell
Set-Location frontend
npm run test -- --run src/app/App.test.tsx
npm run lint
npm run typecheck
npm run build
```

Expected result: six primary navigation destinations are reachable without a mouse, build output contains no secret values, and the app starts in Mock mode by default.

## Task 4: Implement dashboard and market research views against Mock data

**Files:**
- Create: `frontend/src/features/dashboard/{DashboardPage,DashboardMarketCards,RecentReportCard}.tsx`
- Create: `frontend/src/features/market/{MarketPage,MarketChart,DerivativePanel,NewsTimeline,TimeframeTabs}.tsx`
- Create: tests under `frontend/src/features/dashboard/` and `frontend/src/features/market/`

- [ ] Write RTL/MSW tests for dashboard loading, error, stale and populated states before page implementation.
- [ ] Render BTCUSDT and ETHUSDT cards with price, daily change, volume, funding rate, open interest, source and data timestamps. Every number must be formatted by `format.ts`; the raw decimal string remains the source of truth.
- [ ] Build the market route around the four fixed timeframes. `MarketChart` may convert canonical decimal strings to `number` in a one-way `toChartSeries()` display adapter only. No converted number is saved, sent to an API or used in PnL logic.
- [ ] Render derivative metrics, a source-linked news timeline and freshness state. News title/summary is plain text, never HTML injection; external links use `target="_blank" rel="noopener noreferrer"`.
- [ ] Provide a `生成 AI 研究报告` control that calls `startReport`; label it as research generation and never as a trading action.

**Verification:**

```powershell
Set-Location frontend
npm run test -- --run src/features/dashboard src/features/market
npm run build
```

Expected result: the page accurately exposes source and timestamp metadata in all states; no control uses verbs such as “下单”、“开仓”或“自动交易”.

## Task 5: Implement report, journal, analytics and settings Mock pages

**Files:**
- Create: `frontend/src/features/reports/{ReportListPage,ReportDetailPage,ReportGenerator,EvidenceList,RiskFlags}.tsx`
- Create: `frontend/src/features/trades/{TradeListPage,TradeEditorPage,TradeForm,TradeLegEditor,TradeFilters,TradeTable}.tsx`
- Create: `frontend/src/features/analytics/{AnalyticsPage,AnalyticsFilters,KpiCards,PnlChart,TradeCalendar}.tsx`
- Create: `frontend/src/features/settings/{SettingsPage,preferences-store}.ts`
- Create: focused unit/RTL tests beside each feature

- [ ] Write tests that demonstrate report lifecycle states (`queued`, `running`, `completed`, `degraded`, `failed`), evidence rendering, risk/limitation rendering, and retry behavior before report components.
- [ ] Render reports as observations and uncertainty, with a distinct visual treatment for facts, inference, risk flags and limitations. `EvidenceList` must show source, observation time and immutable evidence ID.
- [ ] Add `基于此分析创建交易日志`, which only pre-fills `linkedAnalysisReportId`; it must not copy report content into the trade draft and must not construct a trade recommendation.
- [ ] Implement a Mock journal editor with dynamic legs, Zod validation for positive decimal strings and UTC timestamps, and a display-only `decimal.js` preview. Enforce on the client that closing quantity cannot exceed opened quantity, while documenting in UI code that the backend will be authoritative.
- [ ] Render Mock analytics using backend-shaped data: net PnL, win rate, profit factor, expectancy, maximum drawdown, equity curve and calendar. Chart components require a text summary/table alternative.
- [ ] Persist only display preferences in `preferences-store`: `theme`, `displayTimezone`, `refreshPreference`. Do not persist drafts, raw reports, account information or keys there.

**Verification:**

```powershell
Set-Location frontend
npm run test -- --run src/features
npm run lint
npm run typecheck
npm run build
```

Expected result: all user journeys work in Mock mode, and interfaces remain independent of the later HTTP implementation.

## Task 6: Add browser-level regression coverage and handoff contract

**Files:**
- Create: `frontend/e2e/{navigation,trade-journal,report-to-trade,analytics}.spec.ts`
- Modify: `frontend/package.json`, `frontend/README.md`

- [ ] Write Playwright tests for navigation, entering a multi-leg Mock trade, filtering it, creating a journal from a report, and calendar drill-down.
- [ ] Run screenshots at 1280 px and 1440 px in CI/local test artifacts; inspect failures manually rather than snapshot-updating blindly.
- [ ] Add an accessibility assertion for each primary route and confirm charts have text alternatives.
- [ ] Document the frozen client contract: decimal strings, UTC ISO strings, error envelope, pagination shape and SSE event names. Plans 02–04 must implement this contract rather than changing page code opportunistically.

**Verification:**

```powershell
Set-Location frontend
npm run test:e2e
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

Expected result: all listed browser journeys pass in Mock mode. This phase is complete when an implementation worker can replace only `create-api.ts` and `http-workbench-api.ts` while keeping feature components unchanged.
