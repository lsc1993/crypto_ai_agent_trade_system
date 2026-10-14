# 项目状态与文档索引

核对日期：2026-10-14。整理前代码基线：`c6f7dfe`，并核对本次币种准入诊断修复与文档变更。下列“已实现”表示存在对应代码和测试入口；运行部署、公开源连通和真实模型质量需要独立证据，不能从历史计划或单元测试推断。

## 当前能力

当前交付形态为本地研究工作台：FastAPI、React、PostgreSQL 和 Docker Compose。综合研究、独立技术研究、确定性回测及手动模拟盘是不同路径；研究模型不能生成或执行 `TradeIntent`。

| 能力 | 当前实现与范围 | 代码/测试入口 |
| --- | --- | --- |
| 公开行情与存储 | Binance USDⓈ-M 公开行情、K 线及衍生品指标；实时查询与已存储研究数据分别有接口 | [market](../backend/src/app/market/)、[市场测试](../backend/tests/market/) |
| 研究币种管理 | 合约准入检查、目录登记、初始同步、状态展示与归档；动态研究范围不扩大交易范围 | [symbols](../backend/src/app/symbols/)、[管理页](../frontend/src/features/research-symbols/ResearchSymbolManagementPage.tsx)、[测试](../backend/tests/symbols/) |
| 按需 AI 研究 | 固定 LangGraph、冻结证据、中文双周期叙事、模型校验与降级；无模型工具调用 | [agent](../backend/src/app/agent/)、[测试](../backend/tests/agent/) |
| 报告专题 | 美国政策、近七天资金费率、BTC/ETH 美国现货 ETF 资金流；各专题独立处理缺失和失败 | [专题说明](report-factors.md)、[因子测试](../backend/tests/agent/test_factors.py) |
| 独立技术研究 | v2 两阶段模型、程序验证的条件候选、引用校验、规则降级与持久化后台任务；保留 v1 同步接口和历史读取 | [交易计划书](technical-trading-plan.md)、[technical](../backend/src/app/agent/technical/)、[模型测试](../backend/tests/agent/test_technical_plan_model.py)、[worker 测试](../backend/tests/agent/test_technical_worker.py) |
| 技术报告展示 | 字段路径、状态与方法中文展示；多周期结构对照、条件计划与分析依据，原始引用可追溯 | [中文映射](../frontend/src/features/technical-reports/technical-presentation.ts)、[市场结构](../frontend/src/features/technical-reports/TechnicalMarketStructure.tsx)、[计划书](../frontend/src/features/technical-reports/TechnicalPlanBook.tsx) |
| 受控 Harness | Phase 1 协调层与 Phase 2 审计：策略准入、固定生命周期、审计仓储 | [harness](../backend/src/app/harness/)、[测试](../backend/tests/harness/)、[架构决策](superpowers/specs/2026-08-31-controlled-agent-harness-architecture-design.md) |
| 模型失败可观测性 | 综合研究提供安全摘要、有限格式重试及超长正文压缩；技术 v2 提供白名单规则反馈、保留合法段落的有限纠错及安全拒绝日志 | [维护指南](ai-maintenance.md)、[综合模型](../backend/src/app/agent/model.py)、[技术模型](../backend/src/app/agent/technical/plan_model.py) |
| 确定性回测 | 当前 BTCUSDT SMA 回测、风控、模拟成交与审计；收盘决策、下一根开盘成交 | [回测](../backend/src/app/research/backtests/)、[测试](../backend/tests/research/backtests/) |
| 手动模拟盘 | 当前 BTCUSDT 本地账户、手动意图或单次策略评估、快照模拟成交、绩效与审计 | [模拟盘](../backend/src/app/paper_trading/)、[测试](../backend/tests/paper_trading/) |
| 交易日志与复盘 | 本地持久化交易记录、统计和看板；不接入真实交易账户 | [trades](../backend/src/app/trades/)、[dashboard](../backend/src/app/dashboard/) |
| 本地部署 | Compose 的 PostgreSQL/API/前端，以及 API 内币种同步与技术研究任务 | [部署说明](local-deployment.md)、[配置](../compose.yaml) |

## 本次整理的行为

研究币种准入失败返回结构化、安全的检查详情，管理页展示后端消息并去重检查提示。公开行情超限、限流和超时使用固定摘要，不透出上游异常原文。Binance 公开 JSON 响应上限调整为 1,500,000 字节，允许原上限以上的正常合约目录，仍拒绝超过新上限的响应。相关回归见[错误接口测试](../backend/tests/api/test_errors.py)、[行情适配器测试](../backend/tests/market/test_binance_usdm.py)、[资金费率测试](../backend/tests/market/test_funding_history.py)、[准入服务测试](../backend/tests/symbols/test_service.py)及[页面测试](../frontend/src/test/research-symbols.test.tsx)。

共享文档按当前代码整理开发入口、数据模式、来源与验证要求。工具会话、诊断文件、测试临时目录及本地备份不属于项目交付文件。

## 最近验证

2026-10-14，在本次整理的工作区执行：

- `backend/`：`uv run ruff check .`、`uv run pyright` 通过；完整 pytest 656 项通过，数据库测试使用独立、无持久化卷的 PostgreSQL 测试实例。`uv run alembic heads` 返回 `0018_technical_report_runs`。
- `frontend/`：lint、typecheck、完整 Vitest 299 项和 build 通过；构建保留单包超过 500 kB 的体积提示。
- 共享文档的相对链接与 `git diff --check` 通过；运行边界安全文档测试包含在后端全量测试内。
- 未运行 Playwright、真实公开源连通或付费模型验证，未重新部署或迁移业务数据库；上述测试不替代运行环境与模型质量验收。

## 已知差异与待验收项

- 研究币种管理已有主要实现，但不能将 [2026-09-07 计划](superpowers/plans/2026-09-07-research-symbol-management.md)全部勾为完成：当前同步实现是单 worker；计划中的双 worker、120 秒整任务上限和 10 秒租约心跳未在该实现中落实。当前币种路由没有独立的手动同步/重试端点。
- 初始同步采集行情/K 线/衍生品和资金费率。资讯、情绪留待报告运行时按需采集；管理侧 ETF 能力当前标为不支持。报告侧另有 BTC/ETH ETF 适配器，两个状态不能混为一谈。
- 技术研究的数值与价格由确定性程序计算或按冻结字段渲染，模型不能改写数值、扩大交易范围或自动执行条件计划。历史触发状态冻结，到期不自动重算。
- 当前迁移链头为 `0018_technical_report_runs`，v2 部署需前后端与该迁移配套。测试库迁移通过不代表业务库已升级；业务环境须按[部署说明](local-deployment.md)另行验收。
- 真实模型曾出现数值、引用和交易措辞校验降级；有限纠错与合法段落保留已有实现。个别成功样本不代表长期成功率、模型质量基准或交易表现，固定评估集仍待补充。
- 当前不提供真实执行、模型任意工具、长期用户记忆或自动策略交易。Harness 后续阶段保留为规划，不能因历史设计列出就视为启用。

## 阅读顺序

1. [根目录 AGENTS.md](../AGENTS.md)：全局安全与协作规则。
2. [后端约定](../backend/AGENTS.md) / [前端约定](../frontend/AGENTS.md)：按任务范围阅读。
3. [运行边界](operational-boundaries.md)、[AI 维护指南](ai-maintenance.md)：数据源、模型、Harness 与回归入口。
4. [部署说明](local-deployment.md)、[前端 README](../frontend/README.md)、[专题口径](report-factors.md)：运行与产品行为。
5. `docs/superpowers/specs/` 与 `docs/superpowers/plans/`：查阅相关功能的历史设计和实施记录。

[早期 MVP 执行索引](superpowers/plans/2026-07-23-mvp-execution-index.md)中的独立 market-worker、CCXT、固定研究币种以及部分契约是当时的设计，不能直接作为当前运行说明。历史 checkbox 不是自动维护的验收状态；保留历史文件，通过本索引标记现状和差异。

## 维护方式

功能变更时更新相应能力、限制、核对日期和证据链接。区分“代码实现”“测试验证”“运行验收”三个结论；未执行的检查明确列出，不从提交标题或计划推断通过。稳定规则放 AGENTS.md，变化较快的进展留在本文，详细设计仍放原设计文档。
