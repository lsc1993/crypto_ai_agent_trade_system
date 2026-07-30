# 持久化市场研究数据读取设计

**状态：已确认**
**日期：2026-07-30**

## 目标

在不改变现有 Binance 实时市场接口的前提下，将已持久化到 PostgreSQL 的 BTCUSDT、ETHUSDT 公开研究数据提供给前端工作台。读取接口只返回标准化摘要、已收盘 K 线和新鲜度，不提供原始交易所载荷、账户信息或交易能力。

## 方案选择

采用独立的持久化研究数据路由：

```text
GET /api/v1/research/markets
GET /api/v1/research/market/{symbol}
```

它们与现有的 `GET /api/v1/markets`、`GET /api/v1/market/{symbol}` 保持并存。原有路由继续经受限 Binance 公开网关读取实时数据；新路由只读取数据库。前端以显式环境变量选择市场数据来源，默认仍使用实时路由。

本方案避免了把“实时”与“已采集研究数据”混为同一语义，也避免在数据库暂时没有数据时悄悄回退为 Mock 行情。

## 范围与非范围

范围内：

- 在 PostgreSQL 已有的 `market_candles`、`derivative_observations`、`market_snapshots` 上建立只读查询实现。
- 复用当前 `MarketSummary`、`MarketDetail`、`CandleSeries` 和 `DataFreshness` 的 HTTP/前端契约。
- 从最新不可变快照恢复市场摘要，从 K 线表读取指定周期的已收盘 K 线。
- 按最新快照的抓取时间计算 `fresh` 与 `stale`，并在没有完整数据时返回明确的不可用错误。
- 新增 `VITE_MARKET_DATA_SOURCE=live|research`，让市场卡片与市场详情在不修改页面组件的情况下切换请求路径。

明确不在范围内：

- 修改现有实时路由的行为、增加自动回退、合并实时与持久化数据或修改前端页面领域模型。
- 新增依赖、数据库迁移、写入、数据补齐、常驻 worker、WebSocket、新闻、LLM、账户、订单或任何交易所私有 API。
- 返回快照完整 JSONB 载荷、数据库 ORM 模型、数据库连接串或交易所原始响应。

## 架构与数据流

```text
React 页面
    │ WorkbenchApi + VITE_MARKET_DATA_SOURCE
    ├──────── live ────────► /api/v1/market… ─► Binance 公开网关
    │
    └────── research ─────► /api/v1/research/market…
                                      │
                                      ▼
                         PersistedMarketReader port
                                      │
                                      ▼
                           SQLAlchemy 只读适配器
                                      │
                                      ▼
             market_snapshots + market_candles + derivative_observations
```

`PersistedMarketReader` 是应用层只读协议。其 SQLAlchemy 实现创建短生命周期异步 session，只执行 `SELECT`，并将记录转换为现有 Pydantic 市场 DTO；路由、前端和 Agent 后续都不导入 ORM 模型。

应用工厂在 `DATABASE_URL` 已配置时创建研究数据 reader 及其 engine，并在 FastAPI lifespan 结束时关闭 engine。未配置数据库时，研究路由仍存在，但稳定返回 `market_research_unavailable`，不会尝试连接数据库或回退到实时数据。现有实时网关和其 HTTP client 生命周期不变。

## 查询与接口语义

### 市场摘要

`GET /api/v1/research/markets?symbols=BTCUSDT&symbols=ETHUSDT` 接受与现有实时摘要路由相同的标的枚举、去重规则和数量上限，并返回相同的 `{ "items": [...] }` 形状。

对每个标的，reader 选择 `captured_at` 最新的 `market_snapshots` 记录，读取其标准化 `payload.summary`，并用 `MarketSummary` 重新校验。摘要中的价格、24 小时变化、成交量、资金费率、未平仓量、来源、观测时间和抓取时间都以快照中的受控值为准。

请求中的任一标的没有快照、快照载荷不符合受控摘要形状、或数据不属于允许标的时，整个请求返回稳定的 `503` 错误信封：`{ "code": "market_research_unavailable", "message": "持久化市场研究数据不可用", "details": {} }`。不会用旧 Mock 或实时网关数据补齐。

### 市场详情

`GET /api/v1/research/market/{symbol}?timeframes=15m&timeframes=1h` 接受与现有实时详情路由相同的标的、周期枚举、去重规则和最多四个周期限制，并返回相同的 `MarketDetail` 形状。

摘要按上述快照规则读取。对每个请求周期，reader 以 `open_at` 降序读取最近 200 根 `market_candles`，再按升序转换为 `CandleSeries`。只返回已经持久化的 K 线；不查询交易所，也不根据当前时间生成或修改 K 线。

任一请求周期没有 K 线时返回同一 `market_research_unavailable` 错误。`news` 在此阶段固定为空数组，保留既有前端契约。

## 新鲜度规则

以最新快照的 `captured_at` 与注入的 UTC 时钟比较：

- 间隔小于或等于 2 分钟：摘要 `freshness.status` 为 `fresh`。
- 间隔超过 2 分钟：摘要 `freshness.status` 为 `stale`，其余最后成功数据保持可读。
- 没有快照、载荷无效、数据库未配置或查询失败：不构造伪造的 `missing`／`failed` 摘要，返回 `market_research_unavailable` 错误。

响应保留快照中原始的 `source`、`observed_at`、`fetched_at`；只有 `status` 由 reader 重新计算。时间必须仍是 UTC 带时区值，数值必须仍是 `Decimal`。

## 前端切换

`VITE_MARKET_DATA_SOURCE` 的合法值为：

- `live`：默认值。`HttpWorkbenchApi` 保持调用现有 `/api/v1/markets` 与 `/api/v1/market/{symbol}`。
- `research`：`HttpWorkbenchApi` 使用 `/api/v1/research/markets` 与 `/api/v1/research/market/{symbol}`。

该变量只影响市场摘要和市场详情的路径选择。`VITE_DATA_MODE=mock` 时仍完全使用 Mock；`market-api` 时仍由 `HybridWorkbenchApi` 仅将市场数据交给 HTTP；`api` 时其余未实现的业务端点继续按当前行为报告 unavailable。`research` 不会改变浏览器页面、Zod schema、报告、交易、分析或设置的数据来源。

## 模块边界

- `app.market.research`：定义只读 DTO/协议、查询服务和新鲜度计算；不导入 SQLAlchemy。
- `app.infrastructure.persistence.research_reader`：实现 `PersistedMarketReader`；唯一读取 ORM 模型的应用适配器。
- `app.api.routes.research_market`：解析和校验 HTTP 参数，调用研究 reader，复用现有市场响应模型与错误信封。
- `app.main`：在数据库配置存在时组合 reader，并管理其 engine 生命周期。
- `frontend/src/shared/config/env.ts`：校验市场数据来源变量并提供默认值。
- `frontend/src/shared/api/http-workbench-api.ts`：按来源构造市场读取路径；不改变 `WorkbenchApi` 接口。

## 错误与安全行为

- reader 只执行数据库 `SELECT`，不调用采集、迁移、交易所网关或任何写入方法。
- 数据库错误只映射为稳定不可用错误；日志若存在，只记录错误类别与请求范围，不能记录连接串、SQL 参数、完整快照载荷或凭证。
- 路由、reader、仓储和前端静态安全测试不得出现账户、订单、余额、仓位、杠杆、转账、提现或私有交易所能力。
- 所有 API 数字继续序列化为十进制字符串，时间继续序列化为 UTC RFC3339 `Z` 字符串。

## 验证策略

先写失败测试，再实现：

- reader 集成测试在 `TEST_DATABASE_URL` 的临时 schema 写入受控批次后，验证最新快照选择、200 根上限、时间升序、`fresh`／`stale` 转换和缺数据错误。
- API 测试以假 reader 验证新路径与既有 `MarketDetail` JSON 契约一致、非法参数保留现有验证信封、reader 不可用返回稳定 503。
- 前端 Vitest 测试验证默认 `live` 路径、`research` 路径、环境变量拒绝非法值，以及 `market-api` 混合模式不改变非市场 Mock 行为。
- 回归测试验证现有实时市场 API 路由、数据模式和安全边界行为不变。

完成后运行：

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

测试不执行公开网络请求；本阶段不运行迁移或真实采集命令，因为没有 schema 或采集逻辑变更。
