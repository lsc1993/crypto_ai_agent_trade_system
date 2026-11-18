# AI 研究与 Harness 维护指南

本指南描述当前项目实现，配合[根目录规则](../AGENTS.md)、[后端约定](../backend/AGENTS.md)与[运行边界](operational-boundaries.md)使用。能力进展和未完成项见[项目状态](project-status.md)。

文中的“Harness”指系统级运行支撑与治理能力；其策略准入和审计内核现位于 `backend/src/app/governance/`。`HarnessAudit*` 存储类型、既有 `harness_*` 表/审计事件值和日志名保留，用于读取历史记录；旧 `app/harness/` 包不再存在。

## 执行路径与修改入口

当前技术页面使用 [v2 交易计划书](technical-trading-plan.md)及专用后台 worker。`plan_model.py` 分开思考分析与非思考编排，`references.py` 校验引用，数字由程序按字段渲染。原始 reasoning_content 不保存或转发。下段定性投影描述保留的 v1 同步路径，综合研究不变。迁移为 0018，迁移与部署需按运行环境核验；个别真实模型成功样本不构成长期质量基准。

本节及后续重试、压缩说明描述原有综合研究。独立技术研究位于 `agent/technical/`，路径为公开行情采集 → 确定性事实与条件计划 → 受限定性模型解释 → 不可变保存，通过单独的治理策略运行。它不使用综合报告的新闻图或正文压缩；技术模型显式关闭思考模式，仅接收冻结分析的定性投影与已审查方法，完整数值分析仍由确定性代码计算、保存及展示。格式校验失败最多尝试三次，纠正仅使用相同投影和白名单字段路径/错误类别，超时与上游错误直接降级。2026-10-09 经用户确认，正常定性中文不因包含中文数字字符被直接拒绝，但具体数值、数量、交易语言及引用继续校验；不替换原文。安全诊断日志为 `technical_model_response_rejected`，不记录模型原文；接口、方法指纹、迁移及测试入口见 [Skill 技术研究报告](technical-reports.md)。

研究请求经 API 与治理内核准入后进入固定 LangGraph：采集市场 → 采集新闻 → 计算确定性市场结构 → 证据门 → 模型生成并校验保存，或保存降级报告。模型无权选择工具或改变图路径；该链路不调用策略、风控放行或模拟/真实下单。

| 关注点 | 入口 |
| --- | --- |
| 服务装配、资源和 checkpoint 生命周期 | [main.py](../backend/src/app/main.py) |
| 治理策略、运行和审计契约 | [policy.py](../backend/src/app/governance/policy.py)、[runtime.py](../backend/src/app/governance/runtime.py)、[audit.py](../backend/src/app/governance/audit.py) |
| 图节点、研究编排与冻结证据 | [graph.py](../backend/src/app/agent/graph.py)、[service.py](../backend/src/app/agent/service.py)、[evidence.py](../backend/src/app/agent/evidence.py) |
| Prompt、模型请求、校验、重试与压缩 | [prompt.py](../backend/src/app/agent/prompt.py)、[model.py](../backend/src/app/agent/model.py) |
| 市场结构与专题事实 | [market_structure.py](../backend/src/app/agent/market_structure.py)、[factor_collection.py](../backend/src/app/agent/factor_collection.py)、[factors.py](../backend/src/app/agent/factors.py) |
| 持久化与 HTTP 诊断映射 | [report_repository.py](../backend/src/app/infrastructure/persistence/report_repository.py)、[analysis_reports.py](../backend/src/app/api/routes/analysis_reports.py) |
| 客户端契约与报告展示 | [report.ts](../frontend/src/domain/report.ts)、[报告页面](../frontend/src/features/reports/) |

### 交互式工具守卫（T09 模块）

`backend/src/app/agent/interactive/tools/` 提供 C6 工具契约、不可变目录、逐次网关和六个只读研究工具：读取冻结行情、读取批准新闻摘要、计算技术事实、评估所选策略、检索研究知识和读取所选策略定义。注册只来自服务端代码；目录指纹覆盖工具名称、版本、输入/输出 Schema、能力和范围，目录变化会使旧运行拒绝调用。

`ToolGateway.call` 每次重新读取运行快照，核对策略/工具目录/策略版本，验证参数 Schema 与当前币种/周期范围，然后在 C5 预算账本中预留 TOOL 步骤并提交发送，之后才调用处理器；结果必须通过输出 Schema、8 KiB 摘要、来源时间和未来时间校验，成功/失败/未知均结算。工具串行执行，进程内只缓存已成功观察；重启后重复步骤只复用持久化结果引用并显式降级，不伪造摘要。

T11 已提供模块级模型图，但工具模块**仍未接入生产 lifespan/HTTP/前端**；当前固定研究路径仍不向模型提供工具。`read_approved_news_factors` 的默认读取器明确返回“未装配”，不是无新闻；生产新闻读取器如访问真实公开源，必须自行使用同一 C5 传输预算逐次预留/发送/结算。工具不生成订单、数量、资金或 TradeIntent，也不访问私有账户或执行服务。

### 本地只读 MCP 适配（T10 模块）

`backend/src/app/infrastructure/mcp/` 提供固定 loopback 端点、进程内服务凭据、有界 Streamable HTTP 传输和同进程只读服务。服务只登记 `read_strategy_definition`，协议固定为 `2026-07-28`；`McpEndpointRegistry` 冻结主机、端口、路径和工具输入/输出 Schema 指纹，客户端在调用前核对 SDK 协商版本、工具集合与指纹。服务凭据只在进程内创建并交给客户端登记，不出现在公开 descriptor、日志或浏览器投影。

`BoundedMcpTransport` 在官方 SDK 之前拒绝未登记目标、任何 3xx、超过 64 KiB 的 JSON/SSE 单事件，以及单次工具调用超过 64 个实际 HTTP 请求的路径；JSON 响应增量读取，超限立即中止而不是先无界缓冲。SDK 的自动重连/重列也会逐请求计数并受同一上限。`McpToolClient` 实现 T09 `ToolHandler`，必须由 `ToolGateway` 完成预算预留/发送提交后调用；其公共 `call` 在未绑定网关时直接失败，避免绕过守卫。`build_research_mcp` 返回 ASGI app、受控 lifespan 和公开服务描述；宿主挂载时必须显式运行 lifespan，宿主装配可用 `build_client_registry` 取得不含凭据外泄的客户端登记。

T11 的模型图仅通过注入的 `ToolPort` 消费已登记工具，未把 MCP 端点、凭据或协议暴露给模型；MCP 适配器仍未接入生产 lifespan/HTTP/SSE/前端。没有通用 MCP 客户端、stdio、外部服务发现、sampling/roots/elicitation 或交易/账户能力。真实模型质量、真实外部 MCP 和业务库迁移不在 T10/T11 证明范围。

### 模型驱动研究与原生 Tool Calling（T11 模块）

`backend/src/app/agent/interactive/model_port.py` 定义 `ToolBatch`、`ModelControlDecision`、`FinalAnalysis` 三种模型决策和 `AnalysisArtifactStager` 协议。`ModelControlDecision` 是 T06 `ControlProposal` 的薄包装，额外携带本次 usage/供应商标识；不修改审核材料类型。`ModelPort.decide` 仍是唯一决策入口，另外提供 `available`、`requested_model` 与 `estimate_request` 供预算/降级/指纹记录使用。

`deepseek.py` 使用注入的 httpx 客户端向固定 DeepSeek 端点发送 `messages`、原生工具 `tools`、`thinking:{type:disabled}` 和 4096 `max_tokens`；不发送工具选择参数、不依赖 `reasoning_content`、不自动重试。工具调用参数解析为 JSON object；超过四个调用、无效参数/JSON、缺失模型名、超长响应和未知 finish reason 都转成固定 `ModelCallError`。usage 缺失保持 `None`，不写零；trace 只记录 requested/returned model、Prompt/Schema/工具目录指纹、供应商标识和已知用量。

`graph.py` 的 `build_interactive_graph(GraphDependencies) -> SegmentRunner` 在单个片段内完成：加载当前运行/冻结证据/上下文 → 每次模型决策经 C5 预留/mark_sent/结算 → ToolBatch 逐个经 T09 `ToolGateway` → 控制提案经 `DecisionPolicy` 分类后只准备 preparing 待办 → FinalAnalysis 经 `AnalysisArtifactStager` 和证据引用校验后完成或准备 AP-01 审核。每次模型/工具外部调用前用账本活动时间加本片段已耗时及 15 秒安全余量做准入；`mark_sent` 返回后、实际模型请求前再次检查，已标记 sent 但未发出请求按 failed 记录 `budget_exhausted_before_request`，不按 prepared 释放。片段结束、异常或取消在 finally 记录一次活动时间，避免下一片段漏记。模型失败/预算不足/上下文超限安全降级；失败/超时分别按 failed/unknown 结算，不自动重放。图状态仅保存阶段、计数、结果类型、引用和 preparing 待办；live tool turn 只在片段内存中，不写入 checkpoint，也不成为第二业务真相。

`worker.py` 新增 `runner` + `audit_coordinator` 注入路径：由 `GovernedSegmentExecutor` 完成 T07 四阶段审计和原子提交；已有 `executor` 注入保持兼容。等待片段在模型提出澄清/审核并保存 preparing 待办后立即结束，等待期间不轮询模型。当前未接入生产 lifespan/HTTP/前端，未调用真实模型；真实模型语义质量、抗注入、真实 MCP 发送和业务库迁移不在 T11 证明范围。

### 确定性手动规划计算（T12 模块）

`backend/src/app/trade_planning/` 的 T12 模块提供纯函数：`calculate_size` 计算线性永续数量/名义额/初始保证金/止损路径风险/目标净收益/净盈亏比，`evaluate_planning_risk` 输出逐项 `ValidationCheck`，`build_manual_checklist` 生成人工操作步骤与异常分支。输入是已完成版本/指纹校验的 C3 资料、公开规则快照、T01 价格候选和短时报价；模块不读写数据库、不调用模型/工具/MCP/私有账户/订单服务，也不生成 `TradeIntent`。

计算使用后端 `Decimal` 与显式 80 位 localcontext，最终按 18 位结算精度量化：风险/保证金向上、收益/比率向下。风险额度取政策与资料的多项最小值；数量只按步长向下取整，最小数量/名义额冲突直接阻断，不向上加量或移动结构。入场带按 tick 向内取整；止损/目标仅在评估器声明 `strict` 或 `conservative_one_tick` 时处理；市价单必须有明确最大不利成交价并与报价/滑点上界一致。成本使用声明上界，入场费、退出费、滑点/价差和持有成本各计一次；最终净盈亏比由结算量化后的风险/收益复算。入场与止损/目标退出分别验证订单类型、MARKET_LOT_SIZE 步长/上下限和退出名义额；清单要求完整固定检查集合及正确 required 语义。缺失输入为 unknown，确定冲突才 fail；当日损益检查在下一 UTC 零点到期。

保证金证据标记为用户声明的交易所预览，必须与本次产品、方向、入场价、数量、名义额和初始保证金一致；历史 T03 快照缺少绑定字段时保持待补，不物化默认值。强平检查只验证止损在参考价安全一侧，**不**等于真实强平公式、账户核实或不会强平。任何缺项/未知项返回 `unknown`，不会因用户采纳变成 pass。当前 T12 未实现规划服务、readiness/采纳、资金池占用、持久化、HTTP/SSE、前端或生产 lifespan；这些属于 T13/T14，不可从本模块测试推断产品手动计划闭环已上线。验证入口为 `tests/trade_planning/`，不连接真实资金或交易所。

## AI Agent 生成与维护代码的注释要求

生成或修改后端代码时，遵循[后端注释规范](../backend/AGENTS.md#代码注释与-ai-agent-生成原则)：用详细中文注释解释模块职责、契约、关键流程与设计原因，并随代码变更同步维护。研究和治理内核/Harness 尤其要说明冻结输入、确定性验证、有限重试、降级、安全日志和交易隔离的实际边界；不要把规划写成当前能力，也不要将实现说明插入模型 Prompt、冻结方法或证据载荷。测试与迁移同样需要场景、断言意图和兼容性说明。

## 必须保持的约束

- 模型只接收本次冻结的公开证据；引用 UUID 必须属于当前报告，专题解释必须引用对应专题证据。支撑/阻力与市场结构由确定性代码计算，模型不能改写。
- RSS 标题、摘要和其他外部文本均为不可信数据。保留新闻内容边界与转义，不能把其中的指令升级为系统指令。
- 缺失、失败、未披露、零值、历史快照是不同含义。来源故障不得用旧值冒充本次输入；ETF 日期、暂定值与回填限制见[专题说明](report-factors.md)。
- 研究目录准入不授权交易。新增币种不得扩大静态交易契约；新增来源也不得增加模型工具或私有账户权限。
- 报告、证据及治理审计保持可关联与不可变。持久化变更需说明迁移、旧报告读取及失败处理，不修改已保存的模型结果来伪造成功。

## 模型修改与诊断

当前使用受限 DeepSeek JSON 格式化器。允许的模型配置在 `AppSettings` 中；密钥缺失时不发模型请求，产生可审计的降级结果。配置值与凭证不得打印。

当前格式校验最多尝试三次（包含首次请求），仅 `model_invalid_response` 进入格式纠正；超时或上游错误直接交给降级路径。纠正提示使用有界的字段路径、错误类别和长度信息，不拼接原始错误响应。

未请求专题（`factor_analysis` 为 `None`）时，模型的 `factor_interpretations` 必须为空；非空结果按 `model_invalid_evidence` 拒绝，不进入格式纠错。已请求专题仍逐项校验对应的状态和证据集合，合法市场证据ID不能代替政策专题准入。

综合正文的具体数值改为结构化事实引用：`numeric_facts.py` 只从冻结快照、公开上下文、政策计数和已结算资金费率标量建立目录，模型通过根级 `fact_refs` 数组选择 `{target, fact_id}`，正文保持定性；程序校验目标段落自身证据绑定后移除传输字段并渲染包含字段、单位与UTC范围的完整语句。专题的真实观测时间和研究统计截止分开，最新结算保留单点时刻；没有完整类型化交易日期绑定的ETF不生成数值事实，确定性专题区仍展示原数值。未知/跨证据引用、内联重贴标签、阿拉伯/全角等自由数字及受限中文数量表达在压缩前拒绝，按 `model_invalid_response` 有限纠错；渲染后再走长度、交易语言和引用校验，不能通过压缩隐藏不合法尾部。历史评估v2使用结构化Candle生成窗口和逐根OHLCV事实，v1保留。没有目录的事实保持定性，不从新闻文本猜测数值。该语法门禁不证明所有中文绕写、相邻句语义或因果判断正确，仍需内容复核；方案与范围见[事实一致性修复方案](superpowers/plans/2026-11-02-research-factual-consistency.md)。

压缩器按本次目录中的完整语句识别程序事实，为全部事实尾部预留预算，只裁剪定性前文的完整句；不能容纳则拒绝，不能留下时刻/窗口却删除字段和值，也不能静默删掉整条所选事实。普通定性方括号标题不作为事实。公开上下文使用真实 `PublicResearchContext` 契约投影；其集合时刻取多个来源的最小值，目录明确标为“合并上下文参考时刻”，并说明单项观测时刻未单独提供，不能据此声称每个指标都在该时刻观测。

模型可见数值目录最多十六条，由完整冻结目录按来源/字段交错、同组首尾时点优先选择；Prompt与渲染白名单共用 `select_numeric_facts`，不得一侧筛选另一侧放行隐藏事实。原始证据不删减，缺少可见事实不等于原始数据缺失。输入提供合法引用片段和渲染字符长度；数值类纠错用白名单中文说明日期、时刻、周期数字和根数也受限制，不照抄statement或回显候选。安全schema诊断保留已知字段名，未知键仍折叠为schema。

数值检查按读者字段汇总有界错误，最多记录九十九个问题及八个去重位置，一次纠错提示检查全文。任一错误都使整份临时结果丢弃；临时空值只是诊断遍历内部占位，不得保存或作为部分合格候选返回。诊断不保留各字段原文。

正文长度校验与 Prompt 的目标长度有不同用途；当前校验区间为 1100–2500 字符。超长候选先按完整句/完整分句压缩，headline 也进入压缩候选；压缩到不超过 2500 即可接受，不要求一定达到 2200 目标。仍超长时按整条程序事实省略并在既有限制中记录数量；标题无句末标点时允许字符级限长。修改此逻辑时不能截断事实语句、价格、证据条件或交易语言校验，也不能通过省略绕过证据和引用门禁。实际限制以 `model.py` 为准，修改常量时同步更新本段与测试。

排障先看报告的 `validationFailure`（尝试次数、问题数、字段路径、错误类别），再按运行标识关联安全日志。相关事件包括 `agent_research_started/completed/failed`、`agent_model_response_rejected`、`agent_model_format_retry_started/completed` 和 `agent_model_narrative_compacted`。只记录白名单元数据，不输出完整 Prompt、模型原文、新闻全文、证据载荷或密钥。

改动报告字段时同时核对 Prompt 示例、Pydantic 模型、最终验证、持久化映射、API 响应、前端 schema 与展示。不能只改 Prompt 就认定新契约已经生效。

## 回归清单

技术队列的运行验收见[质量验证](quality-verification.md#研究报告-http-与任务恢复验收)。`tests/persistence/test_technical_worker_recovery.py` 使用真实 SQL、worker 和可控故障窗口验证重建、实际进程终止、取消与去重；`frontend/e2e-http/research-persistence.spec.ts` 验证真实 HTTP 生成、完成/降级及历史读取。未保存的过期任务不自动重放，保存成功优先恢复为报告终态；取消是 worker 生命周期动作，不代表新增用户取消接口。

现有测试与样本是起点，无需为日常验证调用真实付费模型。以下命令在 `backend/` 执行，不包含依赖 PostgreSQL 的持久化验收：

```powershell
uv run pytest tests/agent tests/governance tests/security
```

| 场景 | 当前主要验证入口 |
| --- | --- |
| 合法中文双周期 JSON、枚举与无工具请求 | `tests/agent/test_model.py` |
| 缺失密钥、无效 JSON、超时、有限重试与安全日志 | `tests/agent/test_model.py`、`tests/agent/test_service.py` |
| 伪造证据 ID、错误专题引用、新闻边界和交易操作语言 | `tests/agent/test_model.py`、`tests/agent/test_factors.py`、`tests/security/` |
| 超长/不足正文、压缩不截断数值 | `tests/agent/test_model.py` |
| 准入拒绝、治理生命周期及审计关联 | `tests/governance/`，数据库部分另见 `tests/persistence/test_harness_audit_repository.py` |
| 报告保存、旧报告兼容和诊断展示 | `tests/persistence/test_agent_research_repository.py`、`tests/api/test_agent_analysis_reports.py`，以及前端报告测试 |

修改数据源或专题时还需运行相应 `tests/market/`、`tests/news/`、`tests/symbols/`。新增 schema 或报告字段需要专用测试数据库与前后端联验；聚焦测试不替代这些检查。

固定适配器离线评估集位于 [`backend/evaluation/`](../backend/evaluation/README.md)，在 `backend/` 执行 `uv run python -m scripts.evaluate_research`，或从根目录使用统一入口 `scripts/verify.py eval`。它使用合成冻结证据与固定 HTTP 替身，通过真实综合研究适配器验证合法输出、格式/引用/交易文本拒绝、新闻边界和配置/超时错误，记录样本、Prompt 与契约指纹；接受、拒绝和可降级错误分别统计。

该评估不需要真实密钥、网络或数据库，不证明真实模型质量、抗注入能力或数值事实准确性，也不单独覆盖完整研究图的证据不足门控与降级持久化。上述图/持久化回归继续使用现有服务及仓储测试；真实模型质量基准仍待补充，不能把替身评估通过等同于模型质量已获验证。统一命令、证据与 CI 见[质量验证](quality-verification.md)。

第二阶段另有[研究服务流程评估](../backend/evaluation/flows/README.md)：通过实际综合研究服务、技术 v2 两阶段适配器及证据门控，验证不足时不调模型、成功或降级后按合同保存和重读。其内存仓储证明范围与[真实数据库历史回归](../backend/tests/persistence/test_research_flow_evaluation_history.py)分开；后者使用受限测试库、实际治理审计与新仓储读取技术 v2 降级报告。两类评估均不代表真实模型质量或数值事实准确性。

当前传输协议为 `structured-v1`，不改变持久化与HTTP报告契约。数组最多十六项，同段最多五条；target只允许带evidence_ids的叶子段落，thesis不接受fact_refs。重复引用与单段超额分别诊断；重复、越界、非规范索引、未知/跨证据绑定与旧内联token均拒绝，一个段落可列多个evidence_id，输入提供多证据与叶子目标示例。压缩先为已选事实尾部预留预算，只裁剪定性完整句；无法容纳则按原长度门禁拒绝，不能静默删掉事实。缺少数组的纯定性提案兼容为空；历史报告不重新校验。方案见[独立引用协议](superpowers/plans/2026-11-03-structured-fact-refs.md)。

可定位的单条事实引用失败（未知/跨证据/重复/超额）在最终提案中部分恢复：丢弃失败项、保留定性正文，并把省略数量作为既有 `limitations` 写入；根形状错误仍整份拒绝。正文自由数字按完整句替换为固定省略句，不展示未验证数字；只改叙述性字段，标题、枚举、标签和 timing 仍拒绝，无法保留中文内容或最终正文长度不足时回退整份降级。部分恢复不改变报告状态或新增持久化字段，详细安全路径只进入日志。圈号等纯枚举符号不按数量处理；中文数量、分数/上标等符号数字仍按自由数字省略。未绑定数字不会因部分事实过滤而被接受或静默删除。

安全诊断仅记录固定数值类别（日期时间、小数、整数、中文数量、其他数字符号）及schema类别（枚举、缺字段、多余字段、类型、长度、JSON、其他约束、截断）。未知键折叠为schema，不记录拒绝原文、数值或任意错误消息。数值/事实引用类别（`unbound_numeric_claim`、`numeric_reference`、`fact_reference_schema`、`unknown_fact_reference`、`unknown_fact_target`、`fact_evidence_mismatch`、`duplicate_fact_reference`、`excess_fact_reference`、历史`duplicate_or_excess_fact_reference`、`model_output_truncated`）同样可能成为最后一次尝试的终态，必须同时加入后端降级摘要白名单和前端 schema/中文标签；否则报告会在保存或解码阶段失败。纠错提示只追加服务端构造的字段路径、事实标签与 evidence UUID，不回显模型正文。
