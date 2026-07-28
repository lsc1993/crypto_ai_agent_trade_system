# Binance 公开市场数据接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留 Mock 研究流程和零交易权限边界的前提下，为 BTCUSDT、ETHUSDT 仪表盘与市场页接入可归因、可降级的 Binance USDⓈ-M 公开 REST 行情。

**Architecture:** FastAPI 通过受限 `BinanceUsdmPublicMarketGateway` 访问唯一的公开上游；网关将第三方载荷解析成 Pydantic DTO，再由 `MarketQueryService` 暴露两个只读 API。前端 `HybridWorkbenchApi` 以 HTTP 市场数据覆盖 Mock 市场数据，同时把报告、交易日志、复盘和设置继续交给 `MockWorkbenchApi`，使页面组件不感知切换细节。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、httpx、pytest、Ruff、Pyright；React、TypeScript、Zod、TanStack Query、Vitest、React Testing Library、Playwright。

## Global Constraints

- 仅支持 `BTCUSDT`、`ETHUSDT` 和 `15m`、`1h`、`4h`、`1d`；在后端边界拒绝所有其他标的、周期和任意 URL。
- 上游唯一为 `https://fapi.binance.com` 的 USDⓈ-M **公开** REST 市场数据；不使用 API Key、Secret、Passphrase、Cookie 或账户标识。
- 不实现、导入或调用订单、账户、持仓、余额、杠杆、资金、提现、用户数据流或任何私有 API；业务代码不能直接调用外部 HTTP。
- 所有价格、数量、成交量、资金费率和未平仓量在 Python 中为 `Decimal`，在线上 JSON 契约中为十进制字符串；禁止把它们持久化或计算为 `float`。
- 所有时间均为 UTC、带时区对象或带 `Z` 的 RFC3339 字符串；每个公开响应包含来源、`observedAt`、`fetchedAt` 和新鲜度状态。
- 缓存只存在于进程内，不是事实存储；默认前端模式仍为 `mock`，`market-api` 不得在失败时悄悄显示 Mock 行情。
- 先写失败测试，确认失败原因正确后再写最小实现；正常自动化测试只能使用夹具、假网关或 `httpx.MockTransport`，不得访问 Internet。
- 不修改 `.env`、凭证、生产配置或真实账户文件；本阶段不新增第三方运行时依赖，复用已有 `httpx`。

---

## Target file layout

```text
backend/
├── src/app/
│   ├── api/routes/market.py
│   └── market/
│       ├── __init__.py
│       ├── binance_usdm.py
│       ├── cache.py
│       ├── contracts.py
│       ├── gateway.py
│       └── service.py
└── tests/
    ├── api/test_market.py
    └── market/{test_binance_usdm.py,test_contracts.py,test_service.py}

frontend/
├── src/shared/api/{http-workbench-api,hybrid-workbench-api}.ts
├── src/shared/api/{create-api,http-workbench-api,hybrid-workbench-api}.test.ts
├── src/shared/config/env.ts
└── src/features/{dashboard,market}/…
```

### Task 1: Define the bounded market contract and public-only gateway port

**Files:**
- Create: `backend/src/app/market/__init__.py`
- Create: `backend/src/app/market/contracts.py`
- Create: `backend/src/app/market/gateway.py`
- Create: `backend/tests/market/test_contracts.py`

**Interfaces:**
- Produces `ContractSymbol`, `MarketTimeframe`, `MarketSummary`, `Candle`, `MarketDetail`, `FreshnessStatus`, `MarketDataUnavailableError` and `PublicMarketGateway`.
- Later tasks may request only `get_summaries(symbols)` and `get_market(symbol, timeframes)` from `PublicMarketGateway`.

- [ ] **Step 1: Write failing contract tests for scope, decimals and UTC**

```python
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.market.contracts import Candle, ContractSymbol, MarketTimeframe


def test_candle_rejects_unsupported_scope_and_naive_time() -> None:
    with pytest.raises(ValidationError):
        Candle(
            symbol="SOLUSDT",
            timeframe=MarketTimeframe.M15,
            open_at=datetime(2026, 7, 28, 0, 0),
            close_at=datetime(2026, 7, 28, 0, 15, tzinfo=UTC),
            open_price=Decimal("1"), high_price=Decimal("1"),
            low_price=Decimal("1"), close_price=Decimal("1"),
            volume=Decimal("0"), observed_at=datetime.now(UTC), fetched_at=datetime.now(UTC),
        )


def test_candle_retains_decimal_values_without_float_coercion() -> None:
    candle = Candle(
        symbol=ContractSymbol.BTCUSDT, timeframe=MarketTimeframe.M15,
        open_at=datetime(2026, 7, 28, 0, 0, tzinfo=UTC),
        close_at=datetime(2026, 7, 28, 0, 15, tzinfo=UTC),
        open_price=Decimal("68000.10"), high_price=Decimal("68001.20"),
        low_price=Decimal("67999.90"), close_price=Decimal("68000.30"),
        volume=Decimal("12.34567890"), observed_at=datetime.now(UTC), fetched_at=datetime.now(UTC),
    )
    assert candle.close_price == Decimal("68000.30")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `Set-Location backend; uv run pytest tests/market/test_contracts.py -q`
Expected: FAIL because `app.market` and its types do not exist.

- [ ] **Step 3: Add immutable Pydantic DTOs and gateway protocol**

```python
class ContractSymbol(StrEnum):
    BTCUSDT = "BTCUSDT"
    ETHUSDT = "ETHUSDT"


class MarketTimeframe(StrEnum):
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class PublicMarketGateway(Protocol):
    async def get_summaries(
        self, symbols: tuple[ContractSymbol, ...]
    ) -> tuple[MarketSummary, ...]: ...

    async def get_market(
        self, symbol: ContractSymbol, timeframes: tuple[MarketTimeframe, ...]
    ) -> MarketDetail: ...
```

Implement timezone validators that reject naive datetimes, `Decimal` validators that reject non-finite and negative values where the contract requires non-negative values, and DTO serializers that emit Decimal values as strings. Define `MarketDataUnavailableError(code, message)` without storing upstream bodies or headers.

- [ ] **Step 4: Verify GREEN and static checks**

Run: `Set-Location backend; uv run pytest tests/market/test_contracts.py -q; uv run ruff check src/app/market tests/market/test_contracts.py; uv run pyright`
Expected: all commands exit `0`.

- [ ] **Step 5: Commit the contract boundary**

```powershell
git add -- backend/src/app/market backend/tests/market/test_contracts.py
git commit -m "feat: add bounded public market contract"
```

### Task 2: Implement a fixture-tested Binance public REST adapter with short-lived cache

**Files:**
- Create: `backend/src/app/market/cache.py`
- Create: `backend/src/app/market/binance_usdm.py`
- Create: `backend/tests/market/test_binance_usdm.py`
- Test: `backend/tests/market/test_service.py`

**Interfaces:**
- Consumes `PublicMarketGateway` types from Task 1.
- Produces `BinanceUsdmPublicMarketGateway(client, clock)` implementing the port and `AsyncTtlCache.get_or_load(key, loader, ttl)`.
- The adapter allowlist is exactly `/fapi/v1/ticker/24hr`, `/fapi/v1/klines`, `/fapi/v1/premiumIndex` and `/fapi/v1/openInterest`.

- [ ] **Step 1: Write failing adapter tests using `httpx.MockTransport`**

```python
@pytest.mark.asyncio
async def test_gateway_calls_only_allowlisted_public_paths_and_normalizes_fixture() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "fapi.binance.com"
        assert request.url.path == "/fapi/v1/klines"
        return httpx.Response(200, json=[[1787616000000, "68000.10", "68001.20", "67999.90", "68000.30", "12.34", 1787616899999]])

    gateway = BinanceUsdmPublicMarketGateway(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=fixed_clock,
    )
    detail = await gateway.get_market(ContractSymbol.BTCUSDT, (MarketTimeframe.M15,))

    assert detail.series[0].candles[0].close_price == Decimal("68000.30")
    assert all(request.headers.get("X-MBX-APIKEY") is None for request in requests)


@pytest.mark.asyncio
async def test_gateway_maps_429_to_stable_unavailable_error() -> None:
    gateway = gateway_returning(429, headers={"Retry-After": "1"})
    with pytest.raises(MarketDataUnavailableError, match="market_data_rate_limited"):
        await gateway.get_summaries((ContractSymbol.BTCUSDT,))
```

Also cover malformed decimal strings, malformed K-line rows, timeout, 5xx, an unclosed most-recent K line, cache hit, expired cache, and two concurrent same-key reads invoking the loader only once.

- [ ] **Step 2: Run the focused adapter test and verify RED**

Run: `Set-Location backend; uv run pytest tests/market/test_binance_usdm.py -q`
Expected: FAIL because the adapter and cache do not exist.

- [ ] **Step 3: Implement the fixed upstream boundary and cache**

```python
BINANCE_USDM_BASE_URL = "https://fapi.binance.com"
ALLOWED_PATHS = frozenset({
    "/fapi/v1/ticker/24hr", "/fapi/v1/klines",
    "/fapi/v1/premiumIndex", "/fapi/v1/openInterest",
})

async def _get_public_json(self, path: str, params: dict[str, str]) -> object:
    if path not in ALLOWED_PATHS:
        raise ValueError("公开市场数据路径不在允许列表中")
    response = await self._client.get(path, params=params, timeout=5.0)
    if response.status_code == 429:
        raise MarketDataUnavailableError("market_data_rate_limited", "公开行情请求受到限流")
    response.raise_for_status()
    return response.json()
```

Use a base URL fixed in the injected `httpx.AsyncClient`, never accept it from a request. Retry only idempotent GET calls at most twice for transport errors and 5xx; use the response `Retry-After` if present for 429. Cache summary for 10 seconds, derivatives for 30 seconds and candles for 60 seconds. Every cache record carries its source and `fetched_at`; no raw upstream body is retained after normalization.

- [ ] **Step 4: Verify GREEN and provider-safety scan**

Run: `Set-Location backend; uv run pytest tests/market/test_binance_usdm.py tests/market/test_service.py -q; uv run ruff check .; uv run pyright`
Expected: all tests use `MockTransport`; none make an Internet request.

Run: `rg -n -i "api[_-]?key|secret|passphrase|create[_-]?order|cancel[_-]?order|fetch[_-]?(balance|positions)|withdraw" backend/src/app/market`
Expected: no matches.

- [ ] **Step 5: Commit the adapter**

```powershell
git add -- backend/src/app/market backend/tests/market
git commit -m "feat: add Binance public market gateway"
```

### Task 3: Expose typed, read-only FastAPI market endpoints

**Files:**
- Create: `backend/src/app/api/routes/market.py`
- Modify: `backend/src/app/api/router.py`
- Modify: `backend/src/app/main.py`
- Create: `backend/tests/api/test_market.py`

**Interfaces:**
- Consumes `MarketQueryService` and DTOs from Tasks 1–2.
- Produces `GET /api/v1/markets?symbols=BTCUSDT,ETHUSDT` and `GET /api/v1/market/{symbol}?timeframes=15m,1h,4h,1d`.
- Both endpoints return only values validated by Task 1; no route imports `httpx` or accesses Binance directly.

- [ ] **Step 1: Write failing API tests with an injected fake gateway**

```python
def test_market_detail_rejects_unknown_symbol(client: TestClient) -> None:
    response = client.get("/api/v1/market/SOLUSDT?timeframes=15m")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_market_summary_returns_source_and_utc_freshness(client: TestClient) -> None:
    response = client.get("/api/v1/markets?symbols=BTCUSDT,ETHUSDT")
    assert response.status_code == 200
    first = response.json()["items"][0]
    assert first["freshness"]["source"] == "binance_usdm_public_rest"
    assert first["freshness"]["fetchedAt"].endswith("Z")
```

Add tests that fake a `market_data_rate_limited` error and assert HTTP 503 with exactly `{code, message, details}`, plus duplicate timeframe and more-than-four timeframe rejection.

- [ ] **Step 2: Run API tests and verify RED**

Run: `Set-Location backend; uv run pytest tests/api/test_market.py -q`
Expected: FAIL because the routes and injectable service are absent.

- [ ] **Step 3: Add service injection and routes**

```python
router = APIRouter(prefix="/api/v1", tags=["market"])

@router.get("/markets", response_model=MarketSummaryListResponse)
async def list_markets(
    symbols: Annotated[list[ContractSymbol], Query(min_length=1, max_length=2)],
    service: Annotated[MarketQueryService, Depends(get_market_service)],
) -> MarketSummaryListResponse:
    return MarketSummaryListResponse(items=await service.get_summaries(tuple(symbols)))
```

`create_app()` accepts an optional `market_service` only for dependency injection in tests; production construction uses the fixed-base-url gateway. Add the market router to the existing API router. Convert `MarketDataUnavailableError` to a 503 `ErrorEnvelope` in the established exception layer without logging raw provider bodies.

- [ ] **Step 4: Verify API contract**

Run: `Set-Location backend; uv run pytest tests/api/test_health.py tests/api/test_market.py -q; uv run ruff check .; uv run pyright`
Expected: all commands exit `0`; API tests use only fake gateway data.

- [ ] **Step 5: Commit read-only routes**

```powershell
git add -- backend/src/app/api backend/src/app/main.py backend/tests/api/test_market.py
git commit -m "feat: expose public market data API"
```

### Task 4: Implement `market-api` client composition without changing feature components

**Files:**
- Create: `frontend/src/shared/api/hybrid-workbench-api.ts`
- Create: `frontend/src/shared/api/hybrid-workbench-api.test.ts`
- Modify: `frontend/src/shared/config/env.ts`
- Modify: `frontend/src/shared/api/create-api.ts`
- Modify: `frontend/src/shared/api/create-api.test.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.test.ts`

**Interfaces:**
- `DataMode` becomes `"mock" | "market-api" | "api"`.
- `HttpWorkbenchApi.listMarketSummaries(): Promise<MarketSummary[]>` maps `/api/v1/markets`; `getMarket()` maps `/api/v1/market/{symbol}`.
- `HybridWorkbenchApi` implements all `WorkbenchApi` methods. Market methods use HTTP; every non-market method delegates to `MockWorkbenchApi`.

- [ ] **Step 1: Write failing frontend tests for mode selection and no-silent-fallback**

```tsx
it("selects the hybrid adapter for market-api mode", () => {
  expect(createWorkbenchApi({
    VITE_API_BASE_URL: "http://localhost:8000",
    VITE_DATA_MODE: "market-api",
  })).toBeInstanceOf(HybridWorkbenchApi);
});

it("rejects dashboard loading when live market summaries fail", async () => {
  const api = new HybridWorkbenchApi(mockApi, failingMarketApi);
  await expect(api.getDashboard()).rejects.toMatchObject({ code: "market_data_unavailable" });
});
```

Add tests that a successful dashboard preserves Mock `news` and `recentReports`, replaces only `markets`, and derives `generatedAt` from the newest live `fetchedAt`. Test that HTTP responses are parsed by `marketDetailSchema` and malformed JSON raises `WorkbenchResponseError`.

- [ ] **Step 2: Run the focused frontend tests and verify RED**

Run: `Set-Location frontend; npm run test -- --run src/shared/api/create-api.test.ts src/shared/api/hybrid-workbench-api.test.ts`
Expected: FAIL because `market-api`, hybrid composition and market endpoint mappings do not exist.

- [ ] **Step 3: Add the narrow adapter implementation**

```tsx
export class HybridWorkbenchApi implements WorkbenchApi {
  constructor(
    private readonly mockApi: MockWorkbenchApi,
    private readonly marketApi: HttpWorkbenchApi,
  ) {}

  async getDashboard(): Promise<DashboardSnapshot> {
    const [mockDashboard, markets] = await Promise.all([
      this.mockApi.getDashboard(), this.marketApi.listMarketSummaries(),
    ]);
    const generatedAt = markets
      .map((market) => market.freshness.fetchedAt)
      .sort()
      .at(-1) ?? mockDashboard.generatedAt;
    return dashboardSnapshotSchema.parse({ ...mockDashboard, markets, generatedAt });
  }

  getMarket(input: { symbol: Symbol; timeframes: Timeframe[] }): Promise<MarketDetail> {
    return this.marketApi.getMarket(input);
  }
}
```

Delegate every other `WorkbenchApi` method to `mockApi` explicitly. Keep `api` behavior unchanged: it remains a full HTTP implementation and still reports unavailable endpoints until later plans implement them.

- [ ] **Step 4: Verify GREEN**

Run: `Set-Location frontend; npm run test -- --run src/shared/api; npm run typecheck; npm run lint`
Expected: all commands exit `0`; no page component imports `HttpWorkbenchApi` directly.

- [ ] **Step 5: Commit client composition**

```powershell
git add -- frontend/src/shared/api frontend/src/shared/config/env.ts
git commit -m "feat: add hybrid public market data mode"
```

### Task 5: Make provenance and degraded behavior visible, document startup, and complete controlled validation

**Files:**
- Modify: `frontend/src/features/dashboard/DashboardPage.test.tsx`
- Modify: `frontend/src/features/market/MarketPage.tsx`
- Modify: `frontend/src/features/market/MarketPage.test.tsx`
- Modify: `frontend/.env.example`
- Modify: `frontend/README.md`
- Modify: `frontend/e2e/navigation.spec.ts`
- Create: `backend/scripts/check_public_market.py` (仅在用户明确启动时执行的连通性检查)

**Interfaces:**
- Market-page empty news copy must be “Binance 公开行情模式尚未配置新闻源。”
- Existing `DataFreshnessBadge` renders provider source, observed time, fetched time and text status for every live market result.
- `market-api` is opt-in through non-secret variables: `VITE_DATA_MODE=market-api` and `VITE_API_BASE_URL=http://127.0.0.1:8000`.

- [ ] **Step 1: Write failing UI tests for provenance and unavailable data**

```tsx
it("shows the public provider and an explicit no-news state", async () => {
  renderMarketPageWithApi(liveMarketApiWithNoNews());
  expect(await screen.findByText("来源：binance_usdm_public_rest")).toBeVisible();
  expect(screen.getByText("Binance 公开行情模式尚未配置新闻源。")).toBeVisible();
});

it("does not render Mock market values when the public provider is unavailable", async () => {
  renderMarketPageWithApi(unavailableMarketApi());
  expect(await screen.findByText("公开行情暂不可用")).toBeVisible();
  expect(screen.queryByText("Mock 数据模式")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the UI tests and verify RED**

Run: `Set-Location frontend; npm run test -- --run src/features/dashboard/DashboardPage.test.tsx src/features/market/MarketPage.test.tsx`
Expected: FAIL because the explicit public-news and unavailable states are absent.

- [ ] **Step 3: Implement visible source and failure treatment**

Keep `DataFreshnessBadge` as the source of truth for observed/fetched timestamps. Change only the empty-news branch in `NewsTimeline`/`MarketPage`; do not add a client-side fallback data source. Extend the README with two terminal windows:

```powershell
# window 1
Set-Location backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# window 2, temporary non-secret local configuration
$env:VITE_DATA_MODE = "market-api"
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
Set-Location frontend
npm run dev -- --host 127.0.0.1 --port 4173
```

Document that `mock` remains the default and that opening `market-api` makes a public, read-only market-data request; no `.env` change is required.

- [ ] **Step 4: Run automated quality gates**

Run:

```powershell
Set-Location backend
uv run ruff check .
uv run pyright
uv run pytest

Set-Location ../frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
npm run test:e2e
```

Expected: all commands exit `0`; normal tests have no Internet dependency.

- [ ] **Step 5: Perform the opt-in public connectivity check and commit**

After the automated suite passes, run `Set-Location backend; uv run python scripts/check_public_market.py` and then start the two local processes above. Open `http://127.0.0.1:4173/market/BTCUSDT` and verify source text, two timestamps, `fresh`/`stale` state, decimal formatting and no account/order UI. If the provider is unavailable or region-restricted, record the error envelope and retain `mock` as the normal mode; do not add a fallback exchange.

```powershell
git add -- frontend backend/scripts/check_public_market.py
git commit -m "feat: surface public market data safely"
```

## Plan self-review

- **Spec coverage:** Tasks 1–2 implement the bounded public-only provider, decimals, UTC, allowlist, cache and failure classification. Task 3 supplies typed FastAPI routes and error envelopes. Task 4 preserves the `WorkbenchApi` boundary in explicit `market-api` mode. Task 5 covers visible provenance, degraded UI, documentation, automated regression and opt-in connectivity.
- **Out of scope:** Database persistence, CCXT, WebSocket, news fetching, reports backed by HTTP, accounts, orders, funds and private APIs have no task and cannot be introduced by this plan.
- **Type consistency:** The backend `ContractSymbol`/`MarketTimeframe` map one-to-one to the existing frontend `Symbol`/`Timeframe`; wire numerics are strings and wire timestamps are UTC `Z` strings throughout.
- **Placeholder scan:** 未发现占位标记、泛化错误处理语句或未指定测试。
