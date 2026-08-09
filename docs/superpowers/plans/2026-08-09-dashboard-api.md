# 工作台汇总 API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为纯 API 前端模式提供真实、只读的研究工作台汇总数据，消除 Dashboard 的端点未定义错误。

**Architecture:** 新增独立 `DashboardService`，并行读取 BTCUSDT/ETHUSDT 的既有公开行情与最近 5 条持久化报告；路由将领域对象序列化为既有前端 schema 所需的 JSON。前端 HTTP 客户端调用新端点，页面组件保持既有加载、错误和空状态逻辑。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、httpx ASGI 测试、pytest、TypeScript、Zod、Vitest。

## Global Constraints

- 仅访问现有公开行情网关；不得新增交易所密钥、私有 API、后台任务、下单、撤单、资金划转或提现能力。
- Dashboard 路由只读：不得创建报告、交易、账户、订单、数据采集记录或数据库 schema。
- 固定聚合 `BTCUSDT` 与 `ETHUSDT`，报告只读第一页 5 条，资讯永远返回空数组。
- 金额、数量和价格继续由既有 `Decimal` 领域模型表示；时间必须为带 UTC 时区的值。
- 行情源异常沿用 `MarketDataUnavailableError` 的 503 错误包络；报告存储异常必须返回稳定的 503 包络，不能泄漏异常正文。
- 前端继续使用 `VITE_DATA_MODE=api`，不回退到 Mock 或 Hybrid 数据。
- 不读取、修改、打印或提交 `.env`、凭据、真实账户资料；不新增依赖或数据库迁移。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `backend/src/app/dashboard/service.py` | 汇总公开市场与已持久化报告，输出不可变 Dashboard 领域快照。 |
| `backend/src/app/api/routes/dashboard.py` | 声明 `GET /api/v1/dashboard` 及稳定 camelCase 响应模型。 |
| `backend/src/app/main.py` | 创建并注入 `DashboardService` 到应用状态。 |
| `backend/src/app/api/router.py` | 在版本化 API 路由中注册 Dashboard 路由。 |
| `backend/src/app/api/errors.py` | 将 `ReportStorageUnavailableError` 规范化为 503 错误包络。 |
| `backend/tests/api/test_dashboard.py` | 从 HTTP 边界验证汇总成功、市场失败与报告存储失败。 |
| `frontend/src/shared/api/http-workbench-api.ts` | 将 `getDashboard()` 映射到真实 HTTP 端点。 |
| `frontend/src/shared/api/http-workbench-api.test.ts` | 验证端点路径与既有 Dashboard Zod schema 解析。 |

## Task 1: 后端只读 Dashboard 汇总端点

**Files:**
- Create: `backend/src/app/dashboard/__init__.py`
- Create: `backend/src/app/dashboard/service.py`
- Create: `backend/src/app/api/routes/dashboard.py`
- Create: `backend/tests/api/test_dashboard.py`
- Modify: `backend/src/app/main.py`
- Modify: `backend/src/app/api/router.py`
- Modify: `backend/src/app/api/errors.py`

**Interfaces:**
- Consumes: `MarketQueryService.get_summaries(tuple[ContractSymbol, ...])`, `AnalysisReportRepository.list(page, page_size, symbol, status)` and `AnalysisReportSummary`.
- Produces: `DashboardService.get_snapshot() -> DashboardSnapshot` and `GET /api/v1/dashboard`.

- [ ] **Step 1: 写出 HTTP 失败测试**

在 `backend/tests/api/test_dashboard.py` 定义与既有市场测试相同的 `httpx.ASGITransport` 辅助函数、`FakeMarketGateway` 与内存报告仓库。测试成功响应必须断言：

```python
response = await get(create_app(
    market_gateway=FakeMarketGateway(),
    analysis_report_repository=InMemoryReportRepository((recent_report,)),
), "/api/v1/dashboard")

assert response.status_code == 200
assert [item["symbol"] for item in response.json()["markets"]] == ["BTCUSDT", "ETHUSDT"]
assert response.json()["news"] == []
assert response.json()["recentReports"][0]["id"] == str(recent_report.id)
assert response.json()["generatedAt"].endswith("Z")
```

再添加两个最小错误测试：`RateLimitedGateway.get_summaries()` 抛出 `MarketDataUnavailableError("market_data_rate_limited", ...)` 时返回 503 与该 `code`；报告仓库 `list()` 抛出 `ReportStorageUnavailableError("研究报告读取不可用")` 时返回 503、`code == "report_storage_unavailable"`，且 `message` 为固定安全文案。

- [ ] **Step 2: 运行测试并确认正确 RED**

Run（工作目录：`backend`）：

```powershell
uv run pytest tests/api/test_dashboard.py -v
```

Expected: Dashboard 成功测试因 `/api/v1/dashboard` 尚不存在而得到 404；报告存储测试尚未有稳定 503 包络。测试不能因导入、夹具或临时目录错误而替代该业务 RED。

- [ ] **Step 3: 实现领域服务、路由和错误包络**

在 `app/dashboard/service.py` 定义 Pydantic 不可变模型与服务：

```python
class DashboardSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    markets: tuple[MarketSummary, ...]
    recent_reports: tuple[AnalysisReportSummary, ...]
    generated_at: UtcDateTime


class DashboardService:
    async def get_snapshot(self) -> DashboardSnapshot:
        markets, reports = await asyncio.gather(
            self._market.get_summaries((ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT)),
            self._reports.list(page=1, page_size=5, symbol=None, status=None),
        )
        return DashboardSnapshot(
            markets=markets,
            recent_reports=reports.items,
            generated_at=_require_utc(self._clock()),
        )
```

`_require_utc` 必须拒绝无时区或非 UTC 时钟值。`main.create_app()` 创建服务并保存到 `app.state.dashboard_service`；新增可选 `dashboard_clock` 注入参数，以便测试使用固定 UTC 时间。`api/router.py` 注册 dashboard 路由。

在 `dashboard.py` 创建带 `alias_generator`、`serialize_by_alias=True` 的响应模型；`news` 固定为 `()`, `recent_reports` 逐字段映射为前端 `analysisReportSummarySchema` 的 camelCase 字段。不得复用带下划线的私有转换函数。

在 `errors.py` 增加 `ReportStorageUnavailableError` handler，响应：

```python
_response(
    503,
    ErrorEnvelope(
        code="report_storage_unavailable",
        message="研究报告存储暂不可用",
    ),
)
```

- [ ] **Step 4: 运行后端目标测试并确认 GREEN**

Run（工作目录：`backend`）：

```powershell
uv run pytest tests/api/test_dashboard.py tests/api/test_market.py tests/api/test_analysis_reports.py -v
uv run ruff check src tests/api/test_dashboard.py
uv run pyright
```

Expected: Dashboard 成功、行情 503、报告存储 503 与既有市场/报告 API 测试均通过；Ruff 和 Pyright 无错误。

- [ ] **Step 5: 提交后端端点**

```powershell
git add -- backend/src/app/dashboard backend/src/app/api/routes/dashboard.py backend/src/app/main.py backend/src/app/api/router.py backend/src/app/api/errors.py backend/tests/api/test_dashboard.py
git commit -m "feat: add dashboard api"
```

## Task 2: 前端 HTTP 客户端接入

**Files:**
- Modify: `frontend/src/shared/api/http-workbench-api.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.test.ts`

**Interfaces:**
- Consumes: `GET /api/v1/dashboard` 返回既有 `dashboardSnapshotSchema`。
- Produces: `HttpWorkbenchApi.getDashboard(): Promise<DashboardSnapshot>` 的实际 HTTP 实现。

- [ ] **Step 1: 写出前端失败测试**

在 `http-workbench-api.test.ts` 增加固定 `dashboardWire`，使用 `fetchImpl` 返回该 JSON：

```typescript
const api = new HttpWorkbenchApi({
  baseUrl: "http://localhost:8000",
  fetchImpl: vi.fn(() => Promise.resolve(Response.json(dashboardWire))),
});

await expect(api.getDashboard()).resolves.toEqual(dashboardWire);
expect(new URL(fetchImpl.mock.calls[0]?.[0] as URL).pathname).toBe(
  "/api/v1/dashboard",
);
```

`dashboardWire` 必须含两条合法 `MarketSummary`、`news: []`、一条合法报告摘要和 UTC `generatedAt`，以验证真实 schema 解析而不是只验证请求路径。

- [ ] **Step 2: 运行测试并确认正确 RED**

Run（工作目录：`frontend`）：

```powershell
npm run test -- --run src/shared/api/http-workbench-api.test.ts
```

Expected: 失败原因是现有 `getDashboard()` 抛出 `WorkbenchEndpointUnavailableError`，而不是测试数据 schema 无效。

- [ ] **Step 3: 实现最小客户端映射**

在 `http-workbench-api.ts` 导入 `dashboardSnapshotSchema` 与 `DashboardSnapshot`，将现有 `getDashboard()` 替换为：

```typescript
getDashboard(): Promise<DashboardSnapshot> {
  return this.transport.request(
    "/api/v1/dashboard",
    dashboardSnapshotSchema,
  );
}
```

保留 `WorkbenchEndpointUnavailableError` 给其他尚未映射的接口使用；不修改 `DashboardPage`、数据模式、Mock API 或 Hybrid API。

- [ ] **Step 4: 运行前端质量门并确认 GREEN**

Run（工作目录：`frontend`）：

```powershell
npm run lint
npm run typecheck
npm run test -- --run src/shared/api/http-workbench-api.test.ts
npm run build
```

Expected: 新客户端测试与项目检查通过，生产构建继续使用 `VITE_DATA_MODE=api`。

- [ ] **Step 5: 提交前端接入**

```powershell
git add -- frontend/src/shared/api/http-workbench-api.ts frontend/src/shared/api/http-workbench-api.test.ts
git commit -m "feat: load dashboard through api"
```

## Task 3: Compose 运行验收

**Files:**
- Modify: 无

**Interfaces:**
- Consumes: 已构建的 `api` 与 `frontend` Compose 服务。
- Produces: 浏览器可用的研究工作台，无“数据加载失败”。

- [ ] **Step 1: 重建并启动本地服务**

Run（仓库根目录，Docker Desktop PowerShell）：

```powershell
docker compose up -d --build
docker compose ps
```

Expected: `postgres` healthy，`api` 与 `frontend` running；不得运行卷删除、迁移降级或数据重置命令。

- [ ] **Step 2: 验证 API 与同源代理**

Run：

```powershell
(Invoke-WebRequest http://localhost:8000/api/v1/dashboard).Content
(Invoke-WebRequest http://localhost:8080/api/v1/dashboard).Content
```

Expected: 两条响应均含 `markets`、`news: []`、`recentReports`、UTC `generatedAt`；如果公开行情临时不可用，均返回既有安全 503 错误包络而不是 HTML 或浏览器 CORS 错误。

- [ ] **Step 3: 浏览器验收与安全停止**

在 Chrome 打开 `http://localhost:8080`，进入“研究工作台”。Expected: 市场摘要和最近报告可显示；资讯显示空态；不显示“无法读取研究工作台数据”。测试后如需停止，仅运行：

```powershell
docker compose down
```

该命令保留 `postgres_data`；禁止附加删除卷选项。

## Plan Self-Review

### Spec coverage

- 真实 Dashboard API、两种数据来源、空资讯、UTC 时间：Task 1。
- 前端 API 模式接入与既有 schema：Task 2。
- 公开行情/报告错误语义、无写入与无真实交易：Task 1、Task 3。
- Compose 与浏览器端到端验收且不删除数据：Task 3。

### Placeholder scan

已检查本计划；不含 TBD、TODO、未定义接口或“适当处理”等空泛步骤。

### Type consistency

- 后端接口固定为 `GET /api/v1/dashboard`；前端固定请求同一路径。
- `DashboardSnapshot` 使用 `markets`、`recent_reports`、`generated_at`；响应转换为 `markets`、`news`、`recentReports`、`generatedAt`。
- 固定市场为 `BTCUSDT`、`ETHUSDT`，报告分页为 `page=1`、`page_size=5`。
