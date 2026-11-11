# T05 审查请求：步骤账本、预算与未知调用

- 任务/审查单元：T05（D2）
- 执行模型：`deepseek-flash`（运行环境标识）；具体供应商构建、参数版本与上下文版本未在仓库内可确认，记为**未知**。执行载体为 DeepSeek Harness。
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0（日期均为 2026-11-06）。
- 自测状态：`verified`（首轮实现、正式审查 F1–F4 修复、复审 R1 修复、聚焦、SQL、阶段、静态、迁移链和最终后端 full 已完成）。
- 正式审查状态：`approved`。用户于 2026-11-11 传回原审查助手对 `reviewed_tip=f9454adab111218eaa8bc5880b37987031c11bb7` 的正式通过结论（复审报告 `T05-rereview-f9454ad.md`）；通过结论仅针对该 tip 的 T05 模块代码，不代表后续模块或业务库迁移已验收。
- 审查请求生成：2026-11-11（Asia/Shanghai）；复审修复更新：2026-11-11；R1 修复更新：2026-11-11；正式通过记录：2026-11-11。
- 本审查请求文件本身在 implementation tip 之后作为独立 docs 提交；不把该文档提交号写入 implementation tip，避免循环引用。

## 1. 工作区、分支与审查范围

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main`，T05 开始时干净，tip `4d1af68`） |
| 隔离工作区 | `D:\t05`（短路径；为规避 Windows 260 字符路径上限，从 `.worktrees\manual-agent-t05-20261111` 移动，分支/内容/提交不变） |
| 分支 | `t05-agent-attempts-budget`（已合并到 `main`，保留用于审查追踪） |
| base | `4d1af68fc704f50b21b9f9b0619b446f315f66d6`（`main`，T04 复审/合并文档之后） |
| implementation tip | `f9454adab111218eaa8bc5880b37987031c11bb7`（`fix: reject settled call counts without actual amount`，R1 修复 tip） |
| 首轮 implementation tip | `249a8adc3769c9576015c7ff4a4edaa3e1798a6b`（`feat: account for agent attempts and cumulative budgets`） |
| 上轮修复 tip | `bd2a59df2e323248046db33ac929cd5d5d8c1063`（`fix: harden agent attempts and budget settlement`） |
| implementation tree | `a6fc8607c41add1477bda3799852685e9ce89b01`（R1 修复 tip） |
| 代码审查范围 | 累计 `4d1af68..f9454ad`，16 个文件，+4407 / -6；R1 修复 `bd2a59d..f9454ad`，3 个文件，+189 / -13；上轮修复 `249a8ad..bd2a59d`，9 个文件，+567 / -22 |
| 文档提交 | 首轮材料 `9c4c105`；上轮材料 `bd800e8`；R1 材料 `3cf1185`；批准材料为本次独立 docs 提交；代码审查以 `f9454ad` 为准 |
| reviewed_tip | `f9454adab111218eaa8bc5880b37987031c11bb7`（用户传回原审查助手正式通过） |
| 复审报告 | `docs/superpowers/reviews/manual-agent/T05-rereview-f9454ad.md` |
| 合并 | `cbffb4f530fdcb4009ae7b2946633188f8bd120e`（fast-forward 到 `main`；本 docs 提交记录合并/推送） |

实现提交只包含本任务的代码/测试/迁移文件；`main` 工作区保持干净。未修改 `.env`、凭证、真实账户或业务库；未夹带其他任务未提交内容。首轮正式审查的 F1–F4 与复审 R1 已逐项复现和修复，详细记录见第 9 节。

## 2. 任务范围、依赖与 FR/AC/HN

### 2.1 本轮范围

按实施计划 T05 与契约 C4/C5，本轮交付：

- C4 纯类型：`RunFence`、`ExecutionContext`、`SegmentOutcome`、`CompletionDecision`、`PlanAdoptionProposal`。
- C5 纯类型与账本：`AttemptCategory`、`AttemptStatus`、`AttemptRequest`、`AttemptResult`、`StepAttempt`、`TokenUsage`、逻辑步骤标识与状态迁移规则。
- `BudgetLimits`、`BudgetStatus`、`BudgetLedger` 协议；初始档、部署硬上限、有效上限合并、追加授权与活动时间检查。
- PostgreSQL 实现：`SqlAlchemyBudgetLedger.reserve/mark_sent/settle/status/record_activity/append_authorization`。
- `agent_steps`、`agent_attempts`、`budget_authorizations`、`budget_reservations` 四表与 `0023_agent_attempts`/`0024_agent_attempt_hardening`/`0025_agent_attempt_shape_fix` 前向迁移（后两者为 F1–F4 与 R1 修复）。
- 纯契约、纯预算和真实 PostgreSQL 三组测试；复审修复增加发送前预算检查、跨修订回执对账、发送前 failed/released 与直接 SQL 形状拒绝回归。

明确不在本轮：

- 领取/心跳/租约恢复/worker 循环（T07）；实际子进程终止恢复（T07/T17）。
- 人工审核、AP-05 用户交互与差异展示（T06）；只提供追加授权原语，不判断用户是否批准。
- 工具/MCP/模型实际发送（T09/T10/T11）；T05 只证明“先预留再发送”的账本边界。
- 产物持久化、HTTP/API、前端、规划计算与可实施状态（T12–T16）。
- 真实模型、真实供应商 usage/回执、私有账户、TradeIntent、风控放行、模拟订单或真实交易。

### 2.2 依赖核对

| 依赖 | 核对结果 |
| --- | --- |
| T00 治理迁移 | 已正式通过并合并在 `main`；T05 未导入 `app.harness`，未修改治理/交易边界 |
| T01 C1/C2 | 已正式通过；复用 `VersionRef`、`ArtifactRef`、`AgentModel`、`UtcDateTime` |
| T02 知识 | 已正式通过；T05 未触碰知识表/检索 |
| T03 C3 | 已正式通过；T05 只导入既有 `PlanningRefs` 类型，测试用合成 `planning_pools` 验证预算追加不改变 generation |
| T04 C4 | 已正式通过（`reviewed_tip=0df86fe`）；T05 复用 `agent_runs` 行及 owner/lease_epoch/lease_expires_at 字段，不修改 0022 迁移 |
| 迁移链 | 从 `0022_agent_tasks` 串行新增 `0023_agent_attempts`，F1–F4 修复新增 `0024_agent_attempt_hardening`，R1 修复新增 `0025_agent_attempt_shape_fix`；未改写已提交迁移。T06/T07/T13 计划迁移号顺延为 `0026_agent_interactions`/`0027_agent_segments`/`0028_manual_plans` |

### 2.3 FR/AC/HN 映射

| 标识 | 本轮实现/证明 | 不宣称 |
| --- | --- | --- |
| FR-06 | 任务级模型/工具/传输次数与累计 Token 预留；per-revision/per-segment 不重置；已知 usage 按实际结算，缺失 usage 保留最坏预留；追加授权与硬上限；活动时间与安全余量 | 前端预算展示、费用估算、真实供应商 usage 精度、真实模型质量 |
| FR-12 | 成功逻辑步骤复用结果；in_flight 可保守标记 unknown；unknown 不自动重放；未知回执结算需可验证供应商回执 | 实际 worker 领取/心跳/租约恢复/审计原子提交（T07） |
| AC-06 | 预算临界（第 9 次模型/第 13 次工具）、重试、未知 usage、追加授权均有真实 SQL 回归 | 用户界面上的预算提醒/审核流程（T06/T16） |
| AC-11 | 提供 AP-05 追加授权原语：绝对值、单调不减、部署硬上限、授权引用幂等 | 用户审查差异、批准交互与审计事件（T06） |
| AC-15 | 账本层证明未知付费调用不自动重放、成功结果复用、未知保留最坏额度 | worker 崩溃后的真实恢复与整段重放防护（T07/T17） |
| HN-04 | 成功复用、未知不自动重放、未知不能被无回执结算 | 模型/工具适配器实际接线（T09–T11） |
| HN-05 | 每次预留/发送/结算均写 meter 行；跨片段/修订累计；重试新 attempt；测试证明不使用隐藏自动重试 | 所有未来发送路径是否都调用账本（T09–T11 接线审查） |
| HN-14 | 预算类型/表不包含交易资金字段；AP-05 测试断言合成 `planning_pools.generation` 不变；错误不泄漏财务值 | 完整财务投影与前端隔离（T14/T16） |

## 3. 改动清单与文件指纹

### 3.1 改动文件

| 文件 | 说明 |
| --- | --- |
| `backend/src/app/agent_runs/segments.py` | C4 执行围栏、服务端执行上下文、片段结果、提交裁决、计划采纳提案纯类型 |
| `backend/src/app/agent_runs/attempts.py` | C5 尝试类别/状态、请求、结果、快照、逻辑步骤标识与状态迁移 |
| `backend/src/app/agent_runs/budget.py` | 初始/硬上限、预算快照、账本协议、追加授权与活动时间规则 |
| `backend/src/app/agent_runs/contracts.py` | 追加 T05 稳定错误码；旧错误码保持不变 |
| `backend/src/app/agent_runs/ports.py` | 重新导出 `BudgetLedger` 端口；T04 仓储协议不变 |
| `backend/src/app/agent_runs/__init__.py` | 导出 T04/T05 公共类型，不装配数据库或 worker |
| `backend/src/app/infrastructure/persistence/agent_attempt_repository.py` | PostgreSQL 账本：行锁/fence、初始授权、预留、发送、结算、未知、活动、追加授权 |
| `backend/src/app/infrastructure/persistence/models/agent_attempts.py` | 四表 ORM、约束、索引、meter 与 JSONB 空值语义 |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | 注册 T05 模型 |
| `backend/alembic/versions/0023_agent_attempts.py` | 前向迁移：四表、约束、索引、身份/终态/形状触发器；回退显式拒绝 |
| `backend/alembic/versions/0024_agent_attempt_hardening.py` | 复审修复迁移：发送前 failed 时间约束、released 状态、meter/state actual 形状 CHECK 与触发器替换 |
| `backend/alembic/versions/0025_agent_attempt_shape_fix.py` | R1 前向修复：次数 settled 显式要求 actual 非空且为 1，替换同一形状 CHECK |
| `backend/tests/agent_runs/test_segments.py` | C4 纯类型边界测试 |
| `backend/tests/agent_runs/test_attempts.py` | 逻辑步骤、类别预留、状态迁移、终态结果测试 |
| `backend/tests/agent_runs/test_budget.py` | 初始/硬上限、追加授权、有效上限、活动时间、快照一致性测试 |
| `backend/tests/persistence/test_agent_attempts.py` | 真实 PostgreSQL：F1–F4、R1、预留/发送/结算、跨片段/修订、未知、重试、并发、追加、活动、fence、不可变与回滚 |

### 3.2 SHA-256 文件指纹（implementation tip `f9454ad`）

| 文件 | SHA-256 |
| --- | --- |
| `backend/alembic/versions/0023_agent_attempts.py` | `6c238c2ff457e7f85600ff68d3fd6f09cb8a1e449ae914df31ea46cec024ff6b` |
| `backend/alembic/versions/0024_agent_attempt_hardening.py` | `965c4bebeb1a1cf92e6bac4c44e13bab72fc712a80772af8a86a33d943649cae` |
| `backend/alembic/versions/0025_agent_attempt_shape_fix.py` | `34a2f1a5b933fe37aa5d43b46486f136e37b2476b7180b93eca7e2dc5cc3a944` |
| `backend/src/app/agent_runs/__init__.py` | `80966d83ce1038d3dadccabbff141d9720445963828de40106d1bf8e80dbcac7` |
| `backend/src/app/agent_runs/attempts.py` | `af36e763e45d837e75719d4aa4fd607689723e16d690ee9a06e382202fc163ab` |
| `backend/src/app/agent_runs/budget.py` | `76042e8202430a79d45be218915b1b593d093925a2bd3294f6e536e944767668` |
| `backend/src/app/agent_runs/contracts.py` | `29d3ea0dd0986b43216b635cee66dbbbe13e7089ad66ed85ca33912025c61841` |
| `backend/src/app/agent_runs/ports.py` | `3e9a04bc1cd0e6e15c6e6906f6d785b4cf9e2e5c0472c86a1f1d2496f2c6f771` |
| `backend/src/app/agent_runs/segments.py` | `ae5a7e8e89e37bd25a501540c3bd0e5e9cf38582a5d9e2fc8ff3d684b4a954ae` |
| `backend/src/app/infrastructure/persistence/agent_attempt_repository.py` | `094664e0f577f71d8868cba14d8f5451fe49b4735d7caf48c478672c46d87e32` |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | `1db862e5177e6278a1fcb7a3c5ae7646be4ccb94aafdaa17b147b99858918cd6` |
| `backend/src/app/infrastructure/persistence/models/agent_attempts.py` | `97ab104099c239aa75c8c17b02452939d1c302dc402c204cfa1ef0de4829faf9` |
| `backend/tests/agent_runs/test_attempts.py` | `bb11412bb445cd78cba8a297ac0137a4b8ea45a6391bff06fdf7d9b6d458142f` |
| `backend/tests/agent_runs/test_budget.py` | `90089f19baadc8091b931316f376f6eba363f1bd108554cabbb18549fd80ad82` |
| `backend/tests/agent_runs/test_segments.py` | `9275e2e6392bea1eac1cf67599a2f2ebfee925dabf5701ecd1cf45249e25664b` |
| `backend/tests/persistence/test_agent_attempts.py` | `368bb4fd7b6479354d9c9ad41ac2610fa2ca6702c43c5bc1b7eb730e18c95acc` |
| `backend/tests/agent_runs/test_budget.py` | `90089f19baadc8091b931316f376f6eba363f1bd108554cabbb18549fd80ad82` |
| `backend/tests/agent_runs/test_segments.py` | `9275e2e6392bea1eac1cf67599a2f2ebfee925dabf5701ecd1cf45249e25664b` |
| `backend/tests/persistence/test_agent_attempts.py` | `1561c52eca9614ac8a2e764f5bb23f535376c9bc8059675c744a31f005be0e75` |

## 4. 关键实现取舍

1. **逻辑步骤在发送前确定。** `logical_step_id(fence, request)` 由 run/revision/动作序号/输入指纹/类别派生 UUID；`agent_steps` 对 `(run_id, revision, action_sequence)` 唯一。相同步骤重入返回原 attempt/结果；同动作序号换输入或类别返回 `step_conflict`。这保证调用方不能在外部调用之后才生成幂等键。
2. **meter 行是预算权威账本。** 每次真实发送创建 `model_calls`/`tool_calls`/`transport_calls` 及模型 `input_tokens`/`output_tokens` 行；已占用为 `COALESCE(actual_amount, reserved_amount)`。prepared/unknown 保留最坏预留；已知 usage 才写入 actual。未知 usage 不会被当成 0。
3. **先提交发送状态再给传输许可。** `reserve` 只返回 prepared；`mark_sent` 在 run 行锁内把 attempt 置为 in_flight、写入 sent_at 并返回后，调用方才可发送。重复 `mark_sent` 返回 `invalid_attempt_transition`；prepared 允许新片段接管围栏，但只能有一个 attempt。
4. **fence 校验在任务行锁内完成。** 每次操作锁 `agent_runs` 行，核对工作台、当前 revision、owner、lease_epoch，并用数据库 `clock_timestamp()` 判断 `lease_expires_at` 未过期；不信任客户端时钟。T05 不实现 claim/heartbeat，测试直接构造 running+租约；T07 必须复用该 fence 语义。
5. **未知调用保守处理。** in_flight 可由当前有效 fence 标记 unknown（失租恢复）；unknown 只有在提供 `receipt_verified=True` 且非空 `provider_receipt` 时才能结算为 succeeded/failed。同一逻辑键在 unknown 状态下 `reserve` 直接拒绝 `unknown_not_replayable`；后续工作必须使用新的动作序号/明确新授权。
6. **重试与成功复用分开。** 每个逻辑步骤最多 2 个 attempt；已知可重试失败后新 attempt 独立占预算，第三次返回 `attempt_limit`；成功步骤再次预留直接返回保存的 `ArtifactRef`，不新增调用或 Token。
7. **AP-05 追加授权只改 Agent 预算。** 授权为绝对值；新授权逐维度不得低于当前有效上限、至少一项增加、不得超过部署硬上限，授权引用唯一且同内容重放幂等。初始授权在首次预留/追加时惰性写入；只有 `planning_pools.generation` 不变测试证明不触碰交易资金/规划代次。
8. **活动时间按片段记录。** 一个片段只允许一条 `activity_seconds` 记录，重放同秒数幂等、不同秒数拒绝；`reserve`/`mark_sent` 检查剩余时间至少 15 秒。实际超时如实累计并阻塞后续新调用，不反向删除已发生活动。
9. **数据库约束与触发器多层防护。** 步骤/尝试身份字段不可变；attempt 终态与已发送围栏不可回写；step succeeded 必须带 result_ref 且不可重开；reservation unknown 可被回执结算为 settled，但 settled 不可再改；授权与账本行禁止删除。应用层仍先执行状态机校验。
10. **成功结果引用保持不透明。** T05 只保存 `ArtifactRef`，不创建产物行、不内嵌模型响应或财务值。T11/T14 接线时必须提供真实已校验结果引用；这是后续任务需要核对的依赖，不由 T05 冒充已实现产物服务。
11. **发送前预算准入不重复预留（F1）。** `mark_sent` 使用 `validate_send_fits` 检查当前累计是否已越限；该 prepared 的次数/Token 已在累计中，不再加一份预留。恰好等于上限允许发送，越限返回 `budget_exhausted` 并保持 prepared，直到追加授权。
12. **跨修订回执对账（F2）。** `_load_attempt` 区分“发送只限当前修订”和“结算可读历史已发送尝试”。当前有效 owner/fence 可对同 run/workspace 的历史 in_flight/unknown 凭可验证回执结算；旧 revision fence 仍 `lease_lost`，旧 prepared 仍不能发送或结算。历史回执无 `receipt_verified` 返回 `receipt_required`。
13. **发送前失败是明确未发送终态（F3）。** prepared→failed 保持 `sent_at=NULL`、不保存 usage/回执、写 settled_at；次数/Token meter 全部 `released` 并从预算累计排除；attempt 行保留，仍占用该逻辑步骤两次尝试之一。这样失败不伪造发送、不消耗调用成本，也不能无限预检重试。
14. **meter/state 形状由数据库统一约束（F4）。** `0024` 增加同时作用于 INSERT/UPDATE 的 CHECK：未结算 Token 的 actual 必须 NULL，`released` 必须 actual NULL，次数 meter 在 charged 时允许合法 actual=1，settled 次数必须 actual=1；触发器仅允许 reserved→released，已发送 charged 不得释放。
15. **次数 settled 必须显式非空（R1）。** 0024 的 `state='settled' AND actual_amount=1` 在 actual=NULL 时整体为 NULL，CHECK 会放行；`0025` 前向替换同一约束为 `actual_amount IS NOT NULL AND actual_amount = 1`。0024 不改写；若既有库存在 direct-SQL 写入的非法 settled+NULL 行，迁移 fail-closed，需先审计/修复，不自动改写账本历史。

## 5. 接口、依赖与迁移影响

### 5.1 公共接口

- C4 纯类型：`RunFence`、`ExecutionContext`（包含可选 `EvidenceEpoch`）、`SegmentOutcome`、`CompletionDecision`、`PlanAdoptionProposal`。
- C5 类型：`AttemptCategory`、`AttemptStatus`、`AttemptRequest`、`AttemptResult`、`StepAttempt`、`TokenUsage`；`logical_step_id`、`attempt_transition_allowed`。
- 预算：`BudgetLimits`、`BudgetStatus`、`BudgetLedger` 协议；`initial_budget_limits`、`hard_budget_limits`、`effective_budget_limits`、`validate_append_limits`、`validate_activity_start`、`validate_reservation_fits`、`validate_send_fits`。
- PostgreSQL：`SqlAlchemyBudgetLedger.reserve/mark_sent/settle/status/record_activity/append_authorization`；meter 状态增加 `released`（仅发送前失败）。
- 新增稳定错误码：`budget_exhausted`、`attempt_limit`、`attempt_in_flight`、`attempt_not_found`、`unknown_not_replayable`、`step_conflict`、`invalid_attempt_transition`、`receipt_required`、`lease_lost`、`invalid_budget_authorization`、`invalid_activity`。旧 T04 错误码保持不变。

相对契约 C5 的扩展：`BudgetLedger` 在固定 `reserve/mark_sent/settle` 之外增加只读 `status`、活动时间 `record_activity` 与 AP-05 `append_authorization`。这些是 T05 交付所需的账本能力，不改变已有三方法的语义；T06/T07 分别消费追加授权与 fence。

### 5.2 依赖

- 无新增生产依赖；未升级 LangGraph、MCP、httpx 或其他锁定依赖。
- 未调用真实模型、未访问私有账户、未接入交易执行；测试使用合成 UUID、用量、回执和临时 schema。
- T06 需要在 AP-05 批准后调用 `append_authorization`，不能由模型自批；T07 需要实现 claim/heartbeat 并以当前 fence 调用账本；T09/T10/T11 必须在真实发送前调用 `reserve/mark_sent`，发送结果经 `settle` 提交。

### 5.3 迁移

- `0023_agent_attempts`，`down_revision=0022_agent_tasks`；F1–F4 修复新增 `0024_agent_attempt_hardening`，R1 修复新增 `0025_agent_attempt_shape_fix`，当前 head 为 `0025_agent_attempt_shape_fix`。
- 四表：`agent_steps`、`agent_attempts`、`budget_authorizations`、`budget_reservations`；外键只指向既有 `agent_runs`/本迁移新表。
- `0025` 只前向替换 `ck_budget_reservation_shape`，不改写 0024：次数 settled 要求 `actual_amount IS NOT NULL AND actual_amount = 1`，覆盖 INSERT/UPDATE；合法历史行不受影响，非法历史行会使约束校验失败并 fail-closed。
- 约束覆盖：步骤/尝试身份、状态集合、attempt 1..2、时间一致性、授权硬上限与 initial/append 形状、meter 集合/活动记录唯一、result_ref 与 succeeded 一致、meter/state actual 形状。
- 触发器覆盖：步骤/尝试身份不可变、attempt/step 终态、未知回执可结算、reservation 终态与状态迁移（reserved→released 仅发送前失败）、授权只追加、四表禁止删除。
- 回退显式 `NotImplementedError`；未修改 0022/0023/0024 或任何已提交迁移；未迁移业务库。首次 T05 操作会为已有 T04 run 惰性写入初始预算授权，不要求回填。

## 6. 测试执行与证据

所有 SQL 测试使用显式进程环境 `TEST_DATABASE_URL` 指向专用测试 PostgreSQL 17（固定库名/受限角色，通过身份预检）；未记录连接串，未指向业务库。测试命令在 `D:\t05\backend`（聚焦/阶段）或 `D:\t05`（full）执行。

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 首轮预期红 | `uv run --locked --no-sync pytest tests/agent_runs/test_segments.py tests/agent_runs/test_attempts.py tests/agent_runs/test_budget.py tests/persistence/test_agent_attempts.py -q` | 4 collection errors（缺少新模块），退出 1；符合测试先行预期 |
| F1–F4 预期红 | 真实 PostgreSQL 执行 F1–F4 新回归 | F1 `mark_sent` 未拒绝；F2 新围栏 `attempt_not_found`；F3 `invalid_attempt_transition`；F4 直接 SQL 未报错；4 failed，退出 1；已逐项复现 |
| R1 预期红 | `pytest ...::test_sql_count_settled_requires_non_null_actual_but_allows_one` | 次数 settled + `actual_amount=NULL` 直接 INSERT 未报错（DID NOT RAISE）；退出 1 |
| R1 修复聚焦 | `uv run --locked --no-sync python -m pytest tests/agent_runs tests/persistence/test_agent_attempts.py -q --basetemp=..\.tmp\pytest\t05-r1-focus` | 41 passed，退出 0；证据 `D:\t05\.tmp\quality\t05-r1-focus.log` |
| R1 修复阶段回归 | `uv run --locked --no-sync python -m pytest tests/agent_runs tests/persistence/test_agent_attempts.py tests/persistence/test_agent_runs.py tests/persistence/test_migrations.py tests/security tests/governance -q --basetemp=..\.tmp\pytest\t05-r1-stage` | 185 passed，退出 0；证据 `D:\t05\.tmp\quality\t05-r1-stage.log` |
| R1 修复后端 full | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t05-r1-full.json` | `verification=passed`；1183 collected / 1183 passed / 0 failed / 0 skipped / 0 collection errors；证据 `D:\t05\.tmp\quality\manual-agent-t05-r1-full.json` |
| Ruff | `uv run --locked --no-sync ruff check .` | 通过，退出 0 |
| 格式 | `uv run --locked --no-sync ruff format --check .` | 通过，退出 0 |
| Pyright | `uv run --locked --no-sync python -m pyright` | 0 errors / 0 warnings，退出 0；移动工作区后使用模块入口避开 uv trampoline 路径问题 |
| 架构门禁 | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，38 files，findings=[]，退出 0 |
| 迁移链 | `uv run --locked --no-sync python -m alembic heads` | `0025_agent_attempt_shape_fix (head)`，退出 0 |

### 6.1 失败与重跑说明

首轮 full 的 1175 passed、上轮修复 full 的 1182 passed 报告仍保留；R1 修复后以 1183 passed 报告为准。首轮 full 曾受宿主环境变量和 Windows 长路径临时目录影响，最终在隔离环境与短路径下通过；两次失败已保留记录，未删改，不计入最终通过证据。

### 6.2 测试覆盖断言摘要

- 第 9 次模型、第 13 次工具在未追加授权时 `budget_exhausted`；追加后成功，超过部署硬上限/降低上限/同引用异内容被拒绝。
- **F1：** 6 个大预留 + 1 个待发送预留，前 4 个实际输入 16384 结算后累计 98560 > 98304；`mark_sent` 返回 `budget_exhausted`，目标仍 prepared；追加输入授权后才能发送，且不重复加自身预留。
- **F2：** revision 1 的 unknown 在 revision 2 当前围栏下无回执返回 `receipt_required`，有可验证回执可结算为 succeeded 并更新实际用量；revision 1 旧围栏仍 `lease_lost`，旧 prepared 的 `mark_sent` 仍 `attempt_not_found`。
- **F3：** reserve 后直接 settle(failed) 成功；attempt 为 failed、`sent_at IS NULL`、`settled_at` 非空；三条 meter 全为 `released` 且 actual 为空；预算次数/Token 归零；同键重试为 attempt 2，第二次发送前失败后第三次 `attempt_limit`。
- **F4：** 直接 UPDATE prepared 的 input/output `actual_amount=0` 被数据库拒绝，预算仍为 1024/512；直接 INSERT unknown+actual=0 和 reserved 次数+actual=1 均被 CHECK 拒绝；正常 charged 次数 actual=1 仍可写入。
- **R1：** 使用无既有 `(attempt_id,meter)` 的合成模型尝试直接 INSERT `model_calls, settled, actual=NULL` 被拒绝，SQLSTATE 23514 且错误文本含 `ck_budget_reservation_shape`；同形状 settled+actual=1、charged+actual=1 插入合法。原直接 INSERT 测试已改用不冲突数据，避免唯一键掩盖形状校验。
- 7 个模型调用后并发竞争最后 1 个额度，只有一个成功；同一逻辑步骤并发双预留返回同一 attempt 和一份预算。
- 成功 usage 结算后预留释放为实际值；缺失 usage 的 unknown 保留 16384/4096；同键 unknown 不自动重放；可验证回执可结算并更新实际用量。
- 跨片段/跨 revision 的 `model_sent`、输入/输出累计不重置；同一成功逻辑键复用不新增预算；第二次失败后第三次返回 `attempt_limit`。
- 活动时间 584 秒仍可开始调用，585 秒（剩余 15 秒）被拒绝；同片段同秒数幂等、不同秒数拒绝；追加活动时间后恢复。
- fence owner/epoch/revision/workspace 不匹配与租约过期返回 `lease_lost`；已成功步骤/尝试不能回写，授权/账本不能删除，回滚不留下半个步骤或 reservation。
- AP-05 追加后合成 `planning_pools.generation` 保持 3，证明预算追加不推进交易规划代次或资金资料。

## 7. 未验证项、已知风险与重点审查位置

### 7.1 未验证项

- T07 实际 claim/heartbeat/recover_expired、真实子进程终止后的 unknown 标记与结果复用，以及跨修订历史 unknown 的恢复枚举；T05 通过直接构造 running+lease 行验证 fence/对账语义，但不是 worker 端到端。
- T06 的 AP-05 用户审核、差异材料、批准记录与 `append_authorization` 调用；T05 只提供原语，无法证明用户授权流程。
- T09/T10/T11 的工具/MCP/模型实际发送是否每次都先 `reserve`、`mark_sent`、再 `settle`；T05 未接线，也未证明 SDK 隐藏重试已关闭；发送前 failed 的调用方语义需由这些适配器统一。
- T14 的产物持久化与 `ArtifactRef` 真实内容；成功结果引用目前只有协议约束，尚无生产 ArtifactService。
- 真实供应商回执真实性、回执与具体 attempt/请求绑定；`receipt_verified` 仍是受信调用方断言，T05 未实现供应商查询。
- HTTP/API、前端、浏览器 e2e、完整 Compose、业务库迁移、真实供应商 usage/回执、真实模型质量。
- 工具并发固定为 1 的运行时强制属于 T09；T05 只冻结常量，未证明并发守卫。

### 7.2 已知风险

1. **成功结果引用依赖后续产物服务。** `AttemptResult.succeeded` 必须提供 `ArtifactRef`；T11/T14 需要真实 staging 适配器，否则模型决策无法合法结算。审查重点：该约束是否会把产物实现风险错误地推迟到后续任务。
2. **fence 语义跨任务。** T05 的行锁 + 数据库时钟检查是 T07 租约的基础，但 claim/heartbeat 尚未实现；如果 T07 使用不同 owner/epoch 生命周期或客户端时间，可能出现误判。审查重点：`_lock_fenced_run` 的字段与 T07 契约是否一致。
3. **未知回执结算路径。** 应用层信任调用方传入 `receipt_verified`，数据库只允许 unknown→settled；没有供应商查询实现。F2 进一步允许当前 owner/fence 对历史已发送尝试做同样对账，回执真实性/绑定具体 attempt 必须由后续适配器负责。审查重点：是否应把回执核验下沉到端口，避免调用方自报或跨尝试复用回执。
4. **活动时间记录粒度。** 当前一个片段只允许一条活动记录，T07 必须在片段结束时聚合后写入；若未来需要分段多次记录，需扩展而非覆盖。审查重点：该约束是否会影响恢复/多阶段片段。
5. **Token 超限的实际结算。** `BudgetStatus` 对调用次数强制不超过上限，但 Token/活动时间允许实际值超过上限以如实反映供应商回执；F1 已让 `mark_sent` 在越限时停止新发送。审查重点：是否还需要额外告警事件，而不是仅返回 `budget_exhausted`。
6. **初始授权惰性写入。** 已有 T04 run 首次 T05 操作时才写 initial 授权；`status` 在无授权行时按初始档只读返回。审查重点：审计是否需要迁移时预填，或当前惰性创建已足够。
7. **数据库触发器与未知结算。** `budget_reservations` 允许 unknown→settled 以支持可验证回执；若调用方伪造回执，数据库不能识别。审查重点：应用层/端口责任边界。
8. **发送前失败语义。** F3 选择“保留 attempt 计数、释放次数/Token、无 sent_at”；需确认这与 T07/T11 对预检失败、取消和格式纠错的预期一致，避免把预检重试误当成免费无限重试。
9. **历史对账权限边界。** F2 只放开当前有效 owner/fence 对历史 in_flight/unknown 的回执结算；旧 prepared 仍不能发送或结算，旧 revision fence 仍拒绝。需确认 T07 恢复枚举不会绕过该边界。
10. **数据库形状约束的维护成本。** F4 的 `ck_budget_reservation_shape` 同时约束 INSERT/UPDATE；未来新增 meter/state 时必须同步迁移与模型，否则会被 fail-closed 拒绝。审查重点：约束是否完整覆盖当前全部合法写入路径。
11. **次数 settled 的 SQL 三值逻辑。** R1 说明 `actual_amount = 1` 单独使用会在 NULL 时得到 NULL 并被 CHECK 放行；`0025` 已显式 `IS NOT NULL`。审查重点：未来新增 meter/state 分支时是否都显式处理 NULL，避免重复同类缺口。
12. **长路径与 tester 临时目录。** 最终 full 依赖短工作区路径；普通长路径工作区仍可能触发 `pytester` 的 Windows 路径问题，属于验证环境限制，不是 T05 行为。审查重点：是否需要单独向质量工具报告，而不是在本轮扩大代码范围。

## 8. 请求审查的重点

1. 核对 `agent_attempts` 身份/终态触发器、`agent_steps` succeeded result_ref 约束、`budget_reservations` unknown→settled/released 路径是否形成可绕过的状态漏洞。
2. 核对 run 行锁 + `clock_timestamp()` fence 检查与 T04 owner/lease 字段、T07 预期契约是否一致；确认 F2 只放开对账读取，不放开旧发送/写入。
3. 核对 meter 账本的 `COALESCE(actual, reserved)` 在 prepared/in_flight/succeeded/failed/unknown/released、缺 usage、实际超预留、跨片段/修订下是否保守且不重复计费。
4. 核对 F1 的 `validate_send_fits` 在恰好等于上限、实际用量超限、追加授权前后是否按“不重复加预留”的语义工作。
5. 核对 F3 的 prepared→failed：`sent_at=NULL`、settled_at、attempt 计数与 meter released 是否一致，是否仍存在伪造发送或无限预检窗口。
6. 核对 F4/R1 的 CHECK 是否同时覆盖 INSERT/UPDATE、次数 meter 在 settled 时必须 actual 非空且为 1、charged 时 actual=1 合法，并复核直接 SQL 绕过路径及 SQLSTATE/约束名断言是否真实。
7. 核对 AP-05 追加授权的绝对值/单调性/硬上限/引用幂等，以及是否确实与交易资金、规划代次和风险政策隔离。
8. 核对并发预留、双重预留、重试 attempt 上限、成功复用和未知拒绝重放是否存在竞态或重复发送窗口。
9. 核对活动时间“一片段一条记录 + 15 秒余量”的语义，以及 T07 接线时的可操作性。
10. 核对 0025 仅前向替换约束、未改写 0023/0024；确认兼容影响（合法历史行通过、非法历史行 fail-closed）被准确记录。
11. 核对测试是否真实使用 PostgreSQL 行锁/触发器，而不是以 Mock 或纯模型自评替代；确认未验证项没有被写成已通过。

## 9. 正式审查修复记录（第 2 轮）

首轮正式审查报告：`docs/superpowers/reviews/manual-agent/T05-formal-review.md`，结论为需要修改、未通过，4 项均为 P2。开发端先在真实 PostgreSQL 复现，再修复：

| 编号 | 核对/复现 | 根因 | 修复 |
| --- | --- | --- | --- |
| F1 | 6 个大预留 + 1 个待发送预留，前 4 个实际输入 16384 结算后累计 98560 > 98304；`mark_sent` 未拒绝，prepared 取得发送许可 | `mark_sent` 只复查活动时间，未检查已越限的 Token | 新增 `validate_send_fits`，只比较当前累计与上限，不再加已有预留；越限返回 `budget_exhausted`，prepared 保持；追加授权后可发送 |
| F2 | revision 1 下 unknown；推进 revision 2 后新围栏 `settle` 返回 `attempt_not_found`，旧围栏 `lease_lost` | `_load_attempt` 强制 attempt.revision 等于当前 revision；fence 也要求当前 revision | settle 使用 `allow_historical=True`；当前有效 owner/fence 可读取同 run/workspace 历史 in_flight/unknown，但必须有可验证回执；旧 fence、旧 prepared 发送仍拒绝 |
| F3 | reserve 后直接 `settle(failed)` 返回 `invalid_attempt_transition`；数据库强制 failed 有 sent_at | 纯状态机允许 prepared→failed，但结算守卫只处理 in_flight/unknown；时间约束无法表示发送前失败 | 显式发送前失败分支：`sent_at=NULL`、不保存 usage/回执、写 settled_at；meter 全 `released`；attempt 行保留并占用两次尝试之一；`0024` 放宽 failed 时间约束 |
| F4 | 直接 UPDATE prepared 的 Token reservation `actual_amount=0` 未报错；直接 INSERT unknown+actual=0 未报错 | 触发器只对 unknown/settled 约束 actual；INSERT 无形状 CHECK | `0024` 增加 INSERT/UPDATE 共用 `ck_budget_reservation_shape`；reserved/charged Token 的 actual 必须 NULL，released actual NULL，charged 次数 actual 允许 1；触发器允许 reserved→released，禁止已发送释放 |

复审修复提交：`bd2a59df2e323248046db33ac929cd5d5d8c1063`（`fix: harden agent attempts and budget settlement`），范围 `249a8ad..bd2a59d`，9 个文件，+567 / -22。修复后聚焦 40 passed、阶段回归 184 passed、后端 full 1182 passed / 0 failed / 0 skipped，迁移 head `0024_agent_attempt_hardening`。

### 9.1 复审剩余问题 R1（第 3 轮）

复审报告：`docs/superpowers/reviews/manual-agent/T05-rereview-bd2a59d.md`。

- **复现**：在真实 PostgreSQL 上，使用无既有 `(attempt_id, meter)` 的合成模型尝试直接 INSERT `meter='model_calls', state='settled', actual_amount=NULL`，0024 的 CHECK 未拒绝（DID NOT RAISE）。原直接 INSERT 测试还复用了已存在的 `(attempt_id, meter)` 唯一键，宽泛 DBAPIError 不能证明形状约束。
- **修复**：新增前向 `0025_agent_attempt_shape_fix`，不修改 0023/0024；替换同一 `ck_budget_reservation_shape`，次数 settled 改为 `actual_amount IS NOT NULL AND actual_amount = 1`；同步 ORM。
- **兼容影响**：合法历史行（settled 次数 actual=1）通过；若升级库已存在 direct-SQL 写入的非法 settled+NULL 行，`ADD CONSTRAINT` fail-closed，要求先审计/修复，不自动改写账本历史。
- **回归**：settled+NULL INSERT 拒绝并核对 SQLSTATE 23514/约束名；settled+1 合法；charged+1 合法；既有直接 INSERT 测试改用无冲突数据。
- **提交**：`f9454adab111218eaa8bc5880b37987031c11bb7`（`fix: reject settled call counts without actual amount`），范围 `bd2a59d..f9454ad`，3 个文件，+189 / -13；累计 `4d1af68..f9454ad`，16 个文件，+4407 / -6。
- **验证**：聚焦 41 passed、阶段回归 185 passed、后端 full 1183 passed / 0 failed / 0 skipped，迁移 head `0025_agent_attempt_shape_fix`。

## 10. 状态与转交

- 自测状态：`verified`（上述 F1–F4/R1 复现、聚焦、阶段、full、静态、架构、迁移链均实际执行）。
- 正式审查状态：`approved`，`reviewed_tip=f9454adab111218eaa8bc5880b37987031c11bb7`；用户于 2026-11-11 传回原审查助手正式通过结论（`T05-rereview-f9454ad.md`）。
- T05 代码/批准文档已以 fast-forward 合并到 `main`（合并 tip `cbffb4f`），随后推送远端；未部署、未迁移业务库。
- 审查材料：本文件、首轮正式报告 `T05-formal-review.md`、复审报告 `T05-rereview-bd2a59d.md`、最终复审 `T05-rereview-f9454ad.md`、implementation tip `f9454adab111218eaa8bc5880b37987031c11bb7`、首轮 tip `249a8ad`、上轮 tip `bd2a59d`、基线与上文文件指纹/证据路径。
- 通过结论仅针对 T05 当前 reviewed_tip；T06/T07 及真实模型/工具/MCP、回执真实性、产物持久化、HTTP/前端、业务库迁移仍未完成。
