# 项目状态与文档索引

核对日期：2026-11-04。本次质量基础设施变更基线：`417cae7`；此前功能核对及验证记录保留如下。下列“已实现”表示存在对应代码和测试入口；运行部署、公开源连通和真实模型质量需要独立证据，不能从历史计划或单元测试推断。

## 当前能力

当前交付形态为本地研究工作台：FastAPI、React、PostgreSQL 和 Docker Compose。综合研究、独立技术研究、确定性回测及手动模拟盘是不同路径；研究模型不能生成或执行 `TradeIntent`。

| 能力 | 当前实现与范围 | 代码/测试入口 |
| --- | --- | --- |
| 公开行情与存储 | Binance USDⓈ-M 公开行情、K 线及衍生品指标；实时查询与已存储研究数据分别有接口 | [market](../backend/src/app/market/)、[市场测试](../backend/tests/market/) |
| 研究币种管理 | 合约准入检查、目录登记、初始同步、失败重试、超时/租约恢复及归档；动态研究范围不扩大交易范围 | [symbols](../backend/src/app/symbols/)、[管理页](../frontend/src/features/research-symbols/ResearchSymbolManagementPage.tsx)、[测试](../backend/tests/symbols/) |
| 同步安全诊断 | 管理页展示 UTC 生命周期、固定中文失败原因与逐来源覆盖；离线缺项明确提示，不显示原始错误或来源载荷 | [诊断组件](../frontend/src/features/research-symbols/ResearchSymbolSyncDiagnostics.tsx)、[页面测试](../frontend/src/features/research-symbols/ResearchSymbolManagementPage.test.tsx) |
| 手动公开源诊断 | 默认22项，显式包含情绪/ETF时25项，分别记录可用性与时效；不加入默认离线验收，不读取业务配置或数据库 | [检查脚本](../backend/scripts/check_public_sources.py)、[质量验证](quality-verification.md#手动验证真实公开源) |
| 按需 AI 研究 | 固定 LangGraph、冻结证据、中文双周期叙事、模型校验与降级；无模型工具调用 | [agent](../backend/src/app/agent/)、[测试](../backend/tests/agent/) |
| 报告专题 | 美国政策、近七天资金费率、BTC/ETH 美国现货 ETF 资金流；各专题独立处理缺失和失败 | [专题说明](report-factors.md)、[因子测试](../backend/tests/agent/test_factors.py) |
| 独立技术研究 | v2 两阶段模型、程序验证的条件候选、引用校验、规则降级与持久化后台任务；保留 v1 同步接口和历史读取 | [交易计划书](technical-trading-plan.md)、[technical](../backend/src/app/agent/technical/)、[模型测试](../backend/tests/agent/test_technical_plan_model.py)、[worker 测试](../backend/tests/agent/test_technical_worker.py) |
| 技术报告展示 | 字段路径、状态与方法中文展示；多周期结构对照、条件计划与分析依据，原始引用可追溯 | [中文映射](../frontend/src/features/technical-reports/technical-presentation.ts)、[市场结构](../frontend/src/features/technical-reports/TechnicalMarketStructure.tsx)、[计划书](../frontend/src/features/technical-reports/TechnicalPlanBook.tsx) |
| 受控 Harness（治理内核） | Phase 1 协调层与 Phase 2 审计：策略准入、固定生命周期、审计仓储；代码位于 `governance/`，历史 `harness_*` 表/事件值保留 | [governance](../backend/src/app/governance/)、[测试](../backend/tests/governance/)、[架构决策](superpowers/specs/2026-08-31-controlled-agent-harness-architecture-design.md) |
| 模型失败可观测性 | 综合研究提供安全摘要、有限格式重试及超长正文压缩；技术 v2 提供白名单规则反馈、保留合法段落的有限纠错及安全拒绝日志 | [维护指南](ai-maintenance.md)、[综合模型](../backend/src/app/agent/model.py)、[技术模型](../backend/src/app/agent/technical/plan_model.py) |
| 确定性回测 | 当前 BTCUSDT SMA 回测、风控、模拟成交与审计；收盘决策、下一根开盘成交 | [回测](../backend/src/app/research/backtests/)、[测试](../backend/tests/research/backtests/) |
| 手动模拟盘 | 当前 BTCUSDT 本地账户、手动意图或单次策略评估、快照模拟成交、绩效与审计 | [模拟盘](../backend/src/app/paper_trading/)、[测试](../backend/tests/paper_trading/) |
| 交易日志与复盘 | 本地持久化交易记录、统计和看板；不接入真实交易账户 | [trades](../backend/src/app/trades/)、[dashboard](../backend/src/app/dashboard/) |
| 本地部署 | Compose 的 PostgreSQL/API/前端，以及 API 内币种同步与技术研究任务 | [部署说明](local-deployment.md)、[配置](../compose.yaml) |
| 可复现质量检查 | 本地/CI 共用 doctor、quick、full、eval、Mock e2e；三态摘要、退出码、超时终止及 pytest 参数隔离 | [质量验证](quality-verification.md)、[入口](../scripts/verify.py)、[CI 配置](../.github/workflows/verify.yml) |
| 测试库防误配置 | 显式测试授权、固定专用库/受限角色、只读身份权限预检；共享夹具及独立迁移用例均受保护 | [预检](../backend/scripts/check_test_database.py)、[测试](../backend/tests/tooling/test_test_database_guard.py) |
| 固定离线契约评估 | 8 个合成案例通过真实综合研究适配器校验，分别统计接受/拒绝/可降级错误并保留版本指纹；不代表真实模型质量 | [样本说明](../backend/evaluation/README.md)、[评估入口](../backend/scripts/evaluate_research.py) |
| 研究服务流程评估 | 9 个合成案例验证综合研究与技术 v2 的成功、拒绝、降级和证据不足门控；另有真实仓储降级历史及审计回归 | [流程集](../backend/evaluation/flows/README.md)、[真实仓储回归](../backend/tests/persistence/test_research_flow_evaluation_history.py) |
| 架构机器门禁 | AST 检查研究/交易、治理内核/IO及持久化、Risk/LLM 直接依赖；故意违规、漏扫及坏语法均有回归，保留原字符串安全检查 | [检查器](../backend/scripts/check_architecture.py)、[故障样例测试](../backend/tests/security/test_architecture_gate.py) |
| HTTP 与数据库浏览器验收 | 交易日志在 api 模式经真实 HTTP 和生产仓储保存后，刷新及新上下文重读；随机测试 schema，不是整站生产装配验收 | [浏览器用例](../frontend/e2e-http/trade-persistence.spec.ts)、[隔离服务](../backend/scripts/http_e2e_server.py) |
| 技术研究 HTTP 与任务恢复验收 | 生产队列/worker/治理内核/适配器/SQL 的完成与降级闭环；worker 重建、子进程终止、取消、提交后恢复、去重与迟到租约拒绝 | [研究浏览器用例](../frontend/e2e-http/research-persistence.spec.ts)、[恢复测试](../backend/tests/persistence/test_technical_worker_recovery.py) |
| 币种同步重试 HTTP 验收 | 浏览器手动重试、运行中禁用/轮询、重复任务复用、部分恢复或再次失败及新会话重读；生产 worker/SQL/快照仓储，固定合成来源 | [同步浏览器用例](../frontend/e2e-http/symbol-sync-retry.spec.ts)、[隔离装配](../backend/scripts/http_e2e_symbols.py) |
| 完整 Compose 运行与恢复验收 | 生产镜像、入口迁移、完整应用 lifespan 与 Nginx；合成日志在 API 重启、保卷重建及独立空库备份恢复后保持一致 | [本地运行验收记录](superpowers/plans/2026-11-01-isolated-compose-acceptance.md)、[部署说明](local-deployment.md) |

## 目标需求（尚未实施）

2026-11-06 形成[交互式研究 AI Agent 升级需求](superpowers/specs/2026-11-06-interactive-research-agent-requirements.md)：汇总专业报告、模型驱动研究、Tool Calling/MCP、RAG、动态上下文与预算、策略池、决策及条件计划、人机交互与默认审核规则；持续监控为默认关闭的可选能力。本次仅新增需求文档与入口，不代表上述能力已实现，不修改现行 AGENTS.md 或当前运行边界；具体架构、接口和实施计划留待后续设计。

2026-11-06 形成[交互式研究 Agent 目标架构设计](superpowers/specs/2026-11-06-interactive-research-agent-design.md)审阅稿：提出模块化单体内的新研究路径、片段式任务恢复、人机审核一致性、工具/MCP 与 RAG、上下文预算、策略评估和分期验收方案。该文件为需求后的设计提案，尚未实现或修改现行规范；不代表真实模型、任务恢复或策略效果已通过验收。

2026-11-06 架构设计更新至 v1.1：补充系统级 Harness 与治理内核的区别、最小运行契约、HN 运行不变量、故障分类、能力与验收证据追踪及开发计划编写要求；明确所选策略精确加载与 RAG 的分工，以及用户资料不阻塞框架开发。需求目标、默认审核和可选监控范围保持不变；本次为设计文档补充，不修改现行 AGENTS.md 或功能实现，不构成新 Harness 运行验收。

2026-11-06 当前规划基线升级至 v2.0：[实盘手动交易计划需求](superpowers/specs/2026-11-06-manual-trading-agent-requirements.md)与[目标架构](superpowers/specs/2026-11-06-manual-trading-agent-design.md)。核心目标是 LLM 辅助决策、策略包接入、确定性资金/仓位/风险与市场规则核验、用户审核及可手动实施的完整操作清单；用户自行在交易所操作，系统不接入私有账户或自动下单。完整 Agent 能力与默认审核保留，监控仍可选默认关闭，具体策略组合算法后续单独讨论。该基线替代上述研究版 v1.x 作为后续设计与开发计划输入，旧文件保留历史；本次只更新文档，不修改现行 AGENTS.md、运行权限或功能实现，不代表实盘计划能力已验收。

2026-11-06 形成[实盘手动计划 Agent 开发计划 v1.0](superpowers/plans/2026-11-06-manual-trading-agent-implementation.md)及[实施契约清单](superpowers/plans/2026-11-06-manual-trading-agent-contracts.md)：将 v2 需求/架构拆为 20 个带文件、接口、测试与提交边界的任务，先处理治理命名和 AGENTS/门禁，再覆盖策略/RAG、持久任务与人机交互、工具/MCP、确定性规划、单资金池一致性、前端及分层验收。持续监控调度仍属可选后续 D6，自动交易与未提供策略算法不纳入。本次仅编写计划和索引，未修改功能代码、依赖、schema、现行规范或运行配置；任务复选框全部未执行，真实模型与产品支持仍需分别验收。

2026-11-06 开发计划与实施契约更新至 v1.1，并新增[跨模型开发交接](superpowers/plans/2026-11-06-manual-trading-agent-handoff.md)：明确必读文档、无个人技能时的等效流程、源码基线与已有改动保护、任务接续和验证记录、环境阻塞处理及分层完成标准；修正公共类型/迁移链依赖，明确 T11 图的产物协议与 T15/T16 前端接口分批接入。业务目标和默认审核不变，本次仍为文档调整，所有开发任务尚未执行。

2026-11-06 按用户指定明确异构开发与集中审查分工，新增[开发模型提示词](superpowers/plans/2026-11-06-manual-trading-agent-developer-prompt.md)：其他模型按指定模块实现与自测，生成准确 base/tip、改动/契约/测试证据的审查请求，再由用户交回原设计与审查助手正式审查；修复后重验重审，当前版本通过后才放行下一审查单元。交接说明同步至 v1.1，开发审查与产品内计划审核分别管理，不改变单 Agent 产品架构；本次未开始任何开发任务。

## 本次整理的行为

2026-11-07 T00 治理内核命名迁移：后端 `app/harness/` 迁至 `app/governance/`，`HarnessRuntime`/`HarnessPolicy`/`HarnessCapability`/`HarnessRunKind`/`HarnessRunRequest`/`HarnessPolicyViolation`/`HarnessWorkflow` 及两个 `Harnessed*` 服务分别改为 `Governance*`/`Governed*` 命名；测试迁至 `tests/governance/`，导入、装配、AST 安全门禁与当前规范同步更新。`HarnessAudit*` 存储类型、表/审计事件值、`harness_*` 错误码、日志事件名及拒绝日志 `error_type` 保持历史值，以兼容既有观测与审计读取。复审阶段已在专用测试库通过 full（后端 1017 passed），并完成旧报告/审计读取 SQL 回归 34 passed；开发状态保持 `implemented`，等待原审查助手复审，不自行标记 `verified`。

2026-11-07 原审查助手复审通过 T00（`reviewed_tip=f870de1`），随后以 fast-forward 将任务分支合并到 `main`。T00 状态为 `verified`/`approved`；下一审查单元须等待用户明确指定，不自动进入 T01。

2026-11-08 T01 策略包版本与已有规则评估基础实现：新增版本引用/证据 epoch 公共类型、策略草稿/发布/归档目录、受限参数 Schema、只读评估器端口与既有技术突破规则适配器，并新增 `0019_strategy_catalog` 前向迁移（含发布不可变触发器）。原审查助手首轮判定不通过后，已修复相同 request_id 并发重放、嵌套证据/策略内容快照重验及参数 Schema 根节点校验，并补充真实 PostgreSQL 双会话并发回归；修复后后端 full 为 1049 passed。原审查助手已于 2026-11-08 复审通过（`reviewed_tip=159a43b`），T01 代码与复审文档以 fast-forward 从 `e12de3a` 合并到 `main`；T01 状态为 `verified`/`approved`。该能力尚未接入 HTTP API 或前端，不改变当前运行边界、默认审核、自动交易限制或产品规划支持范围；下一审查单元等待用户明确指定，不自动进入 T02。

2026-11-09 T02 可用的关键词 RAG 实现：新增版本化知识文档/不可变版本/分块词项数组、确定性 NFKC 英文词与中文双字词索引、固定 4:1 标题/正文评分、GIN 交集检索、请求幂等与归档历史读取，并新增 `0020_research_knowledge` 前向迁移（正文/分块不可变触发器、工作台/状态/时间/范围过滤）。首轮实现聚焦 30 passed、阶段回归 126 passed、后端 full 1079 passed；独立审查判定 P1（已发布版本仍可追加分块）和 P2（锁等待前采样发布时间）不通过。修复提交 `8835a1d` 增加分块 INSERT 数据库防护、发布/检索的分块集合与版本正文一致性校验、锁后时间采样和受控锁等待回归；修复后聚焦 40 passed、阶段回归 136 passed、后端 full 1089 passed / 0 failed / 0 skipped，架构门禁 38 文件无 findings。原审查助手已于 2026-11-09 复审通过（`reviewed_tip=8835a1d`），T02 代码与复审文档以 fast-forward 从 `fed38bd` 合并到 `main`；T02 状态为 `verified`/`approved`。该能力尚未接入 HTTP API、前端或 Agent 工具循环，未验证真实知识库召回质量、真实模型质量或业务库迁移，不改变当前运行边界、默认审核、自动交易限制或产品规划支持范围；下一审查单元等待用户明确指定，不自动进入 T03。

2026-11-09 T03 规划资料、政策与受支持产品规则实现：新增 C3 本地规划资料/风险政策/成本/保证金证据/公开规则快照契约、单工作台资金池与 generation、请求幂等、不可变版本查询和 BTC/ETH USDT 线性永续逐仓支持目录；新增 Binance USDⓈ-M `exchangeInfo` 类型化读取与真实 `PRICE_FILTER`/`LOT_SIZE`/`MARKET_LOT_SIZE`/`MIN_NOTIONAL` 解析，旧准入方法保持兼容；新增 `0021_planning_inputs` 前向迁移（资金池唯一工作台、版本/请求不可变触发器）。首轮正式审查判定 4 项 P2 不通过后，修复提交 `4f0e7ae` 增加冷却状态显式三态、规则刷新带锁重放、缓存来源时间和网关异常转换；第二轮正式审查判定 1 项历史快照 P2 不通过后，修复提交 `023e5a2` 按 `model_fields_set` 版本感知校验首轮快照原指纹、历史序列化和旧请求指纹兼容；第三轮正式审查判定 1 项旧请求重放 P2 不通过后，修复提交 `8d75a7a` 允许历史 Draft 读取但首次写入严格校验，同时匹配首轮缺字段/第二轮显式 null 两种请求指纹，并用两版实际生成的 fixture 覆盖重放、冲突和并发。修复后纯契约/规则 23 passed、SQL 16 passed、阶段回归 183 passed、后端 full 1128 passed / 0 failed / 0 skipped，架构门禁 38 文件无 findings，迁移 head 为 `0021_planning_inputs`。自测状态为 `verified`，正式审查状态为 `approved`（用户于 2026-11-10 传回原审查助手正式通过结论，`reviewed_tip=8d75a7a`；第三轮受审 tip `023e5a2`，第二轮受审 tip `4f0e7ae`，首轮受审 tip `144e501`）。T03 代码与复审文档以 fast-forward 合并到 `main`。尚未接入 HTTP API、前端或规划数量/风险计算，未迁移业务库，未验证真实公开规则持续可用性、真实产品规则发布或实盘可实施性；不改变自动交易限制、默认审核或现有模拟盘/回测范围。T04 须等待用户明确指定，不自动开始。

2026-11-10 T04 持久任务、修订与安全事件实现：新增 C4 `RunInput`/`RunSnapshot`/`RunStatus`、`AgentRunError`、请求内容指纹、`AgentRunRepository.enqueue/get/list_events`、薄 `AgentRunService.start`、任务内安全事件白名单与游标分页，以及 `0022_agent_tasks` 前向迁移（线程、任务、不可变修订/请求映射/事件、证据/产物前向表、队列单例、owner/lease/终态/删除触发器）。请求键按工作台隔离，同键同内容重放、异内容冲突，不同请求键不按币种合并；全局可运行容量 20，等待态不占运行并发；父任务必须终态且同会话，终态后新工作通过 `parent_run_id` 关联。T04 尚未接入消费者、HTTP API、人工审核/消息、证据冻结或产物提交；`agent_evidence_epochs`/`agent_artifacts` 仅按 C9 预留，未写入占位成功行。聚焦 18 passed、阶段回归 315 passed、后端 full 1146 passed / 0 failed / 0 skipped，Ruff/格式/Pyright/架构门禁全绿，迁移 head 为 `0022_agent_tasks`。自测状态为 `verified`，正式审查状态为 `awaiting_review`（`implementation tip=2e17368`；审查请求 `docs/superpowers/reviews/manual-agent/T04-review-request.md`）。未迁移业务库，未调用真实模型、访问私有账户或发起真实交易；T05 须等待原审查助手正式通过，不得自动开始。

2026-11-04 报告 `4a89ab15-867e-4c92-8531-697f2d8fca46` 降级诊断与长度压缩修复：三次尝试分别为 `trading_instruction`（3 个驱动/专题字段）和两次 `narrative_length`（3433、2993 字符）；模型在重试后已避开交易措辞，但正文超长未被压缩器救回。修复包括：`headline` 进入压缩候选；压缩到不超过 2500 即接受，不再因未达到 2200 目标而回退原文；极长句无句号时允许退到完整分句；仍超长时按整条程序事实省略并写入限制；Prompt 与重试明确全文不超过 2500、headline/heading 不超过 30 字，并提示描述情绪时也不要用“做多/做空”。新增标题压缩、分句回退、事实按长度省略与交易措辞重试回归；未调用真实模型，运行中容器仍是旧镜像，需重建后再生成本地报告。

2026-11-04 报告 `b6de0fa2-85af-45a9-821a-975b405e0870` 降级诊断与部分事实恢复：该次三次尝试均为 `unbound_numeric_claim`（`numeric_symbol` 与 `chinese_quantity`），不是事实引用与段落证据不匹配；正文已经把数字直接写进叙述，没有可丢弃的 `fact_refs`，因此过滤事实引用不会救回该次。随后实现可定位单条事实引用的部分恢复：未知事实、未知目标、跨证据、重复或单段超额只丢弃该项并保留定性正文，省略数量写入既有 `limitations`；根形状错误仍整份拒绝。正文自由数字按完整句替换为固定省略句，不展示未验证数字；标题、枚举、标签和 timing 仍拒绝，无法保留中文内容或正文长度不足时回退整份降级。圈号等纯枚举符号不再被当作数量；Prompt 与纠错明确禁止中文数量、圈号、罗马数字、分数/上标等写法。新增/更新事实引用、模型、契约与页面回归；未调用真实模型，运行中容器仍是旧镜像，需重建后再生成本地报告。

2026-11-04 事实引用协议与重试诊断优化：综合研究 `structured-v1` 现在只允许 `fact_refs.target` 指向带 `evidence_ids` 的叶子段落，`short_term.thesis`/`long_term.thesis` 不再接受事实引用；每段上限由三条提高到五条，并新增多 evidence 段落与叶子目标示例，明确“fact 的 evidence_id 必须出现在目标段落自身 evidence_ids 中”。政策计数与 ETF 交易日/美元净流量明确为不在 `numeric_facts` 目录中的专题区数值，正文只做定性解释，不得编造 fact_id。拒绝诊断把重复引用与单段超额拆成独立类别，并在纠错请求中追加服务端构造的 target、事实标签和 evidence UUID 提示；完成原因为 `length` 时使用截断专用提示并保存 `model_output_truncated` 类别，完成原因与 completion tokens 进入安全日志。UUID 证据绑定按规范字符串比较，大小写或连字符差异不再误判。新增/更新事实引用、模型提示、契约、API、页面与离线评估回归；未调用真实模型，生产 `max_tokens` 仍为 7000，扩容需真实截断证据后再评估。

2026-11-04 综合研究降级诊断契约修复：本机运行 `4b59b358-381c-449e-a198-6324f8774a49` 在三次模型尝试后降级。日志显示前两次分别因 `fact_refs.11` 的 `fact_evidence_mismatch`、`fact_refs.3/4/5` 的 `duplicate_or_excess_fact_reference` 与 `fact_evidence_mismatch` 被拒，第三次为单条 `schema`；报告已按 `degraded`、`model_invalid_response` 保存，未展示模型正文。排查确认请求输入、行情/新闻/专题冻结与 HTTP 传输正常，失败来自模型输出未满足结构化事实引用协议。同时发现 `ModelValidationFailure` 与前端 Zod/标签只允许旧的六类文本与结构类别；若最终尝试停在新的数值/事实引用类别，降级报告会在保存或前端解码时失败。已将七类事实引用诊断纳入后端白名单、前端 schema 与中文标签，并补充契约、API 与页面回归；页面摘要明确为“最后一次尝试发现 N 项问题”，避免把末次摘要误读为累计问题。随后同日批次完成协议与重试提示优化；未调用真实模型重测接受率。

2026-11-03 独立引用协议真实单案验证（代码基线 `281d4d5`）：经用户要求，仅用当前flash运行 `baseline-history`，上限三次请求，实际三次（含两次格式纠错），耗时48.110秒，输入12745、输出6795 token，usage完整；未提供单价，不估算账单。案例被拒绝，接受0、错误0、额度阻塞0。前两次为 `unbound_numeric_claim`，安全数字类别均为 `numeric_symbol`（分别六处和五处）；第三次在 `fact_refs.3` 触发 `duplicate_or_excess_fact_reference`，即重复引用或同一目标超过三条，不能凭该聚合类别区分两者。拒绝原文未保存，不能推断具体符号或事实值。已在三次上限停止，不自动追加付费请求；本地复核产物无已接受提案，真实基线仍未通过，具名人工质量评分仍未完成。新协议版本指纹与安全诊断留在忽略的本地产物；不能将运行completed或脚本退出0误称为案例通过。

本批离线验证：根目录统一full全部22项通过，后端982项且零跳过，前端lint/typecheck/test/build、迁移与两组离线评估通过；独立测试库临时schema为零且实例已回收。未新增付费模型、浏览器或完整Compose运行证据。

2026-11-03 独立事实引用优化：综合研究改用根级 `fact_refs`（`structured-v1`），正文保持定性，程序验证可见事实、规范目标与段落自身证据后追加完整字段/单位/UTC时段，并在保存前移除数组。最多十六条、同段三条，重复和旧内联token拒绝；压缩保留全部已选事实，不能容纳则拒绝。安全诊断增加固定数值/schema类别并遮蔽未知键。无数据库或前端契约变更，v1/v2固定输入及历史报告不改；本批无付费调用，真实接受率与具名人工复核仍未完成。方案见[独立引用协议](superpowers/plans/2026-11-03-structured-fact-refs.md)。

2026-11-02 新闻条目隔离：逐条隔离已知元数据/时间/URL/英文规范化拒绝，保留合法条目；未知程序异常、网络与安全响应错误仍按整源失败处理。每次请求返回局部安全计数，兼容原有 `fetch_items` 调用；协调器在币种筛选前计算来源窗口覆盖。报告沿用冻结 `limitations` 和 `sourceCoverage`，分别说明读取失败、过滤、空订阅、窗口无内容及预算截取，不新增迁移或改写旧报告。公开源诊断同步反映过滤导致的部分覆盖。

2026-11-01 研究币种同步恢复：新增携带失败任务 ID 的手动重试 API 与管理页操作，目录行锁合并并发请求，迟到的旧失败请求不再排队。单 worker 默认整任务 120 秒、心跳 10 秒、租约 30 秒；领取前回收过期运行，失租取消采集，不自动重放失败任务。页面区分研究资格与最新同步状态，只在有活跃任务时轮询。复用现有表和依赖；设计及验证范围见[同步恢复设计](superpowers/specs/2026-11-01-symbol-sync-recovery-design.md)。

研究运行验收批次：扩展独立 HTTP 工厂，以合成行情和固定模型传输运行真实技术 v2 队列，BTC 完成、ETH 缺配置降级；新增报告刷新、历史列表和新会话读取。回收测试 schema 前先停止 worker/模型客户端。新增真实数据库故障恢复测试，不修改生产 worker、仓储规则或 schema；取消指协程/worker 生命周期，当前不增加用户取消 API，也不自动重放失败任务。

2026-10-31：统一入口新增 `http-e2e`、AST 架构门禁及研究服务流程评估；pytest 安全插件保留失败代码标识，移除参数化值，零执行、缺失或损坏产物不可通过。CI 增加分支 push 触发、真实 HTTP 流程及两套评估/测试摘要归档。该工作不修改生产 schema、依赖锁文件或模型权限，远端 CI 与合并门禁仍需独立验收。

2026-10-27：新增统一质量入口、GitHub Actions 配置、测试库预检和离线契约评估，运行契约见[质量验证](quality-verification.md)。数据库测试仅接受进程显式 `TEST_DATABASE_URL`，不再从 `.env` 自动授权；未修改业务配置、schema 或依赖锁文件。为使格式门禁可用，对 66 个存量文件执行 Ruff 机械格式整理：历史迁移 AST 不变，两处普通函数文档字符串缩进调整，其他格式文件 AST 不变。首次浏览器回归发现两条旧用例填写非 UUID 交易腿 ID，已改为合成 UUID，保持应用契约不变。

研究币种准入失败返回结构化、安全的检查详情，管理页展示后端消息并去重检查提示。公开行情超限、限流和超时使用固定摘要，不透出上游异常原文。Binance 公开 JSON 响应上限调整为 1,500,000 字节，允许原上限以上的正常合约目录，仍拒绝超过新上限的响应。相关回归见[错误接口测试](../backend/tests/api/test_errors.py)、[行情适配器测试](../backend/tests/market/test_binance_usdm.py)、[资金费率测试](../backend/tests/market/test_funding_history.py)、[准入服务测试](../backend/tests/symbols/test_service.py)及[页面测试](../frontend/src/test/research-symbols.test.tsx)。

共享文档按当前代码整理开发入口、数据模式、来源与验证要求。工具会话、诊断文件、测试临时目录及本地备份不属于项目交付文件。

后端全部 248 个 Python 文件（源码、脚本、测试和历史迁移）补充中文注释，说明职责、关键流程、契约、失败路径与设计原因；可添加注释的构建配置同步补充说明。根目录与后端 `AGENTS.md`、[AI 维护指南](ai-maintenance.md)明确 AI Agent 生成代码必须维护详细注释，具体要求见[后端规范](../backend/AGENTS.md#代码注释与-ai-agent-生成原则)。锁文件、严格 JSON/XML 样本、版本标记与冻结技术方法保留原内容；Windows Alembic 配置采用 ASCII 注释以兼容本地编码读取。

## 最近验证

2026-11-04 长度压缩与交易措辞回归：根目录统一 `quick` 的 19 项检查全部通过；后端 915 collected/passed，零失败、跳过或收集错误；前端依赖、lint、typecheck 与 Vitest 通过；离线评估与研究流程评估通过。新增回归覆盖超长 headline 压缩、无句号长句退到分句、达到 2500 上限即接受、按整条事实省略以满足篇幅，以及交易措辞重试提示。未运行数据库 pytest、浏览器验收或真实付费模型；运行中 Compose 容器仍是旧镜像。本批验证结果位于本地忽略产物 `.tmp/quality/length-quick.json`。

2026-11-04 部分事实恢复与降级诊断验证：根目录统一 `quick` 的 19 项检查全部通过；后端 912 collected/passed，零失败、跳过或收集错误；前端依赖、lint、typecheck 与 Vitest 通过；离线评估与研究流程评估通过。新增回归覆盖单条事实丢弃、合法事实保留、自由数字按句省略、非叙述字段仍拒绝、圈号不按数量处理，以及 `b6de0fa2` 同类的 `unbound_numeric_claim` 字段摘要。未运行数据库 pytest、浏览器验收或真实付费模型；运行中 Compose 容器仍是旧镜像。本批验证结果位于本地忽略产物 `.tmp/quality/redaction-quick.json`。

2026-11-04 事实引用协议优化验证：根目录统一 `quick` 的 19 项检查全部通过；后端 906 collected/passed，零失败、跳过或收集错误；前端依赖、lint、typecheck 与 Vitest 通过；离线评估与研究流程评估通过。事实引用、模型、契约、API 与评估工具的聚焦回归另行通过，Ruff、格式和 Pyright 通过。未运行数据库 pytest、浏览器验收或真实付费模型；生产 `max_tokens` 仍为 7000，截断扩容需真实 `finish_reason` 证据后再评估。本批验证结果位于本地忽略产物 `.tmp/quality/fact-refs-quick-final.json`。

2026-11-03 数值协议定向优化：经用户要求先做基线单案诊断，三次均在 `market_overview.summary` 触发 `unbound_numeric_claim`，首次拿到逐次类别；不能据此推断未保存原文中的具体数值。新增 `--case` 并明确单案选择范围；按机器类别解释日期/时刻/周期数字/根数的引用限制，提供同次输入的合法片段及渲染后字符预算。可见目录最多十六条，按来源/字段交错、同组首尾优先，Prompt与渲染器共用规则；完整64条冻结事实和v1/v2输入不改，不允许引用隐藏token，也不把目录筛选冒充证据缺失。方案见[定向优化](superpowers/plans/2026-11-03-numeric-protocol-optimization.md)。

本批诊断与优化验证各三次、合计六次付费请求，均使用当前flash且只运行基线。优化构建期验证仍拒绝：首次schema、后两次分别为概况和短期驱动段的未绑定数字，未获接受；同样三次请求输入由27160降至12140 token（约55%），输出由7863增至8690，不能将输入下降说成总费用下降或质量提高。该次schema路径曾被泛化，随后已修复已知契约字段的安全诊断保留，未知键/错误值仍不回显；不回填旧报告。验证后补充目录预算不等于数据缺失的措辞与回归，未再付费。六次上限已停止，不扩展其他案例，真实协议可用性与具名人工评分仍未完成。

另依据错误位置逐段推进与代码复现，补充多字段有界反馈：原先遇到首个数值问题即停止，现一次提供最多八个位置/九十九个问题，整份候选仍拒绝；未知键和原文不回显，临时部分渲染不返回。两项测试先失败后通过，独立审查验证三项回归及三百个坏字段的封顶拒绝，无剩余P1/P2。此补充只做离线验证，没有追加付费或宣称真实接受率提高。

本批根目录统一 `full` 的22项检查通过（多字段补充前后端947项）；补充后最终根目录 `full --component backend` 的15项全部通过，后端949 collected/passed、零失败/跳过/收集错误，同批前端七项检查通过且未修改前端。最终聚焦183项、Ruff/格式/Pyright通过；独立审查无剩余P1/P2。单案prepare为0次调用，冻结64/可见16、引用示例与字符预算校验通过；v1/v2所有JSON逐字保持，链接与差异检查通过。测试库全部非系统临时schema为0且一次性容器已回收；未改配置、依赖或数据库schema，未推送或执行远端CI。构建期付费结果仍为拒绝，不能将代码检查通过当作真实质量验收。

2026-11-02 付费评估后修复：用户选择保留正文数值，已接入[结构化事实引用与程序渲染](superpowers/plans/2026-11-02-research-factual-consistency.md)。目录由冻结结构化快照/上下文/标量专题生成，模型只选择独占行token，程序渲染完整字段、单位和UTC范围；自由数值与未知/跨证据引用在压缩前拒绝，渲染后复用原长度/交易语言/引用校验。不修改数据库或前端契约，不回写历史报告。未请求专题时非空解读亦被拒绝，沿用 `model_invalid_evidence` 且不重试。独立v2评估输入新增结构化历史K线事实目录，v1保留；尚不能宣称整体语义质量通过。

v2协议构建过程中的真实复测使用当前flash及8次请求额度：1案接受、2案在三次格式尝试后拒绝、1案在一次候选后因总额度阻塞；耗时117.361秒，输入64944、输出18783 token，均有usage。与首轮合计12次请求，未追加费用额度或估算账单。该次报告未保留逐次拒绝类别，无法事后确定具体门禁原因；随后已补充安全的逐次类别/契约字段/计数，并回归真实观测与统计截止分离、无交易日期ETF不猜测绑定。后续改动未再付费复测，各次证据以版本指纹区分。唯一接受的稀疏案例不再生成未请求专题，但辅助复核发现“中性即风险大致对称”的语义仍需质疑；拒绝/阻塞案例不评分，具名人工评分均pending，不能宣称协议可用性或质量验收通过。

本批审查前根目录统一 `full` 的22项检查曾全部通过（后端939项）。独立审查又复现两项P2：压缩在事实内部分号截断、公开上下文误读字段而目录为空，已补失败后通过回归并修复；审查者独立复跑两项通过，无剩余P1/P2。压缩保护完整事实；上下文由真实DTO投影，明确集合参考时刻不代表逐项实际观测。审查后最终根目录 `full --component backend` 的15项检查全部通过，后端941 collected/passed，零失败/跳过/收集错误；同批前端node/npm/依赖/lint/typecheck/Vitest/build七项通过。最后聚焦175项通过；完整范围那次曾读取到修正前测试夹具的类型错误，修正后的类型与全部后端检查已由最终15项入口重新验证，未将失败报告称为通过。

两份旧错误提案离线回放均按未绑定数值拒绝，v2准备四案成功且模型请求为0。全量曾发现安全诊断依赖全局缓存日志器，已通过显式有界诊断回调修复；早期无测试库的3项阻塞由专用库全量覆盖，未称为通过。v1全部JSON字节不变，v2暂存字节/来源SHA/生产事实重建、文档链接与差异检查通过。一次性测试库全部非系统临时schema为0且容器已回收，未推送或执行远端CI。时点、诊断及独立审查修复后未再付费，真实协议接受率仍待改进；以上是代码门禁证据，不是本批真实模型质量通过。

2026-11-02 首次真实付费模型评估：经用户明确要求，使用项目当前配置 `deepseek-v4-flash` 运行四案固定语料，实际4次HTTP请求、0次格式纠错，四案全部通过生产合同与引用ID校验；用时54.306秒，供应商返回输入6334、输出8700 token。未提供单价，未估算或宣称实际账单金额。运行限制为最多12次请求、输入131072字节、输出7000 token、单次60秒/总300秒；未改生产配置、Prompt、校验或数据库。

本次 Agent 辅助内容复核发现两例实质数值错误：baseline-history 将窗口最低价写为76717.00，真实窗口最低价为76444.00，并错配成交量时段；conflicting-evidence 总览将首根收盘77208.20当成开盘（实际77962.60），低点亦与正确正文矛盾。稀疏案例承认证据不足，但生成未请求的政策专题并引用市场证据，需复核语义；注入案例未输出攻击哨兵，明确排除合成新闻，但单例不能证明普遍抗注入。故4/4合同接受不构成质量通过。具名人工评分仍pending；本地安全报告、已接受提案与明确标注的Agent辅助复核均在忽略目录，未将模型正文或配置纳入提交。

本批仅执行既有工具并更新说明：`backend/` 安全文档测试55项通过，文档相对链接与差异检查通过；未修改可执行代码，未重跑全量，上一工具建设批次的22项完整验收/921项后端测试证据保留其原范围。

2026-11-02 真实模型评估工具建设：新增四案固定语料，基线为公开BTC历史十二根小时K线，其余为显式合成冲突/稀疏/不可信指令扰动。新增默认离线prepare、显式live的综合模型适配器入口，实际HTTP纠错请求也计入额度，安全报告与可选已接受提案人工复核产物分离。程序只报告合同接受与运行指标，语义评分保留人工pending。本批不改生产Prompt/模型校验/风控，不执行付费调用，也不宣称真实质量已获验证。用法见[评估说明](../backend/evaluation/real-model/README.md)。

本批在根目录运行统一 `full`，22项检查全部通过，后端921 collected/passed、零失败/跳过/收集错误，前端lint/typecheck/Vitest/build通过。后端评估工具聚焦40项、安全55项另行通过；实际四案prepare成功且模型请求为零。修复并回归压缩响应、极端单价、文件独占与关闭失败处理；固定JSON使用LF且暂存字节与来源指纹一致。文档相对链接及差异检查通过，一次性测试库临时schema为0且容器已回收。首次full因Docker未运行被阻塞，启动引擎并新建专用测试库后完整重跑通过；未将首次阻塞当作成功，未运行远端CI、推送或付费模型。

2026-11-02 来源范围调整：按用户要求从活动白名单删除 Treasury/CFTC RSS，剩余 SEC、美联储、CoinDesk、Decrypt、Blockworks、The Block 六源；政策来源覆盖分母同步为 SEC/美联储。默认公开源诊断22项，含情绪/ETF时25项。历史来源记录和冻结报告保留，无数据删除、迁移或来源供应商新增。

本批统一 `full` 的22项检查全部通过，后端881 collected/passed、零失败/跳过/收集错误，前端lint/typecheck/Vitest/build通过。聚焦109项及文档安全55项通过；真实25项诊断不含退役两源，六个RSS均可读取，过滤或预算截取仍明确为部分覆盖。文档链接和差异检查通过，临时schema清零且测试数据库容器已回收，未推送或运行远端CI。

2026-11-02 集中收尾：逐项核对历史优化，当前本地可执行项已汇总至[优化收尾清单](optimization-closeout.md)。补齐综合研究生产采集/新闻隔离/冻结证据/缺配置模型/真实SQL新仓储重读和不可变审计回归；由此发现并修复 Harness 降级事件读取不接受数据库已保存安全错误码的兼容缺陷，完成事件约束保持不变，无schema变更。可选情绪/ETF三项真实诊断通过；另以真实公开源运行一次隔离综合研究，23份证据、部分覆盖、零模型HTTP传输，降级报告与新仓储重读一致。固定测试与实时采集的证明范围分别记录，不等于真实模型质量验收。

集中收尾最终验证：根目录统一 `full` 的22项检查全部通过，后端878 collected/passed，零失败/跳过/收集错误，前端lint/typecheck/Vitest/build通过。上下文诊断离线40项、Harness聚焦56项及综合SQL闭环1项通过；文档安全另55项通过。独立复核无P1/P2，链接与差异空白检查通过。测试schema清零且独立tmpfs数据库容器已回收。未执行付费模型、业务迁移、远端CI或推送；外部不可用及预算依赖继续明确保留。

2026-11-02 新闻源地址与网络批次：CoinDesk 旧链接 308 仅去掉末尾斜线；直接验证同站规范路径 HTTP 200 后，更新固定登记地址，继续禁止自动跳转。生产适配器实测保留 20 条近期新闻、拒绝 0 条、预算截取 5 条，标为部分覆盖。Treasury 主机/临时容器在 5 秒及一次 15 秒复查均读超时，CFTC 两侧均 403；未发现需要修改本地配置的分歧，也没有成功证据支持增加生产超时。CFTC 官方另公告 RSS 自 2026 年 10 月起暂时停用，保留失败覆盖。官方依据、检查范围及资源回收见[地址复核记录](public-source-endpoints.md)。

本批根目录统一 `full` 的 22 项检查通过，后端 856 collected/passed、零失败/跳过/收集错误，前端 lint/typecheck/Vitest/build 通过。聚焦新闻/安全/诊断测试 128 项通过，文档更新后安全检查另 55 项通过；链接和差异空白检查通过。测试临时 schema 清零且专用数据库容器已回收；未修改业务配置、数据库 schema 或依赖，未运行远端 CI、推送或付费模型。

2026-11-02 新闻逐条隔离批次：RSS 元数据/英文文本校验拒绝不再拖垮合格条目；请求局部计数区分拒绝和返回预算截取。报告完成及降级分支沿用现有冻结限制字段，来源覆盖有过滤/空源/保留样本无近期/截取时不标为完整。新增未知异常、取消、安全 XML、并发计数、预算后拒绝及截去近期样本的回归；聚焦后端 120 项通过。完整与降级报告的新说明及旧报告兼容由前端页面回归验证，无新增迁移或外部来源。

本机于 `2026-11-02T07:11:03Z` 至 `07:11:11Z` 使用修改后的生产适配器只读复验：24 分项为 17 passed、4 partial、3 failed，按契约退出 1。BTC/ETH 市场 16 项仍全部通过；Federal Reserve 保留 18 条、拒绝 2 条，Blockworks 保留 20 条、拒绝 2 条、预算截取 28 条，两者不再整源失败。Blockworks 保留样本的近七日条数为 0，不推断其余条目。SEC 与 Decrypt 也因返回预算截取而明确标为部分覆盖；The Block 通过。CFTC 拒绝、Treasury 超时、CoinDesk 重定向仍是未解决的来源读取问题，本批未修改固定源地址或放宽边界。该次主机复验不代表完整报告或模型质量验收。

本批根目录统一 `full` 的 22 项检查通过，后端 855 collected/passed、零失败/跳过/收集错误，前端 lint/typecheck/Vitest/build 通过。后端安全文档另 55 项通过，前端报告页面聚焦 33 项通过；独立审查发现的保留样本窗口误称全源问题已修复并补回归，无剩余 P1/P2。文档相对链接与差异空白检查通过，测试临时 schema 为 0，专用 tmpfs 数据库容器已回收。未运行远端 CI、推送、业务迁移或付费模型。

2026-11-02 同步诊断与真实公开源批次：管理页新增 UTC 生命周期、白名单中文失败原因和逐来源覆盖；目录解码只保留展示字段，来源正文/载荷与原始阶段不进入诊断投影，未知失败与重试错误不回显任意正文。前端新增行为及契约回归先失败后通过，聚焦 31 项通过；两条真实 HTTP 同步旅程已验证部分覆盖或再次失败后的时间、原因、来源状态、刷新和新会话读取。没有更改同步状态机、准入条件或交易能力。

本机进程于 `2026-11-02T03:55:07Z` 至 `03:55:15Z` 显式运行公开源诊断，24 项中 19 项通过、5 项失败，命令按契约退出 1（部分通过）：BTC/ETH 的合约、摘要、四周期、衍生品及七日费率共 16 项全部通过，两币种各有 21 条费率记录；SEC、Decrypt、The Block 三个 RSS 解析及近七日覆盖通过。其余源有限复核：CFTC 返回 403，CoinDesk 返回 308 且未跟随跳转，Treasury 超时；Federal Reserve 和 Blockworks 返回 HTTP 200/XML，但被现有英文文本规范化校验拒绝，不属于连接失败。复核只记录安全类别，未保存新闻文本或放宽语言、大小及重定向边界。

以上是单次主机环境下的生产适配器读取证据，不能推广为容器网络、长期可用性或完整研究报告质量；本次未验证情绪/ETF，不调用真实模型、不读取业务数据库或修改环境配置。重现命令、阈值及安全摘要范围见[手动验证真实公开源](quality-verification.md#手动验证真实公开源)。

本批根目录统一 `full` 的 22 项检查全部通过，后端 837 collected/passed、零失败/跳过/收集错误，前端 lint/typecheck/Vitest/build 通过；统一 `http-e2e` 五条旅程通过。公开源脚本的 20 项离线回归与 55 项安全测试另合计 75 项通过。审查收窄了聚合时间检查的证明范围，未改生产适配器。专用 tmpfs 测试数据库结束时临时 schema 为 0，核对标签后移除测试容器；本批未运行远端 CI 或推送。

2026-11-02 币种同步 HTTP 验收：新增 SOL 首次失败后手动重试为部分覆盖、XRP 再次失败两条浏览器旅程，经真实重试路由、生产同步 worker、SQL 租约/审计及快照仓储，验证 202 入队、运行中禁用与轮询、重复请求复用、旧失败请求 409、刷新及新上下文读取。初次失败同样由 worker 写入，目录与行情来自固定合成夹具；未注入资金费率，未将部分覆盖宣称为就绪。修复 Playwright worker 重载配置时重新生成 token 导致控制请求 403 的验收配置问题；测试控制入口只在独立验收服务注册，生产应用未增加接口。

根目录统一 `full` 的 22 项检查全部通过，后端 817 collected/passed、零失败/跳过/收集错误，前端 lint/typecheck/Vitest/build 通过；统一 `http-e2e` 的五条浏览器旅程通过，后端目录安全文档回归 55 项通过。独立只读审查未发现 P1/P2；四份说明相对链接与 `git diff --check` 通过。测试使用本次独立 tmpfs PostgreSQL 和受限身份，结束时临时 schema 为 0，核对标签后移除测试容器。未新增生产依赖、迁移或业务接口，未操作远端 CI、推送、业务配置或真实公开源。

2026-11-01 隔离 Compose 验收，代码基线 `bf35bb0`：使用现有生产 Dockerfile 构建当前 API、前端及恢复实例的独立前端镜像，经实际入口迁移启动 PostgreSQL/API/Nginx。API 与数据库仅连接独立 internal 网络，空模型密钥且未设置非空代理环境变量；前端额外使用独立入口桥接网，仅发布回环端口。本机 Docker Desktop 的纯 internal 网络未发布宿主机端口，临时拓扑调整后重新启动验证通过，没有修改业务 Compose。

真实生产页面保存合成交易日志，刷新和新 context 重读通过。随后 API 重启的 `StartedAt` 改变，保留原卷的 down/up 使三个容器 ID 均改变；再将 `pg_dump` 自定义格式备份恢复到不同卷、不同数据库集群的空库。四个阶段的同一交易 ID、完整响应 SHA256 与迁移链头 `0018_technical_report_runs` 一致。共四次浏览器验收通过；最终停止原栈，恢复实例的新浏览器只请求自己的入口，仍能读取原记录。两个研究币种在隔离网络下的初始同步均为失败，未冒充公开源同步成功。

本批证明范围是合成交易日志及迁移链在正常重启、保卷重建和逻辑备份恢复后可用；不覆盖全部业务数据、断电恢复、PITR、真实公开源或模型质量。没有修改生产代码、Dockerfile、业务 Compose、依赖或 schema；没有执行远端 CI、推送、合并或部署到业务环境。详细步骤与资源回收结果见[验收记录](superpowers/plans/2026-11-01-isolated-compose-acceptance.md)。

本地版本收尾：2026-11-01 在开发分支按纯格式整理、质量与研究验收、同步恢复形成三组本地提交。提交前重新执行统一 `full`，22 项检查全部通过，后端 813 项测试通过且零跳过，前端 lint/typecheck/Vitest/build 通过。收尾审查修正了运行边界文档中仍否认失败重试端点的旧说明。没有推送、合并、运行远端 CI、设置合并门禁或部署；此前各批次的“未提交”等记录保留其当时的验证状态。

2026-11-01 同步恢复批次：根目录 `uv run --project backend --locked --no-sync python scripts/verify.py full --report .tmp/quality/symbol-sync-full.json` 的 22 项检查通过，包含前端 lint/typecheck/Vitest/build。独立审查发现并修复终态提交等待期间未持续监控心跳的竞态，新增用例先失败后通过；随后执行 `full --component backend --report .tmp/quality/symbol-sync-backend-final.json`，最终 15 项后端检查通过，813 collected/passed，failed/skipped/collection_errors 均为 0，包含 Ruff/格式/Pyright/AST/迁移链头及两套离线评估。

同批统一 `http-e2e`（3 条）与 Mock `e2e`（16 条）通过。新增重试交互由 Vitest 验证、真实 HTTP 路由及 SQL 由 pytest 验证；已有浏览器流程只作为回归，不宣称新增同步重试已做浏览器全链验收。真实 SQL 另覆盖心跳延寿、归档取消、超时/取消可重读、快照提交后取消；队列短暂故障后的消费恢复也有回归。审查复核无剩余 P1/P2 阻断项。临时 schema 残留 0，独立 PostgreSQL 17 测试容器已回收。

本批无新增依赖或迁移，不连接真实公开源或模型，不修改业务数据库、生产配置或交易能力；未提交、推送、运行远端 CI 或部署。完整 Compose 启停/生产进程重启仍待独立验收。

研究运行验收批次：根目录统一 `full` 最终通过，安全摘要记录 790 collected/passed，failed/skipped/collection_errors 均为 0。后端 Ruff/格式/Pyright/AST/迁移链头/两套评估及前端 lint/typecheck/Vitest/build 均通过；统一 `http-e2e` 的日志、研究完成、研究降级共 3 条用例通过，统一 Mock `e2e` 的 16 条通过。

专用 PostgreSQL 17 使用受限角色与随机 schema；实际终止 worker 子进程后验证租约恢复，另外验证保存后收尾故障、模型执行中取消、提交报告后取消、并发去重与旧所有者拒绝。独立只读审查无 P1/P2 阻断项；审查后补充的提交后取消窗口纳入最终全量回归。临时 schema 残留 0，测试容器已回收。没有修改生产 worker/仓储规则、业务数据库、迁移链或模型权限，未提交、推送、部署或运行远端 CI。

证明范围：实际被终止的子进程使用阻塞执行器，完整 Harness/适配器链由其他测试覆盖；浏览器新 context 不等于后端 OS 重启。只验证 worker/协程取消，未新增用户取消接口。固定响应及合成行情不代表真实模型质量或公开源连通性。

2026-10-31，根目录统一 `full` 最终通过，安全 pytest 摘要记录 collected/passed 均为 780，failed/skipped/collection_errors 均为 0：

- 后端 Ruff、格式、严格 Pyright、AST 架构门禁、完整 pytest、迁移链头及两套离线评估通过；AST 扫描 32 个受保护源码文件，0 findings。适配器评估 8/8、服务流程评估 9/9 匹配，后者接受 2、拒绝 2、降级 3、证据不足 2。
- 前端 lint、typecheck、完整 Vitest、build 通过；统一 `e2e` 的 16 个 Mock 浏览器用例通过，统一 `http-e2e` 的 1 个真实 HTTP/PostgreSQL 浏览器闭环通过。HTTP 测试库使用独立临时 PostgreSQL 17、受限角色及随机 schema，没有访问业务库。
- 新增真实 SQL 回归覆盖三类技术 v2 降级历史重读及 Harness 审计；独立代码审查未发现需阻断的 P1/P2 问题。共享链接、workflow YAML 解析与 `git diff --check` 通过。
- 本地验证不替代远端 CI；本轮尚未提交、推送、运行 GitHub Actions 或设置分支保护。未部署、迁移业务库、调用真实模型或验证真实公开源。

2026-10-27，本次质量基础设施变更后，在仓库根目录执行 `uv run --project backend --locked --no-sync python scripts/verify.py full --report .tmp/quality/full-final.json`，最终退出 0，各检查均为 passed：

- 后端 Ruff lint、格式检查、Pyright、完整 pytest 706 项通过；测试使用新建独立 PostgreSQL 17 与受限测试角色，迁移链头仍为 `0018_technical_report_runs`。临时测试容器已停止并自动清理，未迁移业务库。
- 前端 lint、typecheck、完整 Vitest 和 build 通过。单独执行统一入口 `e2e`，两个桌面视口下共 16 个 Mock 界面用例通过；首次运行中的过期非 UUID 测试输入已修复。
- 适配器离线评估 8/8 预期匹配：接受 2、拒绝 4、可降级错误 2；未调用真实模型。详细样本、版本与证明范围见[评估说明](../backend/evaluation/README.md)。
- 独立代码审查发现并修复 `PYTEST_ADDOPTS` 污染风险；首次运行临时目录缺失也已补红绿回归。共享文档链接、workflow YAML 解析及 `git diff --check` 通过。
- 未推送、执行远端 GitHub Actions、设置分支保护、重新部署、迁移业务库或验证真实公开源及付费模型。HTTP/数据库端到端验收与真实模型质量基准仍未完成。

2026-10-14，在本次整理的工作区执行：

- `backend/`：`uv run ruff check .`、`uv run pyright` 通过；完整 pytest 656 项通过，数据库测试使用独立、无持久化卷的 PostgreSQL 测试实例。`uv run alembic heads` 返回 `0018_technical_report_runs`。
- `frontend/`：lint、typecheck、完整 Vitest 299 项和 build 通过；构建保留单包超过 500 kB 的体积提示。
- 共享文档的相对链接与 `git diff --check` 通过；运行边界安全文档测试包含在后端全量测试内。
- 未运行 Playwright、真实公开源连通或付费模型验证，未重新部署或迁移业务数据库；上述测试不替代运行环境与模型质量验收。

2026-10-14，后端注释整理后再次验证：`backend/` 的 Ruff、Pyright 和完整 pytest 656 项通过，使用独立无持久化卷的 PostgreSQL 测试实例及专属 pytest 临时目录；迁移链头仍为 `0018_technical_report_runs`。全部 248 个 Python 文件的可执行 token、AST 和原始代码行与整理前一致，新增行仅为 `#` 注释；构建配置的有效值和非注释行保持一致，容器入口仍使用 LF。相对链接与 `git diff --check` 通过。本次仅验证后端及相关文档，未重新运行前端、公开源或真实模型验收。

## 已知差异与待验收项

- 研究币种管理保持单 worker；2026-11-01 补齐 120 秒整任务上限、10 秒心跳和手动失败重试。历史 [2026-09-07 计划](superpowers/plans/2026-09-07-research-symbol-management.md)中的双 worker 未实施，不能将该计划全部勾为完成。原始行情保存与同步任务终态仍是独立事务，失租前已提交的行情不会回滚；旧任务不能再改写同步状态、来源或快照关联。
- 初始同步采集行情/K 线/衍生品和资金费率。资讯、情绪留待报告运行时按需采集；管理侧 ETF 能力当前标为不支持。报告侧另有 BTC/ETH ETF 适配器，两个状态不能混为一谈。
- 技术研究的数值与价格由确定性程序计算或按冻结字段渲染，模型不能改写数值、扩大交易范围或自动执行条件计划。历史触发状态冻结，到期不自动重算。
- 当前迁移链头为 `0018_technical_report_runs`，v2 部署需前后端与该迁移配套。测试库迁移通过不代表业务库已升级；业务环境须按[部署说明](local-deployment.md)另行验收。
- 真实模型曾出现数值、引用和交易措辞校验降级；有限纠错与合法段落保留已有实现。首次四案付费评估已执行，4/4合同接受但Agent辅助复核发现两例实质数值错误，尚未获得正向质量结论，具名人工评分未完成。既有离线回归和单次真实样本不代表长期真实质量、普遍抗注入能力或交易表现。
- 当前活动来源已按用户要求删除 Treasury/CFTC，两源不再采集或计入政策覆盖分母。历史超时/拒绝记录仅作诊断档案，不列为当前恢复待办；历史报告与新闻来源归因保留。其余来源仍按实际过滤与预算情况显示覆盖，单次检查不代表长期可用性。
- 当前交付使用本地验收，远端 CI 与合并门禁不纳入本轮交付要求；已有 workflow 配置保留但未运行。HTTP 浏览器验收覆盖日志及技术 v2 的局部装配；另有完整生产 Compose 的日志、进程重启和备份恢复验收，两类证据不能扩展为整站功能或真实模型质量。AST 门禁只覆盖可解析直接依赖，不是任意动态代码执行安全证明。
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
