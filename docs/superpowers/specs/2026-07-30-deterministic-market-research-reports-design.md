# 确定性市场研究报告设计

## 目标

在不接入模型、账户、私有交易所 API 或任何下单能力的前提下，为 BTCUSDT 和 ETHUSDT 生成可审计、可复核的市场研究报告。报告只使用 PostgreSQL 中已经持久化的公开市场研究数据，并冻结生成时使用的证据。

## 范围与非目标

本期提供报告的手动生成、持久化列表与详情读取、重试，以及一次性 SSE 状态回放。

本期不提供 LangGraph、LLM、OpenAI 配置、后台常驻 Worker、资讯抓取、个人交易统计、账户查询、交易信号、仓位/杠杆建议、下单或自动化交易。不会读取、写入或展示 `.env` 内容。

## 方案选择

采用同步、持久化的确定性生成方案。`POST` 在一个有限的请求中读取、冻结并生成报告后再返回；报告已完成或降级，因此按需启动的 Docker 环境不需要保活后台任务。浏览器随后订阅 SSE 时，服务从持久化状态发送唯一的最终事件并关闭连接。

该方案优于仅在内存中临时返回报告，因为报告和证据可以被历史列表、详情页和后续复盘引用；也避免了当前不需要的任务队列、恢复机制、模型依赖与常驻服务。

## 数据模型与迁移

新增 Alembic `0003_create_analysis_reports.py`，创建以下表。

### `analysis_reports`

- `id`：UUID，报告标识。
- `analysis_id`：UUID，唯一的生成运行标识。
- `symbol`：仅允许 `BTCUSDT`、`ETHUSDT`。
- `status`：仅允许 `completed`、`degraded`。
- `title`、`summary`：长度受限的中文展示文本。
- `facts`、`inferences`、`risks`、`limitations`：受限 JSONB 字符串数组。
- `generated_at`：UTC 生成时间。
- `data_cutoff_at`：UTC 的实际证据截止时间；若无法读取任何持久化研究数据则为 `NULL`。
- `created_at`：UTC 数据库创建时间。

`analysis_id` 唯一，且建立 `(symbol, created_at DESC)` 和 `status` 索引。报告生成后不更新或删除。

### `analysis_evidences`

- `id`：UUID，证据标识。
- `analysis_report_id`：引用 `analysis_reports.id` 的外键。
- `symbol`、`source`、`source_url`。
- `observed_at`、`fetched_at`：UTC 来源时间。
- `summary`：长度受限的纯文本说明。
- `payload`：受限 JSONB 冻结快照，保存报告所使用的市场摘要和每个请求周期的最新已收盘 K 线。
- `payload_sha256`：规范化 JSON 的小写 SHA-256。
- `created_at`：UTC 数据库创建时间。

迁移为两个表安装 PostgreSQL `BEFORE UPDATE OR DELETE` 触发器，使证据和报告在数据库层不可改、不可删；仓储层只公开插入与读取方法。测试使用独立 `TEST_DATABASE_URL` 临时 schema 验证该行为。

## 生成与降级逻辑

`DeterministicResearchReportService` 依赖现有 `PersistedMarketReader`，不依赖 `PublicMarketGateway`。每次手动请求：

1. 读取指定标的最新快照，以及 `15m`、`1h`、`4h`、`1d` 各最多 200 根持久化 K 线；只选择每个周期最后一根已收盘 K 线作为证据。
2. 将摘要、最新 K 线、观测时间、抓取时间和来源规范化为不可变证据；计算 SHA-256 后在同一事务中插入证据和报告。
3. 仅按确定性模板生成事实、有限的非交易性推断、风险与限制。推断只能描述趋势一致性、数据新鲜度或数据缺口，不能出现价格预测、买卖、开仓、仓位、杠杆、止损、收益保证或等价表述。
4. 当任一必要周期缺失、快照缺失、快照过期两分钟以上或读取发生 `MarketDataUnavailableError` 时，创建 `degraded` 报告。它不包含市场结论；风险至少说明数据过期或缺失，限制说明原因。完全缺失时 `data_cutoff_at` 为 `NULL`。

生成服务从不调用 Binance、HTTP 市场网关或任何账户/交易接口。持久化读取失败不会尝试网络回退。

## HTTP 契约

所有路由位于 `/api/v1`，沿用标准错误 envelope。

- `POST /analysis-runs`：请求体只含允许的 `symbol`；生成并持久化报告后返回 `201 { "analysisId": "<UUID>" }`。
- `GET /analysis-runs`：支持现有 `page`、`page_size`、`symbol`、`status` 过滤，返回报告摘要分页。
- `GET /analysis-runs/{report_id}`：返回完整报告和冻结证据；未知 ID 返回稳定的 404 envelope。
- `POST /analysis-runs/{report_id}/retry`：读取原报告标的，创建新的 `analysisId` 和新报告；不修改原报告或证据。
- `GET /analysis-runs/{analysis_id}/events`：以 `text/event-stream` 发送一条已持久化的 `completed` 或 `degraded` 状态事件后关闭；未知 ID 返回稳定的 404 envelope。

响应字段保持前端 `AnalysisReport`、`AnalysisReportSummary`、`AnalysisEvidence` 和 `AnalysisStreamEvent` 的 camelCase 形状。`dataCutoffAt` 改为可空；前端在为空时展示“无可用数据”。证据来源 URL 固定为不发起请求的公开 Binance 站点链接，仅用于来源标注。

## 前端集成

保持现有报告列表、详情、生成器、重试按钮和 `WorkbenchApi` 方法签名。

`HttpWorkbenchApi` 实现报告列表、详情、创建、重试和 SSE 订阅；`HybridWorkbenchApi` 与 `MockWorkbenchApi` 不改变其现有行为。选择 `VITE_DATA_MODE=api` 时，报告页面使用真实 HTTP 路由；选择 `market-api` 或 `mock` 时继续使用 Mock 报告数据。

报告详情中空的 `dataCutoffAt` 显示为“无可用数据”，并继续明确状态、风险、限制与证据。页面不新增交易行动、策略信号或模型配置入口。

## 错误处理和安全边界

- 参数范围外的标的、状态和分页值由 FastAPI 返回既有 422 envelope。
- 不存在报告或分析运行返回既有 404 envelope。
- 能读取数据库但市场证据不足时，返回并保存 `degraded` 报告，而非伪造事实。
- 数据库本身不可用、无法持久化报告或违反不可变约束时，只返回既有安全 500 envelope；不暴露连接 URL、SQL、异常正文或任何配置值。
- 测试、日志和响应中不包含凭证、数据库 URL、原始未受限载荷、账户信息或交易功能。

## 测试与验收

测试先行覆盖：证据和报告不可修改/不可删除、哈希与 UTC 校验、完整数据的确定性 `completed` 报告、过期/缺失数据的 `degraded` 报告、绝不调用实时网关、API 分页/详情/重试/SSE 契约，以及前端 HTTP 映射和空数据截止时间展示。

验收命令：

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
```

所有测试仅使用 fake reader、受控 fixture 和 `TEST_DATABASE_URL` 临时 schema；不执行公开网络请求、模型请求、迁移到用户开发数据库或任何交易动作。
