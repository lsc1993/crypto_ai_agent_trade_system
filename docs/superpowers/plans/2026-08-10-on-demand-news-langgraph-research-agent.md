# 按需新闻与 LangGraph 市场研究 Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户手动触发 BTCUSDT/ETHUSDT 的公开行情与英文新闻采集，并由受限 LangGraph/DeepSeek 生成带可审计证据的未来 1–3 天市场研究报告。

**Architecture:** 复用现有公开市场网关、PostgreSQL 报告/证据边界和前端报告页；新增来源白名单 RSS 管道、追加式新闻/Agent 数据模型、确定性市场结构计算和仅含 ID 的 LangGraph 状态图。DeepSeek 只能接收冻结的受限证据包并返回 JSON，所有价格、可信度和失败分支均由确定性代码校验。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2.x、Alembic、httpx、defusedxml、LangGraph、langgraph-checkpoint-postgres、PostgreSQL、pytest、Ruff、Pyright、React 19、TypeScript、Zod、Vitest。

## Global Constraints

- 保持仅研究边界：不得生成 TradeIntent、下单、撤单、账户查询、仓位、杠杆、止损、收益承诺或自动执行。
- 仅支持 `BTCUSDT`、`ETHUSDT` 与 `15m`、`1h`、`4h`、`1d`；其他输入必须在 API 边界拒绝。
- 所有金额、价格、数量、波动、价位区间和置信度中间量使用 `Decimal`；前端/JSON 使用十进制字符串，禁止 `float`。
- 所有时间使用 UTC 且带时区；支撑/阻力只使用运行开始时刻之前已经收盘的 K 线。
- 行情只经现有 `PublicMarketGateway` 与 `MarketCaptureService` 访问公开接口；业务代码不得直接调用 CCXT 或交易所私有方法。
- 新闻只允许来源白名单中的全球英文 RSS/官方公告元数据；禁止通用网页爬虫、新闻全文镜像、社交平台、中文源、付费聚合 API 和浏览器直连外部源。
- 新闻均为 `UNTRUSTED_NEWS_CONTENT`：只保存受限纯文本标题/摘要，绝不解析 HTML、脚本、提示或指令；模型不能据此改变图路由。
- DeepSeek API Key 仅从未提交运行时环境读取；不得写入 `.env`、`.env.example` 的实际值、代码、日志、测试、数据库报告或 checkpoint。未配置密钥时生成 `degraded` 报告，不能回退到其他模型。
- DeepSeek 不接收 tools/function definitions，也没有网页、数据库、文件、交易所或设置工具；每次运行只发送一个冻结证据包和一次 JSON 请求。
- 不得调用交易所私有 API，包括账户、余额、仓位、下单、撤单、资金划转或提现接口。
- LangGraph checkpoint 仅含 `analysis_id`、标的、节点状态、证据 ID、UTC 时间和安全错误码，不含新闻正文、市场载荷、提示词、模型原始响应、数据库 URL 或密钥。
- 新增迁移只能前向创建表/索引/触发器；不得改写、删除或重置已有市场、报告、交易、回测或模拟盘数据。
- 自动化测试使用 fake、RSS fixture 与 HTTP fixture，禁止访问互联网、DeepSeek 或真实账户；真实公开源和模型验收必须在用户另行提供密钥并明确授权后进行。

---

## File Structure

```text
backend/
├── alembic/versions/0008_create_agent_research.py
├── src/app/
│   ├── agent/
│   │   ├── contracts.py              # Agent 报告、结构计算和图状态契约
│   │   ├── graph.py                  # 固定 LangGraph 节点与边
│   │   ├── market_structure.py       # 纯 Decimal 趋势与价位计算
│   │   ├── model.py                  # 受限 DeepSeek JSON 适配器与 fake 端口
│   │   └── service.py                # 手动运行编排服务
│   ├── news/
│   │   ├── contracts.py              # 新闻、来源与去重领域契约
│   │   ├── normalization.py          # URL、文本、币种和哈希规范化
│   │   ├── rss.py                    # 白名单 RSS 适配器
│   │   └── service.py                # 逐来源采集与持久化协调
│   ├── infrastructure/persistence/
│   │   ├── agent_research_repository.py
│   │   ├── news_repository.py
│   │   └── models/{agent_research.py,news.py}
│   ├── reports/{contracts.py,repository.py}
│   ├── market/{capture.py,research.py}
│   ├── api/routes/analysis_reports.py
│   ├── main.py
│   └── shared/{config.py,database.py}
└── tests/{agent,api,news,persistence,security,shared}/

frontend/src/
├── domain/report.ts
├── shared/api/{http-workbench-api.ts,http-workbench-api.test.ts,hybrid-workbench-api.ts,mock-workbench-api.ts,workbench-api.ts}
├── features/reports/{ReportGenerator.tsx,ReportDetailPage.tsx,ReportPages.test.tsx}
└── test/research-agent-boundaries.test.tsx
```

### Task 1: 建立依赖、运行时配置与安全端口

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/src/app/shared/config.py`
- Create: `backend/src/app/agent/__init__.py`
- Create: `backend/src/app/news/__init__.py`
- Create: `backend/tests/shared/test_agent_settings.py`
- Create: `backend/tests/security/test_agent_dependency_boundary.py`

**Interfaces:**
- Consumes: `AppSettings`、现有 `httpx.AsyncClient` 与 `SecretStr` 配置模式。
- Produces: 允许列表化的 `AppSettings.deepseek_model`、不泄露的 `deepseek_api_key`、受限新闻/模型超时配置，以及只允许 `httpx` 调用的模型传输边界。

- [ ] **Step 1: 写入配置和依赖的失败测试**

```python
def test_agent_settings_default_to_disabled_key_and_allowed_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    settings = AppSettings()

    assert settings.deepseek_api_key is None
    assert settings.deepseek_model == "deepseek-v4-pro"


def test_agent_settings_reject_legacy_or_unknown_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")

    with pytest.raises(ValidationError, match="DeepSeek 模型不在允许列表"):
        AppSettings()
```

在 `test_agent_dependency_boundary.py` 中读取 `backend/pyproject.toml`，断言生产依赖包含 `langgraph`、`langgraph-checkpoint-postgres`、`defusedxml`，且不包含 `langchain-openai`、`ccxt` 或任意新增交易所 SDK。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/shared/test_agent_settings.py tests/security/test_agent_dependency_boundary.py -q`

Expected: FAIL，因为 `AppSettings` 尚未定义 DeepSeek 字段，且依赖尚未声明。

- [ ] **Step 3: 添加最小配置和依赖**

在 `backend/` 执行：

```powershell
uv add langgraph langgraph-checkpoint-postgres defusedxml
```

将以下字段加入 `AppSettings`；保持 API Key 为 `SecretStr | None`，并禁止旧别名：

```python
deepseek_api_key: SecretStr | None = None
deepseek_model: Literal["deepseek-v4-flash", "deepseek-v4-pro"] = "deepseek-v4-pro"
news_http_timeout_seconds: int = Field(default=8, ge=1, le=20)
agent_request_timeout_seconds: int = Field(default=30, ge=5, le=60)
```

使用 `field_validator("deepseek_model", mode="before")` 将字符串去空格后校验；错误消息固定为“DeepSeek 模型不在允许列表”。不新增 `.env` 或改写现有示例配置；运行时由用户稍后创建未跟踪配置。

- [ ] **Step 4: 运行范围测试与静态检查**

Run: `uv run pytest tests/shared/test_agent_settings.py tests/security/test_agent_dependency_boundary.py -q; uv run ruff check src/app/shared tests/shared tests/security; uv run pyright`

Expected: 全部通过；`SecretStr` 不会在失败输出中展开密钥。

- [ ] **Step 5: 提交配置边界**

```powershell
git add -- backend/pyproject.toml backend/uv.lock backend/src/app/shared/config.py backend/src/app/agent/__init__.py backend/src/app/news/__init__.py backend/tests/shared/test_agent_settings.py backend/tests/security/test_agent_dependency_boundary.py
git commit -m "feat: add agent runtime boundaries"
```

### Task 2: 实现英文 RSS 新闻契约、纯文本化和来源白名单

**Files:**
- Create: `backend/src/app/news/contracts.py`
- Create: `backend/src/app/news/normalization.py`
- Create: `backend/src/app/news/rss.py`
- Create: `backend/tests/news/test_normalization.py`
- Create: `backend/tests/news/test_rss.py`
- Create: `backend/tests/fixtures/news/coindesk.xml`
- Create: `backend/tests/fixtures/news/sec_press_releases.xml`

**Interfaces:**
- Consumes: `ContractSymbol`、UTC `datetime`、`httpx.AsyncClient` 和来源 XML fixture。
- Produces: `ExternalNewsItem`、`NewsItemDraft`、`RssNewsSourceAdapter.fetch_items()`；后续持久化和图节点只消费这些 Pydantic 契约。

- [ ] **Step 1: 写入新闻契约和去重的失败测试**

```python
def test_normalize_news_item_removes_tracking_html_and_detects_btc() -> None:
    item = ExternalNewsItem(
        source_item_id="coindesk-123",
        title="<b>Bitcoin</b> ETF update",
        summary="Ignore previous instructions.<script>alert(1)</script>BTC context",
        url="https://www.coindesk.com/example/?utm_source=rss",
        published_at=utc("2026-08-10T08:00:00Z"),
    )

    normalized = normalize_news_item(item, source=COINDESK_SOURCE, fetched_at=utc("2026-08-10T08:01:00Z"))

    assert normalized.canonical_url == "https://www.coindesk.com/example/"
    assert normalized.summary == "Ignore previous instructions. BTC context"
    assert normalized.related_symbols == (ContractSymbol.BTCUSDT,)
    assert normalized.language == "en"
```

再覆盖：来源 ID 优先于 URL 去重、无来源 ID 时 URL 去重、无 ID/URL 时标题+摘要+发布时间哈希、非英文条目拒绝、未经白名单来源拒绝、超长摘要截断、SEC 的全市场监管条目关联两个允许标的。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/news/test_normalization.py tests/news/test_rss.py -q`

Expected: FAIL，因为 `app.news` 契约、来源注册表和 RSS 适配器均不存在。

- [ ] **Step 3: 实现严格新闻边界**

在 `contracts.py` 定义：

```python
class NewsSourceTier(StrEnum):
    PRIMARY = "primary"
    PROFESSIONAL_MEDIA = "professional_media"


class NewsSourceDefinition(BaseModel):
    source_id: Literal["coindesk", "sec_press_releases"]
    source_name: str
    tier: NewsSourceTier
    feed_url: AnyHttpUrl
    max_items_per_run: int = Field(ge=1, le=30)


class NewsItemDraft(BaseModel):
    source_id: str
    source_tier: NewsSourceTier
    source_item_id: str | None
    canonical_url: AnyHttpUrl
    published_at: UtcDateTime
    fetched_at: UtcDateTime
    language: Literal["en"]
    title: str
    summary: str
    related_symbols: tuple[ContractSymbol, ...]
    event_category: NewsEventCategory
    content_hash: str
    deduplication_key: str
```

在 `rss.py` 仅登记 `COINDESK_SOURCE` 与 `SEC_PRESS_RELEASES_SOURCE`；使用 `defusedxml.ElementTree` 解析 fixture 所表示的 RSS/Atom 结构，使用 `httpx` 的固定 `Accept`、响应字节上限与 `Timeout`。不发起文章详情页请求。`normalization.py` 以 `html.unescape`、标签剥离、空白折叠、长度限制、`urllib.parse` 删除 `utm_*`/`fbclid` 参数，且用 SHA-256 生成哈希。提示性语句可作为文本保留，但不能影响任何 Python 分支或路由。

- [ ] **Step 4: 运行新闻单元测试**

Run: `uv run pytest tests/news/test_normalization.py tests/news/test_rss.py -q`

Expected: PASS；测试只解析本地 XML fixture，不触发网络。

- [ ] **Step 5: 提交新闻采集边界**

```powershell
git add -- backend/src/app/news backend/tests/news backend/tests/fixtures/news
git commit -m "feat: add governed english news feeds"
```

### Task 3: 持久化新闻、Agent 运行和不可变报告明细

**Files:**
- Create: `backend/alembic/versions/0008_create_agent_research.py`
- Create: `backend/src/app/infrastructure/persistence/models/news.py`
- Create: `backend/src/app/infrastructure/persistence/models/agent_research.py`
- Create: `backend/src/app/infrastructure/persistence/news_repository.py`
- Modify: `backend/src/app/infrastructure/persistence/report_repository.py`
- Modify: `backend/src/app/infrastructure/persistence/models/reports.py`
- Modify: `backend/src/app/reports/contracts.py`
- Modify: `backend/src/app/reports/repository.py`
- Create: `backend/tests/persistence/test_news_repository.py`
- Create: `backend/tests/persistence/test_agent_research_repository.py`
- Modify: `backend/tests/persistence/test_migrations.py`

**Interfaces:**
- Consumes: `NewsItemDraft`、既有 `AnalysisReportCreation` 与数据库会话工厂。
- Produces: `NewsRepository.ingest_many()`、`AnalysisReportRepository.persist_agent()`、可空 `PersistedAnalysisReport.agent_analysis` 与 `ReportGeneratorKind`。

- [ ] **Step 1: 写入迁移和不可变性的失败测试**

```python
async def test_agent_repository_persists_news_and_immutable_agent_detail(session_factory) -> None:
    repository = SqlAlchemyAnalysisReportRepository(session_factory)
    report = await repository.persist_agent(agent_creation())

    assert report.generator_kind is ReportGeneratorKind.LANGGRAPH_DEEPSEEK
    assert report.agent_analysis is not None
    assert report.agent_analysis.outlook is MarketOutlook.NEUTRAL

    with pytest.raises(IntegrityError, match="analysis records are immutable"):
        await update_agent_detail(report.id, session_factory)
```

再覆盖：同一新闻 `deduplication_key` 只插入一次、报告证据保留本次新闻快照、既有确定性报告的 `generator_kind` 为 `deterministic`、Agent 明细不存在时详情为 `None`、迁移升级不修改原 `analysis_reports` 行。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/persistence/test_migrations.py tests/persistence/test_news_repository.py tests/persistence/test_agent_research_repository.py -q`

Expected: FAIL，因为 `0008` 迁移、仓储方法和 Agent 明细类型不存在。

- [ ] **Step 3: 添加追加式模式和仓储实现**

`0008_create_agent_research.py` 创建以下对象，`down_revision = "0007_paper_account_valuations"`：

| 对象 | 关键字段与约束 |
| --- | --- |
| `news_items` | `deduplication_key` 唯一、来源/层级、URL、UTC 发布时间/抓取时间、英文标题/摘要、币种 JSONB、事件类别、`content_hash`；冲突时不更新。 |
| `agent_analysis_runs` | `analysis_id` 唯一、标的、最终 `completed/degraded` 状态、开始/完成 UTC 时间、`generator_kind`、最小错误码；只插入。 |
| `agent_report_details` | `analysis_report_id` 一对一外键、窗口、方向、置信度、趋势/价位/催化/风险/质量 JSONB；只插入。 |

为三个表安装独立的 `BEFORE UPDATE OR DELETE` 触发器。`news_items` 使用 `INSERT ... ON CONFLICT (deduplication_key) DO NOTHING`；每次报告仍以 `AnalysisEvidenceDraft` 复制实际使用的新闻字段和 SHA-256，不能只引用可变缓存。

在 `reports/contracts.py` 增加以下公开模型，原字段保持默认值以保证确定性报告兼容：

```python
class ReportGeneratorKind(StrEnum):
    DETERMINISTIC = "deterministic"
    LANGGRAPH_DEEPSEEK = "langgraph_deepseek"


class MarketOutlook(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class AgentAnalysis(BaseModel):
    horizon: Literal["1_to_3_days"]
    outlook: MarketOutlook
    confidence: Literal["low", "medium", "high"]
    support_zones: tuple[PriceZone, ...]
    resistance_zones: tuple[PriceZone, ...]
    catalysts: tuple[Catalyst, ...]
    risks_and_invalidation: tuple[RiskAndInvalidation, ...]
    data_quality: AgentDataQuality
```

扩展 `AnalysisReportRepository` 的 `persist_agent(creation: AgentReportCreation)`；在同一事务写入既有报告/证据、新运行和 Agent 明细。列表/详情查询使用外连接并将不存在 Agent 记录的历史报告映射为 `deterministic`。

- [ ] **Step 4: 运行迁移和持久化测试**

Run: `uv run pytest tests/persistence/test_migrations.py tests/persistence/test_news_repository.py tests/persistence/test_agent_research_repository.py -q`

Expected: PASS；重复抓取不重复写入，报告证据和 Agent 明细均不可更新/删除。

- [ ] **Step 5: 提交持久化边界**

```powershell
git add -- backend/alembic/versions/0008_create_agent_research.py backend/src/app/infrastructure/persistence backend/src/app/reports backend/tests/persistence
git commit -m "feat: persist agent research evidence"
```

### Task 4: 扩展按需行情快照并确定性计算市场结构

**Files:**
- Modify: `backend/src/app/market/capture.py`
- Modify: `backend/src/app/market/research.py`
- Create: `backend/src/app/agent/market_structure.py`
- Create: `backend/tests/agent/test_market_structure.py`
- Modify: `backend/tests/market/test_capture.py`
- Modify: `backend/tests/persistence/test_research_reader.py`

**Interfaces:**
- Consumes: `PublicMarketGateway`、`MarketRepository`、`PersistedMarketReader`、完整 `CandleSeries`。
- Produces: `MarketCaptureService.capture_symbol(symbol, captured_at) -> UUID`、`PersistedMarketReader.load_snapshot(snapshot_id)` 与 `calculate_market_structure(detail, captured_at) -> MarketStructure`。

- [ ] **Step 1: 写入按需快照和无未来数据泄漏的失败测试**

```python
def test_market_structure_excludes_candles_closing_after_capture_time() -> None:
    structure = calculate_market_structure(
        detail_with_future_bearish_candle(),
        captured_at=utc("2026-08-10T12:00:00Z"),
    )

    assert structure.trend_alignment[MarketTimeframe.H1] is TrendDirection.BULLISH
    assert all(zone.upper < Decimal("70000") for zone in structure.resistance_zones)
```

再覆盖：`capture_symbol` 只请求一个允许标的、只持久化该调用返回的已收盘 K 线、读取指定 snapshot ID 而非“最新”竞态；局部高低点区间使用 `Decimal`；缺少 20 根或 50 根已收盘 K 线时对应周期为 `unknown` 并降低置信度。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/market/test_capture.py tests/persistence/test_research_reader.py tests/agent/test_market_structure.py -q`

Expected: FAIL，因为没有单标的采集、按 ID 读取和 `MarketStructure` 计算器。

- [ ] **Step 3: 实现最小的确定性市场结构服务**

为 `MarketCaptureService` 新增 `capture_symbol`，让旧 `capture()` 继续按原有两标的行为调用该方法。为 `PersistedMarketReader` 增加 `load_snapshot(snapshot_id: UUID)`，并在 SQLAlchemy reader 中按 ID、标的和 UTC 载荷验证读取。

在 `market_structure.py` 实现以下不依赖 HTTP/ORM/LLM 的算法：

```python
def calculate_market_structure(
    detail: MarketDetail,
    *,
    captured_at: datetime,
) -> MarketStructure:
    closed = _closed_candles_before(detail, captured_at)
    trends = {series.timeframe: _trend_from_sma_20_50(series) for series in closed}
    zones = _cluster_pivot_zones(closed, tolerance=_atr14(closed) / Decimal("4"))
    return MarketStructure(trend_alignment=trends, support_zones=zones.support, resistance_zones=zones.resistance)
```

`_trend_from_sma_20_50` 只在至少 50 根已收盘 K 线时比较末端 `SMA20` 与 `SMA50`：`SMA20 > SMA50` 为 bullish，`SMA20 < SMA50` 为 bearish，其他为 neutral；数据不足为 unknown。局部低点/高点采用三根闭合 K 线窗口，价位聚类容忍度为该周期 `ATR14 / 4`，完全使用 `Decimal`。每个周期最多保留最近 3 个支撑和 3 个阻力，且支撑须低于当前价、阻力须高于当前价。

- [ ] **Step 4: 运行结构计算测试**

Run: `uv run pytest tests/market/test_capture.py tests/persistence/test_research_reader.py tests/agent/test_market_structure.py -q`

Expected: PASS；任何运行时刻之后的 K 线不会影响趋势或价位。

- [ ] **Step 5: 提交按需行情与价位计算**

```powershell
git add -- backend/src/app/market/capture.py backend/src/app/market/research.py backend/src/app/agent/market_structure.py backend/tests/market/test_capture.py backend/tests/persistence/test_research_reader.py backend/tests/agent/test_market_structure.py
git commit -m "feat: calculate agent market structure"
```

### Task 5: 实现受限 DeepSeek JSON 模型适配器

**Files:**
- Create: `backend/src/app/agent/model.py`
- Create: `backend/src/app/agent/prompt.py`
- Create: `backend/tests/agent/test_model.py`
- Create: `backend/tests/fixtures/agent/deepseek_completed.json`
- Create: `backend/tests/fixtures/agent/deepseek_invalid_evidence.json`

**Interfaces:**
- Consumes: `AppSettings`、`httpx.AsyncClient`、`MarketStructure`、冻结新闻/市场证据 ID。
- Produces: `ResearchLanguageModel.generate(request: ResearchModelRequest) -> AgentAnalysisProposal`，该端口不能表达 tools、函数调用或多轮历史。

- [ ] **Step 1: 写入模型请求边界的失败测试**

```python
async def test_deepseek_model_posts_one_json_request_without_tools() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=completed_response())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = DeepSeekResearchLanguageModel(client=client, api_key=SecretStr("test-key"), model="deepseek-v4-pro")

    proposal = await model.generate(request_with_evidence_ids("news-1", "market-1"))

    request = requests[0]
    assert request.url == "https://api.deepseek.com/chat/completions"
    assert request.json()["response_format"] == {"type": "json_object"}
    assert "tools" not in request.json()
    assert proposal.catalysts[0].evidence_ids == (UUID("00000000-0000-0000-0000-000000000001"),)
```

再覆盖：缺少 API Key 时不发送 HTTP 请求、`Authorization` 只在请求头中存在、系统提示包含单词 `JSON` 和 `UNTRUSTED_NEWS_CONTENT`、原始响应不写日志、空内容/无效 JSON/无效 schema 返回受控 `ModelOutputError`。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/agent/test_model.py -q`

Expected: FAIL，因为模型端口、提示构造器和 DeepSeek 适配器尚未实现。

- [ ] **Step 3: 实现一次性 JSON 适配器**

定义最小端口与请求对象：

```python
class ResearchLanguageModel(Protocol):
    async def generate(self, request: ResearchModelRequest) -> AgentAnalysisProposal: ...


class ResearchModelRequest(BaseModel):
    symbol: ContractSymbol
    structure: MarketStructure
    evidences: tuple[ModelEvidence, ...]
    horizon: Literal["1_to_3_days"] = "1_to_3_days"
```

`DeepSeekResearchLanguageModel` 只使用现有 `httpx.AsyncClient` 向固定 HTTPS 地址发出 `POST /chat/completions`，JSON body 固定含 `model`、两条 `messages`、`response_format={"type": "json_object"}`、受限 `max_tokens`；绝不发送 `tools`、`tool_choice`、历史对话或用户自由提示。系统提示要求仅返回 `AgentAnalysisProposal` JSON，所有实质结论引用提供的 UUID，且禁止行动性用语。将 `httpx.TimeoutException`、5xx、空 choices、空 content、JSON 解码失败和 Pydantic 校验失败映射为不含密钥/响应正文的错误码。

- [ ] **Step 4: 运行模型测试和静态检查**

Run: `uv run pytest tests/agent/test_model.py -q; uv run ruff check src/app/agent tests/agent; uv run pyright`

Expected: PASS；fixture 验证模型 API 契约，测试输出不显示 `test-key`。

- [ ] **Step 5: 提交模型边界**

```powershell
git add -- backend/src/app/agent/model.py backend/src/app/agent/prompt.py backend/tests/agent/test_model.py backend/tests/fixtures/agent
git commit -m "feat: add constrained deepseek research model"
```

### Task 6: 构建有界 LangGraph 并持久化终态报告

**Files:**
- Create: `backend/src/app/agent/contracts.py`
- Create: `backend/src/app/agent/graph.py`
- Create: `backend/src/app/agent/service.py`
- Create: `backend/src/app/news/service.py`
- Create: `backend/tests/agent/test_graph.py`
- Create: `backend/tests/agent/test_service.py`

**Interfaces:**
- Consumes: Task 2 的 `RssNewsSourceAdapter`/`NewsItemDraft`、Task 3 的 `AnalysisReportRepository`、Task 4 的按需市场快照/`MarketStructure`、Task 5 的 `ResearchLanguageModel`。
- Produces: `AgentResearchService.generate(symbol) -> PersistedAnalysisReport`；图使用 `analysis_id` 作为 LangGraph `thread_id`，且只返回 `completed` 或 `degraded` 终态报告。

- [ ] **Step 1: 写入图路由和降级的失败测试**

```python
async def test_graph_persists_degraded_report_without_model_when_market_is_stale() -> None:
    model = RecordingResearchModel()
    service = agent_service(market=StaleMarketCapture(), model=model)

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.DEGRADED
    assert model.requests == []
    assert "市场数据已过期" in report.risks[0]
```

再覆盖：正常路径冻结市场+去重新闻后只调用模型一次；单个新闻源失败继续并降低 `source_coverage`；全部新闻源失败生成“仅行情”完成报告并在限制中说明；模型空 JSON 重试一次后降级；模型引用未知 evidence ID 降级；图 state 与 checkpoint metadata 不包含标题、摘要、提示词、密钥或市场 JSON。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/agent/test_graph.py tests/agent/test_service.py -q`

Expected: FAIL，因为还没有 LangGraph、采集协调器或 Agent 服务。

- [ ] **Step 3: 实现固定图和最小状态**

`NewsIngestionService.collect(symbol, since, until)` 顺序执行获准来源，使用 `asyncio.gather(..., return_exceptions=True)` 隔离单源失败，调用 `NewsRepository.ingest_many()` 并返回本次不可变新闻快照。它不根据新闻文本决定抓取更多 URL。

在 `graph.py` 使用 `StateGraph[AgentRunState]` 建立固定节点：

```python
builder.add_edge(START, "collect_market")
builder.add_edge("collect_market", "collect_news")
builder.add_edge("collect_news", "compute_structure")
builder.add_conditional_edges("compute_structure", evidence_gate, {
    "model": "generate_model_report",
    "degraded": "persist_degraded_report",
})
builder.add_edge("generate_model_report", "validate_and_persist_report")
builder.add_edge("persist_degraded_report", END)
builder.add_edge("validate_and_persist_report", END)
```

`AgentRunState` 只允许 `analysis_id`、`symbol`、`started_at`、snapshot/evidence UUID、新闻覆盖计数、节点名和安全错误码；各节点需要的完整对象在 `AgentResearchDependencies` 的请求作用域内读取，节点返回给图的更新中不包含这些对象。`evidence_gate` 在关键行情缺失、数据过期、无已收盘周期或模型不可用时走降级路径；新闻完全失败不阻止仅行情报告。

`AgentResearchService.generate()` 为每次手动调用生成新的 UUID，并以 `{"configurable": {"thread_id": str(analysis_id)}}` 调用 `graph.ainvoke()`。用 `InMemorySaver` 测试图；生产 checkpointer 在 Task 7 注入。报告持久化用 Task 3 的单事务 `persist_agent()`，绝不修改既有报告。

- [ ] **Step 4: 运行图测试**

Run: `uv run pytest tests/agent/test_graph.py tests/agent/test_service.py -q`

Expected: PASS；每个失败分支都持久化受限 `degraded` 结果，且模型只在质量门放行后调用。

- [ ] **Step 5: 提交 LangGraph 编排**

```powershell
git add -- backend/src/app/agent/contracts.py backend/src/app/agent/graph.py backend/src/app/agent/service.py backend/src/app/news/service.py backend/tests/agent/test_graph.py backend/tests/agent/test_service.py
git commit -m "feat: orchestrate on-demand research agent"
```

### Task 7: 注入 PostgreSQL checkpoint、API 路由与安全错误语义

**Files:**
- Modify: `backend/src/app/shared/database.py`
- Modify: `backend/src/app/main.py`
- Modify: `backend/src/app/api/routes/analysis_reports.py`
- Modify: `backend/src/app/reports/contracts.py`
- Modify: `backend/tests/api/test_analysis_reports.py`
- Create: `backend/tests/api/test_agent_analysis_reports.py`
- Create: `backend/tests/security/test_agent_api_boundary.py`

**Interfaces:**
- Consumes: `AgentResearchService`、`AsyncPostgresSaver`、既有 `/api/v1/analysis-runs` wire contract。
- Produces: 注入式 `app.state.analysis_report_service`、`agentAnalysis`/`generatorKind` 响应字段、稳定的 completed/degraded API 和仅终态 SSE。

- [ ] **Step 1: 写入应用组合和 API 的失败测试**

```python
@pytest.mark.asyncio
async def test_analysis_post_returns_agent_detail_without_exposing_model_configuration() -> None:
    app = _app(AgentResearchService(fake_dependencies()))

    response = await _request(app, "POST", "/api/v1/analysis-runs", {"symbol": "BTCUSDT"})
    detail = await _request(app, "GET", f"/api/v1/analysis-runs/{response.json()['reportId']}")

    assert detail.json()["generatorKind"] == "langgraph_deepseek"
    assert detail.json()["agentAnalysis"]["horizon"] == "1_to_3_days"
    assert "deepseek" not in detail.text.lower()
    assert "api_key" not in detail.text.lower()
```

再覆盖：无 API Key 返回已持久化 `degraded` 而非 500；非法标的 422；单一媒体事件保留来源层级；详情响应的每个 `evidenceId` 属于当前报告；SSE 只发送一条终态事件；路由和 `main.py` 源码不存在 `create_order`、`fetch_balance`、`tools=` 或浏览器外部 URL。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/api/test_analysis_reports.py tests/api/test_agent_analysis_reports.py tests/security/test_agent_api_boundary.py -q`

Expected: FAIL，因为应用尚未组合 Agent 服务、响应模型没有 Agent 字段。

- [ ] **Step 3: 组合生产依赖并扩展 API**

在 `database.py` 添加只在内存中将 `postgresql+asyncpg://` 转换为 `postgresql://` 的 helper，供 `AsyncPostgresSaver.from_conn_string()` 使用；不得记录转换后的连接串。在 `main.py` 的 lifespan 中创建 `AsyncPostgresSaver`、运行一次 `await checkpointer.setup()`、编译图、在关闭时退出 saver。数据库未配置时注入会生成 `degraded` 的不可用服务，不启动模型网络请求。

让 `create_app()` 接受可选 `agent_research_service` 依赖，测试直接注入 fake。将 `get_analysis_report_service()` 的静态类型扩展为共同的 `AnalysisReportService` Protocol。扩展响应模型：

```python
class AnalysisReportSummaryResponse(_ApiModel):
    generator_kind: ReportGeneratorKind


class AnalysisReportDetailResponse(AnalysisReportSummaryResponse):
    agent_analysis: AgentAnalysisResponse | None
```

沿用当前 `POST`、列表、详情、重试和 SSE 路径。详情/列表映射只输出已验证的明细，不输出模型名、供应商、错误原文、源 XML 或新闻原文。

- [ ] **Step 4: 运行 API 与应用组合测试**

Run: `uv run pytest tests/api/test_analysis_reports.py tests/api/test_agent_analysis_reports.py tests/security/test_agent_api_boundary.py -q; uv run ruff check src/app tests/api tests/security; uv run pyright`

Expected: PASS；测试没有真实 DeepSeek/RSS 网络请求，缺少密钥的业务结果为可审计降级报告。

- [ ] **Step 5: 提交 API 和 checkpoint 组合**

```powershell
git add -- backend/src/app/shared/database.py backend/src/app/main.py backend/src/app/api/routes/analysis_reports.py backend/src/app/reports/contracts.py backend/tests/api backend/tests/security/test_agent_api_boundary.py
git commit -m "feat: expose on-demand agent reports"
```

### Task 8: 接通前端领域契约、HTTP 映射与报告展示

**Files:**
- Modify: `frontend/src/domain/report.ts`
- Modify: `frontend/src/shared/api/workbench-api.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.ts`
- Modify: `frontend/src/shared/api/report-http.test.ts`
- Modify: `frontend/src/shared/api/hybrid-workbench-api.ts`
- Modify: `frontend/src/shared/api/mock-workbench-api.ts`
- Modify: `frontend/src/features/reports/ReportGenerator.tsx`
- Modify: `frontend/src/features/reports/ReportDetailPage.tsx`
- Modify: `frontend/src/features/reports/ReportPages.test.tsx`
- Create: `frontend/src/test/research-agent-boundaries.test.tsx`

**Interfaces:**
- Consumes: Task 7 的 camelCase API 响应、既有 `WorkbenchApi.startReport/getReport/listReports`。
- Produces: Zod 校验后的 `generatorKind`/`agentAnalysis`，以及显示来源、数据质量、支撑阻力、催化与失效条件的只读报告页面。

- [ ] **Step 1: 写入前端契约与可访问性失败测试**

```tsx
it("renders the one-to-three-day agent analysis with cited catalysts and no trade action", async () => {
  renderReportDetail(new AgentReportApi());

  expect(await screen.findByRole("region", { name: "未来 1–3 天市场研判" })).toHaveTextContent("看涨");
  expect(screen.getByRole("region", { name: "关键支撑与阻力" })).toHaveTextContent("67,200");
  expect(screen.getByRole("region", { name: "潜在催化事件" })).toHaveTextContent("已确认公告");
  expect(screen.queryByText(/买入|卖出|开仓|仓位|杠杆|止损/)).not.toBeInTheDocument();
});
```

在 `report-http.test.ts` 中验证 HTTP detail 的 `generatorKind: "langgraph_deepseek"`、十进制字符串价位、`agentAnalysis` 可空字段与 `evidenceIds` 经 Zod 解析；为旧 deterministic fixture 保留 `generatorKind: "deterministic"` 和 `agentAnalysis: null`。

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run test -- --run src/shared/api/report-http.test.ts src/features/reports/ReportPages.test.tsx src/test/research-agent-boundaries.test.tsx`

Expected: FAIL，因为领域 schema 和页面尚未识别 Agent 明细。

- [ ] **Step 3: 实现最小前端映射和只读展示**

在 `domain/report.ts` 添加严格 Zod schema：

```ts
const priceZoneSchema = z.object({
  lower: decimalStringSchema,
  upper: decimalStringSchema,
  timeframe: timeframeSchema,
  rationale: z.string().min(1).max(1_000),
});

const agentAnalysisSchema = z.object({
  horizon: z.literal("1_to_3_days"),
  outlook: z.enum(["bullish", "bearish", "neutral"]),
  confidence: z.enum(["low", "medium", "high"]),
  supportZones: z.array(priceZoneSchema),
  resistanceZones: z.array(priceZoneSchema),
  catalysts: z.array(catalystSchema),
  risksAndInvalidation: z.array(riskSchema),
  dataQuality: dataQualitySchema,
});
```

扩展 summary/detail schema 与 HTTP/Hybrid/Mock API；Mock 为现有 fixture 显式返回 deterministic/null，不伪造实时新闻。`ReportGenerator` 的按钮文案更新为“抓取公开行情与英文新闻并分析”，但继续调用相同受类型保护的 `startReport`。`ReportDetailPage` 仅当 `agentAnalysis` 存在时渲染四个有标签区域：未来 1–3 天市场研判、关键支撑与阻力、潜在催化事件、风险与失效条件；每个催化条目只链接本报告中已有的不可变证据。无 Agent 明细时保留现有确定性报告布局。

- [ ] **Step 4: 运行前端范围验证**

Run: `npm run lint; npm run typecheck; npm run test -- --run src/shared/api/report-http.test.ts src/features/reports/ReportPages.test.tsx src/test/research-agent-boundaries.test.tsx`

Expected: PASS；浏览器不含外部 RSS/DeepSeek 请求或交易行动入口。

- [ ] **Step 5: 提交前端报告集成**

```powershell
git add -- frontend/src/domain/report.ts frontend/src/shared/api frontend/src/features/reports/ReportGenerator.tsx frontend/src/features/reports/ReportDetailPage.tsx frontend/src/features/reports/ReportPages.test.tsx frontend/src/test/research-agent-boundaries.test.tsx
git commit -m "feat: display agent market research"
```

### Task 9: 完成安全回归、运行文档与受控本地验收

**Files:**
- Modify: `docs/operational-boundaries.md`
- Modify: `docs/local-deployment.md`
- Create: `backend/tests/security/test_agent_source_and_secret_safety.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: 已完成的 Agent、来源注册表、Compose 本地 API 与前端报告页。
- Produces: 可审计的操作说明、源码级安全防线和全量质量验证记录；不在此任务中写入密钥或执行真实模型调用。

- [ ] **Step 1: 写入安全扫描和文档断言的失败测试**

```python
def test_agent_sources_are_allowlisted_and_cannot_enable_social_or_full_page_fetch() -> None:
    source = Path("src/app/news/rss.py").read_text(encoding="utf-8")

    assert "coindesk" in source
    assert "sec_press_releases" in source
    assert "telegram" not in source.lower()
    assert "discord" not in source.lower()
    assert "follow_redirects=True" not in source
```

再扫描 `src/app/agent` 与 `src/app/news`，拒绝 `create_order`、`cancel_order`、`fetch_balance`、`fetch_positions`、`tools=`、`tool_choice`、`OPENAI_API_KEY`、`DEEPSEEK_API_KEY` 的日志调用和 `BeautifulSoup`/浏览器自动化导入。允许配置字段名称本身，但测试不得打印其值。

- [ ] **Step 2: 运行安全测试确认失败**

Run: `uv run pytest tests/security/test_agent_source_and_secret_safety.py -q`

Expected: FAIL，因为专项安全扫描和运行文档尚未建立。

- [ ] **Step 3: 实现操作文档与安全测试**

在 `operational-boundaries.md` 写明：仅手动分析、仅公开行情/英文许可来源、模型无工具、报告非投资或交易指令、真实交易始终关闭。`local-deployment.md` 写明：DeepSeek 密钥只由用户在未跟踪本地环境提供；密钥缺失产生降级报告；不要在命令、日志或截图中显示密钥；停止服务仅使用 `docker compose down` 并保留数据卷。根 README 补充入口按钮、数据来源级别、1–3 天报告语义和非目标。

安全扫描仅查看应用源文件，不扫描文档、历史、虚拟环境、lock 文件或用户 `.env`，避免将用户数据读入测试输出。

- [ ] **Step 4: 运行完整验证**

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

Set-Location ..
git diff --check
```

Expected: 所有命令退出码为 0；测试不访问真实新闻、DeepSeek 或交易所私有端点。真实公开源/DeepSeek 的本地手动验收必须等待用户提供运行时密钥并在下一轮明确授权。

- [ ] **Step 5: 提交验证文档与安全门**

```powershell
git add -- docs/operational-boundaries.md docs/local-deployment.md README.md backend/tests/security/test_agent_source_and_secret_safety.py
git commit -m "docs: record agent research boundaries"
```
