# AI 加密货币交易系统

## 项目目标

构建一个以 Python 为主的、可回测、可模拟盘、可审计的 AI Agent 加密货币交易系统。

当前交付形态是本地研究工作台：FastAPI 后端、React 前端、PostgreSQL 和 Docker Compose。支持公开行情研究、确定性回测、交易日志及手动模拟盘；真实交易不支持。功能进展以[项目状态](docs/project-status.md)为入口，历史计划不等于已实现能力。

## 开始任务前

- 修改后端前读取 [backend/AGENTS.md](backend/AGENTS.md)，修改前端前读取 [frontend/AGENTS.md](frontend/AGENTS.md)；跨端任务读取两者。
- 涉及 Agent、模型、报告或 Harness 时，读取 [AI 维护指南](docs/ai-maintenance.md)与[运行边界](docs/operational-boundaries.md)。
- 检查当前分支和工作区差异，保留已有未提交改动；不要把其他任务的改动纳入提交。
- 根据当前代码、契约和验证结果核对历史设计；发现差异应记录，不能仅凭旧计划扩展能力或宣称验收完成。

## 不可违反的安全边界

- 不得将交易所 API Key、Secret、Passphrase、私钥或真实账户信息写入代码、日志、测试夹具或提交记录。
- 不得让 LLM、Codex MCP、浏览器自动化或策略代码直接调用真实下单接口。
- 所有交易请求必须先转换为结构化 `TradeIntent`，再由确定性 Risk Engine 校验后交给 Execution Service。
- 实盘能力默认关闭；任何启用实盘、变更资金上限或新增交易所权限的操作，必须先征得用户明确确认。
- 交易所 API Key 必须禁用提现权限，并使用 IP 白名单、独立子账户和最小权限。
- 不允许绕过仓位、杠杆、止损、单日最大亏损、冷却期和熔断规则。

## 架构约束

以下后端模块均位于 `backend/src/app/`，不得按早期规划另建重复的顶层目录。

| 路径 | 职责与边界 |
| --- | --- |
| `agent/`、`reports/` | 固定研究图、冻结证据、模型输出校验及报告；研究 Agent 只能输出研究结果，不能生成或执行交易请求 |
| `harness/` | 研究运行的策略准入、生命周期和审计；不能成为任意工具路由或调用风控、模拟订单、真实执行 |
| `market/`、`news/`、`symbols/` | 受治理公开源、研究币种准入与初始同步；动态 `ResearchSymbol` 不扩展交易契约的 `ContractSymbol` |
| `research/backtests/`、`strategy/` | 确定性回测与策略；策略生成 `TradeIntent`，不得包含实盘密钥或真实下单实现 |
| `risk/`、`execution/`、`paper_trading/` | 确定性风控、模拟成交与模拟账户；当前 `execution/` 是模拟器，不代表已接入真实交易所执行 |
| `infrastructure/persistence/` | 数据库模型、仓储及不可变报告和审计记录；迁移位于 `backend/alembic/` |
| `api/`、`shared/`、`dashboard/`、`trades/` | HTTP 契约、配置、日志、看板与交易日志/复盘 |

前端位于 `frontend/src/`，页面通过 `WorkbenchApi` 使用 Mock/HTTP/Hybrid 适配器。部署入口是根目录 `compose.yaml`，前后端构建入口分别位于 `backend/Dockerfile` 与 `frontend/Dockerfile`。

交易所访问统一经由适配器接口；禁止业务代码直接调用 CCXT。当前公开行情适配器使用 HTTP，不应因历史计划提及 CCXT 而新增该依赖。

Risk Engine 不得依赖 LLM 输出作最终放行依据；模型研究结论不能替代确定性风控规则。

## 工程规范

- 使用 Python 3.12、`uv` 管理依赖。
- 使用 Ruff 格式化与静态检查，使用 Pyright 做类型检查。
- 后端新增功能或修复必须先编写 pytest 测试；前端对应使用 Vitest/Testing Library，关键交互按需补 Playwright。
- 后端涉及金额、数量、价格和手续费时使用 `Decimal`，禁止使用 `float`；前端使用十进制字符串及 `decimal.js`，仅图表显示适配允许临时转为 `number`。
- 所有时间使用 UTC、带时区的时间对象。
- 订单、成交、风控拒绝和模型决策必须产生可关联的审计事件。
- 公共接口必须使用 Pydantic 模型或明确的数据类定义。
- AI Agent 生成或修改后端代码时，必须同步维护详细中文注释：每个代码文件说明模块职责、主要流程与边界；关键类、公共函数和方法说明输入输出、约束与副作用；复杂算法、异常处理、事务、并发、幂等和安全校验解释设计原因。测试说明场景与断言意图，迁移说明历史目的和兼容性。注释以当前实现为准，避免逐行复述语法、空泛模板或宣称未实现能力；修改行为时同时更新相关注释，不写入凭证或真实账户信息。具体要求见[后端注释规范](backend/AGENTS.md#代码注释与-ai-agent-生成原则)。

## 验证要求

每次改动后按影响范围验证，并报告执行目录、结果和未验证项。后端命令在 `backend/` 执行：

```powershell
uv run ruff check .
uv run pyright
uv run pytest
```

前端命令在 `frontend/` 执行：

```powershell
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

数据库测试前提见后端说明；缺少依赖、测试数据库或权限时应明确报告，不能将跳过或未执行称为通过。纯文档修改检查路径、链接、与代码的一致性；涉及运行边界说明时还要运行对应安全文档测试。

涉及策略、回测或风控时，还必须补充：

- 无未来数据泄漏测试。
- 手续费、滑点和部分成交测试。
- 风控拒单、熔断、幂等下单与订单对账测试。
- 模拟盘结果与回测结果的差异说明。

## 变更管理

- 新增生产依赖、修改数据库 schema、接入新交易所、增加外部 MCP 工具前，先说明方案与影响。
- 不修改 `.env`、凭证、生产配置或真实账户相关文件，除非用户明确要求。
- 不执行真实交易、资金划转、提现或删除数据操作。
- 功能、数据源、运行方式或验证命令变化时，同步维护对应说明及 `docs/project-status.md`；状态应有代码或验证证据，历史设计保留原貌并由状态索引说明差异。
- 本地技能、插件缓存和任务临时目录不是项目规范的替代品；不要将个人工具的绝对安装路径、会话记录或凭证写入共享说明。
