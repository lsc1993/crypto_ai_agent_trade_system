# T06 复审请求：人工审核、连续消息与取消一致性

- 审查单元：T06
- 请求日期：2026-11-12
- 开发执行模型：`deepseek-flash`（provider `deepseek`，reasoning `max`）；具体模型权重版本未知，以上为本地会话环境可确认信息。
- 文档基线：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0。
- 上一次正式审查：`reviewed_tip=1ec0a72`，结论为不通过，需修复 F1（P2）；报告 `docs/superpowers/reviews/manual-agent/T06-formal-review.md`。
- 当前版本：F1 修复 tip `dea9848`，等待原审查助手复审；本文件中的自测不代表正式审查通过。

## 1. 工作区、提交与范围

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main`，T05 合并文档 tip `bbb4e0b`，工作区干净） |
| 隔离工作区 | `D:\t06` |
| 分支 | `t06-agent-interactions` |
| base | `bbb4e0bc010b46e0188923c176d7334e2764b241` |
| implementation tip（当前修复） | `dea98485ac668fd740a53a7dbe8bb69960fdcefc`（`fix: protect agent interaction stage times`） |
| implementation tree（当前修复） | `bd5637770e3c9e530d1ec376af34ce7d2ee13d58` |
| 首轮 implementation tip | `1ec0a72e74682ef17995cfca165967b475f764d8`（`feat: persist human review and task feedback`） |
| F1 修复范围 | `1ec0a72..dea9848`，4 个文件，+286 / -5 |
| 累计代码范围 | `bbb4e0b..dea9848`，19 个文件，+4112 / -7（不含审查文档提交） |
| 工作区状态 | 代码提交后干净；本审查请求与正式审查报告另行形成文档提交 |
| review_status | `awaiting_review`（F1 复审） |
| reviewed_tip | `—`（当前修复版本不得预填通过；上一次正式审查为 `1ec0a72`） |

说明：本次是对 F1 修复版本的复审请求。首轮实现 tip 为 `1ec0a72`，当前修复 tip 为 `dea9848`；审查包文档提交在代码提交之后另行记录，不复用自身提交号。`main` 未被修改，未推送、未合并、未部署。

### 1.1 文件清单（`git show --name-status 1ec0a72`）

```text
A backend/alembic/versions/0026_agent_interactions.py
M backend/src/app/agent_runs/__init__.py
M backend/src/app/agent_runs/contracts.py
A backend/src/app/agent_runs/decisions.py
M backend/src/app/agent_runs/events.py
A backend/src/app/agent_runs/interactions.py
A backend/src/app/agent_runs/messages.py
M backend/src/app/agent_runs/ports.py
M backend/src/app/agent_runs/service.py
M backend/src/app/infrastructure/persistence/agent_attempt_repository.py
A backend/src/app/infrastructure/persistence/agent_interaction_repository.py
M backend/src/app/infrastructure/persistence/agent_run_repository.py
M backend/src/app/infrastructure/persistence/models/__init__.py
A backend/src/app/infrastructure/persistence/models/agent_interactions.py
M backend/src/app/infrastructure/persistence/models/agent_runs.py
A backend/tests/agent_runs/test_interactions.py
A backend/tests/agent_runs/test_messages.py
M backend/tests/agent_runs/test_service.py
A backend/tests/persistence/test_agent_interactions.py
```

### 1.2 关键文件指纹（SHA-256，当前修复 tip）

```text
74a67329f0d06860b0555c8c352a3c6eb1ffb8d82dfa377b4e93355a207b45cf  backend/src/app/agent_runs/decisions.py
d39415512589d967af331831a458fd5b86721dd920f3cc15934442c1db0202a5  backend/src/app/agent_runs/interactions.py
0fc867768481b7dc9b4dfea71bad33a219c7d36e4ec91f069d04e12d87013683  backend/src/app/agent_runs/messages.py
9523bf0abe5bd9465482941ba72a59bd3ee1d97cbe52bc72cceb639fab5bd869  backend/src/app/infrastructure/persistence/agent_interaction_repository.py
e25d04944fce3db26af48f265767f3eba298e3d63ead44afd5d37031d00c30b1  backend/src/app/infrastructure/persistence/models/agent_interactions.py
dd33f004d6a0b4b67a1bb20ec018029205343f7e76b9a8c1ff43f23dfd26fd64  backend/alembic/versions/0026_agent_interactions.py
ec7ec0dcb5c0bea06a664f94e3febdc8df509a15a9620e7eb2c3180e0ec89ebb  backend/tests/agent_runs/test_interactions.py
ae7d90da483c45d897fcc032a6df962ba8c39e5e1f35e3df8e0fc4c82182f3b2  backend/tests/agent_runs/test_messages.py
262b8db54aeeb594ccc5456e3c280d285b06ab778139a01ff7df1e4ae746810d  backend/tests/persistence/test_agent_interactions.py
```

### 1.3 F1 修复文件

```text
M backend/alembic/versions/0026_agent_interactions.py
M backend/src/app/agent_runs/interactions.py
M backend/tests/agent_runs/test_interactions.py
M backend/tests/persistence/test_agent_interactions.py
```

`0026_agent_interactions` 仍未合并、未应用到业务库，因此按 T02 先例直接补强该迁移，不新增 `0027`；任何用旧版 0026 创建的临时测试 schema 需要重建，业务库没有需要前向修补的已应用迁移。

## 2. 任务范围与 FR/AC/HN 映射

T06 负责把人工审核、连续消息和取消从纯类型推进到可持久化、可幂等、可审计的服务与 SQL 仓储：

- AP-01 至 AP-07 的服务端分类；模型只能提出提案，不能自批。
- 审核待办的 `preparing/pending/answered/applied/expired` 状态、材料指纹、状态号 CAS、有效期和单活跃待办。
- 反馈请求键幂等、反馈只记录不提前应用、`adoption_applied=False`。
- 用户消息的单调序号与 `received/applied` 水位。
- running 取消标记、queued/等待态原子取消、终态不重开。
- 迁移 `0026_agent_interactions` 及数据库不可变/状态迁移防护。

| 需求/约束 | T06 覆盖 | 边界 |
| --- | --- | --- |
| FR-01 任务与交互 | 消息记录/水位、交互待办、请求键幂等 | 未实现 HTTP API/前端 |
| FR-11 人机交互与审核 | AP 分类、CAS、材料/有效期、顺序待办、过期拒绝 | 待办发布和应用由 T07 协调器完成 |
| FR-12 Harness/恢复/审计 | 交互/消息/取消事件、取消标记、持久状态 | 租约/心跳/片段恢复/终态原子提交归 T07 |
| AC-10 审阅/拒绝/修改 | 审核响应与回执 | 计划采纳为 T13 |
| AC-11 范围/预算差异 | AP-04/AP-05 分类与差异材料要求 | 不实际修改预算或范围 |
| AC-13 重复/过期/无反馈 | 同键重放、旧材料/旧状态拒绝、过期不默认批准 | 多页面浏览器旅程待 T16/T17 |
| AC-14 长等待后失效 | 过期响应与 `expire_due` 基础 | 行情重验和计划重大变更归 T13/T07 |
| AC-17 过程流安全 | 事件只含 ID/动作/决定/水位 | HTTP/SSE 归 T14/T17 |
| HN-06 等待释放资源 | 等待态无 owner；T06 不轮询 | T07 负责片段结束和 owner 释放 |
| HN-07 版本/材料/时效 | 材料 SHA、状态号、expires_at、数据库时钟 | 用户已明确同一授权的跨任务复用待 T13 |
| HN-08 消息水位 | recorded/applied 分离，终态拒收 | 完成判定归 T07 |
| HN-11 完成只是提案 | 反馈回执不宣称应用/采纳 | 业务完成由 T07/T14 |
| HN-12 安全投影 | 事件不含消息正文/财务/原始载荷 | 受限 HTTP 视图待 T14 |

## 3. 关键实现结果与取舍

### 3.0 正式审查 F1 逐条回应（P2）

**审查发现**：`validate_agent_interaction_update()` 允许在合法状态推进中改写或清空已写入的 `published_at`/`responded_at`。开发端已在真实 PostgreSQL 复现：`answered→expired` 同时清空发布/响应时间成功（测试期望抛错但 `DID NOT RAISE`）；`pending→answered` 改写 `published_at` 也成功；缺少 `responded_at` 的 `pending→answered` 被形状 CHECK 拒绝，未命中触发器原因。

| F1 要求 | 修复 | 回归 |
| --- | --- | --- |
| 已写入阶段时间禁止修改/清空 | 触发器对 `OLD.published_at/responded_at/applied_at/expired_at` 非空值逐项比较 `IS DISTINCT FROM`，改写或清空即 `agent interaction stage time is immutable` | `test_interaction_stage_times_cannot_be_rewritten_or_erased` 直接 SQL 覆盖 answered→expired 清空、pending→answered 改写；失败事务后记录仍保留 |
| 只允许本次合法迁移对应时间首次写入 | 按迁移分支强制：preparing→pending 只写 published_at；pending→answered 只写 responded_at；answered→applied 只写 applied_at；任意→expired 只写 expired_at，并保留旧阶段 | `test_interaction_stage_times_advance_only_with_legal_transition` 覆盖正常发布/响应/应用、缺少 responded_at、取消过期保留历史 |
| 过期保留已有阶段历史 | expired 分支要求 published/responded/applied 与 OLD 相等，只允许 expired_at 从 NULL 首次写入 | answered→expired 正常取消测试断言 published/responded 不变；清空测试断言拒绝 |
| 跳步测试补齐形状并断言具体原因 | 跳步测试补 responded_at/applied_at 使 applied 形状可通过，并断言 `invalid agent interaction transition`；材料改写断言 `agent interaction material is immutable` | `test_interaction_trigger_rejects_skipped_state_and_material_rewrite` |

兼容性：`0026_agent_interactions` 未合并、未应用到任何业务库，因此直接编辑 0026 的触发器函数，不新增 `0027`，迁移 head 仍为 `0026_agent_interactions`。旧版 0026 只可能存在于临时测试 schema，重建即可；没有历史业务数据需要修补。读取侧另补 `HumanInteraction` 不变量：expired 记录不能出现 responded_at 而无 published_at，防止异常历史被当作正常形状读取。

### 3.1 AP 分类

`DecisionPolicy.classify` 是纯函数：

- `read_only_research` → `allow`。
- `clarify` → `clarify`。
- `adopt_manual_plan`、`change_strategy`、`change_parameters`、`expand_scope`、`increase_budget`、`adopt_revised_plan` → 对应 AP-01 至 AP-06 的 `approve`。
- 缺少类型化差异或审核材料 → `clarify`，含糊“继续”不能替代 AP-05/AP-03 等差异。
- `self_approve`、`execute_trade`、`access_private_account` → `reject`。
- `enable_monitoring` → `reject/monitoring_unavailable`，因为监控尚未交付；`ApprovalKind.AP-07` 仅保留契约枚举，不宣称可用。

### 3.2 待办与反馈

- `HumanInteraction` 严格校验状态与 `published_at/responded_at/applied_at/expired_at` 的形状；`preparing` 不可响应，只有 `pending` 可响应。
- `InteractionRepository.prepare` 只在 running fence 下创建 `preparing`，同请求键幂等；单任务活跃待办由部分唯一索引 `ux_agent_interactions_active` 覆盖 `preparing/pending/answered`。
- `InteractionRepository.respond` 的事务顺序为队列锁 → 任务行锁 → 待办/反馈行锁，核对：
  - 工作台/任务/待办归属；
  - 当前待办 `current_interaction_id`；
  - 修订号、材料 SHA-256、`expected_state_version`；
  - 数据库 `clock_timestamp()` 与 `expires_at`；
  - 决定类型与动作匹配（澄清只接受 `provide_input`，审批动作不得用 `provide_input`）。
- 成功响应只把待办置为 `answered`、任务置为 `queued`，写入不可变反馈并追加 `interaction.responded` 事件；回执固定 `receipt_state="recorded"`、`adoption_applied=False`。计划采纳、预算追加和可实施状态均未在此发生。
- 过期响应在事务内把待办和任务置为 `expired`、追加 `interaction.expired`，提交后返回 `review_expired`；`expire_due` 提供维护扫描。

### 3.3 连续消息

- `agent_user_messages` 在任务行锁内分配 `seq`，同请求键同内容重放、异内容冲突。
- `RunSnapshot.received_message_seq` 在记录时推进；`applied_message_seq` 只能由当前 worker fence 推进，且不能超过 received。
- `MessageService.mark_applied` 只接受正水位，仓库按 `seq <= up_to_seq` 对未应用消息写 `applied_at`。
- `message.recorded` / `message.applied` 事件只含序号/水位，不含消息正文。
- 终态任务拒绝新消息；running 取消标记存在时拒绝记录，避免取消后继续扩展上下文。
- `planning_ref` 使用 `JSONB(none_as_null=True)`，空引用写 SQL NULL；否则 SQLAlchemy 默认的 JSON `'null'` 会误满足“已提供资料”的形状约束。

### 3.4 取消

- `AgentRunService.cancel` / `SqlAlchemyAgentRunRepository.cancel` 使用 `(workspace_id, request_id)` 取消请求映射保证幂等。
- `queued` / `waiting_input` / `waiting_approval`：直接置 `cancelled`、`finished_at`、清 `current_interaction_id`；活跃待办置 `expired` 并追加事件。
- `running`：只置 `cancel_requested_at`，保留 owner/lease 和 `running` 状态；活跃准备/待办项过期；追加 `run.cancellation_requested`。
- 终态任务：迟到取消只返回当前快照，不重写成功/失败/完成时间。
- `RunSnapshot` 增加 `cancel_requested_at` 和 `messages_pending`；校验取消标记只能存在于 running。
- T05 预算仓储在 `reserve` 和 `mark_sent` 前检查取消标记，取消后拒绝新的调用/发送；`settle`、`status` 仍允许，以保留已发送调用的真实/未知费用。

### 3.5 事件与数据库防护

新增安全事件类型：

- `message.recorded`、`message.applied`
- `interaction.prepared`、`interaction.pending`、`interaction.responded`、`interaction.applied`、`interaction.expired`
- `run.cancellation_requested`、`run.cancelled`

载荷按类型精确键集合校验；只含 ID、动作/决定、修订、序号、稳定原因，不含消息正文、材料正文、财务值或 Prompt。

`0026_agent_interactions`：

- `agent_runs.cancel_requested_at` 与局部索引。
- `agent_interactions`：不可变材料/差异/有效期，状态单步迁移且 `state_version` 每次恰好 +1；F1 后阶段时间逐项保护，过期保留已有发布/响应历史；单任务活跃待办部分唯一索引。
- 读取侧 `HumanInteraction` 拒绝“expired 但 responded_at 存在而无 published_at”的异常形状；这是数据库触发器之外的防御性校验。
- `agent_interaction_feedback`：追加不可变，工作台内 `request_id` 唯一；是否已应用由待办状态表达，反馈行本身不更新。
- `agent_user_messages`：正文/序号/请求键不可变，只允许 `applied_at` 从空推进一次；`(workspace_id, request_id)` 与 `(run_id, sequence)` 唯一。
- `agent_run_cancel_requests`：不可变幂等映射。
- `downgrade` 明确拒绝，避免删除审核/消息历史。

## 4. 公共接口、依赖与迁移影响

### 4.1 新增/变更接口

- `app/agent_runs/decisions.py`：`ControlAction`、`ControlProposal`、`ProposalDiff`、`GuardAction`、`GuardDecision`、`ApprovalKind`、`DecisionPolicy.classify`。
- `app/agent_runs/interactions.py`：`HumanInteraction`、`InteractionDraft`、`InteractionResponse`、`InteractionChange`、`InteractionStatus`、`InteractionDecision`、`FeedbackReceipt`、`InteractionRepository`、`InteractionService`、幂等指纹函数。
- `app/agent_runs/messages.py`：`MessageKind`、`UserMessage`、`MessageReceipt`、`MessageRepository`、`MessageService`。
- `AgentRunRepository.cancel(...)`；`AgentRunService.cancel(...)`。
- `RunSnapshot.cancel_requested_at`、`RunSnapshot.messages_pending`。
- `RunEventType` 与安全载荷白名单扩展。
- `agent_attempt_repository` 的 `_FencedRun` 增加取消字段；`reserve`/`mark_sent`/`append_authorization` 检查取消标记。

### 4.2 依赖

- 无新增生产或开发依赖。
- 未升级 LangGraph、Pydantic、SQLAlchemy、httpx 或现有模型配置。

### 4.3 迁移

- 新增 `backend/alembic/versions/0026_agent_interactions.py`，`down_revision=0025_agent_attempt_shape_fix`。
- 只新增前向表/列/索引/触发器，不修改 T04/T05 既有表结构或历史行，不改写既有已发布迁移。
- F1 修复直接补强未合并的 0026 触发器函数，不新增 0027；迁移 head 仍为 `0026_agent_interactions`。0026 未应用到业务库，旧版 0026 只可能存在于临时测试 schema，重建即可。
- 未应用到业务库；未执行部署、回退或业务数据迁移。

## 5. 测试执行与证据

执行目录除特别说明外为 `D:\t06\backend`。测试库为临时 PostgreSQL 17 容器（本机回环端口、受限角色 `crypto_research_test_runner`、固定测试库 `crypto_research_test`），`TEST_DATABASE_URL` 只在进程内注入，已通过 `check_test_database` 只读身份预检；未指向业务库。

### 5.1 F1 修复前红测（真实 PostgreSQL）

```powershell
uv run --locked --no-sync pytest tests/persistence/test_agent_interactions.py -q --tb=short --basetemp=../.tmp/pytest/t06-f1-red
```

结果：2 failed / 13 passed，退出码 1。`answered→expired` 清空阶段时间的直接 SQL 得到 `DID NOT RAISE`；`pending→answered` 缺 `responded_at` 被形状 CHECK 拒绝，未命中触发器原因。该失败复现了正式审查 F1，而不是只做静态推断。

### 5.2 最终聚焦（F1 修复后）

```powershell
pytest tests/agent_runs tests/persistence/test_agent_interactions.py -q --basetemp=../.tmp/pytest/t06-f1-final-focus
```

结果：51 passed，退出码 0。新增/覆盖：F1 阶段时间不可改写/清空、正常发布/响应/应用、取消过期保留历史、跳步与材料改写具体触发器原因、expired 读取不变量。

### 5.3 阶段回归（F1 修复后）

```powershell
pytest tests/agent_runs tests/persistence/test_agent_runs.py tests/persistence/test_agent_attempts.py tests/persistence/test_agent_interactions.py tests/persistence/test_migrations.py tests/security tests/governance tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/persistence/test_planning_inputs.py tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t06-f1-stage
```

结果：380 passed，退出码 0；含 T01–T05、迁移链、安全/治理和既有技术引擎回归。

### 5.4 后端 full（F1 修复后）

在 `D:\t06` 根目录：

```powershell
uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t06-f1-full-backend.json
```

结果：`verification=passed`，退出码 0；`backend-tests` 为 1211 collected / 1211 passed / 0 failed / 0 skipped / 0 collection errors。证据：`.tmp/quality/manual-agent-t06-f1-full-backend.json`。full 在修复代码工作树运行，随后以同一内容提交为 `dea9848`；本审查包的文档提交不包含在 full 证据中。

### 5.5 静态、架构与迁移链（F1 修复后）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Ruff | `uv run --locked --no-sync ruff check .` | 通过，退出 0 |
| 格式 | `uv run --locked --no-sync ruff format --check .` | 通过，357 files already formatted |
| 类型 | `uv run --locked --no-sync pyright` | 0 errors / 0 warnings |
| 架构门禁 | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=38`，`findings=[]` |
| 迁移链 | `uv run --locked --no-sync alembic heads` | `0026_agent_interactions (head)` |

### 5.6 环境/测试资源诊断（不计入最终通过）

- 首轮阶段命令因隔离工作区缺少 `.tmp/pytest` 父目录出现 47 个 fixture setup error；补齐测试临时目录后重跑，代码未因该环境问题修改。
- `test_migrations` 曾因手工排查迁移而创建的 `debug_t06` 临时 schema 残留导致 1 failed；删除该临时 schema 后 `tests/persistence/test_migrations.py` 为 16 passed。该 schema 不属于交付物或业务库。
- F1 修复使用新建的临时 PostgreSQL 17 容器重新执行迁移和直接 SQL，避免旧 0026 的残留 schema 影响结论；未指向业务库。
- 上述失败保留记录，未删除、未改写为通过；最终阶段 380 passed 与 full 1211 passed 是清理测试资源后的结果。

## 6. 未验证项与已知风险

### 6.1 明确未验证

- T07：`preparing→pending` 的原子发布、owner 释放、claim/heartbeat/租约回收、终态与 Harness 审计原子提交、worker 实际运行。
- T13：反馈应用、计划采纳、资金池占用、可实施状态；T06 的 `adoption_applied` 永远为 False。
- T14/T16/T17：HTTP API、SSE、前端审阅/取消/消息界面、浏览器旅程、断线重连。
- 真实模型/工具/MCP 调用、真实供应商回执、真实用户消息与知识内容；本轮未发起付费模型调用。
- 业务库迁移、部署、回滚演练；未调用真实账户、未下单、未撤单、未划转资金。
- 前端 lint/typecheck/Vitest/build、浏览器 e2e、HTTP e2e 未执行（T06 未修改前端）。
- 真实规则/资金/保证金/实盘可实施性；T06 不生成手动交易计划。

### 6.2 重点风险/审查位置

1. **锁顺序**：`respond` 先取队列单例锁，再取任务行锁；T07 claim/heartbeat/终态提交必须沿用或证明不会与该顺序死锁。T06 只验证了响应/取消竞态，未接真实 worker。
2. **prepare 与 publish 边界**：T06 只创建 `preparing`；T07 必须在同一事务内更新 `pending`、`published_at`、`state_version+1`、任务 `waiting_*`、`current_interaction_id`、释放 owner 并写事件。若 T07 直接改状态或不递增状态号，触发器会拒绝。
3. **反馈应用**：T06 不更新反馈行；T07 应通过待办 `answered→applied` 表达应用，并追加 `interaction.applied`。不要试图 UPDATE `agent_interaction_feedback`（不可变触发器会拒绝）。
4. **过期提交后抛错**：`respond` 发现过期时在事务内写 `expired` 并提交，然后抛 `review_expired`；审查时请确认调用方不会把异常当成完全回滚。
5. **唤醒容量**：响应等待任务前检查全局可运行容量 20，满时返回 `queue_full` 且不记录反馈；用户需重试。是否应改为记录+延迟排队，欢迎指出。
6. **消息等待态**：`MessageService.record` 不自动唤醒等待任务；澄清必须走类型化 `InteractionResponse`。普通消息只进入上下文水位，不会授权预算/资金/计划。请重点核对这一交互边界是否符合 FR-01/FR-11。
7. **取消标记的终态清理**：`RunSnapshot` 要求 `cancel_requested_at` 只能存在于 running；T07 终态提交必须清空该标记，否则快照加载会 fail-closed。
8. **AP-07**：监控未交付，分类明确拒绝；不要因 AP-07 枚举存在而认为监控可用。
9. **类型化修改**：`InteractionChange` 只携带不可变 `ArtifactRef`，不接收自由金额/数量 JSON；T11/T13 需要把用户表单形成的新版本映射为引用，不能把它解释为可绕过风险校验的数值。
10. **容量/过期扫描**：`expire_due` 目前是显式维护方法，没有内置调度；T07/T14 需在合适生命周期调用或另有恢复扫描。
11. **F1 迁移修补方式**：0026 未合并/未应用到业务库，本次直接编辑触发器函数；已用旧版 0026 创建的临时 schema 必须重建。若审查要求独立迁移号，可讨论改为前向迁移，但当前没有需要修补的业务历史。
12. **F1 复审边界**：正式审查端上次仅独立运行纯测试 35 passed，因缺少 `TEST_DATABASE_URL` 未在 PostgreSQL 实跑；本次开发端已在临时 PostgreSQL 17 复现并验证直接 SQL。复审仍建议由审查端独立重跑或核对 SQL 证据。

## 7. 状态声明

- 自测状态：`verified`（F1 修复、聚焦、SQL/阶段、静态、架构门禁、迁移链和后端 full 已完成）。
- 正式审查状态：`awaiting_review`（F1 复审），当前修复版本 `reviewed_tip=—`；上一次正式审查对 `1ec0a72` 判定不通过（F1）。
- 本轮未自行标记 `approved`，未进入 T07，未开始下一审查单元。
- 请原审查助手重点复核 F1 的已写入阶段时间保护、合法迁移首次写入、正常发布/响应/应用/取消过期，以及上述锁顺序、状态迁移、不可变触发器、取消/反馈竞态、消息水位与 T05 预算护栏的接缝。如需继续修复，将以当前 `dea9848` 为基线补充回归并重新提交。
