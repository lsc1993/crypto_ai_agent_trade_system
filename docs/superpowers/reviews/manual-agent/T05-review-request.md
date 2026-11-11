# T05 审查请求：步骤账本、预算与未知调用

- 任务/审查单元：T05（D2）
- 执行模型：`deepseek-flash`（运行环境标识）；具体供应商构建、参数版本与上下文版本未在仓库内可确认，记为**未知**。执行载体为 DeepSeek Harness。
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0（日期均为 2026-11-06）。
- 自测状态：`verified`（实现、聚焦、SQL、阶段、静态、迁移链和最终后端 full 已完成）。
- 正式审查状态：`awaiting_review`。**尚未取得原审查助手结论；本文件不表示审查通过。**
- 审查请求生成：2026-11-11（Asia/Shanghai）。
- 审查请求文件本身在 implementation tip 之后作为独立 docs 提交；不把该文档提交号写入 implementation tip，避免循环引用。

## 1. 工作区、分支与审查范围

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main`，T05 开始时干净，tip `4d1af68`） |
| 隔离工作区 | `D:\t05`（短路径；为规避 Windows 260 字符路径上限，从 `.worktrees\manual-agent-t05-20261111` 移动，分支/内容/提交不变） |
| 分支 | `t05-agent-attempts-budget`（未合并、未推送） |
| base | `4d1af68fc704f50b21b9f9b0619b446f315f66d6`（`main`，T04 复审/合并文档之后） |
| implementation tip | `249a8adc3769c9576015c7ff4a4edaa3e1798a6b`（`feat: account for agent attempts and cumulative budgets`） |
| implementation tree | `0c5ed301e65cda5f8cfe084784b23cedf4ff01d4` |
| 代码审查范围 | `4d1af68..249a8ad`，14 个文件，+3686 / -6 |
| 文档提交 | 本审查请求、进度/状态/计划注记为 implementation tip 之后的独立 docs 提交；代码审查以 `249a8ad` 为准 |
| reviewed_tip | `—`（尚未取得正式结论） |
| 合并 | 未合并到 `main`，未推送、未部署、未迁移业务库 |

实现提交只包含本任务的 14 个代码/测试/迁移文件；`main` 工作区保持干净。未修改 `.env`、凭证、真实账户或业务库；未夹带其他任务未提交内容。

## 2. 任务范围、依赖与 FR/AC/HN

### 2.1 本轮范围

按实施计划 T05 与契约 C4/C5，本轮交付：

- C4 纯类型：`RunFence`、`ExecutionContext`、`SegmentOutcome`、`CompletionDecision`、`PlanAdoptionProposal`。
- C5 纯类型与账本：`AttemptCategory`、`AttemptStatus`、`AttemptRequest`、`AttemptResult`、`StepAttempt`、`TokenUsage`、逻辑步骤标识与状态迁移规则。
- `BudgetLimits`、`BudgetStatus`、`BudgetLedger` 协议；初始档、部署硬上限、有效上限合并、追加授权与活动时间检查。
- PostgreSQL 实现：`SqlAlchemyBudgetLedger.reserve/mark_sent/settle/status/record_activity/append_authorization`。
- `agent_steps`、`agent_attempts`、`budget_authorizations`、`budget_reservations` 四表与 `0023_agent_attempts` 前向迁移。
- 纯契约、纯预算和真实 PostgreSQL 三组测试。

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
| 迁移链 | 从 `0022_agent_tasks` 串行新增 `0023_agent_attempts`；未改写旧迁移 |

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
| `backend/tests/agent_runs/test_segments.py` | C4 纯类型边界测试 |
| `backend/tests/agent_runs/test_attempts.py` | 逻辑步骤、类别预留、状态迁移、终态结果测试 |
| `backend/tests/agent_runs/test_budget.py` | 初始/硬上限、追加授权、有效上限、活动时间、快照一致性测试 |
| `backend/tests/persistence/test_agent_attempts.py` | 真实 PostgreSQL：预留/发送/结算、跨片段/修订、未知、重试、并发、追加、活动、fence、不可变与回滚 |

### 3.2 SHA-256 文件指纹（implementation tip `249a8ad`）

| 文件 | SHA-256 |
| --- | --- |
| `backend/alembic/versions/0023_agent_attempts.py` | `6c238c2ff457e7f85600ff68d3fd6f09cb8a1e449ae914df31ea46cec024ff6b` |
| `backend/src/app/agent_runs/__init__.py` | `b04527abb271ec5fdfd9235a9ca25a71bf4a40150916b451474aaa2868c2b199` |
| `backend/src/app/agent_runs/attempts.py` | `112f6cf7a96dd53d455ad093c684c6f041120b4902ace10ca54939272dfbf773` |
| `backend/src/app/agent_runs/budget.py` | `1feadc211212790e26fb6f0c404b6e15962436bdea672a2e33705103658b9930` |
| `backend/src/app/agent_runs/contracts.py` | `29d3ea0dd0986b43216b635cee66dbbbe13e7089ad66ed85ca33912025c61841` |
| `backend/src/app/agent_runs/ports.py` | `3e9a04bc1cd0e6e15c6e6906f6d785b4cf9e2e5c0472c86a1f1d2496f2c6f771` |
| `backend/src/app/agent_runs/segments.py` | `ae5a7e8e89e37bd25a501540c3bd0e5e9cf38582a5d9e2fc8ff3d684b4a954ae` |
| `backend/src/app/infrastructure/persistence/agent_attempt_repository.py` | `928c9c98bea526d1b6348c33ad450d40734602d583dd28fda360ccbd736ce1c7` |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | `1db862e5177e6278a1fcb7a3c5ae7646be4ccb94aafdaa17b147b99858918cd6` |
| `backend/src/app/infrastructure/persistence/models/agent_attempts.py` | `4473e8b183a4a5efdf8e8f24cc42f2e004c697dad0d55e0df6eed6a168a0faad` |
| `backend/tests/agent_runs/test_attempts.py` | `b83500ad0b025c27f26747d182079e28bd3d6a6110714e2a713137a8650159a7` |
| `backend/tests/agent_runs/test_budget.py` | `9a5839064d455914980927297279519b7cdeaed2b9127b34d17d9cce89babee0` |
| `backend/tests/agent_runs/test_segments.py` | `9275e2e6392bea1eac1cf67599a2f2ebfee925dabf5701ecd1cf45249e25664b` |
| `backend/tests/persistence/test_agent_attempts.py` | `68b4ff248871a86b15007beadbeb099252df110e4d02390a4addc977ce7272c1` |

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

## 5. 接口、依赖与迁移影响

### 5.1 公共接口

- C4 纯类型：`RunFence`、`ExecutionContext`（包含可选 `EvidenceEpoch`）、`SegmentOutcome`、`CompletionDecision`、`PlanAdoptionProposal`。
- C5 类型：`AttemptCategory`、`AttemptStatus`、`AttemptRequest`、`AttemptResult`、`StepAttempt`、`TokenUsage`；`logical_step_id`、`attempt_transition_allowed`。
- 预算：`BudgetLimits`、`BudgetStatus`、`BudgetLedger` 协议；`initial_budget_limits`、`hard_budget_limits`、`effective_budget_limits`、`validate_append_limits`、`validate_activity_start`、`validate_reservation_fits`。
- PostgreSQL：`SqlAlchemyBudgetLedger.reserve/mark_sent/settle/status/record_activity/append_authorization`。
- 新增稳定错误码：`budget_exhausted`、`attempt_limit`、`attempt_in_flight`、`attempt_not_found`、`unknown_not_replayable`、`step_conflict`、`invalid_attempt_transition`、`receipt_required`、`lease_lost`、`invalid_budget_authorization`、`invalid_activity`。旧 T04 错误码保持不变。

相对契约 C5 的扩展：`BudgetLedger` 在固定 `reserve/mark_sent/settle` 之外增加只读 `status`、活动时间 `record_activity` 与 AP-05 `append_authorization`。这些是 T05 交付所需的账本能力，不改变已有三方法的语义；T06/T07 分别消费追加授权与 fence。

### 5.2 依赖

- 无新增生产依赖；未升级 LangGraph、MCP、httpx 或其他锁定依赖。
- 未调用真实模型、未访问私有账户、未接入交易执行；测试使用合成 UUID、用量、回执和临时 schema。
- T06 需要在 AP-05 批准后调用 `append_authorization`，不能由模型自批；T07 需要实现 claim/heartbeat 并以当前 fence 调用账本；T09/T10/T11 必须在真实发送前调用 `reserve/mark_sent`，发送结果经 `settle` 提交。

### 5.3 迁移

- 新增 `0023_agent_attempts`，`down_revision=0022_agent_tasks`，当前 head 为 `0023_agent_attempts`。
- 四表：`agent_steps`、`agent_attempts`、`budget_authorizations`、`budget_reservations`；外键只指向既有 `agent_runs`/本迁移新表。
- 约束覆盖：步骤/尝试身份、状态集合、attempt 1..2、时间一致性、授权硬上限与 initial/append 形状、meter 集合/活动记录唯一、result_ref 与 succeeded 一致。
- 触发器覆盖：步骤/尝试身份不可变、attempt/step 终态、未知回执可结算、reservation 终态与状态迁移、授权只追加、四表禁止删除。
- 回退显式 `NotImplementedError`；未修改 0022 或任何历史迁移；未迁移业务库。首次 T05 操作会为已有 T04 run 惰性写入初始预算授权，不要求回填。

## 6. 测试执行与证据

所有 SQL 测试使用显式进程环境 `TEST_DATABASE_URL` 指向专用测试 PostgreSQL 17（固定库名/受限角色，通过身份预检）；未记录连接串，未指向业务库。测试命令在 `D:\t05\backend`（聚焦/阶段）或 `D:\t05`（full）执行。

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 预期红 | `uv run --locked --no-sync pytest tests/agent_runs/test_segments.py tests/agent_runs/test_attempts.py tests/agent_runs/test_budget.py tests/persistence/test_agent_attempts.py -q` | 4 collection errors（缺少新模块），退出 1；符合测试先行预期 |
| 聚焦 | `uv run --locked --no-sync python -m pytest tests/agent_runs tests/persistence/test_agent_attempts.py -q --basetemp=..\.tmp\pytest\t05-focus-final` | 33 passed，退出 0；证据 `D:\t05\.tmp\quality\t05-focus.log` |
| 阶段回归 | `uv run --locked --no-sync python -m pytest tests/agent_runs tests/persistence/test_agent_attempts.py tests/persistence/test_agent_runs.py tests/persistence/test_migrations.py tests/security tests/governance -q --basetemp=..\.tmp\pytest\t05-stage-final` | 177 passed，退出 0；证据 `D:\t05\.tmp\quality\t05-stage.log` |
| 最终后端 full | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t05-full-backend-final.json` | `verification=passed`；1175 collected / 1175 passed / 0 failed / 0 skipped / 0 collection errors；证据 `D:\t05\.tmp\quality\manual-agent-t05-full-backend-final.json` |
| Ruff | `uv run --locked --no-sync ruff check .` | 通过，退出 0 |
| 格式 | `uv run --locked --no-sync ruff format --check .` | 通过，退出 0 |
| Pyright | `uv run --locked --no-sync pyright` | 0 errors / 0 warnings，退出 0 |
| 架构门禁 | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，38 files，findings=[]，退出 0 |
| 迁移链 | `uv run --locked --no-sync python -m alembic heads` | `0023_agent_attempts (head)`，退出 0 |

### 6.1 失败与重跑说明

- 首次官方 full 继承了宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`，出现 3 个与本任务无关的 CORS/设置失败（1172 passed / 3 failed），未作为通过证据。
- 移除宿主环境变量后，官方 full 仍遇到 `tests/tooling/test_test_database_guard.py` 的临时文件写入失败；实际原因是长工作区路径叠加 `--basetemp` UUID 与长测试名超过 Windows 260 字符，`pytester` 无法创建临时子目录，不是 T05 代码失败。该用例单独运行及在短路径下通过。
- 将工作区移动到 `D:\t05`、重新同步 editable 安装并将 pytest 临时根放在工作区内后，最终官方 full 通过。失败日志/报告保留在 `.tmp/quality`，未删除或改写；最终结论只引用最后一次通过证据。

### 6.2 测试覆盖断言摘要

- 第 9 次模型、第 13 次工具在未追加授权时 `budget_exhausted`；追加后成功，超过部署硬上限/降低上限/同引用异内容被拒绝。
- 7 个模型调用后并发竞争最后 1 个额度，只有一个成功；同一逻辑步骤并发双预留返回同一 attempt 和一份预算。
- 成功 usage 结算后预留释放为实际值；缺失 usage 的 unknown 保留 16384/4096；同键 unknown 不自动重放；可验证回执可结算并更新实际用量。
- 跨片段/跨 revision 的 `model_sent`、输入/输出累计不重置；同一成功逻辑键复用不新增预算；第二次失败后第三次返回 `attempt_limit`。
- 活动时间 584 秒仍可开始调用，585 秒（剩余 15 秒）被拒绝；同片段同秒数幂等、不同秒数拒绝；追加活动时间后恢复。
- fence owner/epoch/revision/workspace 不匹配与租约过期返回 `lease_lost`；已成功步骤/尝试不能回写，授权/账本不能删除，回滚不留下半个步骤或 reservation。
- AP-05 追加后合成 `planning_pools.generation` 保持 3，证明预算追加不推进交易规划代次或资金资料。

## 7. 未验证项、已知风险与重点审查位置

### 7.1 未验证项

- T07 实际 claim/heartbeat/recover_expired、真实子进程终止后的 unknown 标记与结果复用；T05 通过直接构造 running+lease 行验证 fence 语义，但不是 worker 端到端。
- T06 的 AP-05 用户审核、差异材料、批准记录与 `append_authorization` 调用；T05 只提供原语，无法证明用户授权流程。
- T09/T10/T11 的工具/MCP/模型实际发送是否每次都先 `reserve`、`mark_sent`、再 `settle`；T05 未接线，也未证明 SDK 隐藏重试已关闭。
- T14 的产物持久化与 `ArtifactRef` 真实内容；成功结果引用目前只有协议约束，尚无生产 ArtifactService。
- HTTP/API、前端、浏览器 e2e、完整 Compose、业务库迁移、真实供应商 usage/回执、真实模型质量。
- 工具并发固定为 1 的运行时强制属于 T09；T05 只冻结常量，未证明并发守卫。

### 7.2 已知风险

1. **成功结果引用依赖后续产物服务。** `AttemptResult.succeeded` 必须提供 `ArtifactRef`；T11/T14 需要真实 staging 适配器，否则模型决策无法合法结算。审查重点：该约束是否会把产物实现风险错误地推迟到后续任务。
2. **fence 语义跨任务。** T05 的行锁 + 数据库时钟检查是 T07 租约的基础，但 claim/heartbeat 尚未实现；如果 T07 使用不同 owner/epoch 生命周期或客户端时间，可能出现误判。审查重点：`_lock_fenced_run` 的字段与 T07 契约是否一致。
3. **未知回执结算路径。** 应用层信任调用方传入 `receipt_verified`，数据库只允许 unknown→settled；没有供应商查询实现。审查重点：是否应把回执核验下沉到适配器/端口，避免调用方自报。
4. **活动时间记录粒度。** 当前一个片段只允许一条活动记录，T07 必须在片段结束时聚合后写入；若未来需要分段多次记录，需扩展而非覆盖。审查重点：该约束是否会影响恢复/多阶段片段。
5. **Token 超限的实际结算。** `BudgetStatus` 对调用次数强制不超过上限，但 Token/活动时间允许实际值超过上限以如实反映供应商回执；之后新调用被拒绝。审查重点：这是否符合“超限前停止”的产品语义，或应额外产出明确告警事件。
6. **初始授权惰性写入。** 已有 T04 run 首次 T05 操作时才写 initial 授权；`status` 在无授权行时按初始档只读返回。审查重点：审计是否需要迁移时预填，或当前惰性创建已足够。
7. **数据库触发器与未知结算。** `budget_reservations` 允许 unknown→settled 以支持可验证回执；若调用方伪造回执，数据库不能识别。审查重点：应用层/端口责任边界。
8. **长路径与 tester 临时目录。** 最终 full 依赖短工作区路径；普通长路径工作区仍可能触发 `pytester` 的 Windows 路径问题，属于验证环境限制，不是 T05 行为。审查重点：是否需要单独向质量工具报告，而不是在本轮扩大代码范围。

## 8. 请求审查的重点

1. 核对 `agent_attempts` 身份/终态触发器、`agent_steps` succeeded result_ref 约束、`budget_reservations` unknown→settled 路径是否形成可绕过的状态漏洞。
2. 核对 run 行锁 + `clock_timestamp()` fence 检查与 T04 owner/lease 字段、T07 预期契约是否一致。
3. 核对 meter 账本的 `COALESCE(actual, reserved)` 在 prepared/in_flight/succeeded/failed/unknown、缺 usage、实际超预留、跨片段/修订下是否保守且不重复计费。
4. 核对 AP-05 追加授权的绝对值/单调性/硬上限/引用幂等，以及是否确实与交易资金、规划代次和风险政策隔离。
5. 核对并发预留、双重预留、重试 attempt 上限、成功复用和未知拒绝重放是否存在竞态或重复发送窗口。
6. 核对活动时间“一片段一条记录 + 15 秒余量”的语义，以及 T07 接线时的可操作性。
7. 核对新增错误码/协议方法是否属于可接受的 C5 扩展，是否需要在契约文档中进一步固定。
8. 核对测试是否真实使用 PostgreSQL 行锁/触发器，而不是以 Mock 或纯模型自评替代；确认未验证项没有被写成已通过。

## 9. 状态与转交

- 自测状态：`verified`（上述聚焦、阶段、full、静态、架构、迁移链均实际执行）。
- 正式审查状态：`awaiting_review`，`reviewed_tip=—`。
- 本轮停在审查门槛；未开始 T06/T07，未合并、未推送、未部署、未迁移业务库。
- 审查材料：本文件、implementation tip `249a8adc3769c9576015c7ff4a4edaa3e1798a6b`、基线与上文文件指纹/证据路径。
- 收到审查意见后，开发端先核对或复现，再逐条修复并补回归；有异议以代码和测试说明。修复后记录新 tip、变更范围和验证结果，再次提交审查。只有用户传回原审查助手对当前版本的正式通过结论，且本轮必需验证完成，才放行下一审查单元。
