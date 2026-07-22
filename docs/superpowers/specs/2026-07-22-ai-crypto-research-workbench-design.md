# AI 加密合约交易研究工作台：首期设计规格

**状态：已确认**
**日期：2026-07-22**

## 1. 项目定位

本项目是面向个人、本地部署的加密合约交易**研究、记录与复盘工作台**。首期聚焦币安 USDⓈ-M Futures 的 BTCUSDT、ETHUSDT，帮助用户集中查看市场信息、资讯、个人交易记录和 AI 分析报告。

系统的目标是提升交易研究与复盘的质量、可追溯性和纪律性，而不是承诺提高胜率或预测确定走势。

## 2. 首期范围

### 2.1 需要实现

- BTCUSDT、ETHUSDT 永续合约的公开市场数据展示。
- 以 15m、1h、4h、1d 为主的短期与中期市场观察。
- 新闻与事件聚合、去重、来源、时间和关联标的标记。
- 手动录入、编辑、查询和持久化个人合约交易记录。
- 分批开仓、减仓、平仓、手续费和资金费的交易记录与净盈亏计算。
- 交易胜率、净利润、盈亏比、期望值、最大回撤、利润曲线和交易日历等基础复盘统计。
- 基于 LangGraph 的单一研究 Agent，输出带证据、时间戳、风险和不确定性的结构化市场分析报告。
- Docker Compose 本地部署与本地数据持久化。

### 2.2 明确不实现

- 自动下单、撤单、账户写权限、资金划转或提现。
- 币安账户、持仓、订单和个人成交历史的 API 同步。
- 未经独立验证的技术面交易策略、策略评分、参数寻优或自动回测。
- 多交易所、多用户、移动端完整交易终端、高频或盘口级交易分析。

## 3. 关键原则

- **人工决策**：系统只提供研究信息与分析报告，所有真实交易由用户在外部手动执行。
- **事实与推断分离**：行情、资讯和用户统计必须带来源及时间；Agent 的文字结论必须标记为推断。
- **可复盘**：报告生成时的市场与资讯证据保存为不可变快照，后续行情变化不能改写历史报告。
- **数据缺失优先披露**：关键数据过期、缺失或接口失败时，报告生成降级结果，禁止模型猜测填补数值。
- **最小权限**：首期不保存币安 API Key；任何未来只读账户同步也必须使用独立、无交易和无提现权限的密钥。
- **策略后置**：策略层仅定义未来接口，不作为首期 Agent 的证据输入。

## 4. 用户与市场范围

- 单用户、本地部署。
- 币安 USDⓈ-M Futures。
- 交易标的：BTCUSDT、ETHUSDT 永续合约。
- 首期周期：15 分钟、1 小时、4 小时、1 天。
- 所有持久化时间使用 UTC；前端默认显示 Asia/Shanghai 时区。

## 5. 前端信息架构

界面采用桌面端优先的交易研究工作台：深色主题默认、信息密度适中、所有分析结果均可追溯来源与数据截止时间。

```text
应用
├── 仪表盘
├── 市场分析
│   ├── BTCUSDT 永续
│   └── ETHUSDT 永续
├── AI 分析报告
├── 交易日志
├── 复盘统计
└── 设置
```

| 页面 | 主要内容 |
|---|---|
| 仪表盘 | BTC/ETH 价格、涨跌、成交量、资金费率、未平仓量、资讯摘要、最近报告与数据更新时间 |
| 市场分析 | 标的切换、15m/1h/4h/1d 图表、衍生品数据、资讯时间线、数据新鲜度与报告入口 |
| AI 分析报告 | 手动触发、报告正文、证据引用、风险提示、置信度、历史报告对比 |
| 交易日志 | 新增、编辑、查询、筛选交易，关联报告、截图、入场理由、情绪和复盘结论 |
| 复盘统计 | 净利润、胜率、盈亏比、期望值、最大回撤、利润曲线、交易日历和多维筛选 |
| 设置 | 数据刷新偏好、主题、本地数据导入导出与附件存储管理 |

用户可在一份历史报告中点击“基于此分析创建交易日志”。新日志将保存该报告 ID，但报告与证据快照不被复制或修改。

## 6. 后端技术基线

| 范畴 | 技术选型 | 用途 |
|---|---|---|
| 运行时 | Python 3.12、uv | 依赖锁定与可复现开发环境 |
| API | FastAPI、Uvicorn | HTTP API、SSE、类型化接口和 OpenAPI 文档 |
| 校验 | Pydantic v2 | API、领域 DTO、LangGraph 状态与报告输出 Schema |
| 数据访问 | SQLAlchemy 2.x、asyncpg、Alembic | 异步 ORM、PostgreSQL 访问和迁移 |
| 主存储 | PostgreSQL | 市场快照、新闻、报告、交易日志、统计和审计 |
| 市场 REST | CCXT | 通用行情、市场信息、Ticker 和 OHLCV 适配 |
| 币安专属数据 | 币安官方 USDⓈ-M REST/WebSocket | 资金费率、未平仓量、标记价格与实时推送 |
| Agent 编排 | LangGraph、langchain-core、langchain-openai | 状态图、只读工具、流式执行和结构化报告 |
| Agent 持久化 | langgraph-checkpoint-postgres | PostgreSQL 图状态检查点与恢复 |
| 日志与可观测性 | structlog、OpenTelemetry | 结构化日志、请求与分析链路追踪 |
| 测试 | pytest、pytest-asyncio、httpx TestClient | 单元、异步、集成与 API 测试 |

首期不使用 Redis、Dramatiq、Celery、Kafka、Kubernetes、TimescaleDB、LangGraph Server 或多 Agent。

## 7. 部署与进程拓扑

```text
React 前端（静态文件）
        │ HTTP / SSE
        ▼
FastAPI API ─────────────── PostgreSQL
        │                         ▲
        │                         │
        ▼                         │
LangGraph 分析流                 │
        ▲                         │
        │                         │
Market Worker ── 币安 REST/WebSocket
```

首期 Docker Compose 服务：

- `frontend`：React 构建后的静态站点。
- `api`：FastAPI 请求、交易日志 CRUD、统计查询、LangGraph 流式分析。
- `market-worker`：币安公开行情 WebSocket 连接、REST 补数、数据新鲜度检查与落库。
- `postgres`：唯一事实存储与 LangGraph checkpointer。

Agent 分析由用户手动触发。API 使用 SSE 将节点状态与最终报告流式传递给前端；不引入独立任务队列。若分析失败，保存失败状态、错误类别与已完成的检查点，用户可显式重试。

## 8. 后端模块边界

```text
backend/src/app/
├── api/                  # FastAPI 路由、依赖注入、请求与响应模型
├── application/          # 创建交易、生成报告、查询统计等用例
├── domain/               # 交易、报告、新闻、市场快照等业务规则
├── infrastructure/       # PostgreSQL、CCXT、币安、新闻源、LLM 适配器
├── agent/                # LangGraph 图、只读工具、状态与输出 Schema
├── workers/              # 行情采集、断线重连与历史补数
├── repositories/         # 仓储接口与 SQLAlchemy 实现
└── shared/               # 配置、日志、时间、异常与通用工具
```

约束：

- API 层不得直接访问数据库。
- Agent 节点不得直接访问数据库、CCXT、币安或网络；必须调用 `application/` 的只读查询用例。
- Worker 与 API 复用 application/domain 层，禁止复制业务规则。
- 外部系统通过 adapter 接入，避免供应商细节泄漏到领域层。
- 面向用户、业务规则和复杂计算的注释使用中文。

## 9. 市场数据流

1. `market-worker` 用币安官方 WebSocket 接收实时价格与 K 线状态。
2. Worker 使用 REST 启动校验、历史补齐和断线恢复。
3. CCXT 提供通用 REST 市场数据；币安官方适配器提供资金费率、未平仓量、标记价格等币安专属衍生品数据。
4. 不持久化逐笔成交和完整订单簿；仅保存首期页面和分析所需的 K 线、衍生品指标与定期市场快照。
5. 每条数据均保存 `source`、`observed_at`、`fetched_at`、标的和原始/标准化版本信息。

首期无需币安 API Key。市场数据 adapter 不实现任何私有接口；未来如新增账户只读同步，必须以独立适配器和独立权限流程实现。

## 10. 新闻与事件流

- 新闻源通过 `NewsSourceAdapter` 接入。
- 每条新闻保存来源、原链接、发布日期、抓取时间、语言、摘要、关联标的和去重哈希。
- 先接入少量可追溯且授权清晰的来源；具体来源在实现前单独确认。
- 新闻正文是外部不可信数据，只能作为引文/证据输入，不得作为 Agent 指令。

## 11. 交易日志与统计模型

```text
Trade
├── 基本信息：标的、方向、短期/中期、标签
├── 计划信息：入场依据、止损、止盈、预期盈亏比、风险金额
├── 实际执行：多条 TradeLeg
├── 成本信息：开平仓手续费、资金费
├── 复盘信息：遵守度、情绪、错误、结论
└── 关联：AI 报告、附件、修改审计
```

`TradeLeg` 记录开仓、减仓或平仓的时间、价格、数量和手续费。数量、价格、费用和盈亏均使用 `Decimal` / PostgreSQL `NUMERIC`。

净盈亏计算：

```text
多单： (平仓价 - 开仓价) × 数量 - 手续费 - 资金费
空单： (开仓价 - 平仓价) × 数量 - 手续费 - 资金费
```

杠杆用于保证金和 ROI 展示，不能直接放大实际盈亏。交易日历、胜率和利润曲线从原始交易记录聚合生成，不保存可失真的最终统计值。

核心表：

- `market_snapshots`
- `news_items`
- `analysis_reports`
- `analysis_evidences`
- `trades`
- `trade_legs`
- `trade_attachments`
- `trade_audit_logs`

随着时序数据量增长，K 线与市场快照表可按月分区；首期先保留分区设计能力，不预先增加 TimescaleDB。

## 12. LangGraph 研究 Agent

首期使用单一 `MarketResearchAgent` 图，不做多 Agent。图中除模型节点外均为确定性 Python 节点。

```text
START
  ↓
加载 AnalysisContext
  ↓
检查数据新鲜度与完整性
  ├── 不通过：生成降级报告 → END
  ↓
并行读取市场快照、衍生品上下文、新闻和个人交易统计
  ↓
整理证据上下文
  ↓
LLM 生成结构化 AnalysisReport
  ↓
Pydantic 校验、风险措辞校验与引用完整性校验
  ↓
持久化报告、证据和 LangGraph 状态
  ↓
END
```

只读工具：

```text
get_market_snapshot(symbol, timeframes)
get_derivatives_context(symbol)
get_news_timeline(symbol, time_range)
get_personal_trading_statistics(filters)
get_previous_analysis(symbol)
```

每次运行使用 `analysis_id` 作为 LangGraph `thread_id`。LangGraph 检查点用于失败恢复与运行审计，但应用自己的 `analysis_reports` 和 `analysis_evidences` 表仍是业务事实来源。

`AnalysisReport` 至少包含：

- 标的、生成时间、数据截止时间。
- 事实型 `market_observations` 与证据 ID。
- 资讯上下文与来源。
- 15m、1h、4h、1d 的市场观察。
- 数据异常、事件和高波动等 `risk_flags`。
- 不确定性等级、研究摘要与限制说明。

报告不得包含保证盈利、确定涨跌、全仓建议或自动下单指令。

## 13. 可靠性与安全

- 数据不新鲜、缺失或来源不可用时，报告必须明确降级。
- 所有报告绑定不可变证据快照。
- 资讯输入隔离为不可信内容，防范提示注入。
- LLM 无权修改交易、设置、数据库或外部系统。
- trace 只保存必要运行元数据、耗时、节点状态和报告 ID；不保存完整用户日志、模型输入输出或任何密钥。
- 不在代码、日志、夹具或提交中保存密钥、私钥、账户信息。

## 14. 测试门槛

| 层级 | 验证目标 |
|---|---|
| 单元测试 | 分批成交、净盈亏、资金费、统计聚合、时区与新鲜度判断 |
| 数据集成测试 | CCXT/币安映射、限流、断线恢复、K 线去重和快照落库 |
| Agent 回归测试 | 固定市场/新闻夹具下的 Schema、引用完整性、降级逻辑与风险措辞 |
| API 集成测试 | 交易日志 CRUD、统计筛选、报告读取与 SSE 状态流 |
| 前端端到端测试 | 录入交易、自动计算、筛选、交易日历、由报告创建日志 |
| 审计测试 | 历史报告和交易记录不被新行情或后续变更覆盖 |

## 15. 实施阶段

1. 前端工作台骨架与类型化 Mock 数据。
2. PostgreSQL、数据库迁移、交易日志 CRUD、分批成交与基础统计。
3. CCXT/币安市场数据 worker、K 线与衍生品指标展示。
4. 新闻 adapter、资讯时间线与可追溯数据模型。
5. LangGraph Agent、只读工具、结构化报告与 PostgreSQL 检查点。
6. 质量加固：测试、Docker Compose、备份导出、异常状态和可观测性。

策略模块在上述工作完成并稳定后，作为独立子项目开发。任何策略接入 Agent 前都必须具备独立回测、样本外验证、版本记录和模拟盘观察证据。
