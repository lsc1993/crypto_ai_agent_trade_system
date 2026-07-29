# 市场研究数据持久化设计

## 目标

为已接入的币安 USDⓈ-M 公开行情建立可复现、可审计的 PostgreSQL 研究数据基础：保存已收盘 K 线、市场/衍生品观测，以及供后续回测和研究报告使用的不可变市场快照。首期只支持 `BTCUSDT`、`ETHUSDT` 和 `15m`、`1h`、`4h`、`1d`。

## 决策与影响

采用 PostgreSQL 17、SQLAlchemy 2.x 异步 ORM、`asyncpg` 与 Alembic。该选择与项目既有架构一致，新增三个生产依赖，并引入首个数据库迁移。运行时连接只通过 `DATABASE_URL` 获取；集成测试只通过独立的 `TEST_DATABASE_URL` 获取。两条连接串都不得写入日志、异常响应、测试断言或提交内容。

本设计不改变现有 `GET /api/v1/markets` 与 `GET /api/v1/market/{symbol}` 的公开行情读取方式。它们在本阶段继续直接从受限的公开数据网关读取，避免一次变更同时切换数据来源和存储行为。

## 范围与非范围

范围内：

- 保存规范化的已收盘 K 线、价格、资金费率、未平仓量、24 小时变化和成交量观测。
- 保存不可变、大小受限、带哈希的市场快照。
- 提供一次性公开行情采集命令，用于手动验证持久化链路。
- 使用迁移、仓储和测试保证数据类型、去重、时间和事务边界。

明确不在范围内：

- 账户、余额、仓位、订单、成交、订单簿、逐笔成交或交易所私有接口。
- API Key、Secret、Passphrase、私钥或真实交易能力。
- 常驻 WebSocket worker、回测引擎、策略、风控或前端读库切换。
- 自动清理、删除或归档开发数据库中的市场数据。

## 架构

```text
受限 Binance 公开 GET 网关
            |
            v
MarketCaptureService
  - 固定标的与周期
  - UTC/Decimal 类型校验
  - 过滤未收盘 K 线
            |
            v
MarketRepository port
            |
            v
SQLAlchemy async repository -- PostgreSQL
  market_candles
  derivative_observations
  market_snapshots
```

`MarketCaptureService` 复用现有 `PublicMarketGateway`，分别取得两个受支持标的的市场详情。每次采集使用一个 UTC `captured_at`，只接受 `close_at <= captured_at` 的 K 线。它从 `MarketSummary` 导出市场/衍生品观测，并在单一数据库事务中写入 K 线、观测和一条快照。网关、类型校验或数据库写入任一环节失败时，事务整体回滚，命令以非零退出码结束。

现有 API 服务不在启动时主动连接数据库；数据库连接只在手动采集命令或后续明确接入的持久化用例中创建。这样本地公开行情页面不会因数据库暂时不可用而退化。

## 数据模型

所有金额、价格、数量、费率和计量值使用 `NUMERIC(38,18)`；所有时间使用 `TIMESTAMPTZ`；应用层分别映射到 `Decimal` 和带 UTC 时区的 `datetime`。

### `market_candles`

保存规范化 OHLCV 数据：`symbol`、`timeframe`、`open_at`、`close_at`、`open_price`、`high_price`、`low_price`、`close_price`、`volume`、`source`、`observed_at`、`fetched_at`、`created_at`、`updated_at`。

- `symbol` 仅允许 `BTCUSDT` 与 `ETHUSDT`；`timeframe` 仅允许四个受支持周期。
- 唯一约束为 `(symbol, timeframe, open_at)`，索引为 `(symbol, timeframe, open_at DESC)`。
- 采集重复运行时按该唯一键幂等 upsert；可更新标准化数值和 `fetched_at`，并保留首次写入的 `created_at`。
- 应用层拒绝非 UTC、浮点数、负数、价格区间非法或尚未收盘的 K 线。

### `derivative_observations`

保存 `symbol`、`metric_type`、`value`、`source`、`observed_at`、`fetched_at`、`created_at`。`metric_type` 仅允许 `price`、`funding_rate`、`open_interest`、`change_24h` 与 `volume_24h`；唯一约束为 `(symbol, metric_type, observed_at, source)`，索引为 `(symbol, observed_at DESC)`。

重复观测按唯一键忽略，避免重试或重复采集制造事实重复。各观测的单位由 `metric_type` 固定解释；不会将不同单位写入同一值。

### `market_snapshots`

保存 `id`（UUID）、`symbol`、`source`、`captured_at`、`data_as_of`、`data_version`、`payload`（JSONB）、`payload_sha256` 和 `created_at`。

- 每次成功采集每个标的产生一条新快照；快照不更新、不删除。
- `data_as_of` 是该快照内所有观测和 K 线 `observed_at` 的最早时间；各字段的原始时间仍保留在快照载荷中，因此它是安全的整体新鲜度下界。
- `payload` 只保存已规范化的十进制字符串、UTC 时间、来源、K 线和观测；不保存交易所原始完整响应、HTML、凭证或账户数据。
- 载荷序列化后的 UTF-8 大小上限为 64 KiB，并用 SHA-256 计算 `payload_sha256`。数据库与应用层都执行此上限。
- 对 `payload` 的任何修改或删除都不提供仓储方法；数据库角色的 DDL/DML 权限仍由部署方管理。

## 模块边界

- `app.shared.database`：创建不泄露连接串的 async engine、session factory 与事务边界。
- `app.infrastructure.persistence`：SQLAlchemy 元数据、模型、Alembic 接入和 PostgreSQL 仓储实现。
- `app.market.repository`：面向应用层的窄仓储协议和 DTO；不暴露 ORM 模型。
- `app.market.capture`：只读公开数据采集与校验用例；不包含 HTTP、SQL 或交易逻辑。
- `scripts.capture_market_snapshot`：显式手动入口，调用采集服务；不启动常驻任务，不接触私有交易所 API。

仓储写入只接受已验证的领域 DTO。业务代码不得直接导入 SQLAlchemy 模型；API 路由不得直接读写数据库。

## 错误与安全行为

- 上游公开数据不可用、响应结构非法、包含未收盘 K 线或违反数值/时间约束时，不创建快照且不提交任何该次采集的写入。
- 数据库连接、迁移或约束失败时，异常被归类为持久化失败；日志仅记录操作类别、标的、周期、状态和关联 ID，不记录连接串、完整上游载荷或凭证。
- 手动命令仅可调用现有白名单内的 Binance USDⓈ-M `GET` 端点；它不能创建、取消或修改订单，也不会读取账户信息。
- `TEST_DATABASE_URL` 永远只用于测试夹具。集成测试对独立测试数据库使用临时 schema，结束后仅删除该临时 schema，绝不连接或清理 `DATABASE_URL` 指向的开发数据库。

## 验证策略

先编写测试，再实现：

- 单元测试：`Decimal`／UTC 映射、支持范围限制、未收盘 K 线过滤、快照哈希与 64 KiB 上限。
- 仓储集成测试：Alembic 迁移、K 线幂等 upsert、观测去重、快照只插入、事务回滚和临时测试 schema 隔离。
- 服务测试：受控假网关的成功采集与任一数据类别失败时的整体回滚。
- 安全回归测试：模块中不得出现私有交易所方法或凭证字段；异常和日志断言不得含连接串。

实现完成后，从 `backend` 目录运行：

```powershell
uv run ruff check .
uv run pyright
uv run pytest
uv run alembic upgrade head
uv run python scripts/capture_market_snapshot.py
```

前三项在代码和测试层验证；迁移命令只作用于 `DATABASE_URL` 指向的开发数据库；手动采集命令只进行公开只读请求并写入开发数据库。任何一项失败时，不继续进入回测、策略、风控或模拟执行阶段。
