# T06 审查请求：人工审核、连续消息与取消一致性

- 审查单元：T06
- 请求日期：2026-11-12
- 开发执行模型：`deepseek-flash`（provider `deepseek`，reasoning `max`）；具体模型权重版本未知，以上为本地会话环境可确认信息。
- 文档基线：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0。
- 本轮只交开发自测，不代表正式审查通过；正式结论由用户转交原审查助手。

## 1. 工作区、提交与范围

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main`，T05 合并文档 tip `bbb4e0b`，工作区干净） |
| 隔离工作区 | `D:\t06` |
| 分支 | `t06-agent-interactions` |
| base | `bbb4e0bc010b46e0188923c176d7334e2764b241` |
| implementation tip | `1ec0a72e74682ef17995cfca165967b475f764d8`（`feat: persist human review and task feedback`） |
| implementation tree | `2fc90f8006eb63947603f27532d8bb4394bcc8d4` |
| diff 范围 | `bbb4e0b..1ec0a72`，19 个文件，+3831 / -7 |
| 工作区状态 | 提交后 `git status --short` 为空 |
| review_status | `awaiting_review` |
| reviewed_tip | `—`（不得预填通过） |

说明：本审查请求和开发进度文档在代码提交之后另行形成文档提交；实现 tip 固定指向代码提交 `1ec0a72`，不复用审查包自身提交号。`main` 未被修改，未推送、未合并、未部署。

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

### 1.2 关键文件指纹（SHA-256）

```text
74a67329f0d06860b0555c8c352a3c6eb1ffb8d82dfa377b4e93355a207b45cf  backend/src/app/agent_runs/decisions.py
9a5848ce051691fb11c6f05672d249b81b905d4dec2057da0da8983615d2b1fb  backend/src/app/agent_runs/interactions.py
0fc867768481b7dc9b4dfea71bad33a219c7d36e4ec91f069d04e12d87013683  backend/src/app/agent_runs/messages.py
9523bf0abe5bd9465482941ba72a59bd3ee1d97cbe52bc72cceb639fab5bd869  backend/src/app/infrastructure/persistence/agent_interaction_repository.py
e25d04944fce3db26af48f265767f3eba298e3d63ead44afd5d37031d00c30b1  backend/src/app/infrastructure/persistence/models/agent_interactions.py
e3f419a3f00874b7a9465c40ca623279282fc4093f1d26bf238d8c9edb108363  backend/alembic/versions/0026_agent_interactions.py
f4dec979c749dfae4587a995b7b69abcade0b56e07606f234713e95321202194  backend/tests/agent_runs/test_interactions.py
ae7d90da483c45d897fcc032a6df962ba8c39e5e1f35e3df8e0fc4c82182f3b2  backend/tests/agent_runs/test_messages.py
0c46b170149402fff7c72e1d5bb6d3e083022227c91db4aa4e9571fb65f88bd4  backend/tests/persistence/test_agent_interactions.py
```

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
- `agent_interactions`：不可变材料/差异/有效期，状态单步迁移且 `state_version` 每次恰好 +1；单任务活跃待办部分唯一索引。
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
- 只新增前向表/列/索引/触发器，不修改 T04/T05 既有表结构或历史行，不改写旧迁移。
- 迁移 head：`0026_agent_interactions`。
- 未应用到业务库；未执行部署、回退或业务数据迁移。

## 5. 测试执行与证据

执行目录除特别说明外为 `D:\t06\backend`。测试库为临时 PostgreSQL 17 容器（本机回环端口、受限角色 `crypto_research_test_runner`、固定测试库 `crypto_research_test`），`TEST_DATABASE_URL` 只在进程内注入，已通过 `check_test_database` 只读身份预检；未指向业务库。

### 5.1 测试先行红测

```powershell
uv run --locked --no-sync pytest tests/agent_runs/test_interactions.py tests/agent_runs/test_messages.py tests/persistence/test_agent_interactions.py -q --basetemp=../.tmp/pytest/t06-red
```

结果：3 个 collection error（缺少 `app.agent_runs.decisions/interactions/messages`），退出码 2；符合测试先行预期。

### 5.2 最终聚焦

```powershell
pytest tests/agent_runs tests/persistence/test_agent_interactions.py -q --basetemp=../.tmp/pytest/t06-final-focus
```

结果：48 passed，退出码 0。覆盖 AP 分类、状态形状、回执不宣称采纳、prepare 幂等/单活跃、响应 CAS/材料/过期、并发同键/异键、取消与反馈顺序、消息水位、JSONB 空引用、数据库触发器和安全事件。

### 5.3 阶段回归

```powershell
pytest tests/agent_runs tests/persistence/test_agent_runs.py tests/persistence/test_agent_attempts.py tests/persistence/test_agent_interactions.py tests/persistence/test_migrations.py tests/security tests/governance tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/persistence/test_planning_inputs.py tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t06-stage4
```

结果：377 passed，退出码 0；含 T01–T05、迁移链、安全/治理和既有技术引擎回归。

### 5.4 后端 full

在 `D:\t06` 根目录：

```powershell
uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t06-full-backend.json
```

结果：`verification=passed`，退出码 0；`backend-tests` 为 1208 collected / 1208 passed / 0 failed / 0 skipped / 0 collection errors。证据：`.tmp/quality/manual-agent-t06-full-backend.json`。full 在最终代码工作树运行，随后以同一内容提交为 `1ec0a72`；本审查包的文档提交不包含在 full 证据中。

### 5.5 静态、架构与迁移链

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
- 上述两次失败保留记录，未删除、未改写为通过；最终阶段 377 passed 与 full 1208 passed 是清理测试资源后的结果。

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

## 7. 状态声明

- 自测状态：`verified`（实现、聚焦、SQL/阶段、静态、架构门禁、迁移链和后端 full 已完成）。
- 正式审查状态：`awaiting_review`，`reviewed_tip=—`。
- 本轮未自行标记 `approved`，未进入 T07，未开始下一审查单元。
- 请原审查助手重点核对上述锁顺序、状态迁移、不可变触发器、取消/反馈竞态、消息水位与 T05 预算护栏的接缝；如需修复，将以当前 `1ec0a72` 为基线补充回归并重新提交。
