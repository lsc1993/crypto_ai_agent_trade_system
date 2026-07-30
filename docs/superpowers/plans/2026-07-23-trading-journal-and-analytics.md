# Trading Journal and Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 BTCUSDT/ETHUSDT 合约交易的手工录入、分批成交、审计、持久化与基础复盘统计，确保每一项盈亏和统计都可以追溯至原始成交腿。

**Architecture:** API 路由只负责 Pydantic 请求/响应和依赖注入；`TradeService` 与 `PerformanceAnalyticsService` 承担用例；纯 `TradeCalculator` 承担 FIFO 匹配与 `Decimal` 计算；SQLAlchemy 仓储保存交易和不可变审计事件。统计从原始已完成交易按需聚合，不保存可能失真的预计算统计结果。

**Tech Stack:** FastAPI、Pydantic v2、SQLAlchemy 2.x Async ORM、asyncpg、Alembic、PostgreSQL、pytest、pytest-asyncio、httpx TestClient；前端使用计划 01 已冻结的 `WorkbenchApi` 契约。

## Global Constraints

- 本计划仅支持人工录入；不得接入币安账户、订单、成交历史或任何私有 API。
- `Trade` 的所有货币、价格、数量、手续费、资金费和 PnL 使用 `Decimal`；数据库列使用 `NUMERIC(38,18)`；API/前端使用字符串。
- 每一笔交易和成交腿均不可硬删除。归档、作废和编辑均产生追加式审计事件。
- 默认统计仅纳入完整平仓且未归档的交易；首期不在缺少实时标记价格时计算未实现盈亏。
- 任何数据库写入必须在单一事务中完成交易更新、重算和审计写入。

---

## 数据语义与统计口径

### 交易和成交腿

- `Trade` 表示同一标的、同一方向、同一交易计划的一次持仓生命周期；方向固定为 `long` 或 `short`。
- `TradeLeg.kind` 为 `open`、`reduce` 或 `close`。`reduce` 与 `close` 都消费未匹配的开仓批次；`close` 只表示用户意图为完全平仓，服务仍以计算出的剩余数量为准判断状态。
- 所有成交腿按 `(executed_at, sequence, id)` 稳定排序；`sequence` 用于同一时间的人工录入顺序。每一笔减仓/平仓数量不得超过该时刻之前的未平仓数量。
- `funding_cashflow` 采用“收取为正、支付为负”的约定，避免将费用方向写反。手续费始终非负，存于成交腿。
- 完整平仓交易的 `net_pnl = gross_realized_pnl - total_fees + total_funding_cashflow`。多单已实现毛利为 `(exit_price - entry_price) × matched_quantity`，空单为 `(entry_price - exit_price) × matched_quantity`。
- 杠杆只用于保证金和 ROI 展示，不放大实际 PnL。

### 聚合

- `win_rate = profit_trade_count / (profit_trade_count + loss_trade_count)`；持平交易单列 `breakeven_trade_count`，不稀释胜率。
- `profit_factor = gross_profit / abs(gross_loss)`；没有亏损时返回 `null`，不能返回虚假的无穷大。
- `expectancy = total_net_pnl / closed_trade_count`。
- 最大回撤按 `(closed_at, trade_id)` 排序的已实现净 PnL 累积曲线计算，基线为 0，首期返回 USDT 金额而不伪造百分比回撤。
- 交易日历按 `closed_at` 投影到请求时区（默认 `Asia/Shanghai`）后归组；存储、过滤边界与数据库连接时区始终为 UTC。

## Target file layout

```text
backend/
├── alembic.ini
├── alembic/{env.py,versions/0001_create_journal_core.py,versions/0002_create_trade_attachments.py}
├── src/app/
│   ├── api/{dependencies.py,schemas/{trades.py,analytics.py},routes/{trades.py,analytics.py}}
│   ├── application/
│   │   ├── trades/{commands.py,service.py}
│   │   └── analytics/{models.py,service.py}
│   ├── domain/trades/{calculator.py,enums.py,exceptions.py,models.py}
│   ├── infrastructure/persistence/{base.py,session.py,models/{trades.py,audit.py},repositories/trades.py}
│   ├── repositories/trades.py
│   └── shared/{database.py,decimal.py,time.py,errors.py}
└── tests/
    ├── unit/domain/test_trade_calculator.py
    ├── unit/application/{test_trade_service.py,test_analytics_service.py}
    ├── integration/persistence/test_trade_repository.py
    └── integration/api/{test_trades_api.py,test_analytics_api.py}
```

## Task 1: Add PostgreSQL foundation and schema migration discipline

**Files:**
- Modify: `backend/pyproject.toml`, `backend/src/app/main.py`, `backend/src/app/shared/config.py`
- Create: `backend/src/app/shared/database.py`, `backend/src/app/infrastructure/persistence/{base.py,session.py}`
- Create: `backend/alembic.ini`, `backend/alembic/env.py`, `compose.yaml`
- Create: `backend/tests/integration/persistence/test_database_configuration.py`

- [ ] Before implementation, write an integration test that opens a test PostgreSQL connection, verifies `SHOW TIME ZONE` is `UTC`, rolls back a failed transaction and closes its async session.
- [ ] Add production dependencies `sqlalchemy`, `asyncpg`, and `alembic` to `backend/pyproject.toml`; run `uv lock` and commit the lockfile change. These are the approved persistence dependencies and do not grant exchange access.
- [ ] Implement `DatabaseSettings` with required `database_url` only outside `test` mode. Do not expose its value in health, logs, exception details or OpenAPI examples.
- [ ] Configure `create_async_engine`, `async_sessionmaker`, a FastAPI request-scoped session dependency and Alembic async migration support. Execute `SET TIME ZONE 'UTC'` for every PostgreSQL connection.
- [ ] Add the `postgres` service to root `compose.yaml`: PostgreSQL version is pinned by image tag, data uses named volume `postgres_data`, exposed port is only for local development, and credentials are supplied through non-committed environment variables.
- [ ] Add a documented `TEST_DATABASE_URL` fixture setup. Integration tests must use a separate database/schema from local user data and must never call a destructive command against the production/local volume.

**Verification:**

```powershell
docker compose up -d postgres
Set-Location backend
uv run pytest tests/integration/persistence/test_database_configuration.py
uv run alembic upgrade head
```

Expected result: the test database operates in UTC and migrations can run without accessing any exchange or account API.

## Task 2: Implement the pure FIFO trade calculator with tests first

**Files:**
- Create: `backend/src/app/domain/trades/{enums.py,models.py,exceptions.py,calculator.py}`
- Create: `backend/tests/unit/domain/test_trade_calculator.py`

- [ ] Write parametrized failing tests for long and short trades, one-to-many/many-to-one FIFO matches, partial closes, same-timestamp sequences, all fee allocations, positive/negative funding cashflows, zero remaining quantity, over-close rejection, invalid order and `Decimal` precision.
- [ ] Define immutable calculation inputs. Reject `float` values at Pydantic/domain boundaries rather than converting them silently.

```python
class PositionDirection(StrEnum):
    LONG = "long"
    SHORT = "short"

class TradeLegKind(StrEnum):
    OPEN = "open"
    REDUCE = "reduce"
    CLOSE = "close"

@dataclass(frozen=True)
class TradeLegForCalculation:
    leg_id: UUID
    kind: TradeLegKind
    executed_at: datetime
    sequence: int
    price: Decimal
    quantity: Decimal
    fee_amount: Decimal

@dataclass(frozen=True)
class TradePnl:
    gross_realized_pnl: Decimal
    total_fees: Decimal
    total_funding_cashflow: Decimal
    net_pnl: Decimal
    remaining_quantity: Decimal
    is_fully_closed: bool

class TradeCalculator:
    def calculate(
        self,
        *,
        direction: PositionDirection,
        legs: Sequence[TradeLegForCalculation],
        funding_cashflows: Sequence[Decimal],
    ) -> TradePnl: ...
```

- [ ] Implement FIFO matching without database or HTTP dependencies. Allocate opening-leg fees proportionally only when the associated quantity is matched; include all exit fees as they occur. For a fully closed trade the total equals all leg fees exactly.
- [ ] Validate all timestamps are timezone-aware UTC, `price > 0`, `quantity > 0`, `fee_amount >= 0`, and `sequence >= 0`. Normalize only to a documented decimal quantization at presentation boundaries; do not round intermediate PnL calculations.
- [ ] Keep matching details in a typed result so the application layer can explain PnL without re-implementing arithmetic.

**Verification:**

```powershell
Set-Location backend
uv run pytest tests/unit/domain/test_trade_calculator.py
uv run ruff check src/app/domain/trades tests/unit/domain
uv run pyright
```

Expected result: each calculation rule is independently proven using deterministic fixtures; no database process is needed for this task.

## Task 3: Persist trades, legs, tags, cashflows and immutable audit events

**Files:**
- Create: `backend/alembic/versions/0001_create_journal_core.py`
- Create: `backend/src/app/infrastructure/persistence/models/{trades.py,audit.py}`
- Create: `backend/src/app/repositories/trades.py`, `backend/src/app/infrastructure/persistence/repositories/trades.py`
- Create: `backend/tests/integration/persistence/test_trade_repository.py`

- [ ] Write migration/repository tests before the migration: positive constraints reject invalid numeric data, `(trade_id, executed_at, sequence)` is unique, archived trades are excluded by default, and an audit row remains unchanged after a later edit.
- [ ] Create `trades`, `trade_legs`, `trade_cashflows`, `tags`, `trade_tags`, and `trade_audit_logs` in migration `0001_create_journal_core.py`.
- [ ] `trades` contains UUID primary key, `symbol`, `direction`, `horizon`, `status`, plan/review fields, `opened_at`, `closed_at`, `archived_at`, computed PnL columns, `created_at` and `updated_at`. Constrain symbol to BTCUSDT/ETHUSDT and horizon to short/medium term.
- [ ] `trade_legs` contains UUID primary key, `trade_id`, kind, aware `executed_at`, sequence, price, quantity, fee, `voided_at`, source note, and timestamps. Add `CHECK` constraints for positive price/quantity, nonnegative fee and sequence.
- [ ] `trade_cashflows` contains only `funding` rows in this release, a signed `amount`, aware `occurred_at`, reason and audit timestamps. Do not use a one-way `funding_fee` field because it cannot represent funding income.
- [ ] `trade_audit_logs` is append-only at application level: `(trade_id, occurred_at)` index, action code, correlation ID, before/after JSON snapshots and metadata. Repository methods never update or delete audit rows.
- [ ] Implement repository interfaces that return domain DTOs rather than SQLAlchemy model instances to application services.
- [ ] Do not add `analysis_report_id` to this migration. Plan 04 adds it only after `analysis_reports` exists, preserving referential integrity.

**Verification:**

```powershell
Set-Location backend
uv run alembic upgrade head
uv run pytest tests/integration/persistence/test_trade_repository.py
```

Expected result: repeated migrations are safe, constraints reject invalid manual input, and no test reads/writes user data outside the configured test database.

## Task 4: Expose auditable trade journal use cases and API

**Files:**
- Create: `backend/src/app/application/trades/{commands.py,service.py}`
- Create: `backend/src/app/api/{dependencies.py,schemas/trades.py,routes/trades.py}`
- Modify: `backend/src/app/api/router.py`
- Create: `backend/tests/unit/application/test_trade_service.py`, `backend/tests/integration/api/test_trades_api.py`

- [ ] Write application and API tests first for creation, edit, add/update/void leg, funding cashflow, archive, invalid state transition, transaction rollback, pagination and all supported filters.
- [ ] Implement commands and a service with this stable surface:

```python
class TradeService:
    async def create_trade(self, command: CreateTradeCommand) -> TradeDetail: ...
    async def update_trade(self, trade_id: UUID, command: UpdateTradeCommand) -> TradeDetail: ...
    async def add_leg(self, trade_id: UUID, command: AddTradeLegCommand) -> TradeDetail: ...
    async def update_leg(self, trade_id: UUID, leg_id: UUID, command: UpdateTradeLegCommand) -> TradeDetail: ...
    async def void_leg(self, trade_id: UUID, leg_id: UUID) -> TradeDetail: ...
    async def add_funding_cashflow(self, trade_id: UUID, command: AddFundingCashflowCommand) -> TradeDetail: ...
    async def archive_trade(self, trade_id: UUID) -> None: ...
```

- [ ] On every command, lock the target trade, load non-voided legs/cashflows, run `TradeCalculator`, update computed fields/status and append one audit event in the same transaction. If any validation fails, commit none of those changes.
- [ ] Implement only these routes in this phase:

```text
POST   /api/v1/trades
GET    /api/v1/trades
GET    /api/v1/trades/{trade_id}
PATCH  /api/v1/trades/{trade_id}
POST   /api/v1/trades/{trade_id}/legs
PATCH  /api/v1/trades/{trade_id}/legs/{leg_id}
POST   /api/v1/trades/{trade_id}/legs/{leg_id}/void
POST   /api/v1/trades/{trade_id}/funding-cashflows
POST   /api/v1/trades/{trade_id}/archive
```

- [ ] Return decimal values as canonical strings and UTC datetimes as ISO 8601 strings. Reuse the frozen list/error envelope from the execution index. `POST` creates return 201; archive returns 204; malformed manual input returns 422; missing/archived target returns 404.
- [ ] Accept filtering by symbol, direction, horizon, tag, status, opened/closed UTC ranges and pagination. Reject unsupported symbols/timeframes rather than passing user strings into a query.
- [ ] Do not expose `DELETE` endpoints. Do not accept an analysis report ID until plan 04 provides a real FK and validation path.

**Verification:**

```powershell
Set-Location backend
uv run pytest tests/unit/application/test_trade_service.py tests/integration/api/test_trades_api.py
uv run ruff check .
uv run pyright
```

Expected result: a manual multi-leg trade can be created and amended safely; every mutation has a linked audit event; impossible PnL states are rejected server-side.

## Task 5: Compute and expose review analytics

**Files:**
- Create: `backend/src/app/application/analytics/{models.py,service.py}`
- Create: `backend/src/app/api/{schemas/analytics.py,routes/analytics.py}`
- Create: `backend/tests/unit/application/test_analytics_service.py`, `backend/tests/integration/api/test_analytics_api.py`
- Modify: `backend/src/app/api/router.py`

- [ ] Write fixed-fixture tests for empty data, a win/loss/breakeven mix, only winning trades, partially closed trades, different time zone calendar dates, filtering and maximum drawdown order.
- [ ] Define the service boundary:

```python
class PerformanceAnalyticsService:
    async def get_summary(self, filters: AnalyticsFilter) -> PerformanceSummary: ...
    async def get_equity_curve(self, filters: AnalyticsFilter) -> list[EquityPoint]: ...
    async def get_calendar(
        self,
        filters: AnalyticsFilter,
        timezone: ZoneInfo,
    ) -> list[CalendarDay]: ...
```

- [ ] Query only complete, non-archived trades for result metrics. Return explicit counts and nullable `profit_factor`; do not hide empty datasets behind zero values that imply completed trading.
- [ ] Implement:

```text
GET /api/v1/analytics/summary
GET /api/v1/analytics/equity-curve
GET /api/v1/analytics/calendar
```

- [ ] Require filters to use UTC ISO boundaries. Allow only an IANA display timezone parameter for calendar grouping, defaulting to `Asia/Shanghai`; reject invalid zone names with 422.
- [ ] Connect `HttpWorkbenchApi` to these endpoints and replace only the analytics mock adapter in a focused frontend integration test. Rendering code and decimal formatting must not change.

**Verification:**

```powershell
Set-Location backend
uv run pytest tests/unit/application/test_analytics_service.py tests/integration/api/test_analytics_api.py
Set-Location ../frontend
npm run test -- --run src/features/analytics
```

Expected result: API values match calculator fixtures exactly, and the browser displays clear empty and no-loss states.

## Task 6: Add safe attachment metadata and journal UI integration

**Files:**
- Create: `backend/alembic/versions/0002_create_trade_attachments.py`
- Create: `backend/src/app/application/trades/attachments.py`, `backend/src/app/api/routes/attachments.py`
- Create: `backend/tests/integration/api/test_trade_attachments_api.py`
- Modify: `frontend/src/shared/api/http-workbench-api.ts`, `frontend/src/features/trades/*`

- [ ] Write tests first for MIME/type allowlist, size limit, generated storage key, checksum, filename sanitization, metadata retrieval and rejection of path traversal.
- [ ] Create `trade_attachments` with UUID metadata ID, `trade_id`, generated `storage_key`, user-display filename, MIME type, byte size, SHA-256 checksum, timestamps and soft-removal audit metadata. The table must never contain an absolute filesystem path.
- [ ] Store file bytes only below a configured local mounted directory. Accept PNG, JPEG and WebP in this phase; enforce a documented per-file size limit; reject executable, archive and SVG uploads.
- [ ] Add attachment creation/listing routes beneath `/api/v1/trades/{trade_id}/attachments`; route implementation obtains paths only from a storage service, never from request input.
- [ ] Integrate the real journal endpoints into `HttpWorkbenchApi`, retaining the Mock implementation for isolated UI tests. The UI clearly labels an attachment as a local review artifact, not exchange evidence.

**Verification:**

```powershell
Set-Location backend
uv run pytest tests/integration/api/test_trade_attachments_api.py
uv run ruff check .
uv run pyright
```

Expected result: attachments cannot escape the configured directory; a journal remains functional with no attachment at all; no hard-delete endpoint exists.
