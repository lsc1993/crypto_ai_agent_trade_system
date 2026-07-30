# Persisted Market Research Read API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 将已持久化的 BTCUSDT、ETHUSDT 公共研究行情通过独立只读 API 与显式前端来源开关提供给工作台，同时保持现有实时市场接口不变。

**Architecture:** MarketResearchQueryService 依赖窄 PersistedMarketReader 协议，并负责 2 分钟 fresh/stale 语义与缺数据错误。SQLAlchemy 适配器仅对现有三张市场表执行 SELECT；新路由复用既有市场响应模型。前端在不改变 WorkbenchApi 或页面组件的前提下，以 VITE_MARKET_DATA_SOURCE 切换 HTTP 路径。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2.x async、asyncpg、PostgreSQL、pytest、pytest-asyncio、Ruff、Pyright；React、TypeScript、Zod、Vitest、React Testing Library。

## Global Constraints

- 仅支持 BTCUSDT、ETHUSDT 和 15m、1h、4h、1d；HTTP 边界必须拒绝其他值和重复参数。
- 本计划不新增依赖、不创建数据库迁移、不修改 .env，也不调用采集、迁移或外部网络。
- reader 只执行 SQL SELECT；不得导出 ORM、完整 JSONB 载荷、连接串、交易所原始响应或数据库写入能力。
- 所有 Python 数值保持 Decimal、数据库数值保持 NUMERIC(38,18)，HTTP/前端数值保持十进制字符串；所有时间保持 UTC。
- 未找到、无效或无法完整组成研究行情时返回 MarketDataUnavailableError("market_research_unavailable", "持久化市场研究数据不可用")，不得回退为实时或 Mock 数据。
- fresh 的条件为 captured_at 不超过 2 分钟；超过阈值返回同一最后成功数据但状态为 stale。
- 不得出现订单、账户、余额、仓位、杠杆、转账、提现、API Key、Secret、Passphrase 或任何私有交易所 API。
- 后端测试仅使用 TEST_DATABASE_URL 临时 schema；每项新行为先写 pytest/Vitest 失败测试，再实现最小代码。

---

## Target File Layout

~~~
backend/
├── src/app/
│   ├── api/
│   │   ├── router.py
│   │   └── routes/{market.py,market_responses.py,research_market.py}
│   ├── infrastructure/persistence/research_reader.py
│   ├── market/research.py
│   └── main.py
└── tests/
    ├── api/test_research_market.py
    ├── market/test_research.py
    └── persistence/test_research_reader.py
frontend/src/
├── app/{bootstrap.tsx,bootstrap.test.tsx}
└── shared/
    ├── api/{create-api.ts,create-api.test.ts,http-workbench-api.ts,http-workbench-api.test.ts}
    └── config/{env.ts,env.test.ts}
~~~

app.market.research 不导入 SQLAlchemy；research_reader.py 是唯一直接查询市场 ORM 模型的新增模块；research_market.py 不直接创建 session。market_responses.py 集中共享 HTTP 响应模型和去重校验，避免实时与研究路由分叉。

### Task 1: Define the persisted-reader port and freshness-aware query service

**Files:**
- Create: backend/src/app/market/research.py
- Create: backend/tests/market/test_research.py

**Interfaces:**
- Consumes Candle、CandleSeries、ContractSymbol、DataFreshness、FreshnessStatus、MarketDataUnavailableError、MarketDetail、MarketSummary、MarketTimeframe from app.market.contracts.
- Produces PersistedMarketSnapshot(summary: MarketSummary, captured_at: datetime), PersistedMarketReader, MarketResearchQueryService.
- Produces await MarketResearchQueryService.get_summaries(symbols) -> tuple[MarketSummary, ...] and await MarketResearchQueryService.get_market(symbol, timeframes) -> MarketDetail.

- [ ] **Step 1: Write the failing query-service tests**

~~~python
@pytest.mark.asyncio
async def test_research_query_marks_latest_snapshot_fresh_within_two_minutes() -> None:
    reader = FakePersistedMarketReader(
        snapshot=stored_snapshot(captured_at=NOW - timedelta(minutes=2)),
    )
    service = MarketResearchQueryService(reader, clock=lambda: NOW)

    summary = (await service.get_summaries((ContractSymbol.BTCUSDT,)))[0]

    assert summary.freshness.status is FreshnessStatus.FRESH


@pytest.mark.asyncio
async def test_research_query_marks_last_success_stale_after_two_minutes() -> None:
    reader = FakePersistedMarketReader(
        snapshot=stored_snapshot(captured_at=NOW - timedelta(minutes=2, microseconds=1)),
    )
    service = MarketResearchQueryService(reader, clock=lambda: NOW)

    summary = (await service.get_summaries((ContractSymbol.BTCUSDT,)))[0]

    assert summary.freshness.status is FreshnessStatus.STALE


@pytest.mark.asyncio
async def test_research_query_rejects_missing_snapshot_or_requested_timeframe() -> None:
    service = MarketResearchQueryService(
        FakePersistedMarketReader(snapshot=None),
        clock=lambda: NOW,
    )

    with pytest.raises(MarketDataUnavailableError) as error:
        await service.get_market(ContractSymbol.BTCUSDT, (MarketTimeframe.M15,))

    assert error.value.code == "market_research_unavailable"
~~~

Use a fake reader whose load_recent_candles returns deliberately reverse-ordered candles. Assert get_market returns ascending CandleSeries and news is an empty tuple.

- [ ] **Step 2: Run the test and confirm the expected initial failure**

Run from backend:

~~~powershell
uv run pytest tests/market/test_research.py -v
~~~

Expected: collection fails with ModuleNotFoundError because app.market.research does not exist.

- [ ] **Step 3: Implement the port, snapshot DTO and query service**

~~~python
class PersistedMarketReader(Protocol):
    async def load_latest_snapshot(
        self,
        symbol: ContractSymbol,
    ) -> PersistedMarketSnapshot | None: ...

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]: ...


class MarketResearchQueryService:
    def __init__(
        self,
        reader: PersistedMarketReader,
        *,
        clock: Callable[[], datetime],
    ) -> None: ...
~~~

Validate that every captured_at and clock value is UTC. get_summaries preserves requested-symbol order and fails the entire request when any snapshot is absent. get_market calls load_recent_candles with limit=200 for each requested timeframe, rejects an empty result, sorts every series by open_at, and sets news=(). Rebuild MarketSummary with original numeric/source/timestamp values and replace only freshness.status.

- [ ] **Step 4: Run focused checks**

~~~powershell
uv run pytest tests/market/test_research.py -v
uv run ruff check src/app/market/research.py tests/market/test_research.py
uv run pyright
~~~

Expected: fresh/stale threshold, missing-data error and candle ordering pass without SQLAlchemy or network access.

- [ ] **Step 5: Commit Task 1**

~~~powershell
git add -- backend/src/app/market/research.py backend/tests/market/test_research.py
git commit -m "feat: add persisted market research query service"
~~~

### Task 2: Implement the PostgreSQL read-only adapter

**Files:**
- Create: backend/src/app/infrastructure/persistence/research_reader.py
- Create: backend/tests/persistence/test_research_reader.py

**Interfaces:**
- Consumes PersistedMarketReader and PersistedMarketSnapshot from app.market.research; MarketSnapshotRecord, MarketCandleRecord; async_sessionmaker[AsyncSession].
- Produces SqlAlchemyPersistedMarketReader(session_factory) implementing both reader methods with SELECT only.

- [ ] **Step 1: Write integration failure tests using migrated_database**

~~~python
@pytest.mark.asyncio
async def test_reader_uses_the_latest_snapshot_and_revalidates_its_summary(
    migrated_database: MigratedDatabase,
) -> None:
    await persist_batch(migrated_database, captured_at=OLDER_TIME, price="68000.00")
    await persist_batch(migrated_database, captured_at=NEWER_TIME, price="69000.00")
    reader = SqlAlchemyPersistedMarketReader(migrated_database.session_factory)

    snapshot = await reader.load_latest_snapshot(ContractSymbol.BTCUSDT)

    assert snapshot is not None
    assert snapshot.captured_at == NEWER_TIME
    assert snapshot.summary.price == Decimal("69000.00")


@pytest.mark.asyncio
async def test_reader_limits_candles_to_200_and_returns_ascending_times(
    migrated_database: MigratedDatabase,
) -> None:
    await persist_201_closed_candles(migrated_database, ContractSymbol.BTCUSDT)
    reader = SqlAlchemyPersistedMarketReader(migrated_database.session_factory)

    candles = await reader.load_recent_candles(
        ContractSymbol.BTCUSDT,
        MarketTimeframe.M15,
        limit=200,
    )

    assert len(candles) == 200
    assert candles[0].open_at < candles[-1].open_at
~~~

Create all test records through MarketCaptureBatch and SqlAlchemyMarketRepository. Do not use raw SQL writes, do not read DATABASE_URL, and add a malformed payload test which asserts load_latest_snapshot raises the stable research-unavailable error.

- [ ] **Step 2: Run the test and confirm the expected initial failure**

~~~powershell
uv run pytest tests/persistence/test_research_reader.py -v
~~~

Expected: collection fails because SqlAlchemyPersistedMarketReader is absent.

- [ ] **Step 3: Implement bounded SELECT queries and DTO conversion**

~~~python
async def load_latest_snapshot(
    self,
    symbol: ContractSymbol,
) -> PersistedMarketSnapshot | None:
    statement = (
        select(MarketSnapshotRecord)
        .where(MarketSnapshotRecord.symbol == symbol.value)
        .order_by(MarketSnapshotRecord.captured_at.desc())
        .limit(1)
    )


async def load_recent_candles(
    self,
    symbol: ContractSymbol,
    timeframe: MarketTimeframe,
    limit: int,
) -> tuple[Candle, ...]:
    statement = (
        select(MarketCandleRecord)
        .where(
            MarketCandleRecord.symbol == symbol.value,
            MarketCandleRecord.timeframe == timeframe.value,
        )
        .order_by(MarketCandleRecord.open_at.desc())
        .limit(limit)
    )
~~~

Require 1 <= limit <= 200. Extract only record.payload["summary"], require a mapping, and rebuild it with MarketSummary.model_validate. Convert records to Candle with ContractSymbol(record.symbol) and MarketTimeframe(record.timeframe), then reverse the descending SQL result. Never return the full payload.

- [ ] **Step 4: Run adapter regression and static checks**

~~~powershell
uv run pytest tests/persistence/test_research_reader.py tests/persistence/test_market_repository.py -v
uv run ruff check src/app/infrastructure/persistence/research_reader.py tests/persistence
uv run pyright
~~~

Expected: only the newest summary is read, candles are bounded and ascending, and the existing write repository remains unchanged.

- [ ] **Step 5: Commit Task 2**

~~~powershell
git add -- backend/src/app/infrastructure/persistence/research_reader.py backend/tests/persistence/test_research_reader.py
git commit -m "feat: read persisted market research data"
~~~

### Task 3: Add stable research API routes and database-aware composition

**Files:**
- Create: backend/src/app/api/routes/market_responses.py
- Create: backend/src/app/api/routes/research_market.py
- Create: backend/tests/api/test_research_market.py
- Modify: backend/src/app/api/routes/market.py, backend/src/app/api/router.py, backend/src/app/main.py

**Interfaces:**
- Consumes MarketResearchQueryService, MarketDataUnavailableError, existing market DTOs; SqlAlchemyPersistedMarketReader and database engine/session factories.
- Produces GET /api/v1/research/markets and GET /api/v1/research/market/{symbol} with existing MarketSummaryListResponse and MarketDetailResponse JSON shapes.
- Extends create_app(market_gateway: PublicMarketGateway | None = None, market_research_reader: PersistedMarketReader | None = None) -> FastAPI.

- [ ] **Step 1: Write failing API tests with a fake reader**

~~~python
@pytest.mark.asyncio
async def test_research_detail_keeps_the_existing_market_wire_contract() -> None:
    app = create_app(
        market_gateway=FakeMarketGateway(),
        market_research_reader=FakePersistedMarketReader(detail=RESEARCH_DETAIL),
    )

    response = await get(app, "/api/v1/research/market/BTCUSDT?timeframes=15m")

    assert response.status_code == 200
    assert response.json()["summary"]["price"] == "68000.30"
    assert response.json()["series"][0]["candles"][0]["open"] == "68000.10"


@pytest.mark.asyncio
async def test_research_route_returns_stable_503_when_reader_is_unavailable() -> None:
    response = await get(
        create_app(market_research_reader=UnavailableReader()),
        "/api/v1/research/markets?symbols=BTCUSDT",
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "market_research_unavailable",
        "message": "持久化市场研究数据不可用",
        "details": {},
    }
~~~

Also assert duplicate symbols/timeframes preserve existing rejection behavior, and GET /api/v1/market still calls the injected live PublicMarketGateway.

- [ ] **Step 2: Run the new route tests and confirm failure**

~~~powershell
uv run pytest tests/api/test_research_market.py -v
~~~

Expected: collection fails because research_market.py and application-state dependency are absent.

- [ ] **Step 3: Extract shared response models and implement the route**

Move MarketSummaryListResponse, MarketCandleResponse, MarketCandleSeriesResponse, MarketDetailResponse, MarketNewsItem, and _require_unique from market.py into market_responses.py. Update the live route to import them without changing its path or behavior.

In research_market.py, define get_market_research_service(request: Request) -> MarketResearchQueryService, call the service with the same ContractSymbol/MarketTimeframe parsing rules, and serialize details through MarketDetailResponse with news=(). Include its router from app.api.router.

In main.py, use an injected reader without creating an engine. Otherwise construct SqlAlchemyPersistedMarketReader(create_session_factory(create_database_engine(settings.database_url))) when database_url exists. When it is absent, install an UnavailablePersistedMarketReader that always raises the stable MarketDataUnavailableError. Close only the engine created by this composition in the existing lifespan finalizer.

- [ ] **Step 4: Run API regression and backend static checks**

~~~powershell
uv run pytest tests/api/test_market.py tests/api/test_research_market.py -v
uv run ruff check src/app/api src/app/main.py tests/api
uv run pyright
~~~

Expected: live and research routes coexist, all response decimal/time encodings remain unchanged, and unavailable research data is a stable 503.

- [ ] **Step 5: Commit Task 3**

~~~powershell
git add -- backend/src/app/api/router.py backend/src/app/api/routes/market.py backend/src/app/api/routes/market_responses.py backend/src/app/api/routes/research_market.py backend/src/app/main.py backend/tests/api/test_research_market.py
git commit -m "feat: expose persisted market research API"
~~~

### Task 4: Add the explicit frontend market data-source switch

**Files:**
- Create: frontend/src/shared/config/env.test.ts
- Modify: frontend/src/shared/config/env.ts, frontend/src/shared/api/create-api.ts, frontend/src/shared/api/create-api.test.ts, frontend/src/shared/api/http-workbench-api.ts, frontend/src/shared/api/http-workbench-api.test.ts, frontend/src/app/bootstrap.tsx, frontend/src/app/bootstrap.test.tsx, frontend/src/app/App.tsx, frontend/src/app/App.test.tsx

**Interfaces:**
- Extends WorkbenchEnvironment with VITE_MARKET_DATA_SOURCE?: string.
- Extends WorkbenchConfig with marketDataSource: "live" | "research".
- Extends HttpWorkbenchApiOptions with marketDataSource?: "live" | "research".
- Keeps every WorkbenchApi method signature and every page/domain Zod schema unchanged.

- [ ] **Step 1: Write failing Vitest cases for configuration and paths**

~~~ts
it("defaults the market data source to live", () => {
  expect(parseWorkbenchConfig({
    VITE_API_BASE_URL: "http://localhost:8000",
    VITE_DATA_MODE: "market-api",
  }).marketDataSource).toBe("live");
});

it("rejects an unknown market data source", () => {
  expect(() => parseWorkbenchConfig({
    VITE_API_BASE_URL: "http://localhost:8000",
    VITE_DATA_MODE: "market-api",
    VITE_MARKET_DATA_SOURCE: "fallback",
  })).toThrowError(expect.objectContaining({
    code: "INVALID_MARKET_DATA_SOURCE",
  }));
});

it("uses research paths only when research is explicit", async () => {
  const api = new HttpWorkbenchApi({
    baseUrl: "http://localhost:8000",
    marketDataSource: "research",
    fetchImpl: successFetch,
  });

  await api.getMarket({ symbol: "BTCUSDT", timeframes: ["15m"] });

  expect(requestPath(fetchImpl)).toBe("/api/v1/research/market/BTCUSDT");
});
~~~

- [ ] **Step 2: Verify the front-end tests fail**

Run from frontend:

~~~powershell
npm run test -- --run src/shared/config/env.test.ts src/shared/api/http-workbench-api.test.ts
~~~

Expected: marketDataSource and INVALID_MARKET_DATA_SOURCE do not exist, and the HTTP path remains live.

- [ ] **Step 3: Implement validated source selection without page changes**

Add a Zod enum for live/research. parseWorkbenchConfig defaults an omitted source to live and emits the typed invalid-source error for other values. Include this variable in applyEntrypointDefaults, and render an explicit Chinese safe configuration error in App's configuration-error display for the invalid-source code.

Pass config.marketDataSource through createWorkbenchApi to HttpWorkbenchApi. In HttpWorkbenchApi derive both market paths from:

~~~ts
const marketApiRoot =
  this.marketDataSource === "research" ? "/api/v1/research" : "/api/v1";
~~~

Use the root only in listMarketSummaries and getMarket. Preserve default live paths and HybridWorkbenchApi delegation for all other methods.

- [ ] **Step 4: Run front-end tests and quality checks**

~~~powershell
npm run lint
npm run typecheck
npm run test -- --run src/shared/config/env.test.ts src/shared/api/create-api.test.ts src/shared/api/http-workbench-api.test.ts src/app/bootstrap.test.tsx
npm run build
~~~

Expected: omitting the variable preserves live behavior; research changes only two request paths; invalid values show a safe configuration error; pages do not change.

- [ ] **Step 5: Commit Task 4**

~~~powershell
git add -- frontend/src/shared/config/env.ts frontend/src/shared/config/env.test.ts frontend/src/shared/api/create-api.ts frontend/src/shared/api/create-api.test.ts frontend/src/shared/api/http-workbench-api.ts frontend/src/shared/api/http-workbench-api.test.ts frontend/src/app/bootstrap.tsx frontend/src/app/bootstrap.test.tsx frontend/src/app/App.tsx frontend/src/app/App.test.tsx
git commit -m "feat: switch market reads to persisted research API"
~~~

### Task 5: Verify no-fallback behavior and complete regression

**Files:**
- Modify only the exact test file that demonstrates a regression in Tasks 1-4.

**Interfaces:**
- Consumes all completed tasks and produces verification evidence. It introduces no production interface.

- [ ] **Step 1: Add the no-fallback regression before operational verification**

~~~python
@pytest.mark.asyncio
async def test_research_route_never_invokes_live_gateway_when_data_is_missing() -> None:
    live_gateway = FailingLiveGateway()
    response = await get(
        create_app(
            market_gateway=live_gateway,
            market_research_reader=UnavailableReader(),
        ),
        "/api/v1/research/markets?symbols=BTCUSDT",
    )

    assert response.status_code == 503
    assert live_gateway.calls == 0
~~~

- [ ] **Step 2: Run the regression and confirm its meaning**

~~~powershell
uv run pytest tests/api/test_research_market.py::test_research_route_never_invokes_live_gateway_when_data_is_missing -v
~~~

Expected: it fails only if the research route calls the live gateway or the test has not been added. Do not change the live route to satisfy it.

- [ ] **Step 3: Apply the smallest correction if the regression revealed one**

The research route may access only request.app.state.market_research_service. If it accesses market_service, replace that access with get_market_research_service; do not add any fallback branch.

- [ ] **Step 4: Run the complete backend and front-end verification**

~~~powershell
Set-Location backend
uv run ruff check .
uv run pyright
uv run pytest

Set-Location ../frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
~~~

Expected: every command returns 0. Automated tests use controlled fake readers, fixtures and the temporary test schema; they do not execute a public network request, Alembic migration or capture command.

- [ ] **Step 5: Commit regression adjustments made in this task**

~~~powershell
git add -- backend/tests/api/test_research_market.py frontend/src/shared/api/http-workbench-api.test.ts
git commit -m "test: verify persisted market research reads"
~~~

## Plan Self-Review

- Spec coverage: Task 1 defines exact fresh/stale/missing behavior and no-fallback service semantics; Task 2 reads only latest snapshots and bounded candles; Task 3 exposes isolated stable routes while preserving live routes; Task 4 adds explicit front-end selection without page/schema changes; Task 5 proves no live fallback and runs complete quality gates.
- Placeholder scan: every task names concrete files, interfaces, failure tests, commands, expected failures and commits. No task adds a dependency, migration, network call, write path or private exchange capability.
- Type consistency: PersistedMarketReader is produced in Task 1, implemented by SqlAlchemyPersistedMarketReader in Task 2, injected into create_app in Task 3, and consumed only by MarketResearchQueryService. The front-end consistently calls the selected root through HttpWorkbenchApi while preserving WorkbenchApi signatures.

