# 确定性市场研究报告 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为已持久化的 BTCUSDT、ETHUSDT 公开市场数据生成可审计、无模型依赖、只读且不可修改的研究报告，并接入已有报告页面。

**Architecture:** 后端 `reports` 包定义不可变报告与证据模型；`DeterministicResearchReportService` 只通过 `PersistedMarketReader` 读取数据库中的快照和 K 线，随后在一个事务中写入报告与冻结证据。FastAPI 提供同步触发、分页、详情、重试和单事件 SSE；前端 HTTP 实现复用既有 `WorkbenchApi` 与报告页面，不改变 Mock/Hybrid 的行为。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2 异步、PostgreSQL JSONB/Alembic、pytest、React、TypeScript、Zod、Vitest。

## Global Constraints

- 不新增生产依赖，不读取、修改或输出 `.env`、密钥、账户或数据库连接串。
- 仅支持 `BTCUSDT`、`ETHUSDT` 和 `15m`、`1h`、`4h`、`1d`；金额、价格与数量继续为 `Decimal`，时间必须为带 UTC 时区对象。
- 服务只能使用 `PersistedMarketReader`；不得导入、调用或回退到 `PublicMarketGateway`、Binance HTTP 客户端、账户接口或交易接口。
- 不实现 LLM、LangGraph、后台 Worker、新闻/交易统计读取、价格预测、买卖建议、仓位、杠杆、止损、收益承诺或自动交易。
- 所有新行为先写 pytest/Vitest 失败测试；数据库测试仅使用 `TEST_DATABASE_URL` 生成的临时 schema；测试不发起网络请求。
- 新迁移为 `0003_create_analysis_reports.py`，只在验证的临时 schema 中由测试运行；不得自动迁移用户开发数据库。

---

## Target File Layout

~~~text
backend/
├── alembic/versions/0003_create_analysis_reports.py
├── src/app/
│   ├── reports/{__init__.py,contracts.py,repository.py,service.py}
│   ├── infrastructure/persistence/
│   │   ├── models/reports.py
│   │   └── report_repository.py
│   ├── api/routes/analysis_reports.py
│   ├── api/router.py
│   ├── main.py
│   └── alembic/env.py
└── tests/
    ├── reports/{test_contracts.py,test_service.py}
    ├── persistence/test_report_repository.py
    └── api/test_analysis_reports.py
frontend/src/
├── domain/report.ts
├── features/reports/{ReportDetailPage.tsx,ReportPages.test.tsx}
└── shared/api/{http-transport.ts,http-workbench-api.ts,http-workbench-api.test.ts}
~~~

`reports/contracts.py` 不导入 SQLAlchemy、FastAPI、HTTP 客户端或前端代码；`report_repository.py` 是唯一写入报告表的基础设施模块；`analysis_reports.py` 只依赖应用服务；`main.py` 只进行依赖组合。

### Task 1: 定义不可变报告与证据领域契约

**Files:**
- Create: `backend/src/app/reports/__init__.py`
- Create: `backend/src/app/reports/contracts.py`
- Create: `backend/src/app/reports/repository.py`
- Create: `backend/tests/reports/test_contracts.py`

**Interfaces:**
- Consumes: `ContractSymbol`、`MarketTimeframe`、`UtcDateTime`、`JsonValue`。
- Produces: `AnalysisReportStatus`、`AnalysisEvidenceDraft`、`AnalysisReportDraft`、`PersistedAnalysisEvidence`、`PersistedAnalysisReport`、`ReportPage`；`repository.py` 产生 `AnalysisReportRepository`。
- `AnalysisReportRepository.persist(report: AnalysisReportDraft, evidences: tuple[AnalysisEvidenceDraft, ...]) -> PersistedAnalysisReport` is asynchronous; it has no update/delete method.

- [ ] **Step 1: 写入领域失败测试**

```python
def test_report_draft_rejects_trading_instruction_language() -> None:
    with pytest.raises(ValidationError, match="交易指令"):
        AnalysisReportDraft(
            analysis_id=uuid4(),
            symbol=ContractSymbol.BTCUSDT,
            status=AnalysisReportStatus.COMPLETED,
            title="BTCUSDT 持久化研究",
            summary="建议立即买入 BTCUSDT",
            facts=("价格来自持久化快照。",),
            inferences=(),
            risks=(),
            limitations=(),
            generated_at=NOW,
            data_cutoff_at=NOW,
        )


def test_evidence_draft_requires_a_matching_normalized_payload_hash() -> None:
    with pytest.raises(ValidationError, match="哈希"):
        AnalysisEvidenceDraft(
            report_id=uuid4(),
            symbol=ContractSymbol.BTCUSDT,
            source="binance_usdm_public_rest",
            source_url="https://www.binance.com/en/futures/BTCUSDT",
            observed_at=NOW,
            fetched_at=NOW,
            summary="BTCUSDT 持久化市场快照",
            payload={"summary": {"symbol": "BTCUSDT"}},
            payload_sha256="0" * 64,
        )
```

Add focused cases for non-UTC timestamps, an empty evidence tuple on a `completed` draft, non-empty facts/inferences on a `degraded` draft, invalid symbol, arrays longer than 12 entries, and a valid immutable draft with canonical SHA-256.

- [ ] **Step 2: 验证测试按预期失败**

Run: `uv run pytest tests/reports/test_contracts.py -v`

Expected: collection fails because `app.reports.contracts` does not exist.

- [ ] **Step 3: 实现最小不可变 Pydantic 模型与仓储协议**

```python
class AnalysisReportStatus(StrEnum):
    COMPLETED = "completed"
    DEGRADED = "degraded"


class AnalysisEvidenceDraft(_ReportModel):
    report_id: UUID
    symbol: ContractSymbol
    source: str
    source_url: str
    observed_at: UtcDateTime
    fetched_at: UtcDateTime
    summary: str
    payload: dict[str, JsonValue]
    payload_sha256: str


class AnalysisReportDraft(_ReportModel):
    id: UUID = Field(default_factory=uuid4)
    analysis_id: UUID = Field(default_factory=uuid4)
    symbol: ContractSymbol
    status: AnalysisReportStatus
    title: str
    summary: str
    facts: tuple[str, ...]
    inferences: tuple[str, ...]
    risks: tuple[str, ...]
    limitations: tuple[str, ...]
    generated_at: UtcDateTime
    data_cutoff_at: UtcDateTime | None
```

Use `ConfigDict(frozen=True, extra="forbid")`, the existing canonical JSON/SHA-256 rule pattern from `market.repository`, size-bound JSON to 64 KiB, and one normalized phrase guard shared by title, summary, facts, inferences, risks and limitations. The prohibited normalized phrases are `买入`、`卖出`、`开仓`、`平仓`、`仓位`、`杠杆`、`止损`、`保证收益`、`自动交易`. Completed reports require at least one evidence and may contain bounded facts/inferences; degraded reports require no facts/inferences and at least one risk plus one limitation.

- [ ] **Step 4: 验证领域契约**

Run: `uv run pytest tests/reports/test_contracts.py -v`

Expected: all contract validation cases pass with no database or network access.

- [ ] **Step 5: 提交 Task 1**

```powershell
git add -- backend/src/app/reports/__init__.py backend/src/app/reports/contracts.py backend/src/app/reports/repository.py backend/tests/reports/test_contracts.py
git commit -m "feat: define immutable research report contracts"
```

### Task 2: 添加不可变报告/证据持久化迁移与仓储

**Files:**
- Create: `backend/alembic/versions/0003_create_analysis_reports.py`
- Create: `backend/src/app/infrastructure/persistence/models/reports.py`
- Create: `backend/src/app/infrastructure/persistence/report_repository.py`
- Modify: `backend/alembic/env.py`
- Create: `backend/tests/persistence/test_report_repository.py`

**Interfaces:**
- Consumes: Task 1 的 `AnalysisReportDraft`、`AnalysisEvidenceDraft`、`PersistedAnalysisReport`、`ReportPage`、`AnalysisReportRepository`。
- Produces: `SqlAlchemyAnalysisReportRepository(session_factory)` with `persist`、`get_by_id`、`get_by_analysis_id`、`list` methods.
- `list(page: int, page_size: int, symbol: ContractSymbol | None, status: AnalysisReportStatus | None) -> ReportPage` orders by `created_at DESC, id DESC`.

- [ ] **Step 1: 写入迁移与仓储失败测试**

```python
@pytest.mark.asyncio
async def test_repository_persists_a_report_and_frozen_evidence(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyAnalysisReportRepository(migrated_database.session_factory)
    report = await repository.persist(valid_completed_draft(), valid_evidence_drafts())

    loaded = await repository.get_by_id(report.id)

    assert loaded == report
    assert loaded.evidence[0].payload["summary"]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_database_rejects_report_or_evidence_mutation(
    migrated_database: MigratedDatabase,
) -> None:
    report = await persist_completed_report(migrated_database)

    async with migrated_database.session_factory() as session, pytest.raises(DBAPIError):
        await session.execute(text("UPDATE analysis_reports SET title = 'changed'"))
        await session.commit()
```

Add cases for `get_by_analysis_id`, paginated symbol/status filtering, rejected `DELETE FROM analysis_evidences`, and evidence records linked only to their created report. Construct test data through Task 1 models and repository methods, never direct inserts.

- [ ] **Step 2: 验证失败来自缺失迁移/仓储**

Run: `uv run pytest tests/persistence/test_report_repository.py -v`

Expected: collection fails because the report repository module is absent.

- [ ] **Step 3: 实现表、触发器与 SELECT/INSERT 仓储**

Migration creates `analysis_reports` and `analysis_evidences` using UUID, TIMESTAMPTZ, JSONB, bounded varchar fields, checks for the two symbols/statuses, `analysis_id` unique, report/evidence indexes and foreign key. Add one trigger function and one trigger per table:

```sql
CREATE FUNCTION prevent_analysis_record_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'analysis records are immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_analysis_reports_immutable
BEFORE UPDATE OR DELETE ON analysis_reports
FOR EACH ROW EXECUTE FUNCTION prevent_analysis_record_mutation();
```

Use equivalent DDL for `analysis_evidences`; downgrade drops triggers, function, tables and indexes in dependency order. Map JSON fields to `tuple[str, ...]` and evidence payload to `dict[str, JsonValue]`; catch `SQLAlchemyError` only at repository boundaries and rethrow a report-storage error without SQL text.

In `alembic/env.py`, import `reports` beside `market` so its `Base.metadata` mapping is registered before migrations run.

- [ ] **Step 4: 验证持久化和迁移行为**

Run: `uv run pytest tests/persistence/test_report_repository.py tests/persistence/test_migrations.py -v`

Expected: temporary schema reaches revision `0003_create_analysis_reports`; persisted evidence round-trips; database UPDATE/DELETE attempts fail.

- [ ] **Step 5: 提交 Task 2**

```powershell
git add -- backend/alembic/versions/0003_create_analysis_reports.py backend/alembic/env.py backend/src/app/infrastructure/persistence/models/reports.py backend/src/app/infrastructure/persistence/report_repository.py backend/tests/persistence/test_report_repository.py
git commit -m "feat: persist immutable research reports"
```

### Task 3: 实现只读确定性报告生成服务

**Files:**
- Create: `backend/src/app/reports/service.py`
- Create: `backend/tests/reports/test_service.py`

**Interfaces:**
- Consumes: `PersistedMarketReader`、`PersistedMarketSnapshot`、`AnalysisReportRepository`、Task 1 contracts.
- Produces: `DeterministicResearchReportService(reader, repository, clock)` and `await generate(symbol: ContractSymbol) -> PersistedAnalysisReport`.
- Uses exactly `MarketTimeframe.M15`、`H1`、`H4`、`D1`; every reader request uses `limit=200`.

- [ ] **Step 1: 写入生成服务失败测试**

```python
@pytest.mark.asyncio
async def test_service_freezes_latest_snapshot_and_four_latest_closed_candles() -> None:
    repository = RecordingReportRepository()
    service = DeterministicResearchReportService(
        FreshReader(), repository, clock=lambda: NOW,
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.COMPLETED
    assert report.data_cutoff_at == CANDLE_CLOSES[MarketTimeframe.D1]
    assert len(report.evidence) == 5
    assert repository.persisted_evidence[1].payload["latestClosedCandle"]["timeframe"] == "15m"


@pytest.mark.asyncio
async def test_service_generates_no_market_conclusion_when_snapshot_is_stale() -> None:
    report = await stale_service().generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.DEGRADED
    assert report.facts == ()
    assert report.inferences == ()
    assert "数据已过期" in report.risks[0]


@pytest.mark.asyncio
async def test_service_generates_degraded_report_when_reader_is_unavailable() -> None:
    report = await unavailable_service().generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.DEGRADED
    assert report.data_cutoff_at is None
    assert report.evidence == ()
```

Add a fake reader that records its calls and has no gateway dependency. Assert the calls cover only the fixed scope and `limit=200`, evidence preserves source/observed/fetched timestamps, `completed` output contains no prohibited phrase, and a missing single timeframe is degraded with no fact/inference.

- [ ] **Step 2: 验证失败来自缺失服务**

Run: `uv run pytest tests/reports/test_service.py -v`

Expected: collection fails because `DeterministicResearchReportService` is absent.

- [ ] **Step 3: 实现冻结、完成和降级分支**

```python
class DeterministicResearchReportService:
    def __init__(
        self,
        reader: PersistedMarketReader,
        repository: AnalysisReportRepository,
        *,
        clock: Callable[[], datetime],
    ) -> None: ...

    async def generate(self, symbol: ContractSymbol) -> PersistedAnalysisReport:
        generated_at = _require_utc(self._clock())
        try:
            snapshot = await self._require_snapshot(symbol)
            candles = await self._load_latest_closed_candles(symbol)
        except MarketDataUnavailableError as error:
            return await self._repository.persist(
                _degraded_draft(symbol, generated_at, str(error)), (),
            )
        if generated_at - snapshot.captured_at > timedelta(minutes=2):
            return await self._repository.persist(
                _degraded_draft(symbol, generated_at, "持久化市场数据已过期"),
                _evidence_from(snapshot, candles),
            )
        return await self._repository.persist(
            _completed_draft(symbol, snapshot, candles, generated_at),
            _evidence_from(snapshot, candles),
        )
```

`_load_latest_closed_candles` rejects an empty list, incorrect symbol/timeframe or candle closing after `generated_at`; it chooses the last ascending candle for each timeframe. `data_cutoff_at` is the minimum of the frozen evidence observation times for complete/stale reports. `_completed_draft` lists only source-bound price, 24h change, volume, funding rate, open interest and explicit candle-close facts; its sole inference states that observations are not a directional or trading conclusion. `_degraded_draft` has zero facts/inferences, at least one risk and one limitation, and a `NULL` cutoff only when no evidence was loaded. The service never imports or accepts a live gateway.

- [ ] **Step 4: 验证确定性生成与降级**

Run: `uv run pytest tests/reports/test_service.py -v`

Expected: complete, stale, missing and unavailable branches pass with only fake persisted readers.

- [ ] **Step 5: 提交 Task 3**

```powershell
git add -- backend/src/app/reports/service.py backend/tests/reports/test_service.py
git commit -m "feat: generate deterministic market research reports"
```

### Task 4: 暴露报告 HTTP、单状态 SSE 与应用组合

**Files:**
- Create: `backend/src/app/api/routes/analysis_reports.py`
- Create: `backend/tests/api/test_analysis_reports.py`
- Modify: `backend/src/app/api/router.py`
- Modify: `backend/src/app/main.py`

**Interfaces:**
- Consumes: `DeterministicResearchReportService`, `PersistedAnalysisReport`, `ReportPage`.
- Produces: `POST/GET /api/v1/analysis-runs`, `GET /api/v1/analysis-runs/{report_id}`, `POST /api/v1/analysis-runs/{report_id}/retry`, and `GET /api/v1/analysis-runs/{analysis_id}/events`.
- API list uses wire fields `page`, `page_size`, `total`; report fields use the existing camelCase frontend names; `dataCutoffAt` is `null` for fully unavailable data.

- [ ] **Step 1: 写入 API 失败测试**

```python
@pytest.mark.asyncio
async def test_create_report_returns_a_persisted_completed_result() -> None:
    app = _analysis_app(FreshReader())

    response = await post(app, "/api/v1/analysis-runs", {"symbol": "BTCUSDT"})

    assert response.status_code == 201
    analysis_id = UUID(response.json()["analysisId"])
    detail = await get(app, f"/api/v1/analysis-runs/{response.json()['reportId']}")
    assert detail.json()["analysisId"] == str(analysis_id)
    assert detail.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_analysis_sse_replays_one_persisted_terminal_event() -> None:
    response = await get(app, f"/api/v1/analysis-runs/{analysis_id}/events")

    assert response.headers["content-type"].startswith("text/event-stream")
    assert _event_payload(response.text)["status"] == "degraded"
```

Add cases for pagination with `page_size`, status/symbol filters, unknown report/analysis ID 404, retry producing a distinct report/analysis ID, invalid symbol 422, and a `ForbiddenLiveMarketGateway` which would raise if invoked. The latter must still produce a persisted `degraded` response when the injected reader is unavailable.

- [ ] **Step 2: 验证路由测试按预期失败**

Run: `uv run pytest tests/api/test_analysis_reports.py -v`

Expected: collection fails because the report routes and application state dependency do not exist.

- [ ] **Step 3: 实现序列化、安全状态回放与依赖注入**

Create Pydantic response models in `analysis_reports.py` with the same camel alias policy as `MarketSummary`; include `reportId` with `analysisId` in `POST`/retry results so a caller can immediately navigate after the final state event. Use `StreamingResponse` with exactly one line `data: <json>\n\n`, media type `text/event-stream`, and no request payload, exception text or configuration value.

Extend `create_app` with the injectable `analysis_report_repository: AnalysisReportRepository | None = None` argument for isolated API tests. When `DATABASE_URL` exists, create one session factory from the existing `research_engine`, use it for both `SqlAlchemyPersistedMarketReader` and `SqlAlchemyAnalysisReportRepository`, and compose `DeterministicResearchReportService` with a UTC clock. An injected repository is used unchanged. When database configuration is absent, install an unavailable report service that exposes only the stable service-unavailable error; it must not instantiate a live market client. Register the new router in `api/router.py`.

- [ ] **Step 4: 验证 API 契约与既有市场回归**

Run: `uv run pytest tests/api/test_analysis_reports.py tests/api/test_market.py tests/api/test_research_market.py -v`

Expected: report lifecycle is persisted and replayable; no-fallback test passes; existing live/research market paths remain unchanged.

- [ ] **Step 5: 提交 Task 4**

```powershell
git add -- backend/src/app/api/routes/analysis_reports.py backend/src/app/api/router.py backend/src/app/main.py backend/tests/api/test_analysis_reports.py
git commit -m "feat: expose deterministic research reports API"
```

### Task 5: 接通真实 HTTP 报告客户端与空截止时间展示

**Files:**
- Modify: `frontend/src/domain/report.ts`
- Modify: `frontend/src/features/reports/ReportDetailPage.tsx`
- Modify: `frontend/src/features/reports/ReportPages.test.tsx`
- Modify: `frontend/src/shared/api/http-transport.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.test.ts`
- Create: `frontend/src/shared/api/report-http.test.ts`

**Interfaces:**
- Consumes: existing `WorkbenchApi`, frontend report Zod schemas, backend routes from Task 4.
- Produces: HTTP implementations of `listReports`, `getReport`, `startReport`, `retryReport`, `subscribeReport`.
- `HttpTransport.absoluteUrl(path: string) -> string` validates and resolves same-origin HTTP(S) URLs for EventSource without exposing configuration in UI/errors.

- [ ] **Step 1: 写入前端失败测试**

```ts
it("uses analysis-run paths and maps the report page wire contract", async () => {
  const api = new HttpWorkbenchApi({ baseUrl: "http://localhost:8000", fetchImpl });

  await expect(api.listReports({ page: 2, pageSize: 10, symbol: "BTCUSDT" }))
    .resolves.toMatchObject({ page: 2, pageSize: 10 });

  expect(requestUrl(fetchImpl).pathname).toBe("/api/v1/analysis-runs");
  expect(requestUrl(fetchImpl).searchParams.get("page_size")).toBe("10");
});

it("renders an unavailable data cutoff without creating an invalid time element", async () => {
  renderReportDetail(new DegradedNoCutoffApi());

  expect(await screen.findByText("无可用数据")).toBeVisible();
  expect(screen.queryByText("null")).not.toBeInTheDocument();
});
```

Add an EventSource fake test that asserts `subscribeReport` opens `/api/v1/analysis-runs/{analysisId}/events`, forwards the one valid terminal event, and closes on malformed event data. Add POST assertions for request body `{ symbol: "BTCUSDT" }` and retry path encoding.

- [ ] **Step 2: 验证前端测试按预期失败**

Run: `npm run test -- --run src/shared/api/report-http.test.ts src/features/reports/ReportPages.test.tsx`

Expected: HTTP report methods are unavailable and `dataCutoffAt` cannot accept `null`.

- [ ] **Step 3: 实现最小 HTTP 映射和可空显示**

In `domain/report.ts`, change only `dataCutoffAt` to `utcIsoStringSchema.nullable()`. In `ReportDetailPage.tsx`, render `无可用数据` instead of `<time>` when it is null; existing non-null formatting remains unchanged.

In `HttpTransport`, add `absoluteUrl` by resolving a relative path against its already parsed `baseUrl`. In `HttpWorkbenchApi`, add strict Zod schemas for `{ analysisId, reportId }`, report list/detail wire models, and map:

```ts
POST /api/v1/analysis-runs
GET  /api/v1/analysis-runs?page=&page_size=&symbol=&status=
GET  /api/v1/analysis-runs/${encodeURIComponent(reportId)}
POST /api/v1/analysis-runs/${encodeURIComponent(reportId)}/retry
GET  /api/v1/analysis-runs/${encodeURIComponent(analysisId)}/events
```

Use `subscribeToReportStream` from `report-stream.ts`; do not send query credentials, authorization headers or configuration values. Leave `HybridWorkbenchApi` and `MockWorkbenchApi` unchanged.

- [ ] **Step 4: 验证页面与 HTTP 映射**

Run: `npm run test -- --run src/shared/api/http-workbench-api.test.ts src/shared/api/report-http.test.ts src/features/reports/ReportPages.test.tsx`

Expected: HTTP report calls conform to the backend contract; null cutoff has safe visual output; current Mock report lifecycle tests remain green.

- [ ] **Step 5: 提交 Task 5**

```powershell
git add -- frontend/src/domain/report.ts frontend/src/features/reports/ReportDetailPage.tsx frontend/src/features/reports/ReportPages.test.tsx frontend/src/shared/api/http-transport.ts frontend/src/shared/api/http-workbench-api.ts frontend/src/shared/api/http-workbench-api.test.ts frontend/src/shared/api/report-http.test.ts
git commit -m "feat: connect deterministic research reports to HTTP"
```

### Task 6: 运行无回退与全量质量验收

**Files:**
- Modify only the test file that reveals a regression in Tasks 1-5.

**Interfaces:**
- Consumes: all completed report components.
- Produces: complete regression evidence; no new production contract.

- [ ] **Step 1: 添加跨层无实时回退回归（若 Task 4 尚未覆盖）**

```python
@pytest.mark.asyncio
async def test_report_generation_never_uses_the_live_market_gateway() -> None:
    app = create_app(
        market_gateway=ForbiddenLiveMarketGateway(),
        market_research_reader=UnavailablePersistedMarketReader(),
        analysis_report_repository=InMemoryReportRepository(),
    )

    response = await post(app, "/api/v1/analysis-runs", {"symbol": "BTCUSDT"})

    assert response.status_code == 201
    report = await get(app, f"/api/v1/analysis-runs/{response.json()['reportId']}")
    assert report.json()["status"] == "degraded"
```

`ForbiddenLiveMarketGateway` raises on both protocol methods. The test is valid only when its response remains a degraded report rather than an exception from the live gateway.

- [ ] **Step 2: 运行针对性无回退测试**

Run: `uv run pytest tests/api/test_analysis_reports.py::test_report_generation_never_uses_the_live_market_gateway -v`

Expected: PASS; it would fail if reports reach `app.state.market_service` or any live gateway.

- [ ] **Step 3: 运行后端完整检查**

Run:

```powershell
uv run ruff check .
uv run pyright
uv run pytest
```

Expected: all existing and new backend tests pass; no migration runs against the development database.

- [ ] **Step 4: 运行前端完整检查**

Run:

```powershell
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

Expected: all frontend tests, lint, typecheck and production build pass.

- [ ] **Step 5: 提交回归调整（如有）**

```powershell
git add -- backend/tests/api/test_analysis_reports.py frontend/src/shared/api/report-http.test.ts
git commit -m "test: verify deterministic report safety"
```

## Plan Self-Review

- Spec coverage: Task 1 fixes immutable domain boundaries and safe language; Task 2 implements migration, database immutability and query access; Task 3 freezes only persisted market evidence and deterministic complete/degraded reports; Task 4 exposes the full manual HTTP/SSE contract and composition; Task 5 connects existing pages without changing Mock/Hybrid mode; Task 6 demonstrates no live fallback and full checks.
- Placeholder scan: every task names concrete files, interfaces, test cases, commands and expected failures. The only conditional statement in Task 6 limits edits to an actually failing regression test and introduces no undefined work.
- Type consistency: Task 1 defines `AnalysisReportStatus`, drafts and repository protocol; Task 2 implements the protocol; Task 3 consumes it and returns persisted reports; Task 4 serializes those reports; Task 5 consumes the same camelCase API contract. `dataCutoffAt` is nullable only from backend wire to frontend display.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-30-deterministic-market-research-reports.md`.

1. **Subagent-Driven** — dispatch a fresh implementation/review cycle for each task. This is normally faster, but is unavailable unless you explicitly request delegation in this workspace.
2. **Inline Execution** — implement the tasks sequentially in this session, with a verification checkpoint after each task.
