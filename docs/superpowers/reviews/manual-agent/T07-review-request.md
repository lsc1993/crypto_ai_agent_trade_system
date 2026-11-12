# T07 审查请求：带租约的执行片段、统一审计提交与 worker

- 任务/审查单元：**T07**（D2：持久任务、步骤预算、人工反馈、片段审计/恢复）。
- 执行模型：DeepSeek `deepseek-flash`；具体模型版本未知。
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1（C4 已同步 T07 界面分组）、跨模型交接 v1.1、开发模型提示词 v1.0。
- 自测状态：`verified`（R1 修复后聚焦、D2 阶段、最终后端 full、静态与迁移链均完成；详见第 5 节）。
- 正式审查状态：`changes_requested`（原审查助手 R1/P1 不通过，报告 `T07-review.md`；本轮修复后等待复审，**未预填任何通过结论**）。
- 日期：2026-11-12。

## 1. 工作区、分支与提交范围

| 项目 | 记录 |
| --- | --- |
| 隔离工作区 | `D:\t07` |
| 分支 | `t07-agent-segments`（从 `main` 创建，未推送、未合并、未部署） |
| base | `231d938454834b7f3ecd54180d433c499bcf76ce`（`main`，`ci: disable automatic remote quality checks`） |
| 首轮 implementation tip | `f5091f5805121353f67fa16eb0651ba3e05b6a80`（`feat: fence agent segments and atomic lifecycle commits`） |
| R1 修复 tip（当前） | `ec3e8e541aad7e36b0f247f5ac2c4c3c8e0c8885`（`fix: stop executor when worker is cancelled`） |
| implementation tree（当前） | `61abc0331b8f4f6bb456bac700630b9d7e07550e` |
| 首轮代码范围 | `231d938..f5091f5`，22 个文件，+4377 / -11 |
| R1 修复范围 | `f5091f5..ec3e8e5`，2 个文件，+70 / -5（`worker.py` 与 `test_worker.py`） |
| 正式审查报告 | `docs/superpowers/reviews/manual-agent/T07-review.md`（R1/P1 不通过） |
| 本轮复审文档提交 | `ad831d0b0580cb19eb64e1a21a8f31df163c1fb4`（`docs: record T07 R1 fix and rereview request`）；实现 tip 仍指向代码提交 `ec3e8e5`，避免自身循环引用 |
| 工作区未提交内容 | 仅本审查包的文档变更；没有夹带其他任务改动、`.env`、凭证或业务库修改 |

本轮没有修改 `.env`、生产配置、业务数据库、模拟盘资金/风控配置或交易执行链路；未调用真实模型，未访问私有账户，未发起真实交易。

### 1.1 代码文件清单与 SHA-256 指纹

| 文件 | SHA-256 |
| --- | --- |
| `backend/alembic/versions/0027_agent_segments.py` | `ea00198e16e5d2e228e437a8eac98af77c0b837779dc4df03d0107816484473a` |
| `backend/src/app/agent/interactive/__init__.py` | `7f5030741dc1b314b40557326dde2685eeed5ac95a067544fa248aed760a0a60` |
| `backend/src/app/agent/interactive/ports.py` | `b974bd4c17471345973489ce99b642dfac2a45cfd7706de54010c39305c70b57` |
| `backend/src/app/agent/interactive/worker.py` | `16c220aab1721c3a902760135ab7309b125f0f9738c634741bf680b3b53da599` |
| `backend/src/app/agent_runs/__init__.py` | `1da63465188b11234a67557e902cc29f09687188e06a3eefef48e5f3cc6e7f9d` |
| `backend/src/app/agent_runs/events.py` | `dc8ef0e38920e68b4b21c1532ba8c19f8b5ca458dd7993eacc076b745dc96a76` |
| `backend/src/app/agent_runs/ports.py` | `5c646049a66c7a8c0335346ff92dcb34a141742bd76d1c6f225c75486d34de33` |
| `backend/src/app/agent_runs/segments.py` | `0da7a158e7136493485ca62a82466fe455c76d399fc170a5b3e2d24346f72c56` |
| `backend/src/app/governance/contracts.py` | `745a60612b964d9ba9712394d6ac03ff72dfb7a80a23a33b10e392aaf3b32174` |
| `backend/src/app/governance/interactive_planning.py` | `19ebdedefc65d209013344ea254a1336e0e152aa5ce989c8c2cf488995b7e750` |
| `backend/src/app/governance/policy.py` | `d05989c8cae2d049d9304263695cd1532e6537181cfc6d38c646dc7403937452` |
| `backend/src/app/infrastructure/persistence/agent_commit_coordinator.py` | `bfa9d67d4195c459be08e73102866d2d347bbc683438a9a9a05f34a3b6ab25b3` |
| `backend/src/app/infrastructure/persistence/agent_segment_repository.py` | `4c0a4f5aad5c85a93d130c77908afbe1676ad6472aea2e537e079d61114c6f35` |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | `fcf89cc3eca5f3e1e4eaeaa5588d25219586b9d81cc12ab00d72c2df8a34556d` |
| `backend/src/app/infrastructure/persistence/models/agent_segments.py` | `e7bcec7de8722c1e49d49bba4ac33faf8d236d6b4bd31ac472827d364d84f83a` |
| `backend/src/app/infrastructure/persistence/models/harness.py` | `e4ccc98c046b253a2b609bd55207465dfb1ff84b92fdc17136ea06e323e667fa` |
| `backend/tests/agent_runs/test_contracts.py` | `1817cc48de409bcc92d9d9d1d693a79e3f024f433215407ebfd2d4f17ed1cab4` |
| `backend/tests/agent_runs/test_segments.py` | `7b45c9a20d29f1a9b81a288381718e1614e81ac469628f9797307d37518fe968` |
| `backend/tests/agent_runs/test_worker.py` | `4505f672b7933a23e7f712402c8a2987efd43a0e2ec5d05828b14ca2c4687ee8` |
| `backend/tests/governance/test_interactive_planning.py` | `cdbe2f824b0835cdd90b0ff080ad0f70eff1dee0a98189cb6d678c83f4d0d174` |
| `backend/tests/persistence/test_agent_segment_recovery.py` | `2706ee375ce9f91553c128d88c42867bee4f4c072b029fa55b41ead947defc90` |
| `backend/tests/persistence/test_agent_segments.py` | `0b00db8b2e3e1d06783a730c3d8d8a5327128f680993b0f718ca4d1e132fcc21` |

文档提交会同步修改 `docs/superpowers/plans/2026-11-06-manual-trading-agent-contracts.md` 的 C4 端口分组说明和 `docs/superpowers/execution/2026-11-06-manual-agent-progress.md`。

### 1.2 R1/P1 修复（原审查助手正式审查意见）

| 项目 | 记录 |
| --- | --- |
| 审查问题 | `worker.py:172–174` `_run_with_heartbeat` 的 `finally` 只清理心跳任务；外层取消 `run_once()` 时，`asyncio.wait` 不会取消 `create_task` 启动的 `runner_task`，执行器可在 worker 退出后继续运行 |
| 复现 | 原审查报告命令；修复前输出 `executor_cancelled= False pending_tasks= 1` |
| 修复 | `finally` 同时 `cancel()` 并 `await gather(runner_task, heartbeat_task, return_exceptions=True)`，在执行器/心跳退出后才让 `CancelledError` 继续上抛；清理阶段不提交业务状态 |
| 回归 | 新增 `test_cancelling_run_once_stops_executor_without_commit`、`test_cancelling_run_forever_stops_executor_without_commit`：断言执行器收到取消、无遗留 pending task、无 `commit` 调用、`CancelledError` 传播 |
| 修复后复现 | 同一脚本输出 `executor_cancelled= True pending_tasks= 0` |
| 范围 | `f5091f5..ec3e8e5`，2 个文件，+70/-5；实现 tip `ec3e8e5`，tree `61abc03` |

## 2. 任务范围与 FR/AC/HN 映射

### 2.1 本轮范围

实现 D2 的执行片段基础设施：

- PostgreSQL 片段租约：领取、30 秒租约、10 秒心跳、数据库时钟校验、过期恢复、owner/lease_epoch fencing。
- 治理类别 `interactive_planning`：策略白名单、每片段独立 Harness run、四阶段审计前缀（requested/authorized/started/terminal）。
- 协调器原子提交：业务等待/终态、pending 待办发布、片段终态、合法 Harness 序号 3、安全事件与 owner 释放在同一事务。
- `InteractiveAgentWorker`：恢复 → 领取 → 心跳并发 → 治理执行器 → 原子提交；失租/取消/审计失败时停止而不是伪造结果。
- `0027_agent_segments` 前向迁移与 ORM/触发器/约束。
- 片段的确定性测试替身和真实 PostgreSQL/真实子进程恢复测试。

本轮**不**实现：真实模型/工具/MCP/LangGraph（T08–T11）、确定性交易计划与资金池采纳（T12–T13）、HTTP/SSE/生产装配（T14）、前端（T15–T16）、浏览器/HTTP e2e、真实模型质量、业务库迁移或任何真实订单/私有账户能力。

### 2.2 映射

| 需求/不变量 | T07 证明 | 证据 |
| --- | --- | --- |
| FR-12（Harness、恢复与审计） | 片段租约、四阶段审计、统一提交、过期恢复、拦截迟到写入 | `test_worker.py`、`test_interactive_planning.py`、`test_agent_segments.py`、`test_agent_segment_recovery.py` |
| FR-11（等待审核） | preparing 待办仅在业务/审计/事件/owner 原子提交后转 pending | `test_waiting_commit_publishes_pending_only_after_atomic_commit` |
| FR-01（任务状态与连续消息） | running/queued/waiting/terminal 状态推进；未应用消息阻止完成 | `test_messages_pending_defers_completion_and_keeps_message_unapplied` |
| FR-06（预算） | 领取时建立初始授权引用；恢复不清零账本 | `test_agent_segment_recovery.py` 断言成功步骤保留 |
| AC-12（等待/重启恢复） | 过期恢复重新排队，preparing 材料保留 | 子进程终止用例 |
| AC-13（重复/迟到/旧版本） | 迟到 owner 提交 `lease_lost`；重复提交只一次成功 | `test_concurrent_commits_commit_once_and_reject_late_owner` 等 |
| AC-15（未知调用/结果复用） | 恢复不重置 step/budget；不自动重放已保存成功步骤 | 子进程用例；unknown 的付费调用重放边界仍需 T11 |
| HN-02（单一 owner/代次） | 行锁 + owner/lease_epoch/DB 时间；旧 worker 写入拒绝 | claim/heartbeat/commit 测试 |
| HN-03（原子提交） | 业务/审计/事件/owner 同事务；事件写入失败整体回滚 | `test_commit_event_failure_rolls_back_business_audit_and_owner` |
| HN-04（复用/未知不重放） | 成功步骤保留、恢复只重新准入；不删账本/重置预算 | 子进程用例 |
| HN-06（等待释放资源） | waiting 状态 owner/lease 清空，待办可响应 | waiting 用例 |
| HN-07（fence/材料时效） | 每次审计/领取/心跳/提交核对 fence；preparing 材料过期不发布 | `test_expired_preparing_material_cannot_be_published_for_review` |
| HN-11（完成不只是模型结束） | 只有协调器事务提交才进入 waiting/terminal；缺审计前缀 fail-closed | `test_completion_without_audit_prefix_fails_closed` |

T07 不生成 `TradeIntent`、不访问私有账户、不发送真实订单、不调用模拟订单服务。

## 3. 关键实现取舍

1. **片段 ID 与 Harness run ID 相同**：`agent_segments.id` 直接作为 `harness_runs.run_id`，每个片段一个治理 run；恢复/审计关联不需要额外映射，且能唯一约束 `graph_namespace`。
2. **端口分组**：C4 原稿把 claim/heartbeat/recover_expired 放在 `AgentRunRepository`；本轮保持 T04/T06 的 `AgentRunRepository`（enqueue/get/cancel/list_events）不变，新增 `SegmentRepository`（claim/heartbeat/recover_expired/commit）并让协调器成为唯一实现。worker 读取快照使用窄端口 `AgentRunReader`。这样不强迫 T04 仓储承担租约写入，也不把完整任务写权限带入 worker。契约 C4 已同步说明。
3. **领取时建立初始预算授权**：`ExecutionContext.budget_authorization_id` 必须指向真实行；claim 在 run 行锁内复用/创建 T05 的 `initial` 授权。AP-05 追加授权仍由 T05 账本按 run 聚合，不改变此处引用。
4. **空工具目录指纹**：T07 尚未登记工具，`EMPTY_TOOL_CATALOG_SHA256` 明确表示“没有已授权工具”；T09 注入真实目录后替换，不声明工具已可用。
5. **审计前缀规则**：运行时写入 requested/authorized/started（seq0–2），协调器写 seq3；成功/等待必须有 started 前缀，否则 fail-closed；失败/取消只在 started 已存在时追加 seq3；缺前缀保留中断事实。异常序号 3 经 `commit_audit_failure` 走协调器，不走旧无租约追加路径。
6. **等待发布**：preparing 待办、业务 waiting 状态、片段结束、审计 completed、`interaction.pending` 与 `run.waiting` 事件、owner 释放在同一事务；提交前 `pending` 不可响应。等待容量在队列锁内检查，锁序为队列 → 任务 → 待办。
7. **消息水位**：T07 不信任 runner 自报 `applied_message_seq` 去推进消息；使用 T06 的已提交水位阻断完成，转为 `messages_pending` 重排。消息实际应用仍由 T06/T11 的 `MessageService` 完成。
8. **取消优先**：用户 `cancel_requested_at` 在消息/等待判断前覆盖 completed/degraded/wait 结果；心跳发现取消后停止续租并触发 worker 立即提交取消终态。`CancelledError` 不写成 `workflow_failed`，避免心跳失败/停机被误记为业务失败。
9. **恢复时钟重采样**：过期扫描取得任务行锁后再次读取数据库 `clock_timestamp()`，并同时检查 run/segment 租约，避免等待锁期间被心跳推进后错误中断。
10. **preparing 材料过期**：恢复后若 preparing 待办已过期，不发布为可响应项；安全失败并记录 `review_expired`，不展示过期审核材料。
11. **计划采纳提案**：`SegmentOutcome.plan_proposal` 只随片段 `outcome` JSONB 持久化，T07 不采纳、不占用资金池；实际 AP-01/AP-06 采纳仍由 T13 coordinator 实现。
12. **恢复不重放**：恢复只重置片段/任务运行状态，不删除 `agent_steps`、attempts、预算 meter 或 preparing 待办；成功步骤保留。真实图级复用由 T11 消费这些已提交事实，T07 不冒充图已完成。

## 4. 公共接口、依赖与迁移影响

### 4.1 新增/修改公共接口

- `agent_runs/segments.py`：`LEASE_SECONDS=30`、`HEARTBEAT_SECONDS=10`、`EMPTY_TOOL_CATALOG_SHA256`、`SegmentStatus`、`AgentSegment`、`graph_namespace(fence, prefix="ir")`。
- `agent_runs/events.py`：`run.started`、`run.waiting`、`run.terminated`、`run.requeued` 及精确载荷校验（只允许状态/稳定原因，拒绝财务值）。
- `agent_runs/ports.py`：`AgentRunReader`、`SegmentRepository`；`AgentRunRepository` 保持 T04/T06 方法不变。
- `agent/interactive/ports.py`：`SegmentRunner`、`SegmentExecutor`、`SegmentExecution`。
- `agent/interactive/worker.py`：`InteractiveAgentWorker.run_once() -> bool`、`run_forever(stop: asyncio.Event) -> None`。
- `governance/contracts.py`：新增 `GovernanceRunKind.INTERACTIVE_PLANNING` 与知识/策略/规划/已登记工具能力枚举。
- `governance/policy.py`：`INTERACTIVE_PLANNING_POLICY`（`interactive_planning_v1`，BTC/ETH，公开研究 + 规划能力；不包含私有账户/订单执行）。
- `governance/interactive_planning.py`：`SegmentAuditCoordinator`、`SegmentAuditAdapter`、`InteractivePlanningWorkflow`、`GovernedSegmentExecutor`。
- 持久化：`AgentSegmentRecord`、`SqlAlchemyAgentSegmentRepository`、`SqlAlchemyAgentCommitCoordinator`。
- 文档同步：实施契约 C4 的端口分组说明、开发进度 T07 记录、本审查请求。

### 4.2 依赖

- **无新增生产依赖**；未修改 `pyproject.toml`、`uv.lock`、模型供应商配置或 `.env`。
- 未安装/启用 MCP、向量库、CCXT、付费数据源或真实交易所客户端。

### 4.3 数据库迁移

- 新增前向 `backend/alembic/versions/0027_agent_segments.py`，`down_revision="0026_agent_interactions"`，迁移 head 为 `0027_agent_segments`。
- 新表 `agent_segments`：唯一 graph namespace、运行中片段唯一、owner/epoch、心跳/租约/结束时间、结果 JSONB；触发器禁止身份改写、未释放租约的结束和删除。
- 扩展既有 `harness_runs` 的 run_kind/policy_version CHECK，允许 `interactive_planning` / `interactive_planning_v1`；旧 `market_research`/`technical_research` 序列化值和历史行保持兼容。
- **未修改旧迁移、未回写历史审计/报告/任务、未迁移业务库**。升级到 `0027` 需单独按发布流程执行；本次只在临时测试 schema 验证。

## 5. 验证记录

### 5.1 环境与证明范围

- 执行目录：`D:\t07`（仓库根）与 `D:\t07\backend`。
- 后端锁定环境：`uv sync --project backend --locked`，Python 3.12.12。
- 专用测试库：临时 PostgreSQL 17 容器 `t07-test-postgres`，固定测试库 `crypto_research_test` / 受限角色 `crypto_research_test_runner`；`TEST_DATABASE_URL` 只在验证进程注入，通过 `scripts.check_test_database` 只读身份预检；未指向业务库，未打印连接串。
- 验证进程移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`、`GIT_CONFIG_COUNT`；未修改 `.env`。
- 测试数据：合成任务输入、策略版本、产物引用、待办材料和状态；无真实财务/账户/模型内容。
- 未调用真实模型、工具、MCP、私有账户或交易执行。

### 5.2 实际命令与结果

| 检查 | 目录 | 完整命令 | 退出码 | 实际结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 改动前基线 | `D:\t07\backend` | `uv run --locked --no-sync pytest tests/agent_runs tests/governance tests/security tests/persistence/test_agent_runs.py tests/persistence/test_agent_attempts.py tests/persistence/test_agent_interactions.py tests/persistence/test_migrations.py -q --basetemp=../.tmp/pytest/t07-baseline` | 0 | 213 passed | 终端记录 |
| 首轮预期红 | `D:\t07\backend` | `uv run --locked --no-sync pytest tests/agent_runs/test_worker.py tests/agent_runs/test_segments.py tests/governance/test_interactive_planning.py tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py -q --collect-only --basetemp=../.tmp/pytest/t07-red-1` | 1 | 5 个 collection error（缺少新模块/符号），符合测试先行预期 | 终端记录 |
| 首轮聚焦最终 | `D:\t07\backend` | `uv run --locked --no-sync pytest tests/agent_runs/test_worker.py tests/agent_runs/test_segments.py tests/agent_runs/test_contracts.py tests/governance/test_interactive_planning.py tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py -q --basetemp=../.tmp/pytest/t07-focus-final` | 0 | **42 passed / 0 failed / 0 skipped**（未覆盖 worker 取消窗口） | `.tmp/quality/t07-focus.log` |
| 首轮 D2 阶段回归 | `D:\t07\backend` | `uv run --locked --no-sync pytest tests/agent_runs tests/persistence/test_agent_runs.py tests/persistence/test_agent_attempts.py tests/persistence/test_agent_interactions.py tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py tests/persistence/test_migrations.py tests/persistence/test_harness_audit_repository.py tests/security tests/governance tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/persistence/test_planning_inputs.py tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t07-stage-final2` | 0 | **417 passed / 0 failed / 0 skipped** | `.tmp/quality/t07-stage-final2.log` |
| 首轮后端 full | `D:\t07` | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t07-full-backend-final.json` | `0` | `verification=passed；1243 collected / 1243 passed / 0 failed / 0 skipped / 0 collection errors` | `.tmp/quality/manual-agent-t07-full-backend-final.json` |
| R1 预期红 | `D:\t07\backend` | `uv run --locked --no-sync pytest tests/agent_runs/test_worker.py -q --basetemp=../.tmp/pytest/t07-r1-red` | 1 | **2 failed / 8 passed**：run_once/run_forever 取消后执行器未收到取消、存在 pending task | 终端记录 |
| R1 聚焦最终 | `D:\t07\backend` + 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/agent_runs/test_worker.py tests/agent_runs/test_segments.py tests/agent_runs/test_contracts.py tests/governance/test_interactive_planning.py tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py -q --basetemp=../.tmp/pytest/t07-r1-focus-final2` | 0 | **44 passed / 0 failed / 0 skipped** | `.tmp/quality/t07-r1-focus.log` |
| R1 D2 阶段回归 | `D:\t07\backend` + 临时 PostgreSQL 17 | 同首轮阶段命令，`--basetemp=../.tmp/pytest/t07-r1-stage` | 0 | **419 passed / 0 failed / 0 skipped** | `.tmp/quality/t07-r1-stage.log` |
| R1 后端 full | `D:\t07` + 临时 PostgreSQL 17 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t07-r1-full-backend-final.json` | `0` | `verification=passed；1245 collected / 1245 passed / 0 failed / 0 skipped / 0 collection errors` | `.tmp/quality/manual-agent-t07-r1-full-backend-final.json` |
| Ruff | `D:\t07\backend` | `uv run --locked --no-sync ruff check .` | 0 | All checks passed | 终端记录 |
| 格式 | `D:\t07\backend` | `uv run --locked --no-sync ruff format --check .` | 0 | 368 files already formatted | 终端记录 |
| Pyright | `D:\t07\backend` | `uv run --locked --no-sync pyright` | 0 | 0 errors / 0 warnings | 终端记录 |
| 架构门禁 | `D:\t07\backend` | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `status=passed`，`files_scanned=41`，`findings=[]` | 终端记录 |
| 迁移链 | `D:\t07\backend` | `uv run --locked --no-sync alembic heads` | 0 | `0027_agent_segments (head)` | 终端记录 |

> 说明：R1 修复后的最终 full 结果见上表；R1 预期红直接复现了原审查报告的取消泄漏。此前一次首轮阶段运行因测试库残留 `harness_test_*` schema 导致 1 个迁移隔离用例失败；清理本次临时 schema 后同命令 417 passed，失败原因属于测试环境残留，不是代码缺陷，也未放宽该测试。

## 6. 未验证项、已知风险与重点审查位置

### 6.1 未验证/未执行

- 真实模型、原生 Tool Calling、LangGraph 图、真实 MCP、上下文/证据（T08–T11）。
- 真实交易计划计算、可实施状态、AP-01/AP-06 采纳与资金池占用（T12–T13）。
- 受限 HTTP/SSE、生产 lifespan 装配、前端、浏览器 e2e、http-e2e（T14–T17）。
- 真实模型质量、真实产品规则复验、策略收益、用户实际手动执行反馈（T18–T19 及产品流程）。
- 业务库迁移、部署、回退演练；本轮只验证临时测试 schema。
- 真实 30 秒租约/10 秒心跳墙钟等待；测试通过 SQL 推进租约到期和使用可注入心跳间隔证明逻辑。
- 同池 100 个等待任务的容量边界；当前有容量检查代码，但未构造 100 个 waiting 任务。
- 真实图 checkpoint 丢失后的结果复用；T07 证明成功步骤/预算未被恢复重置，T11 才负责图级复用。
- 多进程生产 worker 部署/竞争；T07 有并发 claim/commit SQL 测试和真实子进程终止测试，但未装配生产长循环。

### 6.2 重点审查位置

1. **R1 复审重点**：`worker.py` `_run_with_heartbeat` 的 `finally` 是否无条件取消并等待 `runner_task` 与 `heartbeat_task`，外层 `CancelledError` 是否在清理后继续传播，且 cleanup 不调用 commit。
2. `agent_commit_coordinator.py` 的 `recover_expired`：行锁后重采样数据库时间、started 前缀规则、cancel 标记优先级。
3. `_commit` 的锁序：等待分支必须先取队列锁再锁任务/待办；completed/failed 分支不得引入 run→queue 反向锁序。
4. `_defer_run` / `_fail_terminal`：重排或失败时审计 seq3、业务状态、事件、owner 释放是否同一事务，是否可能丢失 `messages_pending` 或取消标记。
5. `SegmentAuditAdapter.append_event`：取消/心跳失败不得被写成 `workflow_failed`；异常序号 3 是否只经协调器。
6. `agent_segment_repository.py` 的 claim/heartbeat：初始预算授权、revision 指纹校验、取消续租边界。
7. `0027_agent_segments.py` 的触发器与 ORM 约束是否一致；旧 `harness_runs` 检查约束扩展是否只前向兼容。
8. 测试替身的证明范围：worker 纯替身只证明编排；SQL 用例证明真实事务；子进程用例证明进程终止后的恢复，不等同断电/PITR。R1 回归断言执行器取消、无 pending task、无 commit，不证明真实模型/工具客户端自行遵守取消。

### 6.3 已知限制/临时选择

- `EMPTY_TOOL_CATALOG_SHA256` 是 T07 的空目录指纹；T09 必须替换为真实注册目录指纹。
- `ExecutionContext.budget_authorization_id` 指向初始授权；AP-05 的有效上限由 T05 run 级账本派生。
- `plan_proposal` 仅持久化在片段结果 JSON 中，T07 不执行采纳/资金池检查。
- 消息 `applied_message_seq` 不由此提交推进；T06 的 `MessageService.mark_applied` / T11 负责。
- prepared 审核材料过期时以失败终态收尾（`review_expired`），而不是长期保留为不可响应 preparing；正式等待过期仍由 T06 处理。
- 没有真实模型/工具调用，因此“未知付费调用不自动重放”只在账本/步骤保留层证明，完整发送路径由 T11 验证。

## 7. 审查请求

请原审查助手重点复核 R1/P1 的修复与第 6.2 节；若发现新的阻断问题，请给出复现命令/文件行号与期望行为。开发端会在收到意见后先复现，再逐条修复并补回归，更新新的 implementation tip 与验证证据后再次提交审查。本审查请求不代表正式审查通过，也不授权进入 T08 或任何后续审查单元。
