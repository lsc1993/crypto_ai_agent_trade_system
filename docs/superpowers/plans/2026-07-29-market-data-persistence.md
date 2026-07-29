# Market Data Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist bounded public BTCUSDT and ETHUSDT market research data in PostgreSQL without changing the existing live market API or adding any account or order capability.

**Architecture:** A `MarketCaptureService` consumes the existing allowlisted `PublicMarketGateway`, filters and validates the typed response, then passes batches to a narrow repository port. The PostgreSQL repository owns a single transaction that upserts candles, deduplicates observations, and inserts immutable snapshots. A standalone command composes the existing public gateway, service, and database repository only when explicitly invoked.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x async ORM, asyncpg, Alembic, PostgreSQL 17, httpx, pytest, pytest-asyncio, Ruff, Pyright.

## Global Constraints

- Only `BTCUSDT`, `ETHUSDT`, `15m`, `1h`, `4h`, and `1d` are accepted at every boundary.
- All monetary, price, quantity, fee, rate and metric values remain `Decimal` in Python and `NUMERIC(38,18)` in PostgreSQL. Floats are rejected.
- All timestamps are timezone-aware UTC datetimes in Python and `TIMESTAMPTZ` in PostgreSQL.
- `DATABASE_URL` and `TEST_DATABASE_URL` are local secrets. They must never appear in source, fixtures, logs, API responses, plan commands, or commits.
- `TEST_DATABASE_URL` targets a database distinct from `DATABASE_URL`; integration tests use a generated temporary schema and remove only that schema after each test session.
- The public gateway remains restricted to existing Binance USDⓈ-M allowlisted `GET` endpoints. No adapter, service, repository, command or test may expose account, balance, position, leverage, order, cancellation, transfer, withdrawal, API-key, secret, or passphrase capability.
- The existing market HTTP routes continue to use the live public gateway during this delivery. No browser behavior changes.
- Market snapshots are append-only at the repository API; no application method updates or deletes a snapshot.

---

## Target File Layout

```text
backend/
├── .env.example
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/0001_create_market_persistence.py
├── pyproject.toml
├── uv.lock
├── scripts/capture_market_snapshot.py
├── src/app/
│   ├── infrastructure/persistence/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── repository.py
│   │   └── models/{__init__.py,market.py}
│   ├── market/{capture.py,repository.py}
│   └── shared/{config.py,database.py}
└── tests/
    ├── conftest.py
    ├── persistence/{test_migrations.py,test_market_repository.py}
    └── market/{test_capture.py,test_persistence_contracts.py,test_public_boundary.py}
```

`app.infrastructure.persistence` is the only layer that imports SQLAlchemy table models. `app.market.repository` defines immutable DTOs and the repository protocol; `app.market.capture` coordinates existing public data without SQL or HTTP implementation details. `scripts/capture_market_snapshot.py` is intentionally a thin executable boundary.

### Task 1: Add database toolchain, secret-safe configuration, and Alembic bootstrap

**Files:**
- Create: `backend/.env.example`, `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`, `backend/src/app/shared/database.py`, `backend/tests/persistence/test_migrations.py`
- Create: `backend/tests/conftest.py`
- Modify: `backend/pyproject.toml`, `backend/uv.lock`, `backend/src/app/shared/config.py`, `backend/tests/api/test_health.py`

**Interfaces:**
- Produces `create_async_engine_from_secret(database_url: SecretStr) -> AsyncEngine` and `create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]` for Tasks 3 and 4.
- Produces `upgrade_database(database_url: SecretStr, schema: str | None = None) -> None` in Alembic integration helpers for Task 3 tests.
- Extends `AppSettings` with `test_database_url: SecretStr | None = None`; runtime API code continues to require neither database setting.

- [ ] **Step 1: Write configuration and migration bootstrap failure tests**

```python
def test_settings_redact_both_database_urls() -> None:
    production_url = "postgresql+asyncpg://app:password@localhost/research"
    test_url = "postgresql+asyncpg://test:password@localhost/research_test"
    settings = AppSettings(
        database_url=SecretStr(production_url),
        test_database_url=SecretStr(test_url),
    )

    assert production_url not in repr(settings)
    assert test_url not in repr(settings)


def test_alembic_upgrade_creates_version_table_in_requested_schema(
    test_database_url: SecretStr,
) -> None:
    schema = "test_market_schema"
    upgrade_database(test_database_url, schema=schema)
    assert version_table_exists(test_database_url, schema) is True
```

- [ ] **Step 2: Run the focused tests and confirm the expected initial failure**

Run from `backend`:

```powershell
uv run pytest tests/api/test_health.py::test_settings_redact_both_database_urls tests/persistence/test_migrations.py::test_alembic_upgrade_creates_version_table_in_requested_schema -v
```

Expected: collection or assertion failure because `test_database_url`, `upgrade_database`, and Alembic configuration do not exist.

- [ ] **Step 3: Add the approved dependencies and secret-safe database factory**

Add `sqlalchemy`, `asyncpg`, and `alembic` to production dependencies, regenerate `uv.lock`, and add the optional `test_database_url` field without a default secret value. Implement the factory without logging or serializing its input:

```python
def create_async_engine_from_secret(database_url: SecretStr) -> AsyncEngine:
    return create_async_engine(
        database_url.get_secret_value(),
        pool_pre_ping=True,
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
```

Configure Alembic’s async environment to read `AppSettings().database_url` only at migration execution time. When a validated `schema` argument is provided, execute `SET search_path` for that generated schema and set `version_table_schema` to the same schema. Reject every schema name that does not match `^[a-z][a-z0-9_]{0,47}$`.

`backend/.env.example` contains key names and redacted placeholders only:

```dotenv
DATABASE_URL=postgresql+asyncpg://<user>:<password>@localhost:5432/crypto_research
TEST_DATABASE_URL=postgresql+asyncpg://<user>:<password>@localhost:5432/crypto_research_test
```

- [ ] **Step 4: Re-run focused tests and static checks**

Run from `backend`:

```powershell
uv run pytest tests/api/test_health.py::test_settings_redact_both_database_urls tests/persistence/test_migrations.py::test_alembic_upgrade_creates_version_table_in_requested_schema -v
uv run ruff check src/app/shared tests/api tests/persistence
uv run pyright
```

Expected: both URLs remain redacted, Alembic creates its version table only in the requested test schema, and static checks pass.

- [ ] **Step 5: Commit the toolchain bootstrap**

```powershell
git add -- backend/.env.example backend/alembic.ini backend/alembic backend/pyproject.toml backend/uv.lock backend/src/app/shared/config.py backend/src/app/shared/database.py backend/tests/api/test_health.py backend/tests/persistence/test_migrations.py
git commit -m "feat: add async database bootstrap"
```

### Task 2: Define bounded persistence contracts and create the market schema migration

**Files:**
- Create: `backend/src/app/market/repository.py`, `backend/src/app/infrastructure/persistence/base.py`, `backend/src/app/infrastructure/persistence/models/__init__.py`, `backend/src/app/infrastructure/persistence/models/market.py`, `backend/alembic/versions/0001_create_market_persistence.py`, `backend/tests/market/test_persistence_contracts.py`
- Create: `backend/src/app/infrastructure/__init__.py`
- Modify: `backend/tests/persistence/test_migrations.py`

**Interfaces:**
- Consumes `Candle`, `ContractSymbol`, and `MarketTimeframe` from `app.market.contracts`.
- Produces `MetricType`, `DerivativeObservation`, `MarketSnapshotDraft`, `MarketCaptureBatch`, and `MarketRepository`.
- Produces SQLAlchemy models `MarketCandleRecord`, `DerivativeObservationRecord`, and `MarketSnapshotRecord` for Task 3 only.

- [ ] **Step 1: Write contract and schema failure tests**

```python
def test_snapshot_rejects_a_payload_over_64_kib() -> None:
    with pytest.raises(ValidationError):
        MarketSnapshotDraft(
            id=uuid4(),
            symbol=ContractSymbol.BTCUSDT,
            source="binance_usdm_public_rest",
            captured_at=utc_now(),
            data_as_of=utc_now(),
            data_version="market-v1",
            payload={"value": "x" * 65_537},
            payload_sha256="0" * 64,
        )


def test_migration_creates_unique_candle_key_and_numeric_columns(
    migrated_schema: str,
) -> None:
    assert unique_constraint_exists(
        migrated_schema,
        "market_candles",
        ("symbol", "timeframe", "open_at"),
    )
    assert column_type(migrated_schema, "market_candles", "close_price") == "numeric"
```

- [ ] **Step 2: Run the focused tests and confirm the expected initial failure**

Run from `backend`:

```powershell
uv run pytest tests/market/test_persistence_contracts.py tests/persistence/test_migrations.py::test_migration_creates_unique_candle_key_and_numeric_columns -v
```

Expected: imports or migration assertions fail because the persistence contracts and schema tables do not exist.

- [ ] **Step 3: Implement contracts, ORM metadata, and revision `0001_create_market_persistence`**

Define the exact repository boundary:

```python
class MetricType(StrEnum):
    PRICE = "price"
    FUNDING_RATE = "funding_rate"
    OPEN_INTEREST = "open_interest"
    CHANGE_24H = "change_24h"
    VOLUME_24H = "volume_24h"


class MarketRepository(Protocol):
    async def persist_batches(
        self,
        batches: tuple[MarketCaptureBatch, ...],
    ) -> tuple[UUID, ...]: ...
```

`MarketCaptureBatch` contains one symbol, a non-empty tuple of already-closed `Candle` values, five `DerivativeObservation` values, and one `MarketSnapshotDraft`. It rejects mismatched symbols, naive/non-UTC times, float metrics, unsupported metric types, inconsistent snapshot hash, or a `data_as_of` later than `captured_at`.

The revision creates the following PostgreSQL tables and constraints:

| Table | Columns and constraints |
|---|---|
| `market_candles` | Typed OHLCV, source and timestamps; `NUMERIC(38,18)` numeric columns; unique `(symbol, timeframe, open_at)`; supported-scope checks; `(symbol, timeframe, open_at DESC)` index. |
| `derivative_observations` | Symbol, checked metric type, value, source and timestamps; `NUMERIC(38,18)` value; unique `(symbol, metric_type, observed_at, source)`; `(symbol, observed_at DESC)` index. |
| `market_snapshots` | Python-provided UUID key, symbol, source, captured/data-as-of times, `market-v1` version, JSONB payload, 64-character SHA-256, timestamps; `octet_length(payload::text) <= 65536` check; `(symbol, captured_at DESC)` index. |

Use check constraints for the two symbols, four timeframes, five metric types, UTC-capable timestamps, non-negative OHLCV/volume/open-interest, and valid OHLC price range. `market_snapshots` has no application update/delete operation and the migration grants no broad privileges.

- [ ] **Step 4: Re-run focused tests and type checks**

Run from `backend`:

```powershell
uv run pytest tests/market/test_persistence_contracts.py tests/persistence/test_migrations.py -v
uv run ruff check src/app/market src/app/infrastructure tests/market tests/persistence
uv run pyright
```

Expected: invalid DTOs fail locally and the isolated migrated schema exactly exposes the declared types, checks, indexes, and uniqueness rules.

- [ ] **Step 5: Commit contracts and schema**

```powershell
git add -- backend/alembic/versions/0001_create_market_persistence.py backend/src/app/market/repository.py backend/src/app/infrastructure/__init__.py backend/src/app/infrastructure/persistence/base.py backend/src/app/infrastructure/persistence/models backend/tests/market/test_persistence_contracts.py backend/tests/persistence/test_migrations.py
git commit -m "feat: add market persistence schema"
```

### Task 3: Implement atomic PostgreSQL repository semantics

**Files:**
- Create: `backend/src/app/infrastructure/persistence/__init__.py`, `backend/src/app/infrastructure/persistence/repository.py`, `backend/tests/persistence/test_market_repository.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Consumes `MarketRepository.persist_batches(batches: tuple[MarketCaptureBatch, ...]) -> tuple[UUID, ...]` from Task 2 and the Task 1 session factory.
- Produces `SqlAlchemyMarketRepository`, the sole concrete writer used by Task 4.

- [ ] **Step 1: Write repository integration failure tests against the temporary schema**

```python
@pytest.mark.asyncio
async def test_repository_upserts_candles_deduplicates_metrics_and_inserts_snapshots(
    repository: MarketRepository,
    batch: MarketCaptureBatch,
) -> None:
    first_ids = await repository.persist_batches((batch,))
    second_ids = await repository.persist_batches((batch,))

    assert await count_rows("market_candles") == len(batch.candles)
    assert await count_rows("derivative_observations") == 5
    assert await count_rows("market_snapshots") == 2
    assert first_ids != second_ids


@pytest.mark.asyncio
async def test_repository_rolls_back_all_symbols_when_one_batch_is_invalid(
    repository: MarketRepository,
    valid_batch: MarketCaptureBatch,
    invalid_batch: MarketCaptureBatch,
) -> None:
    with pytest.raises(IntegrityError):
        await repository.persist_batches((valid_batch, invalid_batch))

    assert await count_rows("market_candles") == 0
    assert await count_rows("market_snapshots") == 0
```

- [ ] **Step 2: Run the integration tests and confirm the expected initial failure**

Run from `backend`:

```powershell
uv run pytest tests/persistence/test_market_repository.py -v
```

Expected: failure because `SqlAlchemyMarketRepository` is not implemented.

- [ ] **Step 3: Implement one-transaction persistence**

Within `async with session.begin():`, execute these operations for every batch in order:

```python
await session.execute(
    insert(MarketCandleRecord)
    .values(candle_rows)
    .on_conflict_do_update(
        index_elements=("symbol", "timeframe", "open_at"),
        set_={
            "close_at": excluded.close_at,
            "open_price": excluded.open_price,
            "high_price": excluded.high_price,
            "low_price": excluded.low_price,
            "close_price": excluded.close_price,
            "volume": excluded.volume,
            "source": excluded.source,
            "observed_at": excluded.observed_at,
            "fetched_at": excluded.fetched_at,
            "updated_at": utc_now(),
        },
    )
)
```

Insert observations with `ON CONFLICT DO NOTHING` on `(symbol, metric_type, observed_at, source)`. Insert each snapshot without an update/delete path and return its generated Python UUID. Do not catch `IntegrityError` inside the repository; let the transaction roll back and let the command classify the failure without including exception text that might contain a connection string.

- [ ] **Step 4: Re-run integration tests and relevant quality checks**

Run from `backend`:

```powershell
uv run pytest tests/persistence/test_market_repository.py -v
uv run ruff check src/app/infrastructure tests/persistence
uv run pyright
```

Expected: repeated capture leaves one candle and observation fact per unique key, each capture has a new immutable snapshot, and a failed batch commits nothing.

- [ ] **Step 5: Commit repository behavior**

```powershell
git add -- backend/src/app/infrastructure/persistence/__init__.py backend/src/app/infrastructure/persistence/repository.py backend/tests/conftest.py backend/tests/persistence/test_market_repository.py
git commit -m "feat: persist market capture batches atomically"
```

### Task 4: Add typed capture orchestration and an explicit public-only command

**Files:**
- Create: `backend/src/app/market/capture.py`, `backend/scripts/capture_market_snapshot.py`, `backend/tests/market/test_capture.py`
- Create: `backend/scripts/__init__.py`, `backend/tests/market/test_public_boundary.py`

**Interfaces:**
- Consumes `PublicMarketGateway`, the Task 2 `MarketRepository` protocol, and `SqlAlchemyMarketRepository` from Task 3.
- Produces `MarketCaptureService.capture(captured_at: datetime) -> tuple[UUID, ...]` and `run_capture() -> int`.

- [ ] **Step 1: Write service and command failure tests using a fake gateway**

```python
@pytest.mark.asyncio
async def test_capture_persists_two_symbol_batches_only_after_all_reads_succeed(
    fake_gateway: PublicMarketGateway,
    spy_repository: MarketRepository,
) -> None:
    service = MarketCaptureService(fake_gateway, spy_repository)

    snapshot_ids = await service.capture(captured_at=utc_now())

    assert len(snapshot_ids) == 2
    assert spy_repository.persisted_symbols == (
        ContractSymbol.BTCUSDT,
        ContractSymbol.ETHUSDT,
    )


@pytest.mark.asyncio
async def test_capture_does_not_write_when_one_gateway_read_fails(
    failing_gateway: PublicMarketGateway,
    spy_repository: MarketRepository,
) -> None:
    service = MarketCaptureService(failing_gateway, spy_repository)

    with pytest.raises(MarketDataUnavailableError):
        await service.capture(captured_at=utc_now())

    assert spy_repository.persisted_symbols == ()
```

The command test sets no `DATABASE_URL`, asserts `run_capture()` returns `2`, and asserts captured stdout/stderr does not include `DATABASE_URL`, `TEST_DATABASE_URL`, or either URL value.

- [ ] **Step 2: Run the focused tests and confirm the expected initial failure**

Run from `backend`:

```powershell
uv run pytest tests/market/test_capture.py tests/market/test_public_boundary.py -v
```

Expected: imports fail because capture service and command composition do not exist.

- [ ] **Step 3: Implement capture batching and command composition**

Use these fixed tuples, never command-line input, for every capture:

```python
CAPTURE_SYMBOLS = (ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT)
CAPTURE_TIMEFRAMES = (
    MarketTimeframe.M15,
    MarketTimeframe.H1,
    MarketTimeframe.H4,
    MarketTimeframe.D1,
)
```

`MarketCaptureService.capture()` first awaits all `get_market(symbol, CAPTURE_TIMEFRAMES)` calls. Only after every result has passed existing Pydantic validation does it construct batches, derive exactly five observations from each `MarketSummary`, canonicalize a JSON-safe payload, calculate a SHA-256 hash, and call `persist_batches()` once. A current candle cannot pass because the existing public gateway has already filtered it and the service repeats `candle.close_at <= captured_at` as a defense-in-depth condition.

The command uses `AppSettings().database_url`; absent configuration produces the stable message `数据库未配置，无法执行市场快照采集` and exit code `2`. With configuration it builds the fixed HTTPS `httpx.AsyncClient`, `BinanceUsdmPublicMarketGateway`, async engine, repository, and service; it closes the HTTP client and database engine in `finally`. Successful execution logs only capture status and snapshot count, returns `0`, and never prints the database URL or upstream payload.

Extend the public-boundary source scan to fail if any market persistence or command module contains `create_order`, `cancel_order`, `fetch_balance`, `fetch_positions`, `set_leverage`, `api_key`, `secret`, or `passphrase`.

- [ ] **Step 4: Re-run service, boundary, and command tests**

Run from `backend`:

```powershell
uv run pytest tests/market/test_capture.py tests/market/test_public_boundary.py -v
uv run ruff check src/app/market scripts tests/market
uv run pyright
```

Expected: a complete two-symbol fake capture produces two snapshots, one failure produces zero writes, missing configuration is redacted, and prohibited private exchange capability is absent.

- [ ] **Step 5: Commit capture orchestration**

```powershell
git add -- backend/src/app/market/capture.py backend/scripts/__init__.py backend/scripts/capture_market_snapshot.py backend/tests/market/test_capture.py backend/tests/market/test_public_boundary.py
git commit -m "feat: add public market capture command"
```

### Task 5: Verify the development migration and end-to-end public capture safely

**Files:**
- Modify: `backend/tests/persistence/test_market_repository.py`, `backend/tests/market/test_capture.py`

**Interfaces:**
- Consumes all previous tasks; no new production interface is introduced.
- Produces verification evidence that the developer database migrates and a public read-only capture can persist bounded research data.

- [ ] **Step 1: Write final regression cases before operational verification**

```python
@pytest.mark.asyncio
async def test_snapshot_payload_contains_only_normalized_strings_and_utc_times(
    repository: MarketRepository,
    batch: MarketCaptureBatch,
) -> None:
    snapshot_id = (await repository.persist_batches((batch,)))[0]
    payload = await load_snapshot_payload(snapshot_id)

    assert "apiKey" not in payload
    assert "secret" not in payload
    assert all_decimal_values_are_strings(payload)
    assert all_times_are_utc_rfc3339(payload)
```

- [ ] **Step 2: Run the regression test and confirm its expected initial failure**

Run from `backend`:

```powershell
uv run pytest tests/persistence/test_market_repository.py::test_snapshot_payload_contains_only_normalized_strings_and_utc_times -v
```

Expected: failure until the final payload normalizer and repository retrieval helper are complete.

- [ ] **Step 3: Implement the smallest normalizer/retrieval helper needed by the test**

Serialize `Decimal` with `format(value, "f")` and UTC datetimes using `isoformat().replace("+00:00", "Z")`. The helper may retrieve a snapshot payload by UUID for integration tests only; production repository API remains write-only in this delivery. Do not add a market HTTP read route or expose stored payloads to browsers.

- [ ] **Step 4: Run complete automated verification and apply the development migration**

Run from `backend`:

```powershell
uv run ruff check .
uv run pyright
uv run pytest
uv run alembic upgrade head
uv run python scripts/capture_market_snapshot.py
```

Expected: quality checks pass; tests use only `TEST_DATABASE_URL`; Alembic changes only the developer database selected by `DATABASE_URL`; the command performs only allowed public `GET` requests and writes two immutable snapshots. If the live command fails because Binance is unreachable or rate-limits the request, retain the successful automated results, report the typed failure, and do not substitute Mock data.

- [ ] **Step 5: Commit final verification adjustments**

```powershell
git add -- backend/tests/persistence/test_market_repository.py backend/tests/market/test_capture.py
git commit -m "test: verify market persistence capture"
```

## Plan Self-Review

- Spec coverage: Task 1 implements dependency/configuration/temporary-schema safety; Task 2 implements all three constrained tables and DTO validation; Task 3 implements idempotency, snapshot insertion, and atomic rollback; Task 4 implements fixed-scope public capture and private-capability prevention; Task 5 proves serialization, migration, and manual public capture. The current live API intentionally remains unchanged as required by the specification.
- Placeholder scan: this plan contains concrete paths, symbols, test names, signatures, database constraints, commands, exit codes, and commit commands; no unresolved implementation marker remains.
- Type consistency: Tasks 3 and 4 use the Task 2 `MarketRepository.persist_batches()` and `MarketCaptureBatch` names unchanged. Tasks 1 and 3 use the same `SecretStr`, `AsyncEngine`, and `async_sessionmaker[AsyncSession]` factory contracts.
