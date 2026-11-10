# 实盘手动交易计划 Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

跨模型执行时，若客户端没有上述技能，按[跨模型交接说明](2026-11-06-manual-trading-agent-handoff.md)执行等效的逐任务、测试、审查与记录流程，无需安装个人技能或插件。工程约束以仓库 AGENTS.md 和本文档组为准。

用户已指定开发与审查异构分工：其他模型实现和自测，每个模块结束后由用户交回原设计与审查助手正式审查；执行技能中的自动审查不能代替该结论。按[开发模型提示词](2026-11-06-manual-trading-agent-developer-prompt.md)生成审查包并停在模块边界，通过后才推进下一审查单元。

**Goal:** 交付完整 AI Agent 工作台，以用户选择的策略包和公开证据辅助决策，经本地确定性计算、风险核验及用户审核后，生成用户可自行在交易所手动实施的交易计划。

**Architecture:** 沿用模块化单体、FastAPI/React/PostgreSQL。LangGraph 承担唯一模型与工具循环，持久业务任务以执行片段管理等待和恢复，`governance/` 只负责准入与审计。策略/知识、工具守卫、预算与本地规划服务通过显式协议协作，完整财务值不进入外部模型。

**Tech Stack:** Python 3.12、uv、FastAPI、Pydantic、SQLAlchemy/Alembic、PostgreSQL 17、LangGraph 1.2.10、checkpoint-postgres 3.1.2、React/TypeScript/Vite、Zod、decimal.js、pytest、Vitest、Playwright；预计新增 `mcp==2.3.0` 与 MCP 专用 `httpx2>=2.10.0,<3`，以独立兼容门槛准入。

**Spec:** [需求 v2.0](../specs/2026-11-06-manual-trading-agent-requirements.md)、[架构 v2.0](../specs/2026-11-06-manual-trading-agent-design.md)。跨任务精确类型、数据库与接口选择见[实施契约 C1–C10](2026-11-06-manual-trading-agent-contracts.md)，执行者须同时读取三份文件。

## Global Constraints

- 版本 1.1；2026-11-06；状态为实施计划审阅稿。执行状态（2026-11-10）：T00 已复审通过并合并；T01 已实现并通过后端 full，首轮正式审查不通过后完成并发幂等、嵌套快照重验和根 Schema 校验修复，经原审查助手复审通过（`reviewed_tip=159a43b`）并合并到 `main`；T02 已实现关键词知识检索、不可变版本与 `0020_research_knowledge` 迁移，首轮独立审查判定 P1（已发布版本可追加分块）和 P2（锁等待前采样发布时间）不通过，修复提交 `8835a1d` 后聚焦 40、阶段回归 136、后端 full 1089 passed 全绿，经原审查助手复审通过（`reviewed_tip=8835a1d`）并合并到 `main`；T03 已实现 C3 本地规划资料、单池代次、成本/保证金证据、公开规则适配与 `0021_planning_inputs` 迁移；首轮 4 项、第二轮 1 项、第三轮 1 项 P2 不通过后，提交 `4f0e7ae` 增加冷却状态显式三态、规则刷新带锁重放、来源抓取时间和网关异常转换，提交 `023e5a2` 增加版本感知历史快照指纹/序列化，提交 `8d75a7a` 增加历史 Draft 读取、双格式请求指纹和首次写入严格校验；修复后纯契约/规则 23、SQL 16、阶段回归 183、后端 full 1128 passed，自测 `verified`，经原审查助手复审通过（`reviewed_tip=8d75a7a`）并合并到 `main`；T04 已实现 C4 持久任务、不可变修订、请求幂等、安全事件、owner/lease 字段与 `0022_agent_tasks` 迁移（`implementation tip=2e17368`，聚焦 18、阶段 315、后端 full 1146 passed，自测 `verified`），当前 `review_status=awaiting_review`，等待原审查助手正式结论；其余复选框未执行。本文不授权部署、业务库迁移、真实模型付费调用或系统交易。
- 本期用户审核后自行操作交易所；不保存交易凭证、不访问私有账户、不创建/签名/发送/撤改真实订单、不调用模拟订单服务，不生成 TradeIntent。
- 手动规划是核心交付；MACD、三重过滤及用户未来具体组合算法本期不实现；至少已有规则适配闭环，测试组合不冒充生产策略。
- 现有固定综合/技术研究与报告保留；历史报告、策略/知识版本、证据及审计不可覆盖；新 AGENTS 规则随对应实现落地，本文不覆盖当前规范。
- 后端 Decimal；前端十进制字符串及 decimal.js；所有时间带时区 UTC；结构化财务输入/完整计划/反馈只在本地受限规划域和授权视图中流转。
- 默认审核 AP-01 至 AP-07 保留；普通合法工具不逐次确认。监控默认关闭，本期只暴露不可用状态，D6 调度/提醒不在本核心开发计划内。
- 首期单工作台、单逻辑资金池、同池最多一份待实施计划；未知执行不因到期、取消或跨日自动释放；研究币种不自动扩大规划、回测或模拟盘范围。
- LangGraph 1.2.10、checkpoint-postgres 3.1.2 不借本功能升级；不新增 Redis、向量库、Embedding、CCXT、通用 Shell/文件或浏览器工具。
- 租约 30 秒、心跳 10 秒；图 END 后才发布人工等待；任务总预算跨修订和片段累计，unknown 保守占用，不自动重放未知付费调用。
- 初始模型/工具次数 8/12、工具并发 1；输入/输出单次 16384/4096、累计 98304/32768；模型超时 60 秒、活动 600 秒、传输 64 次，至少留 15 秒安全收尾。
- RAG 单文档 256 KiB、块 1000 字符、重叠 100、最多 6 块；MCP 原始结果 64 KiB、模型摘要 8 KiB；审核 24 小时、等待生命周期 7 天、报价 60 秒；完整参数以契约为准。
- 后端/前端新功能先写失败测试；新 Python 文件、公开方法、复杂算法、事务/并发、安全检查、测试与迁移同步维护详细中文注释。
- 每任务只暂存并提交其自身差异，保留其他任务未提交内容；不修改 `.env`、凭证、真实账户或现有业务配置。

## Review Focus

1. 同名币种却单位/产品不一致，或 NaN、指数/超长十进制输入：拒绝而非误算；T03/T12 的 `test_reject_nonfinite_units_and_decimal_overflow`。
2. 审核跨 UTC 日界线或长期离线：旧日损声明与过期报价不能继续放行；T13 的 `test_midnight_requires_new_daily_risk_declaration`。
3. 前端打开旧导出或多个页面同时采纳：历史清单不持续绿色、仅一个占用合法；T13/T17 的 `test_two_tabs_adopt_one_pool_and_export_expires`。
4. MCP SDK 自动跟随同源跳转、后台重连或超大 JSON：必须在传输层拒绝/计数；T10 的 `test_sdk_redirect_retry_and_json_body_are_guarded`。
5. 财务表单/反馈误入通用报告、SSE 或聊天：本地完整视图可见，模型和公开事件完全不含这些值；T14/T16 的 `test_financial_projection_has_no_model_or_event_values`。

---

## 1. 基线、范围与执行方法

代码核对基线为 `4534ee9`，迁移链头为 `0018_technical_report_runs`。编写计划时工作区已有 20 个跟踪文件未提交，其中包含模型、报告及验证工具的其他改动；不将其视为本计划产物，也不替它们提交、回退或清理。现状依据为[根规则](../../../AGENTS.md)、[后端规则](../../../backend/AGENTS.md)、[前端规则](../../../frontend/AGENTS.md)、[维护指南](../../ai-maintenance.md)、[运行边界](../../operational-boundaries.md)与[统一验证](../../quality-verification.md)。

开始功能执行时使用届时已审阅、包含本计划的提交创建隔离工作区，并按 using-git-worktrees 技能检查基线。依赖其他未提交修复时先记录依赖并由原任务独立处理，不擅自纳入。下面按依赖排序，技术建议均为本计划的决定，不冒充用户逐项指定。

这是一个依赖紧密的系统升级，采用一个主计划加一份契约清单；没有把可单独延期的基础能力拆成不受约束的子项目。任务完成不等于整个核心功能完成；D0–D5 的所有门槛才构成核心交付，真实模型质量和产品规则另有证据。

| 阶段 | 任务 | 可独立检查的交付 |
| --- | --- | --- |
| D0 | T00 | 治理命名迁移与开发规范，旧行为不变 |
| D1 | T01–T03 | 策略包/已有规则、关键词 RAG、本地资料与产品规则 |
| D2 | T04–T07 | 持久任务、步骤预算、人机反馈、片段审计/恢复 |
| D3 | T08–T11 | 冻结上下文、工具守卫、真实 MCP、模型驱动 LangGraph |
| D4-P | T12–T13 | 精确规划、可实施状态、单池一致性与手工反馈 |
| D4-U | T14–T16 | 受限 API、三种适配器、完整前端工作流 |
| D5 | T17–T19 | 故障/浏览器、评估及规则诊断、交付验证与回退说明 |

主依赖：T00 → T01 → T02 → T03（公共类型先落地，D1 迁移链串行接续）；T04 依赖前三者；T05 依赖 T04，T06 依赖 T04/T05（使用 C4 纯类型），T07 依赖 T05/T06；T08/T09 依赖 T01/T02/T04/T05/T07；T10 依赖 T09；T11 依赖 T07–T10；T12 依赖 T01/T03，可在其协议稳定后提前；T13 依赖 T04/T06/T07/T12；T14 依赖 T11/T13；T15 依赖 T14，T16 依赖 T14/T15；T17–T19 汇总。D1 纯算法/组件可以在公共类型稳定后分开准备，但不得在缺少前序迁移时宣称 SQL 验证通过。没有 T12/T13 的实现与拒绝测试，build_manual_trade_plan 不登记为可用工具。

## 2. 文件职责与变更影响

以下是新模块的唯一目录，禁止另建顶层 agent 或重复交易子系统。各任务列出精确文件；包入口 `__init__.py` 只在该任务首次创建包时一并添加职责说明。

| 路径 | 主要责任 |
| --- | --- |
| `backend/src/app/governance/` | 由现有 harness 迁移；策略准入、固定审计协议，新受控片段包装 |
| `backend/src/app/agent_runs/` | 业务任务、修订、用量、反馈、证据冻结与仓储协议 |
| `backend/src/app/agent/interactive/` | 图、模型端口、上下文、worker、工具守卫与已有研究适配器 |
| `backend/src/app/research/strategies/`、`knowledge/`、`research/evidence.py` | 版本化策略/知识和无 Agent 依赖的研究数据契约 |
| `backend/src/app/trade_planning/` | 本地输入、纯计算、风险核验、可实施提案与用户报告反馈 |
| `backend/src/app/infrastructure/persistence/` | SQL 实现、统一提交事务、版本/事件/不可变与唯一约束 |
| `backend/src/app/infrastructure/mcp/`、`market_rules/` | 固定 HTTP/MCP 与产品规则适配，不承载业务授权 |
| `backend/src/app/api/`、`reports/interactive.py` | 本地访问、外部 DTO、安全结果与财务视图分离 |
| `frontend/src/domain/`、`shared/api/`、`features/agent-runs/`、`manual-plans/` | 新契约、适配器、任务与人工计划工作流 |

数据库影响为契约 C9 的 8 个前向迁移；先在专用测试库验证，不自动迁移业务库。新增依赖影响为 MCP 2.3.0、MCP 专用 httpx2 及锁定传递依赖，T10 先审查求解差异与 API 兼容；无新增交易所、付费数据源、外部 MCP 服务或部署组件。内部只读 MCP 与新消费者共享 API lifespan，由新能力开关控制。

验证命令中的 pytest 在 `backend/`，前端命令在 `frontend/`。手工 pytest 若系统临时目录不可用，按质量说明使用 `.tmp/pytest/` 下全新且专属的目录，先验证路径范围与不存在；不能复用会被 pytest 清理的工作目录。SQL 测试只接受显式专用 `TEST_DATABASE_URL` 并通过身份预检，不输出实际连接串。

各任务 Step 5 的提交方式统一为：逐项检查该任务 Files 和差异，仅暂存本任务实际改动，再执行列出的 commit；不得使用 `git add .`。每任务先聚焦红/绿，编辑批次跑 quick，阶段交付跑 full；T17 另跑 http-e2e/e2e。纯规范命名重构测试已存在时先跑基线，增加反向依赖样例证明门禁能拒绝，不为凑红测试虚构行为。

## 3. 实施任务

### T00：迁移治理内核与规范（D0）

**Files:**
- Move：`backend/src/app/harness/__init__.py`、`audit.py`、`contracts.py`、`policy.py`、`runtime.py`、`market_research.py`、`technical_research.py` 到同文件名的 `backend/src/app/governance/`。
- Move：`backend/tests/harness/test_audit.py`、`test_contracts.py`、`test_runtime.py`、`test_market_research.py` 到 `backend/tests/governance/`。
- Modify：第 5 节的 24 个导入文件、`backend/scripts/check_architecture.py`、`backend/tests/security/test_architecture_gate.py`、`test_agent_source_and_secret_safety.py`、`test_agent_dependency_boundary.py`；`AGENTS.md`、`backend/AGENTS.md`、`frontend/AGENTS.md`、`docs/ai-maintenance.md`、`docs/operational-boundaries.md`、`docs/project-status.md`。

**Interfaces:** 消费现有工作流/审计协议；产出 `GovernanceRuntime.run(request: GovernanceRunRequest) -> ResultT`，行为沿用原 Runtime。重命名 HarnessPolicy/Capability/RunKind/RunRequest/PolicyViolation 为 Governance 前缀、HarnessWorkflow 为 GovernedWorkflow、Harnessed 服务为 Governed 前缀；存储 `HarnessAudit*` 类型、表/事件/序列化值保留。

- [ ] **Step 1：运行现有治理/安全基线，补 `test_governance_gate_rejects_trade_io_and_empty_scan`。** 用合成 AST 违规文件证明交易、HTTP/SQL、空扫描仍被拒绝；旧序列化值断言 `market_research`、`technical_research` 原样保持。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/harness tests/security -q`。** 记录基线；新路径断言在迁移前应失败，不以删除旧测试取得绿。
- [ ] **Step 3：按上述映射迁移，更新所有导入与实际文件链接/AST 必需路径。** 此任务只允许新路径的规范定义，不开放工具循环；循环门禁的受控放行留 T09/T11。研究与订单隔离保持，历史迁移不改。
- [ ] **Step 4：运行 `uv run --locked --no-sync pytest tests/governance tests/security -q`、`uv run --locked --no-sync python -m scripts.check_architecture`，再根目录 full。** 全部通过、旧报告/审计读取通过；代码中无 app.harness 导入。文档中的历史说明可保留。
- [ ] **Step 5：提交 `refactor: rename research governance kernel`。** 证据：`.tmp/quality/manual-agent-t00-full.json`；覆盖 AC-18、HN-01/HN-12。

### T01：策略包版本与已有规则评估（D1）

**Files:** Create `backend/src/app/shared/agent_types.py`、`backend/src/app/research/evidence.py`、`backend/src/app/research/strategies/contracts.py`、`ports.py`、`service.py`；`backend/src/app/agent/interactive/adapters/technical_strategy.py`；`backend/src/app/infrastructure/persistence/models/research_strategies.py`、`strategy_catalog.py`；`backend/alembic/versions/0019_strategy_catalog.py`。Test `backend/tests/research/strategies/test_catalog.py`、`test_evaluator.py`、`backend/tests/persistence/test_strategy_catalog.py`；Modify persistence `models/__init__.py`。

**Interfaces:** 产出契约 C1/C2 的 VersionRef、EvidenceEpoch、StrategyCatalog、StrategyEvaluator 与 StrategyEvaluation。`TechnicalStrategyEvaluator.evaluate(...)` 适配现有 `calculate_technical_analysis`，不修改旧算法。生产 evaluator_id 固定 `technical_breakout_v1`，不自动映射其他策略。

- [ ] **Step 1：写 catalog 发布/停用/重复请求、非法 Schema、包组成与候选绑定测试。** 核心断言：
  ```python
  assert published.ref.sha256 != edited_draft_hash
  assert evaluated.strategy_ref == selected_ref
  assert missing_evaluator.candidates == ()
  assert composite.components == frozen_component_refs
  ```
  测试组合评估器只在测试夹具注册；不同证据/参数得到不同候选指纹，不能固定 plans.0。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/research/strategies tests/persistence/test_strategy_catalog.py -q`。** 首次因缺实现失败；SQL 前置未满足则报告 blocked，不以 skip 验收。
- [ ] **Step 3：实现 C2 签名、版本不可变及 evaluator 注册。** published 的方法/参数/组成不可更新，停用阻止新执行；参数 Schema 只支持有界 object/string/number-as-decimal-string/integer/boolean/enum/array，不加载代码、远端 $ref 或任意表达式。旧固定成本门槛如实标注。
- [ ] **Step 4：同命令全绿，额外运行 `tests/agent/test_technical_engine.py`。** 验证旧规则候选没有未来数据泄漏、数值几何未被适配层改写；SQL 禁止改已发布版本。
- [ ] **Step 5：提交 `feat: add versioned strategy packages and evaluator port`。** 证据：聚焦报告/迁移验收；FR-10，AC-07/AC-08/AC-09/AC-28，HN-09/HN-10。

### T02：可用的关键词 RAG（D1）

**Files:** Create `backend/src/app/research/knowledge/contracts.py`、`ports.py`、`indexing.py`、`service.py`；`backend/src/app/infrastructure/persistence/models/knowledge.py`、`knowledge_index.py`；`backend/alembic/versions/0020_research_knowledge.py`；Test `backend/tests/research/knowledge/test_indexing.py`、`test_search.py`、`backend/tests/persistence/test_knowledge_index.py`；Modify models 注册。

**Interfaces:** 消费 VersionRef；产出 C2 `KnowledgeIndex.import_text/search`，以及 `tokenize(text: str) -> tuple[str, ...]`、`chunk_text(text: str) -> tuple[str, ...]`。不依赖外部 Embedding。

- [ ] **Step 1：写 UTF-8 上限/中文英文/同分/无命中/停用与历史可得性测试。**
  ```python
  assert len(hits) <= 6
  assert chunks[0][-100:] == chunks[1][:100]
  assert title_match.score == 4 + body_match_count
  assert historical_hits_for_later_import == ()
  ```
  用含“忽略系统规则”的文档验证仅作为文本返回，不能触发工具或权限变更。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/research/knowledge tests/persistence/test_knowledge_index.py -q`，确认红。**
- [ ] **Step 3：实现 C2 的确定性分块/排序/GIN 查询。** 先在 SQL 中限定工作台、时间、状态和范围再匹配；原文/引用不可变，禁止跟随链接或读取用户给出的本地路径。
- [ ] **Step 4：同命令全绿，断言 SQL 与纯函数排名一致，导入重复幂等、历史引用仍可读取。** 仅使用项目已审查方法和合成资料，不等待用户准备完整知识库。
- [ ] **Step 5：提交 `feat: add governed keyword knowledge retrieval`。** FR-04，AC-04/AC-05，HN-09/HN-10；证据区分索引正确性与真实知识质量。

### T03：规划资料、政策与受支持产品规则（D1）

**Files:** Create `backend/src/app/trade_planning/inputs.py`、`input_repository.py`、`input_service.py`、`product_support.py`；`backend/src/app/infrastructure/market_rules/binance_usdm.py`；`backend/src/app/infrastructure/persistence/models/planning_inputs.py`、`planning_input_repository.py`；`backend/alembic/versions/0021_planning_inputs.py`。Modify `backend/src/app/market/binance_usdm.py`（有类型的公开规则读取，旧准入方法兼容）和 models 注册。Test `backend/tests/trade_planning/test_inputs.py`、`test_product_support.py`、`backend/tests/market/test_planning_rules.py`、`backend/tests/persistence/test_planning_inputs.py`。

**Interfaces:** C3 全部输入类型及 PlanningInputService.create_profile/create_policy/resolve_refs 的精确签名；profile 创建返回 PlanningProfileSnapshot，完整引用齐备后才组合 PlanningRefs。`PublicRuleReader.load(product: ProductKey) -> VenueRuleSnapshot` 为 async；规则端口定义于 input_repository.py，不引用私有接口。

- [ ] **Step 1：写 `test_reject_nonfinite_units_and_decimal_overflow`、未知占用、UTC/时效、同池版本并发及规则解析测试。**
  ```python
  assert missing_position is None  # 不补零
  assert catalog.accepts("BTCUSDT", mode="isolated")
  assert not catalog.accepts("BTCUSDT", mode="cross")
  assert parsed.price_tick == Decimal("0.10")  # 不取 pricePrecision
  ```
  NaN/Infinity/指数/31 位整数、USDT 与币本位混用均拒绝；不打印测试值以外的财务资料。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py tests/trade_planning/test_product_support.py tests/market/test_planning_rules.py tests/persistence/test_planning_inputs.py -q`，确认红。**
- [ ] **Step 3：实现 C3、单池 generation 与 C9 迁移。** 固定 BTC/ETH 逐仓起点；风险政策金额/杠杆均需显式用户输入，资料修改不自动提高政策。过滤器/保证金/费率缺失为 unknown，不调用私有档位接口。金融值不放通用事件。
- [ ] **Step 4：同命令全绿，并跑 `tests/market/test_binance_usdm.py`、`test_public_boundary.py`。** 合成响应验证新旧公开方法兼容；单次只读官方复验在 T18，当前不假称产品已验收。
- [ ] **Step 5：提交 `feat: add local planning inputs and venue rule snapshots`。** FR-14/FR-15，AC-21 至 AC-25/AC-29/AC-30，HN-13/HN-14/HN-15。

### T04：持久任务、修订与安全事件（D2）

**Files:** Create `backend/src/app/agent_runs/contracts.py`、`ports.py`、`service.py`、`events.py`；`backend/src/app/infrastructure/persistence/models/agent_runs.py`、`agent_run_repository.py`；`backend/alembic/versions/0022_agent_tasks.py`；Test `backend/tests/agent_runs/test_contracts.py`、`test_service.py`、`backend/tests/persistence/test_agent_runs.py`；Modify models 注册。

**Interfaces:** C4 `AgentRunRepository.enqueue/get`；`AgentRunService.start(workspace_id: UUID, data: RunInput) -> RunSnapshot` 为 async。此时不启动消费者；新状态、不可变修订和事件 seq 由仓储维护，不复用旧按币种合并队列。

- [ ] **Step 1：写同键同参/异参、不同策略/参数、默认解析后重试及容量测试。**
  ```python
  assert replay.id == first.id
  assert different_request_same_symbol.id != first.id
  assert conflict.code == "request_conflict"
  assert event_sequences == tuple(range(1, len(event_sequences) + 1))
  ```
  并发第 21 个可运行任务拒绝；等待容量 100 不占运行并发；跨工作台读取拒绝。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/agent_runs/test_contracts.py tests/agent_runs/test_service.py tests/persistence/test_agent_runs.py -q`，确认红。**
- [ ] **Step 3：实现 C1/C4 请求指纹与模型、唯一约束、队列锁、事件分页及不可变修订。** 占位产物只保存引用/受限载荷分类，不能令普通事件内嵌财务 JSON；终态后新工作建立 parent_run_id。
- [ ] **Step 4：同命令全绿，SQL 验证重启后重读、无按币种合并、失败回滚不遗留序号或半个任务。**
- [ ] **Step 5：提交 `feat: persist versioned agent tasks and events`。** FR-01/FR-12，AC-07/AC-18，HN-02/HN-08/HN-11/HN-12。

### T05：步骤账本、预算与未知调用（D2）

**Files:** Create `backend/src/app/agent_runs/attempts.py`、`budget.py`、`segments.py`（先定义 C4 的纯类型）；`backend/src/app/infrastructure/persistence/models/agent_attempts.py`、`agent_attempt_repository.py`；`backend/alembic/versions/0023_agent_attempts.py`；Test `backend/tests/agent_runs/test_budget.py`、`test_attempts.py`、`backend/tests/persistence/test_agent_attempts.py`；Modify models 注册及 `agent_runs/ports.py`。

**Interfaces:** 消费 RunFence（在 segments.py 先定义 C4 纯类型，T07 实现租约）；产出 C5 BudgetLedger.reserve/mark_sent/settle，prepared/in_flight/succeeded/failed/unknown 的受限状态迁移。调用方不能先发送后生成步骤标识。

- [ ] **Step 1：写跨片段/修订累计、双重预留、并发临界、缺 usage 与重试计数测试。**
  ```python
  assert ledger.model_limit == 8
  assert after_revision.model_sent == before_revision.model_sent
  assert unknown.reserved_output == 4096
  assert third_retry.code == "attempt_limit"
  ```
  同一成功逻辑键复用结果；每次真实重试新 attempt，不复用首发额度。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/agent_runs/test_budget.py tests/agent_runs/test_attempts.py tests/persistence/test_agent_attempts.py -q`，确认红。**
- [ ] **Step 3：先定义 C4 的 RunFence/ExecutionContext/SegmentOutcome/CompletionDecision/PlanAdoptionProposal 纯类型，再实现 C5 全部初始/硬上限及 append 授权；在 run 锁与 fence 下预留。** 将发送状态提交后才给传输许可；崩溃窗口保守 unknown；已知/未知 usage 分开，未知付费调用不能被恢复器自动重放。无隐藏 SDK 重试。
- [ ] **Step 4：同命令全绿，边界验证第 9 次模型/第 13 次工具在未追加授权时拒绝，交易资金不受 AP-05 影响。**
- [ ] **Step 5：提交 `feat: account for agent attempts and cumulative budgets`。** FR-06/FR-12，AC-06/AC-15，HN-04/HN-05。

### T06：人工审核、连续消息与取消一致性（D2）

**Files:** Create `backend/src/app/agent_runs/interactions.py`、`messages.py`、`decisions.py`；`backend/src/app/infrastructure/persistence/models/agent_interactions.py`、`agent_interaction_repository.py`；`backend/alembic/versions/0024_agent_interactions.py`；Test `backend/tests/agent_runs/test_interactions.py`、`test_messages.py`、`backend/tests/persistence/test_agent_interactions.py`；Modify `agent_runs/contracts.py`、`ports.py` 及 models 注册。

**Interfaces:** C5 InteractionService.respond、MessageService.record；`DecisionPolicy.classify(proposal: ControlProposal, context: ExecutionContext) -> GuardDecision`（纯函数，ControlProposal 在 decisions.py 定义，包含动作类别、差异、材料引用与安全原因）。`AgentRunService.cancel(workspace_id, run_id, *, request_id, expected_version) -> RunSnapshot` 为 async。

- [ ] **Step 1：写 AP-01 至 AP-07 分类、同键重放、并发/过期/旧材料、消息水位和取消测试。**
  ```python
  assert received.receipt_state == "recorded"
  assert received.adoption_applied is False
  assert stale_hash_response.code == "review_conflict"
  assert autonomous_read.action == "allow"
  ```
  不把“继续”当预算或资金增加；用户表单已明确授权的同一修改只记录一次；模型不能自批。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/agent_runs/test_interactions.py tests/agent_runs/test_messages.py tests/persistence/test_agent_interactions.py -q`，确认红。**
- [ ] **Step 3：实现响应 CAS、请求键/材料指纹/有效期校验、单 preparing/pending 待办及顺序反馈。** API 事务只记录并入队；worker 应用前重验。running 取消标记 cancel_requested，各新调用、心跳与终态提交均检查；终态不重开，后续意见创建关联新任务。
- [ ] **Step 4：同命令全绿。** SQL 竞态验证反馈先提交与取消先提交两种顺序，未应用反馈不冒充已实施；用户消息未 applied 时禁止完成旧上下文结果。人工等待阶段不执行模型轮询。
- [ ] **Step 5：提交 `feat: persist human review and task feedback`。** FR-01/FR-11/FR-12，AC-10 至 AC-14/AC-17，HN-06/HN-07/HN-08/HN-11。

### T07：带租约的执行片段、统一审计提交与 worker（D2）

**Files:** Create/complete `backend/src/app/agent_runs/segments.py`；Create `backend/src/app/agent/interactive/ports.py`、`worker.py`；`backend/src/app/governance/interactive_planning.py`；`backend/src/app/infrastructure/persistence/models/agent_segments.py`、`agent_segment_repository.py`、`agent_commit_coordinator.py`；`backend/alembic/versions/0025_agent_segments.py`；Test `backend/tests/agent_runs/test_worker.py`、`backend/tests/governance/test_interactive_planning.py`、`backend/tests/persistence/test_agent_segments.py`、`test_agent_segment_recovery.py`。Modify governance contracts/policy、persistence models/harness.py 及注册。

**Interfaces:** 实现 C4 claim/heartbeat/recover_expired 与 SegmentRepository.commit；`InteractiveAgentWorker.run_once() -> bool`、`run_forever(stop: asyncio.Event) -> None` 为 async。消费 SegmentRunner 协议，此任务用确定性替身验证边界，尚不装配生产长循环。

- [ ] **Step 1：写准备等待/图 END/提交窗口、过期接管/迟到写入、四阶段审计前缀测试。**
  ```python
  assert awaiting.owner is None
  assert pending.can_respond is True  # 仅图结束和原子提交后
  assert stale_worker_commit.kind == "lease_lost"
  assert terminal_event_count == 1
  ```
  模型结果已保存但图更新丢失时复用结果；缺 started 的旧片段不伪造序号 3。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/agent_runs/test_worker.py tests/governance/test_interactive_planning.py tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py -q`，确认红。**
- [ ] **Step 3：实现 30/10 秒租约、唯一 graph namespace、coordinator 原子提交及受限审计适配器。** 所有审计阶段和业务写入检查 fence；数据库行锁后使用实际时刻。异常序号 3 也经 coordinator，旧路径保持原端口；恢复中断旧片段后重新准入，不重放 unknown 付费调用。
- [ ] **Step 4：同命令全绿。** 实际子进程终止后新 worker 恢复 preparing/成功步骤，业务等待/终态、合法审计终态、事件与 owner 释放无半提交。存储不可用即停新调用；心跳失败取消未提交工作。
- [ ] **Step 5：提交 `feat: fence agent segments and atomic lifecycle commits`。** FR-12，AC-12/AC-13/AC-15，HN-02/HN-03/HN-04/HN-06/HN-11；根目录阶段 full 证据 `.tmp/quality/manual-agent-d2-full.json`。

### T08：冻结证据、动态上下文与输入控长（D3）

**Files:** Create `backend/src/app/agent_runs/evidence.py`；`backend/src/app/agent/interactive/context.py`、`context_budget.py`、`adapters/research_evidence.py`；Test `backend/tests/agent/interactive/test_context.py`、`test_evidence_epochs.py`、`test_context_budget.py`、`backend/tests/persistence/test_agent_evidence.py`；Modify `agent_run_repository.py`（证据/manifest 保存）与 `research/evidence.py`（补齐 C5 字段）。

**Interfaces:** C5 `ContextBuilder.build(...) -> ModelContext`；`EvidenceService.freeze(context: ExecutionContext) -> EvidenceEpoch` 为 async，通过注入的受治理公开证据端口读取；`estimate_input(payload: bytes) -> int` 为纯函数，保守模式为 len(payload)+4096。

- [ ] **Step 1：写精确策略加载、历史资料可得性、过期/未来时间、消息水位和裁剪测试。**
  ```python
  assert model_context.manifest.strategy_ref == selected_ref
  assert estimated == len(encoded_request) + 4096
  assert model_context.manifest.applied_seq == processed_seq
  assert private_financial_text not in serialized_model_context
  ```
  无 RAG 命中不丢选定策略；工具消息裁剪保留完整 call/result 配对；没有证据的旧摘要不能变新事实。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/agent/interactive/test_context.py tests/agent/interactive/test_evidence_epochs.py tests/agent/interactive/test_context_budget.py tests/persistence/test_agent_evidence.py -q`，确认红。**
- [ ] **Step 3：实现受限分块加载、manifest 和摘要重建。** C1 输入只保存资料引用；金融值由本地渲染。先删重复/旧上下文，不能裁掉策略/授权/关键条件/失败限制；初始证据读取同样经过工具/传输预算，作为预先采集事实加入上下文，不伪装供应商 tool_calls。
- [ ] **Step 4：同命令全绿。** 超过 16384 预留仍放不下时停止或请求更小范围，不扩大模型窗口；刷新产生新 epoch/必要修订，无法提供历史数据的来源不混入旧截至。
- [ ] **Step 5：提交 `feat: assemble bounded evidence contexts for agent runs`。** FR-04/FR-05/FR-06，AC-04/AC-05/AC-14/AC-16，HN-08/HN-09/HN-10/HN-14。

### T09：逐次工具守卫和内部领域工具（D3）

**Files:** Create `backend/src/app/agent/interactive/tools/contracts.py`、`registry.py`、`gateway.py`、`research_tools.py`；Test `backend/tests/agent/interactive/test_tool_gateway.py`、`test_research_tools.py`；Modify `backend/scripts/check_architecture.py`、`backend/tests/security/test_architecture_gate.py`、`test_agent_source_and_secret_safety.py`、`test_agent_dependency_boundary.py`、后端规范及维护/运行说明的对应新路径段落。

**Interfaces:** C6 ToolGateway.call 与 RegisteredTool/ToolObservation；消费 C2/C5 端口。初期登记六个研究工具，规划工具到 T14 才启用；并发固定 1，input/output Schema 和目录版本冻结。

- [ ] **Step 1：写未登记/参数越权/目录变更/注入、先预留后发送、输出超限/非法 Schema 测试。**
  ```python
  assert forbidden_tool.calls == 0
  assert reservation.committed_before_send
  assert outside_symbol.reason_code == "scope_denied"
  assert observer.max_concurrency == 1
  ```
  用端口 spy 证明预算不足、fence 失效和取消后没有 HTTP/工具发送。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/agent/interactive/test_tool_gateway.py tests/agent/interactive/test_research_tools.py tests/security -q`，确认新测试红、旧范围仍受门禁。**
- [ ] **Step 3：实现 C6 的守卫顺序和固定处理器；禁止模型传任意 URL/SQL/代码/连接。** 同批才将全目录 tools= 禁词细化为“旧模型与治理内核禁止、interactive 允许受控 Schema”，AST 增加 agent_runs/research/trade_planning 到交易/LLM 的适用隔离；不全删安全断言。governance 不导入 MCP/HTTP/SQL。
- [ ] **Step 4：同命令全绿，再运行 architecture。** 内部行情、策略、RAG 的实际调用链及失败审计可关联；工具描述中的恶意指令不改变授权；无下单/私有账户能力。
- [ ] **Step 5：提交 `feat: guard registered agent tool calls`。** FR-02/FR-03，AC-01/AC-03/AC-06/AC-29，HN-01/HN-05/HN-09/HN-12。

### T10：官方 MCP SDK、受控 HTTP 和本地只读服务（D3）

**Files:** Modify `backend/pyproject.toml`、`backend/uv.lock`；Create `backend/src/app/infrastructure/mcp/registry.py`、`client.py`、`transport.py`、`server.py`；Test `backend/tests/mcp/test_compatibility.py`、`test_guarded_transport.py`、`test_local_http.py`、`backend/tests/tooling/test_mcp_lifespan.py`；Modify `backend/pyproject.toml` 类型检查入口、依赖安全测试（允许新 MCP，仍禁交易客户端）。

**Interfaces:** C6 McpToolClient.call、固定 read_strategy_definition 服务；同进程 MCP ASGI mount 的 `build_research_mcp(reader: StrategyCatalog) -> ResearchMcpRuntime` 在 server.py 定义，runtime 只暴露 ASGI app、受控 lifespan 和本地服务描述，不把内部凭据发浏览器。

- [ ] **Step 1：先写 SDK API/生命周期、真实 TCP 和 `test_sdk_redirect_retry_and_json_body_are_guarded`。**
  ```python
  assert called_tool == "read_strategy_definition"
  assert negotiated_protocol == "2026-07-28"
  assert redirected_server.calls == 0
  assert oversized_json.accepted is False
  ```
  包含 SDK 同源 307、SSE 及 JSON 64 KiB 边界、隐藏重试/背景流逐请求记账、禁止 sampling/roots/elicitation 和未知工具。
- [ ] **Step 2：在缺 SDK 时运行 `uv run --locked --no-sync pytest tests/mcp tests/tooling/test_mcp_lifespan.py -q` 确认预期红。** 随后先说明依赖差异，再于隔离工作区执行 `uv add "mcp==2.3.0" "httpx2>=2.10.0,<3"`；检查 uv.lock，原框架版本不变才继续，否则停止此任务并修兼容方案，不能顺手整体升级。
- [ ] **Step 3：按 C6 实现官方 Client/Streamable HTTP 与 bounded transport，锁定完整传递依赖。** httpx2 是适配器直接使用的依赖，单独声明；不装 CLI、遥测 exporter 或第三方 MCP。SDK 前拒绝所有重定向，JSON 和 SSE 分别限额；固定 loopback/Host/路径及内部服务认证，宿主管理 manager 生命周期，不在监听前拨本机 HTTP。
- [ ] **Step 4：同命令全绿、Ruff/Pyright 通过。** 实际网络测试只登记本次本地端口；兼容记录包括 Python/SDK/协议/Schema/HTTP 限制与关闭回收，不能用内存 transport 代替 TCP 证明。
- [ ] **Step 5：提交 `feat: add bounded MCP client and local research service`。** FR-03，AC-02/AC-03/AC-17，HN-01/HN-04/HN-05/HN-12；新依赖和影响同步维护文档。

### T11：原生 Tool Calling 与有限 LangGraph（D3）

**Files:** Create `backend/src/app/agent/interactive/model_port.py`、`deepseek.py`、`prompt.py`、`graph.py`、`state.py`；Test `backend/tests/agent/interactive/test_deepseek.py`、`test_graph.py`、`test_graph_segments.py`；Modify `agent/interactive/worker.py`（注入 SegmentRunner 实现）、后端规范、维护指南与运行边界的新模式说明。

**Interfaces:** C6 ModelDecision/ModelContext/decide 及本任务定义的 AnalysisArtifactStager 协议；`build_interactive_graph(dependencies: GraphDependencies) -> SegmentRunner` 在 graph.py 定义，GraphDependencies（同文件）显式注入模型、上下文、工具、证据、交互和产物端口，无数据库/执行服务。产物只依赖协议，测试注入替身，不提前导入 T14 的具体 ArtifactService；最终业务提交仍归 coordinator。

- [ ] **Step 1：写真实请求 Schema、工具观察后再次判断、主动澄清/审核、预算终止与模型失败测试。**
  ```python
  assert sent_request["tools"]
  assert requests[1]["messages"][-1]["tool_call_id"] == returned_call_id
  assert waiting.segment_ended and waiting.model_calls_while_waiting == 0
  assert trace.requested_model != "" and trace.returned_model != ""
  ```
  MockTransport 验证真实 native 协议；多 tool_calls 逐一守卫，未执行明确 not_executed，不能只用文字“已调用”。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/agent/interactive/test_deepseek.py tests/agent/interactive/test_graph.py tests/agent/interactive/test_graph_segments.py -q`，确认红；不发付费请求。**
- [ ] **Step 3：实现唯一模型循环、类型化控制提案、工具/等待/产物路由。** 首个适配器使用现有 httpx 与已授权模型配置，显式 thinking disabled；不依赖原始 reasoning_content，不更换现有供应商/模型值或启用 beta strict。原生工具/输出能力不支持则准确降级；所有模型调用经 T05 包装，供应商自动重试关闭。
- [ ] **Step 4：同命令全绿，并复跑 T07 的恢复测试。** 图只保存引用/安全计数，END/saver 后业务原子发布等待；正常报告成功不推导计划可实施，错误/预算不足可无计划。真实模型能力与语义质量 T18 单独验证。
- [ ] **Step 5：提交 `feat: run a bounded model-driven research graph`。** FR-02/FR-03/FR-07，AC-01 至 AC-03/AC-10/AC-12/AC-15/AC-16，HN-01 至 HN-12 中适用项；阶段 full 记录 `.tmp/quality/manual-agent-d3-full.json`。

### T12：确定性数量、成本、保证金和操作分支（D4-P）

**Files:** Create `backend/src/app/trade_planning/contracts.py`、`sizing.py`、`risk_checks.py`、`margin.py`、`order_rules.py`、`checklist.py`；Test `backend/tests/trade_planning/test_sizing.py`、`test_risk_checks.py`、`test_margin.py`、`test_order_rules.py`、`test_checklist.py`。消费 T01/T03；无订单/LLM 依赖。

**Interfaces:** C7 `calculate_size(request: PlanningRequest) -> SizingResult`；`evaluate_planning_risk(request, size) -> tuple[ValidationCheck, ...]` 在 risk_checks.py、`build_manual_checklist(request, size, checks) -> ManualChecklist` 在 checklist.py（ManualChecklist 同 contracts 定义，包含 C7 操作/异常分支）。均纯函数。

- [ ] **Step 1：写独立手算样例、多空、舍入/最小额冲突与缺资料测试。** 合成长单 m=1、e=100、s=95、t=110、双边费率 0.001、滑点/持有成本在该夹具显式为 0、R=10、step=0.1、杠杆=2、其他额度不约束：
  ```python
  assert size.quantity == Decimal("1.9")
  assert size.stop_path_loss == Decimal("9.8705")
  assert size.target_net_reward == Decimal("18.601")
  assert size.initial_margin == Decimal("95")
  ```
  这不是用户参数或真实费率；另测非零费用/滑点/资金费、不完整档位/用户预览、冷却熔断/日损/仓位拒绝，以及 Review Focus 的非有限数和单位错误。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/trade_planning/test_sizing.py tests/trade_planning/test_risk_checks.py tests/trade_planning/test_margin.py tests/trade_planning/test_order_rules.py tests/trade_planning/test_checklist.py -q`，确认红。**
- [ ] **Step 3：实现 C7 线性公式、有限档位计算和保守格点规则。** 计算精度使用显式 Decimal localcontext（精度 80，舍入规则显式），最终在相应 tick/step/结算单位向保守方向量化并复验；不枚举无限格点。保证金规则或合格预览缺失为 unknown；强平与止损基准/安全距离由适用规则与用户政策验证，不能简式保证不会强平。
- [ ] **Step 4：同命令全绿。** 断言实际检查覆盖最小名义额/每批退出量/总量/保护性止损、未成交/部分成交/跳价/超时；最小额不能通过加大风险或移动结构达标；不给无价格上界市价单可实施状态。
- [ ] **Step 5：提交 `feat: calculate deterministic manual trade plans`。** FR-09/FR-14/FR-15/FR-16，AC-21 至 AC-26，HN-13；软件数值正确性不代表策略盈利。

### T13：规划服务、可实施状态、跨计划占用与手工反馈（D4-P）

**Files:** Create `backend/src/app/trade_planning/service.py`、`readiness.py`、`commitments.py`、`feedback.py`、`ports.py`；`backend/src/app/infrastructure/persistence/models/manual_plans.py`、`manual_plan_repository.py`；`backend/alembic/versions/0026_manual_plans.py`；Test `backend/tests/trade_planning/test_readiness.py`、`test_feedback.py`、`backend/tests/persistence/test_manual_plan_commitments.py`、`test_manual_plan_revalidation.py`。Modify `agent_commit_coordinator.py`、model 注册。

**Interfaces:** C7 ManualPlanningService.build/revalidate、FeedbackService.record；`derive_readiness(plan, checks, *, now, pool_generation, adoption, commitment) -> PlanReadiness` 在 readiness.py，输入分别为 C7 类型，now 是 UTC datetime。`CommitmentResolution` 在 commitments.py 定义，只有未实施/无挂单声明或承接完整新资料两类，不是交易所撤单指令。

- [ ] **Step 1：写采纳不绕过 fail/unknown、行情/日界线/代次过期、并发占用、反馈未知测试。**
  ```python
  assert unreviewed.readiness == "ready_for_review"
  assert stale_quote.readiness == "needs_revalidation"
  assert approved_with_failed_check.readiness == "blocked"
  assert incomplete_closed_trade.net_profit is None
  ```
  含 `test_midnight_requires_new_daily_risk_declaration`：UTC 跨日不重置额度；`test_two_tabs_adopt_one_pool_and_export_expires` 的 SQL 部分：两计划同池只一个 active/unresolved。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/trade_planning/test_readiness.py tests/trade_planning/test_feedback.py tests/persistence/test_manual_plan_commitments.py tests/persistence/test_manual_plan_revalidation.py -q`，确认红。**
- [ ] **Step 3：实现 C7 提案与本地模型投影，T07 coordinator 内原子应用采纳、池锁/代次、占用和事件。** 采用有效期与核验有效期分离，重验只追加记录；旧终态不重开。修改重大参数/资料按新版本审阅；未实质改变的有效授权可用于重验，不靠刷新延长计划。未知执行不自动释放，已实施旧计划不能当新入场复用。
- [ ] **Step 4：同命令全绿，并复跑 T07/T06 SQL 竞态。** 资料/政策/反馈推进 generation，其他计划立即需重验；用户完整声明承接或未执行/无挂单声明才可解除占用。反馈保持 user_reported，部分成交/缺费不算虚构净收益、不自动进模型/RAG。
- [ ] **Step 5：提交 `feat: gate manual plan readiness and capital commitments`。** FR-14 至 FR-17，AC-21 至 AC-30，HN-07/HN-13/HN-14/HN-15；D4-P 阶段 full 证据单列。

### T14：安全产物、受限 HTTP/SSE 与生产装配（D4-U）

**Files:** Create `backend/src/app/reports/interactive.py`；`backend/src/app/agent/interactive/artifacts.py`、`tools/planning_tool.py`；`backend/src/app/api/agent_session.py`、`agent_responses.py`、`routes/agent_runs.py`、`strategies.py`、`knowledge.py`、`planning_profiles.py`、`manual_plans.py`；`backend/src/app/infrastructure/interactive_agent.py`（装配工厂）；Test `backend/tests/reports/test_interactive.py`、`backend/tests/api/test_agent_session.py`、`test_agent_runs.py`、`test_agent_catalogs.py`、`test_manual_plans.py`、`backend/tests/security/test_interactive_projection.py`。Modify `backend/src/app/main.py`、`shared/config.py`、`api/errors.py`、`agent/interactive/graph.py`、`tools/registry.py`。

**Interfaces:** C8 完整 API 与受限 DTO；`build_interactive_components(settings, session_factory, public_readers, model_transport) -> InteractiveComponents` 在装配工厂定义，封装 worker、services、session 与 MCP lifespan；main 只创建/注册/启停，不塞入全部业务。`ArtifactService.validate_and_stage(context, analysis: FinalAnalysis) -> tuple[ArtifactRef, ...]` 为 async，使用 C6 输出/C7 计划引用。

- [ ] **Step 1：写同源/Host/CSRF/会话、幂等/CAS、分页/SSE seq、财务投影与关闭开关测试。**
  ```python
  assert invalid_origin.status_code == 403
  assert no_session_plan_read.status_code == 401
  assert disabled_capabilities["monitoring"] is False
  assert financial_marker not in model_json + event_json + ordinary_artifact_json
  ```
  `test_financial_projection_has_no_model_or_event_values` 用合成唯一金额/仓位串；授权 manual plan GET 可见完整值，普通报告只含引用。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/reports/test_interactive.py tests/api/test_agent_session.py tests/api/test_agent_runs.py tests/api/test_agent_catalogs.py tests/api/test_manual_plans.py tests/security/test_interactive_projection.py -q`，确认红。**
- [ ] **Step 3：实现 C8 DTO、会话与路由、claim 引用/字段角色/单位检查、HTTP 202 和事件重读；接入规划工具及三类产物。** 原始模型/隐藏推理和财务不进 SSE；安全过程摘要单独标明不作真值。功能旗标默认关闭；无数据库/模型/MCP 能力准确不可用，不回退 Mock。新模型无效可交付真实规则降级，但全部必需规划检查仍不可省略。
- [ ] **Step 4：同命令全绿，加生产 create_app lifespan 集成。** 内部 MCP 和新 worker 受同一生命周期管理，CSRF/服务凭据不进日志；真实 TCP 装配支持 T10 本地工具，旧报告路由/质量回归通过。无任何“执行订单”接口。
- [ ] **Step 5：提交 `feat: expose reviewed manual planning workflows`。** FR-07/FR-08/FR-09/FR-11/FR-12，AC-01 至 AC-03/AC-09 至 AC-19/AC-21 至 AC-30，HN-01 至 HN-15 按实现归属验证。

### T15：前端契约、适配器与策略/知识/规划资料页面（D4-U）

**Files:** Create `frontend/src/domain/agent-common.ts`、`agent-run.ts`、`agent-strategy.ts`、`knowledge.ts`、`manual-plan.ts`；`frontend/src/shared/api/agent-workbench-contract.ts`、`agent-http-api.ts`、`agent-mock-api.ts`、`agent-api.test.ts`；`frontend/src/features/agent-strategies/StrategyPoolPage.tsx`、`StrategyPoolPage.test.tsx`；`frontend/src/features/research-knowledge/KnowledgePage.tsx`、`KnowledgePage.test.tsx`；`frontend/src/features/planning/PlanningProfilePage.tsx`、`PlanningProfilePage.test.tsx`。Modify `shared/api/workbench-api.ts`、`http-workbench-api.ts`、`mock-workbench-api.ts`、`hybrid-workbench-api.ts`、`app/router.tsx`、`components/layout/Sidebar.tsx`、`frontend/vite.config.ts`（同源开发与 preview proxy）。

**Interfaces:** 本任务 `WorkbenchApi` 只扩展 C8.1 的 `AgentCatalogApi`，HTTP/Mock/Hybrid 同批实现全部目录/知识/资料方法。`AgentRunApi` 可声明但尚不并入 WorkbenchApi，不要求为 T16 写空实现。T16 完成后才扩展完整 AgentWorkbenchApi。精确签名见 C8.1、HTTP 映射见 C8；页面不直接 fetch。

- [ ] **Step 1：先补 Zod/HTTP/Mock/Hybrid 和页面测试。**
  ```ts
  expect(ManualPlanViewSchema.safeParse({ ...valid, quantity: 1 }).success).toBe(false);
  expect(httpFailureMockFallbackCalls).toBe(0);
  expect(screen.getByText("尚未接入评估器")).toBeVisible();
  ```
  策略组合组成版本可读，未实现算法明确不能规划；知识无命中/停用可见，资料未知不填 0，政策修改有差异。
- [ ] **Step 2：运行 `npm run test -- --run src/shared/api/agent-api.test.ts src/features/agent-strategies/StrategyPoolPage.test.tsx src/features/research-knowledge/KnowledgePage.test.tsx src/features/planning/PlanningProfilePage.test.tsx`，确认红。**
- [ ] **Step 3：实现新领域 Zod 与适配器委托，构建策略池/导入检索/本地资金风险表单，包括绑定候选/数量的保证金资料补录。** 新 HTTP 客户端与 Vite 开发/preview proxy 按 C8 同源会话规则实现，新增 pageSize Schema 不改旧 page_size 解码；mock 明确模拟，api/market-api 不静默失败回退。财务表单不转成聊天、URL/本地存储或前端日志；全部十进制字符串，不为金融计算转 number。
- [ ] **Step 4：同命令全绿，执行 lint/typecheck。** 错误/关闭/空目录/迟到请求及本地会话过期明确处理；不默认 MACD 参数、资金数额或风险百分比。
- [ ] **Step 5：提交 `feat: add strategy knowledge and planning workbench forms`。** FR-04/FR-10/FR-14，AC-04/AC-08/AC-18/AC-22/AC-28/AC-29；证据为契约/页面测试，不冒充 HTTP+SQL 联验。

### T16：任务交互、过程轨迹与手动计划审核页面（D4-U）

**Files:** Create `frontend/src/features/agent-runs/AgentRunPage.tsx`、`AgentRunPage.test.tsx`、`useAgentRunEvents.ts`、`agent-run-events.test.ts`、`AgentRunTimeline.tsx`、`HumanReviewPanel.tsx`、`agent-runs.css`；`frontend/src/features/manual-plans/ManualPlanPage.tsx`、`ManualPlanPage.test.tsx`、`ManualExecutionFeedbackForm.tsx`、`ManualExecutionFeedbackForm.test.tsx`、`manual-plans.css`；Create `frontend/src/shared/api/agent-run-api.test.ts`；Modify T15 API 契约/适配器及 `app/router.tsx`。

**Interfaces:** 本任务将 `WorkbenchApi` 扩展为 C8.1 的 `AgentWorkbenchApi`，三个适配器同批补齐 AgentRunApi 的全部方法，确保每批可单独通过 typecheck。用户已记录反馈与已应用反馈分别显示，PlanningFeedbackReceipt 不冒充交互反馈已应用。

- [ ] **Step 1：写发起/等待/刷新/批拒/修改、旧材料并发冲突、SSE 重连与可实施时效测试。**
  ```ts
  expect(screen.getByText("反馈已收到，正在核验")).toBeVisible();
  expect(orderSubmitCalls).toBe(0);
  expect(renderedEventSeqs).toEqual([1, 2, 3]);
  expect(screen.getByText("需要重新核验")).toBeVisible();
  ```
  用虚拟时钟推进到报价 60 秒后，不能保持旧绿色状态；合成财务值在计划授权视图可见、轨迹/聊天/事件不可见；用户拒绝不触发自动采纳。
- [ ] **Step 2：运行 `npm run test -- --run src/features/agent-runs/AgentRunPage.test.tsx src/features/agent-runs/agent-run-events.test.ts src/features/manual-plans/ManualPlanPage.test.tsx src/features/manual-plans/ManualExecutionFeedbackForm.test.tsx src/shared/api/agent-run-api.test.ts`，确认红。**
- [ ] **Step 3：实现安全摘要/行动理由/工具轨迹、类型化审核差异、完整手动清单/重验/反馈。** SSE 断开只重连，不取消任务，按 seq 去重并补拉；模型 debug/token 不直接显示。日期/来源/核验期限和仍须在交易所核对项同页可见；待补保证金资料可跳转本地表单，保存后新版本重验。聊天提示其模型处理用途、资金资料使用本地表单；已报告实施清单标历史，取消任务不显示为撤单。
- [ ] **Step 4：同命令全绿，执行 frontend lint/typecheck/test/build。** 页面无自动发单按钮、无无效监控开关；monitoring=false 时说明当前不可用；复制/导出保留版本/有效期/依据，用户自行实施。
- [ ] **Step 5：提交 `feat: review and track manual trading plans in workbench`。** FR-01/FR-07/FR-09/FR-11/FR-16/FR-17，AC-10 至 AC-14/AC-17/AC-19/AC-21 至 AC-30。

### T17：真实 SQL/HTTP/MCP/浏览器及崩溃旅程（D5）

**Files:** Create `backend/scripts/http_e2e_agent.py`、`backend/tests/tooling/test_http_e2e_agent.py`、`backend/tests/persistence/test_interactive_agent_recovery.py`；`frontend/e2e-http/manual-agent.spec.ts`、`manual-plan-review.spec.ts`、`manual-plan-pool.spec.ts`；Modify `backend/scripts/http_e2e_server.py`、`scripts/verify.py`（沿用现有 http-e2e，不新增含混档位）、相关 tooling 测试与 `docs/quality-verification.md`。

**Interfaces:** 测试工厂 `build_agent_e2e_components(...) -> InteractiveComponents` 复用 T14 生产装配，只替换外层行情与模型传输为合成/固定响应，保留真实 worker/governance/SQL/MCP；控制门仅注册于隔离测试服务，不进生产。无 `page.route` 截断业务 HTTP 来伪造成功。

- [ ] **Step 1：先写 6 条旅程：正常计划/采纳/重读；待补/拒绝/修订；SSE 断线和新上下文；过期/重验/旧批准；同池并发及未知占用；user_reported 部分成交/缺费。**
  ```ts
  expect(finalPlan.readiness).toBe("ready_for_manual_execution");
  expect(secondPlan.reasonCode).toBe("capital_pool_occupied");
  expect(exported.validatedAt).toBeTruthy();
  expect(exchangePrivateRequestCount).toBe(0);
  ```
  SQL 进程终止覆盖 requested/started/preparing/结果持久化/收尾各窗口，失租 checkpoint 不能成为新 owner 真相。
- [ ] **Step 2：先运行聚焦 pytest，再根目录 `uv run --project backend --locked --no-sync python scripts/verify.py http-e2e --report .tmp/quality/manual-agent-http-e2e.json`，确认新用例在缺流程时失败而非零收集成功。**
- [ ] **Step 3：补齐隔离装配、可控故障门、MCP 启停和安全摘要记录。** 数据库预检/随机 schema、端口与随机控制 token 沿用现有机制；测试仅用合成财务资料，无真实模型/私有请求，完成后按本任务资源范围回收。
- [ ] **Step 4：聚焦与 http-e2e 全绿，再运行 `scripts/verify.py e2e`（使用根目录 uv 入口）与 full。** 明确记录替身模型、真实 TCP MCP、HTTP/SQL、浏览器各自证明范围；进程终止不等同断电恢复，不冒充真实模型质量。
- [ ] **Step 5：提交 `test: verify interactive manual planning journeys and recovery`。** 所有核心 AC 的系统旅程；重点 HN-01 至 HN-15 的跨模块边界。

### T18：版本化评估、人工量表与只读产品规则诊断（D5）

**Files:** Create `backend/evaluation/manual-agent/README.md`、`protocol-v1.json`、`cases-v1.json`；`backend/scripts/evaluate_manual_agent.py`、`check_planning_rules.py`；`backend/tests/tooling/test_manual_agent_evaluation.py`、`test_planning_rule_diagnostics.py`。Modify `backend/pyproject.toml` 类型检查入口、`scripts/verify.py` 与 tooling 测试（新增离线评估子检查）、`docs/quality-verification.md`。

**Interfaces:** `evaluate_manual_agent.main(argv: Sequence[str] | None = None) -> int` 默认离线；显式 --live + 专用进程密钥 + 预算参数 + 新产物路径才可付费。`check_planning_rules.main(...) -> int` 只读固定 BTC/ETH 规则/状态/时效及支持字段，不加载 `.env`、模型或私有账户，不存原始财务值。

- [ ] **Step 1：预登记至少 30 个分层场景和 6 个重复运行场景，写预算授权/结果分母/人工评分缺失/公开规则失败测试。**
  ```python
  assert len(protocol.cases) >= 30
  assert len(protocol.repeat_case_ids) >= 6
  assert missing_human_scores.quality_status == "pending"
  assert cli_without_live.transport_calls == 0
  ```
  包括趋势/震荡/冲突/无候选/过期/错误策略/无评估器/RAG 错配/注入/越权/应观望，以及规划不可实施与隐私案例。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/tooling/test_manual_agent_evaluation.py tests/tooling/test_planning_rule_diagnostics.py -q`，确认红；不运行 --live。**
- [ ] **Step 3：实现离线协议、具名人工 0–2 分的四维评分和独立复核记录，输出安全版本指纹与分母。** 各维均值 ≥1.5，≥90% 场景 ≥6/8 且无维度 0；关键错误零容忍；应完整交付率 ≥90%、应停止场景全部满足预期。计算/权限/可实施断言全部通过才算软件通过。人工结果缺失为 pending，不由模型自评填满。
- [ ] **Step 4：聚焦全绿，离线 `uv run --locked --no-sync python -m scripts.evaluate_manual_agent` 通过；只读规则诊断在明确联网范围内执行并记录成败。** 实际模型质量运行留到用户明确付费额度后按批执行，未执行标待验收；配置别名、返回 model 与 Prompt/工具/Schema 指纹一并记录。产品支持发布必须有现行公开规则证据及保证金/费用资料流程，不靠固定夹具宣称全部支持。
- [ ] **Step 5：提交 `test: add manual agent evaluation and rule diagnostics`。** FR-02/FR-08/FR-09/FR-15，需求第 10 节与设计 §13.3；本期不要求真实交易、不宣称盈利验收。

### T19：全量交付、迁移兼容和运行说明（D5）

**Files:** Modify `docs/project-status.md`、`docs/ai-maintenance.md`、`docs/operational-boundaries.md`、`docs/local-deployment.md`、`docs/quality-verification.md`、`README.md`、`frontend/README.md`、三份 AGENTS.md 的实际状态部分；Create `docs/manual-trading-agent.md`、`docs/manual-planning-operations.md`、`backend/tests/tooling/test_interactive_startup.py`。只有实测必要时修改 `backend/Dockerfile`/`compose.yaml`，不得夹带部署或配置变化。

**Interfaces:** 产出用户操作流程、能力/限制/时效/审核/隐私/手动反馈说明、依赖与前向迁移清单、保留旧数据的停用方案；状态分别列实现通过、模型质量 pending/passed、产品规则状态及未交付监控。

- [ ] **Step 1：写新开关关闭/开启、旧报告/审计读取、迁移 head 和生产 lifespan 回收测试。**
  ```python
  assert disabled.new_worker_count == 0
  assert old_report_after_migration == old_report_before_migration
  assert shutdown.leaked_tasks == 0
  assert migrated_heads == ("0026_manual_plans",)
  ```
  若执行时编号已重排，断言采用唯一真实新 head，并同步 C9；测试迁移不应用业务库。
- [ ] **Step 2：运行 `uv run --locked --no-sync pytest tests/tooling/test_interactive_startup.py tests/persistence/test_migrations.py -q`；未接齐装配时应红。**
- [ ] **Step 3：修复真实集成缺口并按已验证事实更新操作/维护文档。** 隔离 Compose 验收使用生产镜像、合成资料/固定模型传输，明确与完整真实模型链路的区别；不修改现有 `.env`，只在隔离栈注入任务内配置。停用新入口和消费者作为回退，不降迁移、删任务或改旧审计。业务部署/迁移仍是独立操作，不能从计划审批推定获准。
- [ ] **Step 4：根目录执行 full、e2e、http-e2e，输出独立 `.tmp/quality/manual-agent-final-*.json`，检查新旧功能与所有核心 AC/HN。** 再读本次结果，记录实际运行目录、通过/失败/阻塞/未验证；缺测试库/浏览器/模型评分不得写通过。不重复已绿检查，除非后续修改或发现新问题。
- [ ] **Step 5：提交 `docs: document reviewed manual planning delivery and limits`。** 本地分支完成后独立代码审查，再按用户选定方式处理集成；不自动推送、合并、部署或启用业务开关。

## 4. 需求、审核与 Harness 覆盖

本表是未来验收追踪，不是本轮执行结果。验证证据写入本地忽略目录；提交只保留合成测试、协议与安全摘要规范。

| 需求 | 主要任务 | 主要证据 |
| --- | --- | --- |
| FR-01 | T04/T06/T14/T16 | 幂等/修订/消息 SQL 与任务页面 |
| FR-02 | T08–T11/T18 | 工具观察后动态选择、停止/澄清与模型量表 |
| FR-03 | T09/T10/T11/T17 | native 请求、真实 TCP MCP、权限/传输拒绝 |
| FR-04 | T02/T08/T15 | 实际 SQL 检索、版本/可得性/无命中 |
| FR-05 | T08/T11 | manifest、控长、消息配对、精确策略 |
| FR-06 | T05/T08/T09/T11 | 最大预留/实际 usage/未知/恢复累计 |
| FR-07 | T14/T16/T17 | 安全轨迹、断线补拉、无原始隐藏思考 |
| FR-08 | T08/T14/T18 | 三类内容/引用/语义评分与覆盖限制 |
| FR-09 | T01/T11–T14/T18 | 候选绑定、无计划、程序算值与实盘规划 |
| FR-10 | T01/T15 | 策略/组合版本、能力、无 evaluator、停用 |
| FR-11 | T06/T07/T13/T16/T17 | 动态交互、审核 CAS、等待/恢复 |
| FR-12 | T04–T07/T17 | 业务日志、租约/审计原子性、实际进程终止 |
| FR-13 | T14/T16 | 核心版只验证监控默认关闭/不可用；调度与提醒 D6 后续独立计划 |
| FR-14 | T03/T12/T13/T15 | 本地资料、硬政策、资金池/未知占用与隐私 |
| FR-15 | T03/T12/T13/T18 | tick/step/minimum/成本/保证金/时效、只读规则核对 |
| FR-16 | T12–T14/T16/T17 | 完整手动清单、采纳、重验与异常分支 |
| FR-17 | T13/T16/T17 | user_reported、部分/未知、成本后反馈与来源 |

| 审核规则 | 实现位置与允许结果 |
| --- | --- |
| AP-01 | T06 分类、T13 原子采纳、T16 全量材料；未通过必要检查不变可实施 |
| AP-02 | T01/T06/T08：包/组成差异经用户明确授权，生成新修订，不替换 evaluator |
| AP-03 | T03/T06/T13：策略参数与规划政策独立授权/版本，仍受硬边界约束 |
| AP-04 | T06/T09：扩大范围需审且仅限已支持目录，不扩 ContractSymbol |
| AP-05 | T05/T06：追加 Agent 用量上限，不改变资金与风险；部署硬上限仍有效 |
| AP-06 | T06/T13：材料/条件实质变化新版本重审，旧批准不沿用 |
| AP-07 | T14/T16：未交付监控无法启用；D6 才实现完整授权生命周期 |

| 验收 | 主任务 / 证明 |
| --- | --- |
| AC-01 | T09/T11：缺证据后真实选择工具并根据观察继续 |
| AC-02 | T10/T17：登记工具经真实 TCP MCP 调用 |
| AC-03 | T09/T10：未登记/越权/注入服务端拒绝 |
| AC-04 | T02/T08：命中/无命中/停用/历史可得性 |
| AC-05 | T08：控长不丢策略与授权、时间条件 |
| AC-06 | T05：预算临界/重试/未知与追加授权 |
| AC-07 | T01/T04：不同参数不合并、同键幂等冲突 |
| AC-08 | T01/T15：无评估器不能数值规划 |
| AC-09 | T01/T12/T14：所选已有规则/测试组合闭环 |
| AC-10 | T06/T16/T17：审阅、拒绝、修改及不自动改变 |
| AC-11 | T05/T06：范围/预算差异审核 |
| AC-12 | T07/T17：页面离开/服务重启等待可恢复 |
| AC-13 | T06/T07/T17：重复/过期/无反馈不默认批准 |
| AC-14 | T08/T13/T17：市场过期/重大修订重审 |
| AC-15 | T05/T07/T17：未知调用不自动重放、成功结果复用 |
| AC-16 | T08/T11/T12/T14：缺口/冲突/模型失败真实降级或无计划 |
| AC-17 | T14/T16/T17：SSE seq 补拉、摘要与投影 |
| AC-18 | T00/T04/T19：旧报告/审计与新迁移兼容 |
| AC-19 | T14/T16：单次任务与采纳不触发监控 |
| AC-20 | D6 后续计划：可选监控触发/停止全流程；本核心版未实施，不列为通过 |
| AC-21 | T12–T14/T17：完整资料→程序计划→审核→清单 |
| AC-22 | T03/T13：缺项/过期不填零或可实施 |
| AC-23 | T12：量价格点/最低额/风险上限冲突 |
| AC-24 | T12/T13：日损/冷却/熔断/仓位/杠杆阻断 |
| AC-25 | T03/T12/T18：规则/成本/保证金缺项与不支持 |
| AC-26 | T12/T16/T17：未成交/部分成交/跳价/到期人工分支 |
| AC-27 | T13/T16/T17：用户报告与不完整收益 |
| AC-28 | T01/T15：冻结组合，测试接入不编造算法 |
| AC-29 | T09/T14/T17：财务流向与私有/签名/真实订单请求为零 |
| AC-30 | T13/T17：同池采纳互斥、代次传播、未知占用保留 |

| 不变量 | 主责任与拒绝测试 |
| --- | --- |
| HN-01 | T09/T10，每次调用而非一次准入；越权不发送 |
| HN-02 | T04/T07，业务单一权威、owner/epoch、旧 worker 拒绝 |
| HN-03 | T07/T13，等待/终态/审计/占用/事件原子提交 |
| HN-04 | T05/T07，成功复用、unknown 不自动重放 |
| HN-05 | T05/T09/T10，所有真实发送累计预留/计数 |
| HN-06 | T06/T07，人工等待释放资源且无回复不批准 |
| HN-07 | T06/T13，版本/材料/时效与既有明确授权 |
| HN-08 | T06/T08，消息 recorded/applied 水位与完成阻断 |
| HN-09 | T01/T02/T08/T09，精确策略优先、知识不授权 |
| HN-10 | T02/T03/T08，来源/版本/逐项时间与历史可得性 |
| HN-11 | T07/T11/T14，模型结束不等业务已提交 |
| HN-12 | T00/T09/T10/T14，网络/依赖/载荷与安全投影 |
| HN-13 | T12/T13，必要检查/采纳/时效与可实施判定 |
| HN-14 | T03/T05/T08/T14，资金/Agent 预算与财务隔离 |
| HN-15 | T13/T17，共享池代次、唯一占用及用户声明承接 |

## 5. T00 导入迁移清单

2026-11-06 用 `rg -l 'app\.harness' backend/src backend/tests backend/scripts` 得到以下 24 个文件。执行时重新检索确认新增导入，但不把其他任务改动一起提交；源文件迁移后用目标路径。只调整本任务导入/类型对应行。

```text
backend/scripts/http_e2e_research.py
backend/src/app/main.py
backend/src/app/harness/audit.py
backend/src/app/harness/technical_research.py
backend/src/app/harness/runtime.py
backend/src/app/harness/policy.py
backend/src/app/harness/market_research.py
backend/src/app/infrastructure/persistence/harness_audit_repository.py
backend/src/app/api/routes/technical_reports.py
backend/src/app/api/errors.py
backend/src/app/agent/technical/worker.py
backend/tests/harness/test_runtime.py
backend/tests/harness/test_market_research.py
backend/tests/harness/test_audit.py
backend/tests/harness/test_contracts.py
backend/tests/persistence/test_research_flow_evaluation_history.py
backend/tests/persistence/test_harness_audit_repository.py
backend/tests/persistence/test_comprehensive_research_capture_history.py
backend/tests/persistence/test_agent_research_repository.py
backend/tests/persistence/test_technical_run_repository.py
backend/tests/persistence/test_technical_report_repository.py
backend/tests/api/test_errors.py
backend/tests/api/test_agent_analysis_reports.py
backend/tests/market/test_research_symbols.py
```

另外更新包含路径/类名硬编码的 AST/安全/tooling 测试和现行文档链接；旧迁移/历史设计中的 harness 名称保留，不作全仓库盲目字符串替换。

## 6. 交付门槛与执行交接

每个任务的聚焦验证只证明该任务；D0/D2/D3/D4-P/D4-U/D5 完成时以根目录统一入口生成对应 full 摘要，D1 首次新 schema 同样需专用测试库迁移验收。D5 包含 full、e2e、http-e2e 与隔离生产 lifespan/Compose 运行证据；这些检查不会自动调用付费模型。验收时至少一条实际已有规则旅程能算出并审阅完整清单，不能以纯说明/假工具/静态界面交付。

正式报告分开给出：软件/计算与权限、SQL/故障/浏览器、MCP 协议、真实模型量表、当前产品规则、策略收益与用户自报表现。前四者的部分成功不能证明后两者；没有用户策略算法或实盘反馈时准确写尚无收益证据。不得为了宣布完成降低固定量表、隐藏拒绝样本或要求用户实际下单作为测试。

按用户指定方式，所有模块由开发模型实现/自测后交回原设计与审查助手正式审查，重点核对 T05/T07/T12/T13/T14 的账本、事务、资金与隐私边界。入口为[跨模型交接说明](2026-11-06-manual-trading-agent-handoff.md)及[开发模型提示词](2026-11-06-manual-trading-agent-developer-prompt.md)；具备技能时可复用，否则执行等效工程流程。当前只交付文档，无需再次确认“手动还是自动”、策略算法范围、默认审核或可选监控这些已对齐的目标。

本轮文档检查结果在最终回复中报告；上文任务复选框和未来验证证据保持未完成。计划批准也不等同于实际用户资金参数已设定、业务开关已启用、真实模型额度获批或代码功能已验收。
