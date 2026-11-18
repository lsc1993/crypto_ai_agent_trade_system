# T11 审查请求：原生 Tool Calling 与有限 LangGraph

- 任务/审查单元：**T11**（D3：冻结上下文、工具守卫、真实 MCP、模型驱动 LangGraph 的第四段，也是 D3 的收尾模块）。
- 执行模型：DeepSeek `deepseek-flash`（`PI_PROVIDER=deepseek`、`PI_MODEL=deepseek-flash`、`PI_REASONING_LEVEL=max`）；具体模型版本、推理实现和供应商侧版本未知。
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0；质量验证说明、维护指南与运行边界以当前仓库提交为准。
- 自测状态：**`verified`**（实现、聚焦、阶段、SQL/恢复、quick、独立 PostgreSQL full、Ruff/格式/Pyright/架构/迁移链完成；不等于正式审查通过）。
- 正式审查状态：**`approved`**（2026-11-17 用户传回原审查助手正式通过结论；`reviewed_tip=7c1f336`、`reviewed_tree=dacff63`；首轮 3 项及二次复审 R1/R2 均已关闭）。
- 日期：2026-11-17。

## 1. 工作区、分支与提交范围

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:/project_git/crypto_ai_agent_trade_system`（`main` tip `c45640e`，工作区干净；T10 已合并） |
| 隔离工作区 | `D:/project_git/t11`（从 `main` 的 `c45640e` 创建） |
| 分支 | `t11-model-graph`（未推送、未合并、未部署） |
| base | `c45640e51b6473f42126ac3dea9ae76536124fef`（`main`，`docs: record T10 merge into main`） |
| implementation tip | `7c1f33660f91e0df8c170533ee8f17f222836249`（`fix: close remaining T11 activity and response bounds`；前序修复 `e0bc26e`，首轮受审 `d1e3560` / tree `5c78429`） |
| implementation tree | `dacff63ed8deee4e707c4a32826c82a90cb3e987` |
| 代码/文档范围 | `c45640e..7c1f336`，19 个文件，+4098/-26（T11 源码、测试、规范/计划/状态同步；不含本审查请求和进度 docs 提交） |
| review_status | `approved`（2026-11-17 原审查助手复审通过） |
| reviewed_tip | `7c1f33660f91e0df8c170533ee8f17f222836249` |
| reviewed_tree | `dacff63ed8deee4e707c4a32826c82a90cb3e987` |
| docs 提交 | 本审查请求与进度更新在代码提交之后单独提交；具体 hash 见最终交付回复；不把 docs 自身提交号写入 `implementation tip` |

主工作区未因本轮改动；未修改 `.env`、凭证、业务库、生产配置、模拟盘资金/风控或交易执行链路。未调用真实模型、真实 MCP、私有账户或交易接口。

### 1.1 文件指纹（reviewed code/test tip `7c1f336` 与批准 docs）

| 文件 | SHA-256 |
| --- | --- |
| `backend/src/app/agent/interactive/model_port.py` | `e4d8415c839d575a3ff99afe9116ac2651ce342b2a38f5306dc2da001f0e045b` |
| `backend/src/app/agent/interactive/deepseek.py` | `9e32a2e13e4e2f2dc3c5c6a1bcfc04f4496a2caaacaf1295e7d5ef12c13634e4` |
| `backend/src/app/agent/interactive/prompt.py` | `735395ddd62f6340362479c19dca5888d0ac605ac79c9691065d64d541a6c719` |
| `backend/src/app/agent/interactive/graph.py` | `f8486ed242ffb4ac97f173dba3b96974d34d2fd96cc2b1446206f6ead644c4fb` |
| `backend/src/app/agent/interactive/state.py` | `0894ff092b8c4ac824a04a6b5a0f3ee567509bd633ffc1a0e3f61d029d68231d` |
| `backend/src/app/agent/interactive/worker.py` | `a467d2eda36f6ab56cee54793baf1eff95ffa33f3c1148b8a285702c894dd9bc` |
| `backend/tests/agent/interactive/graph_fixtures.py` | `55ab7e3a9c0aa573a838d7d039924125bc0da4f3fae514ec6e83ed01d691f039` |
| `backend/tests/agent/interactive/test_deepseek.py` | `5c9bca0382204f7eb48ef99581b920ee759f29b11d52f8b775dd94c346d6048c` |
| `backend/tests/agent/interactive/test_graph.py` | `edab64df72e3f4705f9748a852bba2cd851b40fc7fc18367e1bf527a23eca374` |
| `backend/tests/agent/interactive/test_graph_segments.py` | `29587b55cea668cb56adb21780830d860963a2e3ed56ec3b44f02525e37281e3` |
| `AGENTS.md` | `3e4c3317eaabf418c912b614bec6049fdd0d90da05d292818bff7e0225680022` |
| `backend/AGENTS.md` | `f3263a77b4cd39dfe60206aef58f9e1c55916b967b8607884ef5e4c73f350af2` |
| `docs/ai-maintenance.md` | `bbfe804b681e98f8fcc10342b83a33c94dfbaef8274727734447d966af7bd569` |
| `docs/operational-boundaries.md` | `fddb8380a7cfabc1792413640b2487a0d2bfd082b8a4b7dbe7aa85bda5488817` |
| `docs/project-status.md` | `173473d6620e8d804a44f70d0733d4b07e28ddffd56dcac84dd221ab714d8d8d` |
| `docs/superpowers/plans/2026-11-06-manual-trading-agent-implementation.md` | `fe5a5eb4ff49998eff15f0f243d155aed473c440331262d1db45bbfe18cb69c9` |
| `docs/superpowers/plans/2026-11-06-manual-trading-agent-contracts.md` | `92cd10b366d2f06a6e3d1731a2b6d9aff08d5f384e9df0784342e15860889275` |

## 2. 任务范围与 FR/AC/HN 映射

### 2.1 本轮范围

实现 D3 的模型驱动研究循环：

- `model_port.py`：ToolBatch、`ModelControlDecision`（T06 `ControlProposal` 薄包装）、FinalAnalysis、`ModelDecision`、`ModelPort`、`AnalysisArtifactStager`、安全错误与 trace 类型。
- `deepseek.py`：固定 DeepSeek 端点的原生 Tool Calling；发送真实 `messages`/工具 Schema/指定输出上限和 `thinking` 禁用；解析 tool_calls、最终分析、控制提案、usage 和供应商 model 标识；无自动重试。
- `prompt.py`：受治理 Prompt、输出结构描述和稳定 Prompt/Schema 版本指纹；不包含财务值、账户或凭证。
- `graph.py`：`GraphDependencies` 显式注入运行读取、C5 预算、证据、上下文、工具、模型、交互、产物端口；`build_interactive_graph(...) -> SegmentRunner`；模型决策、工具观察回灌、控制提案、等待、最终分析/产物路由。
- `state.py`：仅保存阶段、模型/工具计数、结果类型、安全原因、引用和 preparing 待办；不保存原始上下文/思考/财务值。
- `worker.py`：新增 `runner` + `audit_coordinator` 注入路径，由既有 `GovernedSegmentExecutor` 完成 T07 审计和原子提交；`executor` 旧路径保持兼容。

本轮**不**实现：T12/T13 确定性规划与计划采纳、T14 HTTP/SSE/生产 lifespan/产物服务、T15/T16 前端、真实外部 MCP 发送、真实模型质量、业务库迁移、任何订单/私有账户/自动交易能力。当前生产固定研究图仍不向模型提供工具，不能把本模块称为生产模型工具循环已上线。

### 2.2 映射与证明范围

| 需求/不变量 | T11 证明 | 证据 |
| --- | --- | --- |
| FR-02（模型驱动研究循环） | 模型原生 ToolBatch → T09 工具观察 → 重新决策；控制提案/最终分析路由；预算/失败终止 | `test_deepseek.py`、`test_graph.py` |
| FR-03（Tool Calling） | 真实 wire 请求包含工具 Schema；`tool_call_id` 原生回填；模型不能指定 URL/凭据；工具只经注入 `ToolPort`（生产即 T09 网关） | `test_native_tool_request_is_sent_and_batch_is_parsed`、`test_tool_observation_is_sent_with_native_call_pairing` |
| FR-07（过程可视化，部分） | 仅安全 trace 元数据（requested/returned model、Prompt/Schema/工具指纹、usage）；无事件/SSE/前端展示 | `ModelCallTrace`、`test_native_tool_request_...`；完整事件投影待 T14/T16 |
| AC-01（证据不足后选工具） | ToolBatch → observation → 第二次模型决策；没有用正文文字伪装工具调用 | `test_tool_observation_is_appended_and_model_loop_finishes` |
| AC-02（真实 TCP MCP） | **T11 不重新证明**；工具的 MCP 传输证明归 T10。T11 证明模型图只通过已授权工具端口消费工具 | T10 证据；`test_graph.py` |
| AC-03（未登记/越权/注入拒绝） | 禁止动作拒绝；工具参数/批次/名称上限；实际未登记/范围/参数拒绝由 T09 网关回归继续覆盖 | `test_prohibited_control_action...`、`test_more_than_four_tool_calls...`、`test_invalid_tool_arguments...`；T09 网关回归 |
| AC-10（计划待审） | 有计划的 FinalAnalysis 经 `DecisionPolicy` 准备 AP-01 `WAIT_APPROVAL`，`plan_proposal=None`，不标记可实施 | `test_plan_final_analysis_waits_for_approval...` |
| AC-12（等待结束/恢复） | 澄清/审核后片段立即结束；等待期间无模型轮询；真实 SQL 等待发布/重启恢复由 T07 回归覆盖 | `test_clarification_ends_segment...`、`test_worker_with_graph_runner...`、T07 15 passed |
| AC-15（未知/超时） | 模型超时/传输错误按 `unknown` 结算、不自动重放；`mark_sent` 前失败按释放语义结算 | `test_model_timeout_is_unknown_and_not_retried`、`test_mark_sent_failure_releases_prepared_attempt...` |
| AC-16（模型失败/缺口降级） | 模型失败、上下文超限、证据/产物错误返回 DEGRADED 且不暂存分析 | `test_model_failure...`、`test_context_build_error...`、`test_artifact_staging_error...` |
| HN-01（每次工具权限） | 图只调用注入 `ToolPort`；生产实现必须是 T09 `ToolGateway`，每次调用仍有快照/目录/fence/预算检查 | `GraphDependencies.tools`、`_tools`；T09 回归 |
| HN-04（成功复用/未知不重放） | 失败/超时结算 failed/unknown；模型适配器不自动重试；没有恢复重放路径 | `_call_model`、`test_model_timeout...` |
| HN-05（预算） | 每次模型决策 `reserve`/`mark_sent`/`settle`；输入预留使用适配器实际 wire payload 的保守估算；模型/工具/传输仍共享 run 账本 | `test_tool_observation...` 预算断言、`test_model_budget_exhaustion...` |
| HN-06（等待释放资源） | 控制提案只准备 `preparing` 待办并结束片段，不轮询模型 | `test_clarification_ends_segment...`、worker 测试 |
| HN-07（当前审核材料） | 图用 `DecisionPolicy` 和 material hash 准备待办；响应 CAS/应用仍归 T06/T07/T13 | `_control`、`_finalize`；T06/T07 回归 |
| HN-08（新消息水位） | 图读取 `applied_message_seq` 并在上下文构建时校验；`received>applied` 的提交阻断仍由 T07 协调器负责 | `_prepare`、T07 提交回归；未在 T11 新建事件接口 |
| HN-09（精确策略） | 上下文只来自 T08 `ContextBuilder`；图不自行选择/替换策略 | `ContextPort`、T08 回归 |
| HN-10（证据时点） | FinalAnalysis 证据 ID 必须属于当前 manifest；过期/未来证据仍由 T08 校验 | `test_unknown_analysis_evidence...`、T08 回归 |
| HN-11（模型只是提案） | 模型成功只结算预算；最终分析必须经 stager；计划进入 AP-01；没有完成/采纳直接提交 | `_finalize`、`test_plan_final_analysis...` |
| HN-12（安全投影） | 模型上下文来自 T08 安全投影；trace 只含版本/指纹/用量；无原始思考/财务值/凭证 | `ModelCallTrace`、`test_deepseek` 断言、T08 财务隔离回归 |

T11 不生成 `TradeIntent`、不访问私有账户、不调用模拟/真实订单服务，也不宣称真实模型语义质量、真实 MCP 发送或生产工具循环已交付。

## 3. 改动清单与关键取舍

### 3.1 改动清单

**新增源码**
- `backend/src/app/agent/interactive/model_port.py`：模型决策/最终分析/产物暂存纯契约；ToolBatch 最多四项；FinalAnalysis 证据/事实/候选形状；`ModelControlDecision` 包装。
- `backend/src/app/agent/interactive/deepseek.py`：固定端点原生 Tool Calling 适配器；response 大小上限、usage/trace、错误分级。
- `backend/src/app/agent/interactive/prompt.py`：受治理 Prompt 与输出契约版本/指纹。
- `backend/src/app/agent/interactive/state.py`：轻量 LangGraph 状态（阶段/计数/结果/引用）。
- `backend/src/app/agent/interactive/graph.py`：GraphDependencies、模型/工具/等待/产物路由、SegmentRunner、`not_executed_tool_message`。

**新增测试**
- `backend/tests/agent/interactive/graph_fixtures.py`：合成任务/证据/上下文/预算/模型/工具/交互/产物替身。
- `backend/tests/agent/interactive/test_deepseek.py`：13 项原生协议与错误分级。
- `backend/tests/agent/interactive/test_graph.py`：21 项图路由、预算、等待、取消、证据/产物。
- `backend/tests/agent/interactive/test_graph_segments.py`：worker `runner` 注入和等待不轮询。

**修改**
- `backend/src/app/agent/interactive/worker.py`：新增 `runner` + `audit_coordinator` 注入，内部构造 `GovernedSegmentExecutor`；已有 `executor` 路径保持兼容。
- 根 `AGENTS.md`、`backend/AGENTS.md`、`docs/ai-maintenance.md`、`docs/operational-boundaries.md`、`docs/project-status.md`、实施计划/契约：同步当前实现与未接入边界。

### 3.2 关键取舍（请重点审查）

1. **`ModelControlDecision` 薄包装**：计划契约写 `ModelDecision = ToolBatch | ControlProposal | FinalAnalysis`。T06 的 `ControlProposal` 是审核材料类型，不携带 usage/provider id；为在成功结算中保留真实用量而不修改 T06 类型，T11 用 `ModelControlDecision` 包装 `ControlProposal`。`ModelDecision` 仍是三类联合，控制提案仍由 T06 类型和 `DecisionPolicy` 处理。请确认该细化是否可接受；若要求严格三元联合，需要另设用量传递方式。
2. **`ModelPort` 的额外方法**：除 `decide(context)` 外增加 `available`、`requested_model`、`estimate_request(context)`。前两者用于无密钥/无能力时安全降级和 trace，第三者用于把真实 wire payload 的保守输入预留交给 C5；`decide` 仍是唯一决策入口。
3. **图依赖多一个预算和运行读取端口**：`GraphDependencies` 除模型/上下文/工具/证据/交互/产物外，注入 `budget: BudgetLedger` 和 `runs: AgentRunReader`。预算用于 HN-05 的逐次模型预留/结算；运行读取用于每次决策前复核修订/取消/消息水位。两者都是端口，不导入数据库/执行实现。
4. **live tool turn 不进入图状态**：图状态只保存阶段/计数/结果/引用；assistant call 与 tool 结果只保存在片段内存，用于本片段后续请求。这样 checkpoint 不成为第二业务真相，但跨进程恢复需要 T14/T17 用持久化历史重建；T11 没有跨进程同片段恢复证明。
5. **等待语义**：控制提案只创建 `preparing` 待办并结束片段；`pending` 发布、审计终态、owner 释放仍由 T07 协调器在片段 END 后原子提交。T11 没有实现事件/HTTP UI；worker 测试使用替身，真实 SQL 等待由 T07 回归证明。
6. **计划 AP-01**：有计划最终分析必须绑定候选，且 `plan_ref` 必须出现在 stager 返回的引用中；图用 `DecisionPolicy` 生成 AP-01 待审，不创建 `PlanAdoptionProposal`、不设置 readiness。计划数量/资金/规则/采纳/占用由 T12/T13/T14 负责。
7. **模型适配器没有自动重试/JSON 模式**：`decide` 单次发送；供应商 5xx/超时/无效输出转为稳定错误，由 T11 图按 failed/unknown 结算并降级。最终分析用严格 JSON 内容解析，不依赖 `response_format` 或隐藏 reasoning；真实模型是否稳定支持该协议仍需 T18。
8. **活动时间与 T09 网关窗口**：本轮已改为每次模型/工具调用前用账本活动时间 + 本片段已耗时 + 15 秒安全余量做准入，并在正常/异常/取消路径的 finally 记录本片段活动时间。仍需审查 T09 网关内部 reserve→mark_sent→handler 的短窗口，以及取消时 activity 写入的 best-effort 处理是否足够。
9. **worker 组合位置**：为满足 T11“worker 注入 SegmentRunner”要求，`worker.py` 在 `runner` 路径内部构造 `GovernedSegmentExecutor`；已有 `executor` 注入完全保留。请确认没有削弱 T07 的审计/提交或让 worker 成为第二模型循环。
10. **模型 trace 落盘**：T11 只提供 `trace_recorder` 回调和安全类型，测试收集到内存列表；未写数据库/事件。T14 必须把 trace 接到受控审计/事件投影，不能把 Prompt 原文、隐藏思考或财务值写入。

### 3.3 首轮正式审查 R1–R3 修复

首轮正式审查对 `d1e3560`（前序提交范围）判定 `changes_requested`，提出 3 项必须修复；本轮已在 `e0bc26e` 修复并补回归。修复前基线为新增 30、阶段 236、SQL 244、quick 1190、full 1429；首轮修复后为新增 34、阶段 240、SQL 248、quick 1194、full 1433；二次复审后最终为新增 36、阶段 242、SQL 250、quick 1196、full 1435，详见 3.4。

| 发现 | 根因与复现 | 修复与回归 |
| --- | --- | --- |
| R1/P1 活动时间预算不能阻止片段内继续调用 | 原实现只在片段正常结束后 `record_activity`；模型/工具调用前读取的账本不包含本片段已耗时。复现：账本 570 秒，首模型耗时 20 秒后仍执行工具和第二次模型，累计 610 秒。 | 新增 `_activity_exhausted`/`_enforce_activity_budget`：每次模型决策和每个工具调用前用 `active_seconds + 本片段 elapsed + 15` 检查，超限停止并写入未执行工具观察；`reserve` 后、`mark_sent` 前再次检查并释放 prepared。`InteractiveGraphRunner.run` 在 `finally` 记录一次活动时间，正常/异常/取消均覆盖；已有异常时账本写入失败不掩盖原错误。新增 570+20 停止和异常路径仍记录 20 秒的回归。 |
| R2/P1 响应大小限制在完整缓冲后才检查 | 原实现 `AsyncClient.post()` 后检查 `response.content`，256 KiB 限制前已完整进入内存。 | 改为 `AsyncClient.stream()`，逐块累计；越限立即退出 `async with` 并关闭响应，不消费后续块。测试使用计数异步流，断言只消费 2 个块、响应已关闭。 |
| R3/P2 非成功 finish reason 仍可触发工具执行 | 原实现只特殊处理 `length`，随后直接接受任何非空 `tool_calls`；`content_filter`、缺失/未知原因或不一致形状都能形成 ToolBatch。 | 结束原因白名单限定 `stop`/`tool_calls`：`tool_calls` 必须有非空工具调用，`stop` 不能携带工具调用；过滤/缺失/未知原因返回 `model_finish_reason_unsupported`，形状不一致返回 `model_invalid_response`，均保留已观察 usage/provider id。新增过滤、stop+工具、缺失原因的回归。 |

### 3.4 二次复审 R1/R2 剩余问题修复

二次复审对修复 tip `e0bc26e`（tree `362489a`）仍判定 `changes_requested`：R3 已关闭，R1/R2 各有一处剩余问题。本轮在 `7c1f336`（tree `dacff63`，`4bde392..7c1f336` 8 个文件 +116/-7）修复；修复后新增 36、阶段 242、SQL 250、quick 1196、full 1435。

| 发现 | 根因/复现 | 修复与回归 |
| --- | --- | --- |
| R1/P1 `mark_sent` 等待期间耗尽安全余量仍发送模型 | 最后一次活动检查在 `await mark_sent(...)` 之前；账本 584 秒、`mark_sent` 耗时 2 秒后实际只剩 14 秒，模型仍被调用。 | 在 `mark_sent` 返回后、实际 `model.decide` 前再次检查活动预算。此时账本已标记 sent，不再按 prepared 释放；以 `failed` 结算并记录 `budget_exhausted_before_request`，保留已发送计数和未知 Token 保守占用，不发送模型请求。新增 584+2 秒回归，断言模型零调用、failed 结算和 finally 记录 2 秒。 |
| R2/P1 压缩响应可在 256 KiB 检查前分配更大内存 | 使用 `aiter_bytes()`，锁定 HTTPX 先解压原始块再交给适配器；单块解压分配不受 256 KiB 限制。 | 请求显式 `Accept-Encoding: identity`；读取前拒绝非 identity `Content-Encoding`（返回 `model_content_encoding_unsupported`），并使用 `aiter_raw()` 按原始字节流计数。新增 gzip 响应回归，断言在解压/读取前拒绝、流消费 0 块且响应关闭。 |
| R3/P2 非成功 finish reason | 二次复审确认已关闭：`tool_calls` 必须是非空列表，`stop` 拒绝携带非空工具调用；过滤/缺失/未知原因在工具路由前拒绝并保留 usage/provider id。 | 本轮未修改该项，保留原回归。 |

T07 提交边界保持不变：本次差异未改 worker/审计协调器；活动时间在 runner 返回 `SegmentOutcome` 前记录，正常路径记账失败阻止结果返回，等待发布和终态提交仍由既有治理执行器/协调器负责。

## 4. 公共接口、依赖与迁移影响

### 4.1 新增/修改公共接口

- `model_port.py`：`ToolBatch`、`ModelControlDecision`、`FinalAnalysis`、`ClaimBlock`、`ClaimFactRef`、`ModelDecision`、`ModelPort`、`AnalysisArtifactStager`、`AnalysisStagingError`、`ModelCallError`、`ModelCallTrace`。
- `deepseek.py`：`DeepSeekToolCallingModel`（`available`、`requested_model`、`encode_request`、`estimate_request`、`decide`）；`MAX_MODEL_RESPONSE_BYTES`。
- `graph.py`：`GraphDependencies`、`InteractiveGraphRunner`、`build_interactive_graph`、`not_executed_tool_message`、`MODEL_ACTION_SEQUENCE_BASE`。
- `state.py`：`GraphPhase`、`InteractiveGraphState`。
- `worker.py`：`InteractiveAgentWorker(..., runner=..., audit_coordinator=...)`；原 `executor` 参数仍可用，二者互斥。
- 未改变 T06 `ControlProposal`/`DecisionPolicy`、T07 `SegmentOutcome`/`GovernedSegmentExecutor`、T08 `ModelContext`/`ContextBuilder`、T09 `ToolGateway` 或 T10 MCP 公共类型。

### 4.2 依赖

- **无新增依赖**；无 `pyproject.toml`/`uv.lock` 变化。
- 继续使用既有 `httpx`（T11 DeepSeek 适配器）与 `langgraph==1.2.10`；未引入新模型 SDK、交易所客户端、浏览器或外部 MCP 服务。
- 真实模型调用未执行；`DeepSeekToolCallingModel` 由注入的 httpx 客户端使用，测试全部使用 `httpx.MockTransport`。

### 4.3 数据库迁移

- **无新增迁移**；未修改旧迁移、业务库或历史报告/审计。
- 迁移 head 仍为 `0027_agent_segments`；`alembic heads` 已核验。
- T11 只消费既有 C4/C5/C7 端口和 T07 提交边界；没有新增表/字段。
- full 在临时 PostgreSQL 17 上验证既有迁移链、C5 账本、T07 恢复和交互/消息回归，未迁移业务库。

## 5. 验证记录

### 5.1 环境与证明范围

- 执行目录：`D:/project_git/t11`（根）与 `D:/project_git/t11/backend`。
- 后端锁定环境：`uv sync --project backend --locked`，Python 3.12；隔离 `.venv`。主工作区当前 `.venv` 缺少 T10 依赖，未修改主工作区，已在新 worktree 同步锁定依赖。
- 专用测试库：临时 PostgreSQL 17 容器（Docker 29.9.2），本机回环端口、临时数据目录、固定测试库 `crypto_research_test` / 受限角色 `crypto_research_test_runner`；通过项目 `scripts.check_test_database` 只读身份/权限预检；`TEST_DATABASE_URL` 只在验证进程注入，不记录连接串；验证后停止并删除容器。未指向、迁移或修改任何业务库。
- 验证进程未继承宿主业务 `DATABASE_URL`、`APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`NODE_ENV`、`GIT_CONFIG_COUNT`；未修改 `.env` 或业务配置。
- 前端未改动；本轮 quick/full 使用 `--component backend`，未执行前端 lint/typecheck/Vitest/build、浏览器 e2e、HTTP e2e 或完整生产 lifespan 装配。
- 未调用真实模型、真实 MCP、私有账户或交易执行；模型/工具/证据/上下文/财务值均为合成测试资料。

### 5.2 测试执行

| 检查 | 目录 | 完整命令 | 退出码 | 实际结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 改动前基线 | `D:/project_git/t11/backend` | `uv run --locked --no-sync pytest tests/agent/interactive tests/agent_runs tests/governance/test_interactive_planning.py tests/mcp -q --basetemp=../.tmp/pytest/t11-baseline` | 0 | 171 passed / 0 failed / 0 skipped | `.tmp/pytest/t11-baseline` |
| 首轮预期红（缺模块） | `D:/project_git/t11/backend` | `uv run --locked --no-sync pytest tests/agent/interactive/test_deepseek.py tests/agent/interactive/test_graph.py tests/agent/interactive/test_graph_segments.py -q --basetemp=../.tmp/pytest/t11-red-1` | 2 | 3 个 collection error（`deepseek`/`graph`/`model_port` 不存在），符合测试先行预期；未发付费请求 | `.tmp/pytest/t11-red-1` |
| 新增聚焦最终 | `D:/project_git/t11/backend` | `uv run --locked --no-sync pytest tests/agent/interactive/test_deepseek.py tests/agent/interactive/test_graph.py tests/agent/interactive/test_graph_segments.py -q --basetemp=../.tmp/pytest/t11-review2-focused-2` | 0 | 36 passed / 0 failed / 0 skipped | `.tmp/pytest/t11-review2-focused-2` |
| 交互式/安全/治理/agent_runs 阶段 | `D:/project_git/t11/backend` | `uv run --locked --no-sync pytest tests/agent/interactive tests/agent_runs tests/governance/test_interactive_planning.py tests/security -q --basetemp=../.tmp/pytest/t11-review2-stage-1` | 0 | 242 passed / 0 failed / 0 skipped | `.tmp/pytest/t11-review2-stage-1` |
| SQL/恢复聚焦（专用 PostgreSQL 17） | `D:/project_git/t11/backend` | `TEST_DATABASE_URL` 进程注入；`uv run --locked --no-sync pytest tests/agent/interactive tests/agent_runs tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py tests/persistence/test_agent_attempts.py tests/persistence/test_agent_interactions.py tests/persistence/test_agent_runs.py tests/persistence/test_migrations.py -q --basetemp=../.tmp/pytest/t11-review2-sql-1` | 0 | 250 passed / 0 failed / 0 skipped | `.tmp/pytest/t11-review2-sql-1` |
| T07 恢复专项 | `D:/project_git/t11/backend` | `TEST_DATABASE_URL` 进程注入；`uv run --locked --no-sync pytest tests/persistence/test_agent_segment_recovery.py tests/persistence/test_agent_segments.py -q --basetemp=../.tmp/pytest/t11-t07-recovery` | 0 | 15 passed / 0 failed / 0 skipped | `.tmp/pytest/t11-t07-recovery` |
| 后端 quick | `D:/project_git/t11` | `uv run --project backend --locked --no-sync python scripts/verify.py quick --component backend --report .tmp/quality/t11-final-quick-backend.json` | 0 | `verification=passed`；1196 collected / 1196 passed / 0 failed / 0 skipped / 0 collection errors | `.tmp/quality/t11-final-quick-backend.json` |
| 后端 full（D3 阶段） | `D:/project_git/t11` | `TEST_DATABASE_URL` 进程注入；`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-d3-full.json` | 0 | `verification=passed`；1435 collected / 1435 passed / 0 failed / 0 skipped / 0 collection errors | `.tmp/quality/manual-agent-d3-full.json` |
| Ruff / 格式 | `D:/project_git/t11/backend` | `uv run --locked --no-sync ruff check .`；`ruff format --check .` | 0 | All checks passed；404 files already formatted | 终端记录 |
| Pyright | `D:/project_git/t11/backend` | `uv run --locked --no-sync pyright` | 0 | 0 errors / 0 warnings | 终端记录 |
| 架构门禁 | `D:/project_git/t11/backend` | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `status=passed`，`files_scanned=87`，`findings=[]` | 终端记录 |
| 迁移链 | `D:/project_git/t11/backend` | `uv run --locked --no-sync alembic heads` | 0 | `0027_agent_segments (head)` | 终端记录 |
| 文档链接/差异 | `D:/project_git/t11` | 本地 Markdown 相对链接扫描；`git diff --check` | 0 | 0 broken links；无输出 | 终端记录 |

### 5.3 原生协议与图边界专项

- **真实 wire 形状**：MockTransport 断言请求含 `model`、`messages`、已授权工具 `tools`、`thinking:{type:disabled}`、`max_tokens=4096`；不含工具选择参数。系统 Prompt 与 T08 上下文系统消息合并为唯一 system 消息。
- **工具观察回填**：第二次请求最后一条是 `role=tool` 且 `tool_call_id` 等于供应商返回的 call id；前一条 assistant 消息包含同 id 的原生 tool_calls；模型不能只写“已调用”。
- **结果上限/结束原因/错误**：请求 `Accept-Encoding: identity`，读取前拒绝非 identity `Content-Encoding`；响应用 `aiter_raw` 逐块读取，超过 256 KiB 在越限块处关闭响应，不再消费后续块。测试断言普通计数流只消费 2 个块且 `closed=True`，gzip 响应在读取前被拒绝、消费 0 块。finish reason 只接受 `stop`/`tool_calls`；`content_filter`、缺失/未知原因返回 `model_finish_reason_unsupported`，`stop` + 工具调用返回 `model_invalid_response`，均保留已知 usage。超过四个 tool_calls、无效 JSON 参数、缺失 returned model、HTTP 503 和无效最终 JSON 同样 fail-closed；usage 缺失保持 `None`。
- **预算/活动时间**：测试断言每次模型决策的 `reserve` 输入等于对应 `ModelContext.input_reservation`，`mark_sent`/`settle` 成对出现；`mark_sent` 失败时 prepared attempt 结算为 failed；超时结算为 unknown 且只预留一次。新增“账本 570 秒 + 本片段 20 秒”场景，确认工具和第二次模型都被活动时间准入阻止；另在 `mark_sent` 等待 2 秒、账本 584 秒场景确认请求前停止并结算 failed；异常/取消路径在 finally 记录本片段活动时间。
- **等待**：模型返回 CLARIFY/AP-01 时只准备一个 `preparing` 待办，片段立刻结束；worker 测试断言 `model.contexts==1`，等待期间没有第二次模型调用。
- **图状态**：`InteractiveGraphState` 只含阶段/计数/结果类型/安全原因/引用/preparing 待办；`live_messages` 只在 `_RunScope`，不进入图状态/checkpoint。
- **真实 SQL 边界**：`test_agent_segment_recovery.py`/`test_agent_segments.py` 15 项和更宽 SQL 聚焦 248 项继续覆盖 T07 租约、恢复、提交、C5 账本、交互/消息；T11 没有新增 schema，也没有把纯图替身当作真实事务证明。

### 5.4 证明边界

- 未执行真实 DeepSeek 请求、真实 MCP 发送、生产 `create_app` lifespan、HTTP/SSE、前端、浏览器 e2e 或业务库迁移。
- `test_graph_segments.py` 使用替身片段仓储/审计协调器，只证明 worker 接线和片段 END 语义；真实 SQL 等待发布、并发/重启恢复由 T07 回归和后续 T17 证明。
- 真实模型是否支持当前原生工具/JSON 组合、是否稳定遵守 Prompt、语义质量、抗注入和收益均未验证；T18 单独验收。
- T11 未实现 `build_manual_trade_plan` 工具、计划采纳、资金池占用、可实施状态或交易清单；不能宣称产品手动计划闭环已交付。

## 6. 未验证项、已知风险与重点审查位置

### 6.1 未验证/未执行

- 真实 DeepSeek 协议/能力/语义质量；真实 MCP 发送；真实公开源/新闻传输预算的模型图接线。
- 生产 `create_app` lifespan、HTTP/SSE API、前端任务/审核页面、浏览器 e2e、HTTP e2e。
- T12/T13 确定性规划、计划采纳/占用、可实施状态、手工反馈；T14 产物服务/投影/生产装配；T15/T16 前端。
- 业务库迁移（本轮无迁移）、真实账户/资金/订单、真实策略收益。
- 前端 lint/typecheck/Vitest/build 未运行（本轮无前端改动，quick/full 使用 `--component backend`）。

### 6.2 重点审查位置

1. `model_port.py` 的 `ModelDecision`/`ModelControlDecision` 细化是否可接受；`FinalAnalysis` 的无计划原因/计划绑定/证据字段约束是否足够。
2. `deepseek.py` 的 wire 转换、原生 `tool_call_id` 回填、流式响应限长、finish reason 白名单与形状一致性、usage 缺失、错误分级和 trace 字段；是否还有未计数的供应商自动行为。
3. `graph.py` 的预算顺序（status → reserve → mark_sent → decide → settle）、`mark_sent` 前失败释放、失败/unknown 不重放、模型/工具/等待/产物路由。
4. `graph.py` 的 AP-01 准备是否仍尊重“模型不能自批/不能声明可实施”；`plan_ref` 必须属于已暂存产物、候选绑定和证据 ID 校验是否足够。
5. `graph.py` 的 live tool turn 仅内存、图状态仅计数/引用；跨进程恢复/T14/T17 历史重建是否留下不可接受缺口。
6. `worker.py` 的 `runner` + `audit_coordinator` 组合是否仍由 T07 唯一审计/提交路径收尾，是否可能形成第二模型循环或绕过工具网关。
7. 活动时间准入是否足以覆盖模型/工具调用和取消路径；T09 网关内部控制流与活动检查之间仍有一个短窗口，是否需要把本地 elapsed 显式传入网关。
8. `trace_recorder` 的 T14 接线、事件/前端投影、财务隔离和 Prompt/隐藏思考不泄露；T11 自身只证明安全类型和内存回调。

## 7. 自测与正式审查状态

- 自测状态：**`verified`**。实现、聚焦/阶段/SQL/恢复/quick/full/静态检查均完成；本文件不把开发自测称为正式审查通过。
- 正式审查状态：**`approved`**（2026-11-17 用户传回原审查助手正式通过结论；`reviewed_tip=7c1f336`、`reviewed_tree=dacff63`；首轮 3 项及二次复审 R1/R2 均已关闭）。
- 未进入 T12/T13/T14；未修改自动交易限制、默认审核、产品内计划审核或真实资金权限。开发模块审查与产品内交易计划审核分别管理。
