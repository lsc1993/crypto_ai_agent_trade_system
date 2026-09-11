# 结构化中文市场研究报告 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将按需 BTCUSDT/ETHUSDT 研究升级为基于冻结公开证据的详细中文报告，呈现短期（数天至两周）与长期（数周至数月）观点，并使用结论优先的现代报告页。

**Architecture:** 保留 LangGraph 的手动、一次性研究编排和不可变证据链。新增公开市场上下文与情绪适配器、扩展固定 RSS 白名单；将 DeepSeek 的受限 JSON 输出升级为版本化双层观点结构，并把该结构持久化到前向迁移字段。前端严格解析新的 API 契约；新报告使用结论优先页面，旧报告保持现有兼容展示。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy/Alembic/PostgreSQL JSONB、httpx、LangGraph、DeepSeek Chat Completions、React、TypeScript、Zod、TanStack Query、Vitest、Ruff、Pyright。

## Global Constraints

- 仅使用公开、只读的 Binance USDⓈ-M REST、Alternative.me 和明确登记的英文 RSS；不得接入付费数据源或真实交易接口。
- 不得记录或提交 API Key、完整 Prompt、原始模型响应、新闻全文、数据库连接串或上游异常文本。
- LLM 仅生成非交易性的研究解释；任何展示文本必须继续通过 `validate_research_display_text()`，禁止买卖、仓位、杠杆、入场、出场、止损等交易指令。
- 所有价格和派生数值使用 `Decimal`；所有时间均为 UTC 且带时区。
- 每个模型推断必须引用本次报告冻结证据 UUID；模型不得联网、调用工具或执行外部新闻文本中的指令。
- 单源失败必须显示为覆盖不足，不能用旧数据伪装为新数据；必要市场快照或已收盘 K 线失败时只能生成降级报告。
- 数据库只允许前向 Alembic 迁移；不得更新或重写历史报告。
- 先写失败测试，再写最小生产实现；每个任务结束运行对应测试、Ruff、Pyright 并做一个只包含该任务文件的提交。

---

## File Structure

| 路径 | 责任 |
|---|---|
| `backend/src/app/reports/contracts.py` | 版本化双层观点、中文叙事与证据引用的 Pydantic 领域契约。 |
| `backend/src/app/infrastructure/persistence/models/agent_research.py` | 新报告章节的 JSONB 映射；旧行保持可读。 |
| `backend/alembic/versions/0010_expand_agent_report_narrative.py` | 仅增加 nullable JSONB 字段的前向迁移。 |
| `backend/src/app/infrastructure/persistence/report_repository.py` | 双层观点的写入、读取和历史空字段兼容。 |
| `backend/src/app/api/routes/analysis_reports.py` | 将新版 `AgentAnalysis` 映射为 camelCase HTTP 响应。 |
| `backend/src/app/market/research_context.py` | 公开 Binance 衍生品上下文与 Alternative.me 情绪的受限数据模型、协议和采集器。 |
| `backend/src/app/market/binance_usdm.py` | 只读白名单扩展：基差、全市场多空账户比、主动买卖量；不含任何私有端点。 |
| `backend/src/app/news/contracts.py` | 八个明确来源的不可变定义、来源分级和每源项目上限。 |
| `backend/src/app/main.py` | 注入已登记的 RSS 适配器与公开研究上下文采集器。 |
| `backend/src/app/agent/model.py` / `prompt.py` / `service.py` | 受限中文 JSON、证据容量分配、短期/长期报告汇编及安全降级。 |
| `frontend/src/domain/report.ts` | 新旧 Agent 报告契约的严格 Zod 解析和证据归属校验。 |
| `frontend/src/features/reports/AgentResearchReport.tsx` | 新版结论优先报告组件；旧 `narrative === null` 不由此组件渲染。 |
| `frontend/src/features/reports/ReportDetailPage.tsx` | 选择新/旧 Agent 报告视图，保留现有获取、错误页和重试生命周期。 |
| `frontend/src/features/reports/research-report.css` | 新版深色研究面板、响应式网格、状态与风险颜色。 |
| `frontend/src/features/reports/ReportPages.test.tsx` | 新版页面语义、证据跳转、缺失指标、响应式类和旧版兼容断言。 |
| `README.md` / `docs/operational-boundaries.md` | 更新公开输入、来源归因、研究范围和非交易边界。 |

## Task 1: 版本化报告契约与持久化迁移

**Files:**
- Modify: `backend/src/app/reports/contracts.py`
- Modify: `backend/src/app/infrastructure/persistence/models/agent_research.py`
- Modify: `backend/src/app/infrastructure/persistence/report_repository.py`
- Modify: `backend/src/app/api/routes/analysis_reports.py`
- Create: `backend/alembic/versions/0010_expand_agent_report_narrative.py`
- Modify: `backend/tests/persistence/test_agent_research_repository.py`
- Modify: `backend/tests/persistence/test_migrations.py`
- Modify: `backend/tests/api/test_agent_analysis_reports.py`

**Interfaces:**
- Produces `AgentResearchNarrative`, `MarketOverview`, `ResearchPerspective`, and `EvidenceBackedClaim` from `app.reports.contracts`.
- `AgentAnalysis.narrative: AgentResearchNarrative | None` is `None` only for historical 1–3 日报告; all newly produced dual-layer reports persist a complete narrative.
- `AgentAnalysisResponse.narrative` serializes nested UUID values as camelCase `evidenceIds` without exposing evidence payloads.

- [ ] **Step 1: Write failing domain and persistence tests**

```python
def test_dual_horizon_narrative_requires_chinese_evidence_backed_sections() -> None:
    analysis = AgentAnalysis.model_validate({
        **base_analysis(),
        "horizon": "dual_horizon",
        "narrative": dual_horizon_narrative(evidence_id=EVIDENCE_ID),
    })
    assert analysis.narrative is not None
    assert analysis.narrative.short_term.horizon == "short_term"
    assert analysis.narrative.long_term.horizon == "long_term"


async def test_repository_round_trips_dual_horizon_narrative(session_factory) -> None:
    persisted = await SqlAlchemyAnalysisReportRepository(session_factory).persist_agent(
        dual_horizon_creation()
    )
    assert persisted.agent_analysis is not None
    assert persisted.agent_analysis.narrative is not None
    assert persisted.agent_analysis.narrative.market_overview.headline == "流动性回暖但趋势尚未确认"
```

Add migration assertions that `0010` has `down_revision == "0009"`, adds nullable `market_overview`, `short_term_view`, and `long_term_view` JSONB columns to `agent_report_details`, and contains no `UPDATE`, `DELETE`, or server default that backfills old rows. Add route assertions for `narrative.marketOverview`, `shortTerm`, `longTerm`, nested `drivers[*].evidenceIds`, and legacy `narrative: null`.

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `Set-Location backend; uv run pytest tests/persistence/test_agent_research_repository.py tests/persistence/test_migrations.py tests/api/test_agent_analysis_reports.py -q`

Expected: FAIL because `narrative` fields, migration `0010`, and response mapping do not yet exist.

- [ ] **Step 3: Define bounded, evidence-backed models and storage mapping**

Add the following immutable interfaces to `contracts.py`:

```python
class EvidenceBackedClaim(_ReportModel):
    label: str
    detail: str
    evidence_ids: tuple[UUID, ...]


class MarketOverview(_ReportModel):
    headline: str
    summary: str
    evidence_ids: tuple[UUID, ...]


class ResearchPerspective(_ReportModel):
    horizon: Literal["short_term", "long_term"]
    outlook: MarketOutlook
    heading: str
    thesis: str
    drivers: tuple[EvidenceBackedClaim, ...]
    invalidation: tuple[RiskAndInvalidation, ...]


class AgentResearchNarrative(_ReportModel):
    market_overview: MarketOverview
    short_term: ResearchPerspective
    long_term: ResearchPerspective
```

Apply `validate_research_display_text` to every display field; require 1–4 drivers and 1–4 invalidation items per perspective; require 1–12 known evidence IDs per item. For `horizon == "dual_horizon"`, require a non-null narrative and enforce a combined `headline + summary + thesis + driver detail` character count of 1,500–2,500 Chinese display characters after trimming. Preserve legacy values by allowing `horizon == "1_to_3_days"` and `narrative is None`.

Create `0010_expand_agent_report_narrative.py` with `revision = "0010"`, `down_revision = "0009"`, and three nullable `postgresql.JSONB` columns. Update ORM record mapping, repository insert/read transformation, Pydantic API responses, and `_to_agent_analysis_response()` to carry the three JSON objects. The repository must write the parent report before children exactly as it does today.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `Set-Location backend; uv run pytest tests/persistence/test_agent_research_repository.py tests/persistence/test_migrations.py tests/api/test_agent_analysis_reports.py -q`

Expected: PASS; include an old record with all three new columns null to prove historical read compatibility.

- [ ] **Step 5: Run static checks and commit**

Run: `Set-Location backend; uv run ruff check src/app/reports src/app/infrastructure/persistence tests/persistence tests/api; uv run pyright`

Run: `git add -- backend/src/app/reports/contracts.py backend/src/app/infrastructure/persistence/models/agent_research.py backend/src/app/infrastructure/persistence/report_repository.py backend/src/app/api/routes/analysis_reports.py backend/alembic/versions/0010_expand_agent_report_narrative.py backend/tests/persistence/test_agent_research_repository.py backend/tests/persistence/test_migrations.py backend/tests/api/test_agent_analysis_reports.py; git commit -m "feat: persist dual-horizon research narratives"`

## Task 2: 公开市场上下文与情绪证据

**Files:**
- Create: `backend/src/app/market/research_context.py`
- Modify: `backend/src/app/market/binance_usdm.py`
- Modify: `backend/src/app/agent/contracts.py`
- Modify: `backend/src/app/agent/service.py`
- Modify: `backend/src/app/main.py`
- Modify: `backend/tests/market/test_binance_usdm.py`
- Create: `backend/tests/market/test_research_context.py`
- Modify: `backend/tests/agent/test_service.py`
- Modify: `backend/tests/security/test_agent_source_and_secret_safety.py`

**Interfaces:**
- Produces immutable `PublicResearchContext` containing `basis_rate`, `long_short_account_ratio`, `taker_buy_sell_ratio`, `fear_greed_value`, `fear_greed_classification`, `fear_greed_change_7d`, timestamps and `FreshnessStatus`.
- `PublicResearchContextCollector.collect(symbol, captured_at)` returns a context or a finite safe failure code; it never reads accounts, orders, positions, credentials, or exchanges other than the fixed Binance public host.
- `CapturedAgentMarket.research_context` is optional; a missing context is included in data-quality limitations but does not invalidate an otherwise complete frozen market snapshot.

- [ ] **Step 1: Write failing gateway and agent tests**

```python
async def test_public_context_calls_only_allowlisted_binance_paths_and_fear_greed() -> None:
    context = await collector.collect(ContractSymbol.BTCUSDT, captured_at=NOW)
    assert context.basis_rate == Decimal("0.0004")
    assert context.fear_greed_value == 31
    assert context.fear_greed_change_7d == -8


async def test_context_failure_marks_input_missing_but_preserves_completed_report() -> None:
    report = await service_with_failed_context().generate(ContractSymbol.BTCUSDT)
    assert report.status is AnalysisReportStatus.COMPLETED
    assert "market_context_unavailable" in report.agent_analysis.data_quality.missing_inputs
```

Add negative tests for a non-Binance base URL, a disallowed `/fapi/v1/order` request, malformed decimal values, a fear/greed value outside 0–100, naive timestamps, and missing history. Add source-boundary assertions that no source file mentions private account paths, order methods, `ccxt`, `api_key`, `secret`, or `withdraw`.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `Set-Location backend; uv run pytest tests/market/test_binance_usdm.py tests/market/test_research_context.py tests/agent/test_service.py tests/security/test_agent_source_and_secret_safety.py -q`

Expected: FAIL because the context collector and the three new allowlisted public endpoints do not exist.

- [ ] **Step 3: Implement read-only context collection**

In `binance_usdm.py`, add only these paths to `ALLOWED_PATHS`:

```python
"/futures/data/basis",
"/futures/data/globalLongShortAccountRatio",
"/futures/data/takerlongshortRatio",
```

Use the existing `_get_public_json()` retry/error discipline and request one `period="1h", limit="1"` observation per metric. Create `research_context.py` with a separate fixed-host `AlternativeMeFearGreedGateway` that permits only `https://api.alternative.me/fng/`, requests `limit=8&format=json`, validates UTC timestamps, computes the seven-day signed change from the newest and seventh newest readings, and returns only normalized public values. Combine all fetches with bounded timeouts and a single finite `market_context_unavailable` failure code.

Update `PersistedAgentMarketCapture` to freeze successful context values in `CapturedAgentMarket`; construct a second machine-generated market evidence record with canonical JSON payload and SHA-256. Lower `_MAX_NEWS_EVIDENCE` to 28 so snapshot + context + news never exceeds the existing 30-evidence model limit. On context failure, retain the market snapshot, append only the safe missing-input code, and do not log response bodies.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `Set-Location backend; uv run pytest tests/market/test_binance_usdm.py tests/market/test_research_context.py tests/agent/test_service.py tests/security/test_agent_source_and_secret_safety.py -q`

Expected: PASS, including the partial-context completed report and all public-boundary negatives.

- [ ] **Step 5: Run static checks and commit**

Run: `Set-Location backend; uv run ruff check src/app/market src/app/agent tests/market tests/agent tests/security; uv run pyright`

Run: `git add -- backend/src/app/market/research_context.py backend/src/app/market/binance_usdm.py backend/src/app/agent/contracts.py backend/src/app/agent/service.py backend/src/app/main.py backend/tests/market/test_binance_usdm.py backend/tests/market/test_research_context.py backend/tests/agent/test_service.py backend/tests/security/test_agent_source_and_secret_safety.py; git commit -m "feat: add public market context evidence"`

## Task 3: 八来源英文 RSS 白名单

**Files:**
- Modify: `backend/src/app/news/contracts.py`
- Modify: `backend/src/app/main.py`
- Modify: `backend/tests/news/test_rss.py`
- Modify: `backend/tests/agent/test_service.py`
- Modify: `backend/tests/security/test_agent_dependency_boundary.py`
- Modify: `README.md`
- Modify: `docs/operational-boundaries.md`

**Interfaces:**
- `ALLOWED_NEWS_SOURCES` contains exactly eight IDs: `sec_press_releases`, `cftc_press_releases`, `federal_reserve_press_releases`, `us_treasury_press_releases`, `coindesk`, `decrypt`, `blockworks`, `the_block`.
- `NewsSourceDefinition` remains immutable and validates a fixed direct HTTPS feed URL and 1–30 `max_items_per_run`.
- `NewsCollection` retains independent failure counting; source failure cannot insert an item with a forged `source_id` or `source_tier`.

- [ ] **Step 1: Write failing registry and wiring tests**

```python
def test_allowed_news_sources_are_exactly_the_governed_eight() -> None:
    assert set(ALLOWED_NEWS_SOURCES) == {
        "sec_press_releases", "cftc_press_releases", "federal_reserve_press_releases",
        "us_treasury_press_releases", "coindesk", "decrypt", "blockworks", "the_block",
    }


def test_production_news_ingestion_registers_every_allowed_source() -> None:
    sources = build_news_sources(client=client, timeout_seconds=5)
    assert {source.source.source_id for source in sources} == set(ALLOWED_NEWS_SOURCES)
```

Add RSS tests using XML fixtures for every source definition: no redirects, compressed response rejection, at-most `max_items_per_run`, source attribution matching, `related_symbols` filtering, and one failed source plus successful sources. Add dependency-boundary checks that only the RSS adapter makes network requests to feed URLs and that the model has no URL fetching code.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `Set-Location backend; uv run pytest tests/news/test_rss.py tests/agent/test_service.py tests/security/test_agent_dependency_boundary.py -q`

Expected: FAIL because six approved source definitions and production source construction are absent.

- [ ] **Step 3: Implement the fixed source registry and startup composition**

Define direct, non-redirecting RSS URLs in source definitions:

```python
"https://www.sec.gov/news/pressreleases.rss",
"https://www.cftc.gov/RSS/RSSGP/rssgp.xml",
"https://www.federalreserve.gov/feeds/press_all.xml",
"https://home.treasury.gov/rss/press-releases.xml",
"https://www.coindesk.com/arc/outboundfeeds/rss/",
"https://decrypt.co/feed",
"https://blockworks.com/feed",
"https://www.theblock.co/rss.xml",
```

Create a small `build_news_sources()` factory in `main.py` that returns one `RssNewsSourceAdapter` per ordered registry entry, then use it in lifespan construction. Keep `follow_redirects=False`, 512 KiB response ceiling, XML hardening, per-source error isolation and no article-page fetch. If the CoinDesk endpoint returns a redirect in production, its result is a visible `news_source_failed` contribution, never a redirect follow; replace its configured URL only after adding a direct-feed regression fixture and updating its exact source definition.

Update public documentation to name the eight sources, say that only titles/summaries are fetched, include Alternative.me attribution requirements, and state that source availability can be partial per manual run.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `Set-Location backend; uv run pytest tests/news/test_rss.py tests/agent/test_service.py tests/security/test_agent_dependency_boundary.py -q`

Expected: PASS with every feed fixture, forged attribution rejection, and partial source coverage.

- [ ] **Step 5: Run static checks and commit**

Run: `Set-Location backend; uv run ruff check src/app/news src/app/main.py tests/news tests/agent tests/security; uv run pyright`

Run: `git add -- backend/src/app/news/contracts.py backend/src/app/main.py backend/tests/news/test_rss.py backend/tests/agent/test_service.py backend/tests/security/test_agent_dependency_boundary.py README.md docs/operational-boundaries.md; git commit -m "feat: expand governed research news sources"`

## Task 4: 受限的详细中文 DeepSeek 报告

**Files:**
- Modify: `backend/src/app/agent/model.py`
- Modify: `backend/src/app/agent/prompt.py`
- Modify: `backend/src/app/agent/service.py`
- Modify: `backend/src/app/agent/graph.py`
- Modify: `backend/tests/agent/test_model.py`
- Modify: `backend/tests/agent/test_graph.py`
- Modify: `backend/tests/agent/test_service.py`

**Interfaces:**
- `ResearchModelRequest` passes `report_language="zh-CN"`, frozen `MarketStructure`, snapshot/context evidence, and at most 28 RSS evidence records.
- `AgentAnalysisProposal` produces `AgentResearchNarrative`; all new evidence references are validated against `request.evidences` before persistence.
- `_MAX_TOKENS = 4_000`; thinking remains explicitly disabled; output remains one JSON object and no tool call is enabled.

- [ ] **Step 1: Write failing prompt, parsing, and degradation tests**

```python
async def test_deepseek_request_requires_chinese_dual_horizon_narrative() -> None:
    await model.generate(dual_horizon_request())
    body = recorded_request.json()
    assert body["max_tokens"] == 4000
    assert body["thinking"] == {"type": "disabled"}
    assert "zh-CN" in body["messages"][0]["content"]


def test_model_rejects_narrative_reference_outside_frozen_evidence() -> None:
    with pytest.raises(ModelOutputError, match="model_invalid_evidence"):
        AgentAnalysisProposal.model_validate_json(UNKNOWN_NARRATIVE_EVIDENCE_JSON)
```

Add tests for Chinese section headings and 1,500–2,500 character total, each `drivers` and `invalidation` item having a known evidence ID, English RSS text enclosed as untrusted content, a model response that truncates mid-JSON, and a context-source failure creating a completed report whose narrative lists the missing input. Assert safe logs contain event names/counts/durations only, never prompt text, news title, model content, API key, or response body.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `Set-Location backend; uv run pytest tests/agent/test_model.py tests/agent/test_graph.py tests/agent/test_service.py -q`

Expected: FAIL because the old prompt asks for a 1–3 day schema and has no detailed narrative fields.

- [ ] **Step 3: Implement the dual-horizon Chinese model contract**

Replace the system schema with a Chinese-only `dual_horizon` response that contains:

```json
{
  "horizon": "dual_horizon",
  "market_overview": {"headline": "…", "summary": "…", "evidence_ids": ["…"]},
  "short_term": {"horizon": "short_term", "outlook": "neutral", "heading": "…", "thesis": "…", "drivers": [], "invalidation": []},
  "long_term": {"horizon": "long_term", "outlook": "neutral", "heading": "…", "thesis": "…", "drivers": [], "invalidation": []},
  "catalysts": [],
  "risks_and_invalidation": [],
  "limitations": []
}
```

Tell the model the time definitions, to explain evidence rather than forecast a date-bound price, to write Chinese prose, to preserve deterministic support/resistance, and to avoid investment/trading instructions. Keep all external news inside untrusted delimiters. Build report title from the market-overview heading, summary from its detail, and `AgentAnalysis` from the validated proposal. Legacy degraded behavior remains unchanged; invalid, empty, truncated, unknown-evidence or prohibited-instruction responses create a safe degraded report with frozen evidence.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `Set-Location backend; uv run pytest tests/agent/test_model.py tests/agent/test_graph.py tests/agent/test_service.py -q`

Expected: PASS, including prompt injection, reference rejection, safe logging, and complete/degraded report paths.

- [ ] **Step 5: Run static checks and commit**

Run: `Set-Location backend; uv run ruff check src/app/agent tests/agent; uv run pyright`

Run: `git add -- backend/src/app/agent/model.py backend/src/app/agent/prompt.py backend/src/app/agent/service.py backend/src/app/agent/graph.py backend/tests/agent/test_model.py backend/tests/agent/test_graph.py backend/tests/agent/test_service.py; git commit -m "feat: generate detailed Chinese research narratives"`

## Task 5: 前端契约与结论优先报告界面

**Files:**
- Modify: `frontend/src/domain/report.ts`
- Create: `frontend/src/features/reports/AgentResearchReport.tsx`
- Create: `frontend/src/features/reports/research-report.css`
- Modify: `frontend/src/features/reports/ReportDetailPage.tsx`
- Modify: `frontend/src/features/reports/ReportGenerator.tsx`
- Modify: `frontend/src/features/reports/ReportListPage.tsx`
- Modify: `frontend/src/features/reports/ReportPages.test.tsx`
- Modify: `frontend/src/shared/api/report-http.test.ts`
- Modify: `frontend/src/test/research-agent-boundaries.test.tsx`

**Interfaces:**
- `agentAnalysisSchema` accepts both legacy `horizon: "1_to_3_days", narrative: null` and new `horizon: "dual_horizon", narrative: AgentResearchNarrative`.
- `AgentResearchReport({ report })` requires `report.agentAnalysis.narrative !== null` and renders all new evidence links as `#evidence-<uuid>` anchors.
- `ReportDetailPage` selects `AgentResearchReport` only for dual-horizon narrative reports; it keeps `AgentResearchPanels` for historical Agent reports and generic reports unchanged.

- [ ] **Step 1: Write failing frontend schema and component tests**

```tsx
it("renders a Chinese conclusion-first dual-horizon report with evidence-linked views", async () => {
  renderDualHorizonReport();
  expect(await screen.findByRole("heading", { name: "流动性回暖但趋势尚未确认" })).toBeVisible();
  expect(screen.getByRole("region", { name: "市场概况" })).toHaveTextContent("本次冻结证据");
  expect(screen.getByRole("region", { name: "短期市场观点" })).toHaveTextContent("数天至两周");
  expect(screen.getByRole("region", { name: "长期市场观点" })).toHaveTextContent("数周至数月");
  expect(screen.getByRole("link", { name: /查看证据/ })).toHaveAttribute("href", "#evidence-evidence-btc-001");
});
```

Add tests for six metric cards; a missing metric showing `本次未取得`; source coverage and model confidence in the hero; catalysts and risks retaining evidence anchors; English evidence remaining in the evidence section; generated report list summary; mobile-safe class structure; legacy Agent detail preserving the current `未来 1–3 天市场研判` view; malformed new nested evidence IDs being rejected by Zod.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `Set-Location frontend; npm run test -- --run src/features/reports/ReportPages.test.tsx src/shared/api/report-http.test.ts src/test/research-agent-boundaries.test.tsx`

Expected: FAIL because the strict client schema and dual-horizon components do not yet exist.

- [ ] **Step 3: Implement strict client contract and A-layout components**

Extend `domain/report.ts` with strict narrative schemas mirroring Task 1 and include `marketOverview`, `shortTerm`, `longTerm`, `drivers`, and `invalidation` in the existing evidence ID cross-report refinement. Create `AgentResearchReport.tsx` with semantic regions in this order:

```tsx
<header className="research-report__hero">…headline, timestamps, status, coverage, confidence…</header>
<section aria-label="关键指标">…price, change, volume, sentiment, funding, open interest…</section>
<section aria-label="市场概况">…</section>
<section aria-label="短期市场观点">…drivers, zones, invalidation…</section>
<section aria-label="长期市场观点">…drivers, invalidation…</section>
<section aria-label="潜在催化事件">…</section>
<section aria-label="风险与失效条件">…</section>
```

Use the new CSS file for deep navy surfaces, restrained card shadows, responsive grid-to-single-column breakpoints, accessible focus rings, and semantic positive/negative/neutral colors. Do not use a red/green color alone to communicate a direction. Keep evidence original title/summary inside `EvidenceList`; do not render `payload` or pass raw detail in URLs. Update generation/list copy to say “短期与长期市场观点”, never “未来 1–3 天预测”.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `Set-Location frontend; npm run test -- --run src/features/reports/ReportPages.test.tsx src/shared/api/report-http.test.ts src/test/research-agent-boundaries.test.tsx`

Expected: PASS with exact semantic region names, evidence anchor safety, missing-data presentation, old-report compatibility, and strict wire rejection.

- [ ] **Step 5: Run frontend quality checks and commit**

Run: `Set-Location frontend; npm run typecheck; npm run lint; npm run build`

Run: `git add -- frontend/src/domain/report.ts frontend/src/features/reports/AgentResearchReport.tsx frontend/src/features/reports/research-report.css frontend/src/features/reports/ReportDetailPage.tsx frontend/src/features/reports/ReportGenerator.tsx frontend/src/features/reports/ReportListPage.tsx frontend/src/features/reports/ReportPages.test.tsx frontend/src/shared/api/report-http.test.ts frontend/src/test/research-agent-boundaries.test.tsx; git commit -m "feat: redesign structured research report page"`

## Task 6: 端到端验证、来源归因与运行手册

**Files:**
- Modify: `README.md`
- Modify: `docs/local-deployment.md`
- Modify: `docs/operational-boundaries.md`
- Modify: `backend/tests/api/test_agent_analysis_reports.py`
- Modify: `frontend/src/features/reports/ReportPages.test.tsx`

**Interfaces:**
- A real manual run persists frozen Binance, Alternative.me and successful RSS evidence; no source payload becomes a log or frontend route parameter.
- A partial source run is visibly marked partial and a model failure is visibly degraded, with no claim that the report is current or complete.

- [ ] **Step 1: Write failing end-to-end and documentation assertions**

```python
async def test_manual_report_returns_dual_horizon_chinese_narrative_and_coverage(client) -> None:
    response = await client.post("/api/v1/analysis-runs", json={"symbol": "BTCUSDT"})
    report = await client.get(f"/api/v1/analysis-runs/{response.json()['reportId']}")
    assert report.json()["agentAnalysis"]["horizon"] == "dual_horizon"
    assert report.json()["agentAnalysis"]["dataQuality"]["sourceCoverage"] in {"partial", "complete"}
```

Add a documentation test or focused text assertion that `README.md` names the public-only data policy, eight source labels, Alternative.me attribution, DeepSeek `.env` placement, `LOG_LEVEL=DEBUG` lifecycle fields, and the non-trading limitation without including secrets.

- [ ] **Step 2: Run tests to verify RED**

Run: `Set-Location backend; uv run pytest tests/api/test_agent_analysis_reports.py -q`

Expected: FAIL until the API runs the new dual-horizon pipeline and documentation is updated.

- [ ] **Step 3: Complete documentation and run controlled local verification**

Document the manual workflow, all public source categories, expected partial-coverage behavior, and safe local debugging commands. The only permitted debug instruction is to set `LOG_LEVEL=DEBUG` in the untracked root `.env`, recreate `api`, inspect lifecycle events, then restore `LOG_LEVEL=INFO`; never print environment values or keys. Verify with a local Compose run only after migrations are applied; examine status, report shape, evidence count, and safe logs, not credentials or model content.

- [ ] **Step 4: Run complete verification**

Run:

```powershell
Set-Location backend
uv run ruff check .
uv run pyright
uv run pytest
Set-Location ..\frontend
npm run typecheck
npm run lint
npm run test -- --run
npm run build
Set-Location ..
git diff --check
```

Expected: all checks pass. If PostgreSQL integration fixtures are unavailable because `TEST_DATABASE_URL` is absent, report exactly those skipped/blocked database checks and still run all non-database checks; do not invent a connection string.

- [ ] **Step 5: Commit documentation and verification tests**

Run: `git add -- README.md docs/local-deployment.md docs/operational-boundaries.md backend/tests/api/test_agent_analysis_reports.py frontend/src/features/reports/ReportPages.test.tsx; git commit -m "docs: explain structured market research inputs"`

## Plan Self-Review

- Coverage: Task 1 covers the versioned contract, persistence, API and forward-only migration; Task 2 covers public market/sentiment evidence; Task 3 covers the eight controlled RSS sources; Task 4 covers constrained Chinese model output and safe degradation; Task 5 covers A-layout UI and old-report compatibility; Task 6 covers end-to-end behavior, attribution and safe local diagnostics.
- Placeholder scan: all external sources, interfaces, tests, commands, migration revision, source IDs and failure semantics are explicit; no task relies on an unspecified future implementation.
- Type consistency: backend and frontend use `AgentResearchNarrative`/`narrative`, `MarketOverview`/`marketOverview`, `EvidenceBackedClaim`/`drivers`, `ResearchPerspective`/`shortTerm`/`longTerm`, and the same finite `dual_horizon`, `short_term`, `long_term` values throughout.
