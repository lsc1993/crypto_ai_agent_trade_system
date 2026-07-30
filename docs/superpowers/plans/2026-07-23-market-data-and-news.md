# Market Data and News Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 BTCUSDT 和 ETHUSDT 永续合约建立仅使用公开接口、可追溯、可恢复的 K 线与衍生品数据管道，并提供先以受控假数据源验证的资讯模型与页面接口。

**Architecture:** `market-worker` 通过 application 用例执行启动补数、WebSocket 消费和定时指标抓取；CCXT 与币安官方公开 REST/WebSocket 均隐藏在 infrastructure adapters 后；API 和 Agent 通过只读查询服务获取标准化数据。新闻采用 `NewsSourceAdapter` port，首期只实现 `FakeNewsSourceAdapter`，避免在没有明确授权和条款审阅时抓取真实新闻源。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2.x、PostgreSQL、Alembic、CCXT、httpx、websockets、structlog、pytest、pytest-asyncio；React 前端复用计划 01 的 `HttpWorkbenchApi`。

## Global Constraints

- 只支持 `BTCUSDT`、`ETHUSDT` 与 `15m`、`1h`、`4h`、`1d`。陌生标的或周期必须在边界层拒绝，不能透传给第三方 API。
- CCXT 实例不得设置 `apiKey`、`secret`、`password`、账户代理或私有市场方法；适配器不得提供 `create_order`、`cancel_order`、`fetch_balance`、`fetch_positions` 或杠杆设置方法。
- 只保存已收盘 K 线、必要衍生品指标和研究快照；不保存订单簿、逐笔成交或账户数据。
- 每条持久化数据必须保存标准化来源、观测时间 `observed_at`、抓取时间 `fetched_at` 与版本化原始载荷摘要；时间为 UTC。
- 外部新闻文本是非可信内容，只能以纯文本证据保存和展示，绝不能作为程序指令或 HTML。

---

## Target file layout

```text
backend/
├── alembic/versions/{0003_create_market_data.py,0004_create_news_items.py}
├── src/app/
│   ├── api/{schemas/{market.py,news.py},routes/{market.py,news.py}}
│   ├── application/
│   │   ├── ports/{market_data.py,news.py}
│   │   ├── market/{ingestion.py,queries.py,freshness.py}
│   │   └── news/{ingestion.py,queries.py,normalization.py}
│   ├── domain/{market/models.py,news/models.py}
│   ├── infrastructure/
│   │   ├── exchanges/{ccxt_binance_usdm.py,binance_usdm_rest.py,binance_usdm_ws.py}
│   │   ├── news/{base.py,fake.py}
│   │   └── persistence/{models/{market.py,news.py},repositories/{market.py,news.py}}
│   ├── repositories/{market.py,news.py}
│   ├── workers/market_worker.py
│   └── shared/retry.py
└── tests/
    ├── unit/{domain/test_market_models.py,application/test_freshness.py,application/test_news_normalization.py}
    ├── integration/{exchanges/test_ccxt_binance_usdm.py,exchanges/test_binance_usdm_rest.py,persistence/test_market_repository.py,persistence/test_news_repository.py}
    └── integration/api/{test_market_api.py,test_news_api.py}
```

## Task 1: Add bounded market domain types and public-only adapter ports

**Files:**
- Create: `backend/src/app/domain/market/models.py`, `backend/src/app/application/ports/market_data.py`
- Create: `backend/tests/unit/domain/test_market_models.py`
- Modify: `backend/pyproject.toml`

- [ ] Write failure tests first for invalid symbols/timeframes, non-UTC timestamps, unclosed candles, negative/float values and invalid metric source metadata.
- [ ] Add runtime dependencies `ccxt`, `httpx`, and `websockets` to `backend/pyproject.toml`; update `uv.lock`. Their approved role is public market access only. `httpx` must be a production dependency because adapters use it at runtime.
- [ ] Define strict domain types and ports:

```python
class ContractSymbol(StrEnum):
    BTCUSDT = "BTCUSDT"
    ETHUSDT = "ETHUSDT"

class Timeframe(StrEnum):
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"

@dataclass(frozen=True)
class Candle:
    symbol: ContractSymbol
    timeframe: Timeframe
    open_at: datetime
    close_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    is_closed: bool
    source: str
    observed_at: datetime
    fetched_at: datetime

class OhlcvGateway(Protocol):
    async def fetch_ohlcv(
        self,
        symbol: ContractSymbol,
        timeframe: Timeframe,
        since: datetime | None,
        limit: int,
    ) -> list[Candle]: ...

class BinanceDerivativesGateway(Protocol):
    async def fetch_mark_price(self, symbol: ContractSymbol) -> MarkPrice: ...
    async def fetch_funding_rate(self, symbol: ContractSymbol) -> FundingRate: ...
    async def fetch_open_interest(self, symbol: ContractSymbol) -> OpenInterest: ...
```

- [ ] `Candle` rejects `is_closed=False` in persistence-facing creation. A separate websocket event DTO may represent an in-progress candle but cannot enter the repository layer.
- [ ] Place all exchange symbol mapping in adapters. Domain/application code uses `BTCUSDT`; only CCXT adapter may translate it to the exchange’s required market symbol.

**Verification:**

```powershell
Set-Location backend
uv run pytest tests/unit/domain/test_market_models.py
uv run ruff check src/app/domain/market src/app/application/ports tests/unit/domain
uv run pyright
```

Expected result: unsupported scope is rejected locally before any network request is possible.

## Task 2: Implement and test CCXT and Binance public REST adapters

**Files:**
- Create: `backend/src/app/infrastructure/exchanges/{ccxt_binance_usdm.py,binance_usdm_rest.py}`
- Create: `backend/tests/integration/exchanges/{test_ccxt_binance_usdm.py,test_binance_usdm_rest.py}`
- Create: `backend/tests/fixtures/exchanges/{ccxt_ohlcv.json,binance_premium_index.json,binance_funding_rate.json,binance_open_interest.json}`

- [ ] Write fixture-driven tests before implementation for symbol mapping, 15m/1h/4h/1d mapping, ISO/epoch time conversion, Decimal conversion, malformed responses, 429 `Retry-After`, timeout and upstream 5xx handling.
- [ ] Implement `CcxtBinanceUsdmOhlcvGateway` with `ccxt.async_support.binanceusdm`, `enableRateLimit=True`, public market configuration only, and an explicit finite request timeout. Instantiate it without authentication fields and close it deterministically.
- [ ] Restrict CCXT calls to public market metadata, ticker and OHLCV methods needed by this plan. The adapter must not return raw CCXT dictionaries past its boundary.
- [ ] Implement `BinanceUsdmPublicRestGateway` with a single `httpx.AsyncClient`, an allowlist of public USDⓈ-M endpoints for mark price, funding rate and open interest, explicit timeouts and error classification. Parse payloads to typed `Decimal` DTOs.
- [ ] Implement retry policy for idempotent public reads only: obey `Retry-After` on 429, exponential backoff with bounded attempts for transient errors, and return a typed unavailable result when retries exhaust. Never retry writes because this application has none.
- [ ] Add a source-safety test scanning exchange adapter modules for forbidden private client methods and credential field assignments. It must fail if a new adapter exposes order/account capability without an explicit future security review.

**Verification:**

```powershell
Set-Location backend
uv run pytest tests/integration/exchanges/test_ccxt_binance_usdm.py tests/integration/exchanges/test_binance_usdm_rest.py
uv run ruff check .
uv run pyright
```

Expected result: all adapter tests run exclusively from fixtures, use no credential, and prove reliable normalization/error behavior without hitting the Internet.

## Task 3: Persist idempotent candles, derivative metrics and research snapshots

**Files:**
- Create: `backend/alembic/versions/0003_create_market_data.py`
- Create: `backend/src/app/infrastructure/persistence/models/market.py`
- Create: `backend/src/app/repositories/market.py`, `backend/src/app/infrastructure/persistence/repositories/market.py`
- Create: `backend/src/app/application/market/{ingestion.py,queries.py,freshness.py}`
- Create: `backend/tests/unit/application/test_freshness.py`, `backend/tests/integration/persistence/test_market_repository.py`

- [ ] Write tests first for candle upsert idempotency, duplicate websocket delivery, source/observation metadata, only-closed persistence, a REST backfill gap, stale/missing thresholds and immutable snapshot creation.
- [ ] Create these tables in migration `0003_create_market_data.py`:

| Table | Required uniqueness / purpose |
|---|---|
| `market_candles` | unique `(symbol, timeframe, open_at)`; normalized OHLCV and source metadata. |
| `derivative_metrics` | unique `(symbol, metric_type, observed_at, source)`; mark price, funding rate, open interest. |
| `market_snapshots` | immutable market/derivative context frozen for a later analysis run. |

- [ ] Use `NUMERIC(38,18)` for all market numerics, `TIMESTAMPTZ` for all timestamps, `JSONB` for a size-bounded raw-payload summary, and indexes on `(symbol, timeframe, open_at DESC)` plus `(symbol, observed_at DESC)`.
- [ ] `MarketIngestionService.backfill_candles()` finds the last stored closed candle, fetches from that boundary, drops in-progress/latest candles, and upserts. `capture_derivative_metrics()` saves each observation with both observed and fetched time.
- [ ] `MarketFreshnessService.evaluate()` uses explicit threshold configuration per data category and returns `fresh`, `stale`, `missing` or `failed` with cause and timestamps. It cannot infer freshness from a received HTTP status alone.
- [ ] `MarketQueryService` returns standard DTOs for API/Agent use and does not leak ORM models or raw payloads.

**Verification:**

```powershell
Set-Location backend
uv run alembic upgrade head
uv run pytest tests/unit/application/test_freshness.py tests/integration/persistence/test_market_repository.py
```

Expected result: replaying the same input cannot duplicate candles or metrics, and stale data is visibly distinguishable from unavailable data.

## Task 4: Implement recoverable public WebSocket worker

**Files:**
- Create: `backend/src/app/infrastructure/exchanges/binance_usdm_ws.py`, `backend/src/app/workers/market_worker.py`, `backend/src/app/shared/retry.py`
- Create: `backend/tests/unit/infrastructure/test_binance_usdm_ws.py`, `backend/tests/unit/workers/test_market_worker.py`
- Modify: `compose.yaml`

- [ ] Write unit tests with fake websocket messages for kline event parsing, `k.x` closed-candle gating, duplicate delivery, malformed event isolation, disconnection, bounded backoff and REST gap recovery scheduling.
- [ ] Implement a WebSocket client limited to public kline/mark-price streams for the two allowed symbols and four allowed timeframes. Do not subscribe to depth, user-data, order or account streams.
- [ ] The worker start sequence is: validate configured scope → REST backfill → begin public WebSocket subscriptions → periodically capture derivative REST metrics → on disconnect use bounded exponential backoff → REST backfill before accepting later events.
- [ ] Make `market_worker` runnable by `uv run python -m app.workers.market_worker`. It logs symbol, timeframe, source, status and correlation IDs only; it must not log raw payloads containing unbounded external data.
- [ ] Add a `market-worker` Compose service with the same backend image, a distinct command, and no environment variable for exchange credentials.
- [ ] Stop gracefully: cancel websocket tasks, close HTTP/CCXT clients, flush only completed transactions and exit without deleting data.

**Verification:**

```powershell
Set-Location backend
uv run pytest tests/unit/infrastructure/test_binance_usdm_ws.py tests/unit/workers/test_market_worker.py
docker compose config
```

Expected result: worker behavior is deterministic under fixtures; Compose confirms a worker exists but has no privileged exchange configuration.

## Task 5: Add controlled news domain, de-duplication and fake adapter

**Files:**
- Create: `backend/alembic/versions/0004_create_news_items.py`
- Create: `backend/src/app/domain/news/models.py`, `backend/src/app/application/ports/news.py`
- Create: `backend/src/app/application/news/{normalization.py,ingestion.py,queries.py}`
- Create: `backend/src/app/infrastructure/news/{base.py,fake.py}`
- Create: `backend/src/app/infrastructure/persistence/models/news.py`, `backend/src/app/infrastructure/persistence/repositories/news.py`, `backend/src/app/repositories/news.py`
- Create: `backend/tests/unit/application/test_news_normalization.py`, `backend/tests/integration/persistence/test_news_repository.py`

- [ ] Write tests first for URL canonicalization, source-ID preference, content-hash fallback, duplicate delivery, BTC/ETH symbol association, language metadata, source attribution and plain-text normalization.
- [ ] Define the port:

```python
class NewsSourceAdapter(Protocol):
    source_name: str

    async def fetch_items(
        self,
        *,
        since: datetime,
        until: datetime,
        symbols: frozenset[ContractSymbol],
    ) -> list[ExternalNewsItem]: ...
```

- [ ] Migration `0004_create_news_items.py` creates `news_items` with source, source item ID, canonical URL, published/fetched times, language, title, bounded plain-text summary, related symbols, normalized deduplication key and a `content_trust` label. Add a unique index on deduplication key.
- [ ] `FakeNewsSourceAdapter` uses fixed fixtures only. It exists to finish ingestion, report and front-end behavior without using an unapproved external source.
- [ ] Store incoming text in a clear untrusted representation. No code parses it as YAML, Markdown instructions, templates or executable content. UI later receives only escaped plain text plus the canonical source link.
- [ ] Do not implement a real news crawler in this task. A real adapter requires a separate user-approved source selection, licensing/terms review, rate-limit design and fixture set before it is added.

**Verification:**

```powershell
Set-Location backend
uv run alembic upgrade head
uv run pytest tests/unit/application/test_news_normalization.py tests/integration/persistence/test_news_repository.py
```

Expected result: the same item from a fixture never appears twice, every displayed item has attribution, and no unapproved source network request exists.

## Task 6: Expose market/news read APIs and replace matching frontend adapters

**Files:**
- Create: `backend/src/app/api/{schemas/{market.py,news.py},routes/{market.py,news.py}}`
- Create: `backend/tests/integration/api/{test_market_api.py,test_news_api.py}`
- Modify: `backend/src/app/api/router.py`, `frontend/src/shared/api/http-workbench-api.ts`
- Modify: relevant tests in `frontend/src/features/{dashboard,market}`

- [ ] Write API tests before routes for the two supported symbols, fixed timeframe parsing, empty/stale/fresh data, pagination, source metadata and invalid input rejection.
- [ ] Implement these read-only endpoints:

```text
GET /api/v1/dashboard
GET /api/v1/market/{symbol}?timeframes=15m,1h,4h,1d
GET /api/v1/market/{symbol}/candles?timeframe=15m&limit=200
GET /api/v1/news?symbol=BTCUSDT&page=1&page_size=20
```

- [ ] Every response includes source and timestamps. The dashboard returns no invented value when a metric is missing; it returns an explicit freshness/unavailable record instead.
- [ ] Implement Zod schemas in `HttpWorkbenchApi` for each route and only switch `getDashboard`, `getMarket` and news list reads when backend contract tests pass. Retain Mock as the default local front-end mode until Compose integration succeeds.
- [ ] Add an API/adapter test showing a stale backend response becomes `DataFreshnessBadge` stale state, not a successful-looking live quote.

**Verification:**

```powershell
Set-Location backend
uv run pytest tests/integration/api/test_market_api.py tests/integration/api/test_news_api.py
Set-Location ../frontend
npm run test -- --run src/features/dashboard src/features/market
```

Expected result: UI data switches by adapter without direct browser access to external services, and every market/news output remains read-only and attributable.
