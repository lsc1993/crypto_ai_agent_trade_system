# T04 审查请求：持久任务、修订与安全事件

- 任务/审查单元：T04（D2）
- 执行模型：`deepseek-flash`（运行环境标识）；具体供应商构建、参数版本与上下文版本未在仓库内可确认，记为**未知**。执行载体为 DeepSeek Harness。
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0（日期均为 2026-11-06）。
- 自测状态：`verified`（首轮实现 + P2 修复、聚焦、SQL、静态、迁移链与最终后端 full 已完成）。
- 正式审查状态：`awaiting_review`。本文件不是审查通过结论；开发模型自测或子 Agent 检查不能替代原审查助手结论。首轮正式审查已判定 P2 不通过（JSONB 数值规范化导致请求指纹漂移），本文件记录修复后版本，等待复审。
- 审查请求生成/更新：2026-11-10（Asia/Shanghai）；P2 修复记录见第 8 节。

## 1. 工作区、分支与审查范围

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main`，T04 开始时干净） |
| 隔离工作区 | `D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t04` |
| 分支 | `task/manual-agent-t04` |
| base | `9e45d77b1771efbc1e45eca9a1a414c623991c81`（`main`，T03 复审/合并文档之后） |
| implementation tip | `0df86fe7bbe4dc96062822404dfe45f5f675c06f`（`fix: stabilize agent request fingerprints across jsonb`，P2 修复 tip） |
| 首轮实现 tip | `2e173680a86184c4ea4e6d528e275f1fec3c34a7`（`feat: persist versioned agent tasks and events`） |
| implementation tree | `7ee06515bed978b9a419e9fefc096a0426fc8cba`（首轮实现）；P2 修复 tree 见第 8 节 |
| 复审范围（本轮重点） | `2e17368..0df86fe`，5 个文件，+279 / -28：请求指纹契约、仓储写入/读取、对应测试 |
| 累计代码范围 | `9e45d77..0df86fe`（排除 docs 提交），13 个文件，+2433 / -0 |
| 文档提交 | 本审查请求、进度/状态/契约注记位于实现 tip 之后的独立 docs 提交；该 docs 提交不属于代码审查范围，避免用自身提交号循环引用 |

工作区在实现提交后只包含本任务文件；`main` 未合并 T04，未推送、未部署、未迁移业务库。本轮未使用或修改其他任务未提交改动，未阅读或写入 `.env`、凭证或真实账户资料。

## 2. 任务范围、依赖与 FR/AC/HN

### 2.1 本轮范围

按实施计划 T04 与契约 C4，本轮交付：

- `RunInput`、`RunSnapshot`、`RunStatus`、稳定错误码与请求内容指纹。
- `AgentRunRepository.enqueue/get/list_events` 协议与 PostgreSQL 实现。
- 薄 `AgentRunService.start(workspace_id, data)`；不启动消费者。
- 工作台/线程/任务/不可变修订/请求幂等映射/任务内安全事件/证据与产物前向表/队列单例。
- `0022_agent_tasks` 前向迁移、模型注册和 T04 测试。

明确不在本轮：

- 领取、心跳、恢复、片段提交（T07）；人工审核/消息/取消（T06）；证据冻结与上下文（T08）；工具/MCP（T09/T10）；模型图（T11）；规划计算/可实施状态（T12/T13）；HTTP/API/前端（T14–T16）。
- 任何真实模型调用、私有账户访问、TradeIntent、风控放行、模拟订单或真实交易。

### 2.2 依赖核对

| 依赖 | 核对结果 |
| --- | --- |
| T00 治理迁移 | 已正式通过并合并在 `main`；T04 未导入 `app.harness`，未修改治理/交易边界 |
| T01 C1/C2 | 已正式通过；复用 `VersionRef`、`ArtifactRef`、`ProductKey`、`AgentModel`、`UtcDateTime` |
| T02 知识 | 已正式通过；T04 未触碰知识表/检索 |
| T03 C3 | 已正式通过；`PlanningRefs` 按 C1 作为不内嵌财务值的引用进入 `RunInput` |
| 迁移链 | 从 `0021_planning_inputs` 串行新增 `0022_agent_tasks`；未改写旧迁移 |

### 2.3 FR/AC/HN 映射

| 标识 | 本轮实现/证明 | 不宣称 |
| --- | --- | --- |
| FR-01 | 稳定 `run_id`/`thread_id`/`revision`；`(workspace_id, request_id)` 幂等；同键异内容冲突；不同请求键不按币种合并；持久重读 | 任务页面、消息、取消、交互记录（后续任务） |
| FR-12 | 业务任务行权威状态、不可变修订/请求/事件、owner/lease 字段、事件顺序与分页、终态禁止重开 | 实际租约领取/心跳/恢复/审计原子提交（T07） |
| AC-07 | 同键同参重放、异参冲突、不同策略/参数/请求键分开建立任务；并发同键只产生一个任务 | 前端或 HTTP 幂等映射（T14/T16） |
| AC-18 | 迁移只新增表/触发器，旧报告/审计/迁移链回归通过；未回写历史 | 业务库升级或部署验收 |
| HN-02 | 任务行是业务权威；owner/lease/lease_epoch 字段与状态约束已落库；终态不可重开 | worker 实际 fencing 与旧 owner 拒绝（T07） |
| HN-08 | `received_message_seq`/`applied_message_seq` 字段与 `applied <= received` 约束已建立 | 消息服务与完成阻断（T06/T08） |
| HN-11 | T04 创建后任务保持 `queued`；不把建任务、事件或空产物表当作完成；不写证据/产物占位成功行 | 模型产物、计划、完成判定（T11/T14） |
| HN-12 | 事件按类型精确白名单投影，不含目标原文、策略参数、财务值或完整计划；测试断言财务标记不出现 | 完整 API 投影与前端（T14/T16） |

## 3. 改动清单与文件指纹

### 3.1 改动文件

| 文件 | 说明 |
| --- | --- |
| `backend/src/app/agent_runs/__init__.py` | 领域包入口与导出，不装配数据库/worker |
| `backend/src/app/agent_runs/contracts.py` | `RunInput`、`RunSnapshot`、`RunStatus`、容量常量、错误码、请求指纹 |
| `backend/src/app/agent_runs/events.py` | 事件类型、白名单载荷、事件分页与入队事件构造 |
| `backend/src/app/agent_runs/ports.py` | `AgentRunRepository` 协议（T04 方法） |
| `backend/src/app/agent_runs/service.py` | `AgentRunService.start` 薄封装 |
| `backend/src/app/infrastructure/persistence/agent_run_repository.py` | PostgreSQL 事务实现：请求锁、重放、线程/父任务、队列容量、事件 |
| `backend/src/app/infrastructure/persistence/models/agent_runs.py` | 8 个 ORM 模型与约束/索引 |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | 注册新模型（+18 行） |
| `backend/alembic/versions/0022_agent_tasks.py` | 前向迁移：表、约束、索引、触发器、队列种子 |
| `backend/tests/agent_runs/__init__.py` | 测试包标记 |
| `backend/tests/agent_runs/test_contracts.py` | 输入/指纹/快照/事件契约测试 |
| `backend/tests/agent_runs/test_service.py` | 服务委托与错误透传测试 |
| `backend/tests/persistence/test_agent_runs.py` | 请求幂等、并发容量、线程/父任务、事件、回滚与数据库约束测试 |

### 3.2 SHA-256 文件指纹（实现 tip）

| 文件 | SHA-256 |
| --- | --- |
| `backend/alembic/versions/0022_agent_tasks.py` | `a178b965ec38a0f6ac9b21f730037958c3016cb603c92ce9697b3caa33e009eb` |
| `backend/src/app/agent_runs/__init__.py` | `9a0d4bd94079a95ea57f71d779096d1e7d0049f4b624c6304eb254ff2f2f47b6` |
| `backend/src/app/agent_runs/contracts.py` | `aaefe2d1ee60d10f3d281e947f37e1a284e42b5363447478d9d763fe8f3cca90` |
| `backend/src/app/agent_runs/events.py` | `2f1d40ba0d6ade350fe9184bfa69c6f43130c7bbdecb6109d7d77798b8c52470` |
| `backend/src/app/agent_runs/ports.py` | `c52c6f6895e1f67b91f775b291280a9c73b030c2793398cf494bed03c19fb056` |
| `backend/src/app/agent_runs/service.py` | `8e524a77ecacf0eb3d0ecc2394945066f410caa725c03fafb19b8d6c9207e29f` |
| `backend/src/app/infrastructure/persistence/agent_run_repository.py` | `b955d20a2b2845b3a1e524b8193be2751b7f4d21f9fdc0425fcf3ce866895fb5` |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | `98211b9c345fa9cd2ce7432a8f11ea31ac38dc0510b1a8b0cc394235c120b614` |
| `backend/src/app/infrastructure/persistence/models/agent_runs.py` | `0a374e34bf106eb3a6d6ccb86e2098e84f1c8794787302b2417d299491f98fb2` |
| `backend/tests/agent_runs/__init__.py` | `1321570a7de381eaacb3fe9140cdcfc54a2342f8eb5024a04d54b2cf7627ce0a` |
| `backend/tests/agent_runs/test_contracts.py` | `182b909ef422a4354e8318092b5eb1dbd4f88e0f047a8b59ceaf2617620cdb71` |
| `backend/tests/agent_runs/test_service.py` | `653b263b1863bb38bac4e546713126f26c6109bb5757d6f689ceed18b199d522` |
| `backend/tests/persistence/test_agent_runs.py` | `a790e157aeacecfc6f9d76eb9c219f7989cfc087f0d2b6838c8a47690b73c063` |

## 4. 关键实现取舍

1. **重放先于容量检查。** 同一 `(workspace_id, request_id)` 先取事务级 advisory lock 并读取已提交映射；命中且内容指纹一致时直接返回原任务。这样队列已满时仍能安全重试原请求，不会被误报 `queue_full`。内容不同返回 `request_conflict`。
2. **请求键按工作台隔离。** `agent_run_requests` 使用 `(workspace_id, request_id)` 复合主键；同一 UUID 在不同工作台可对应不同任务，避免跨工作台猜测/泄露。
3. **不同请求键不合并。** 没有按币种/策略的活跃任务唯一索引；即使输入完全相同，不同 `request_id` 也建立独立任务，遵循“用户明确再次研究”的语义。
4. **指纹覆盖规范化输入。** 首轮用 Python JSON 序列化哈希，未覆盖 JSONB 对 `1e20`、`-0.0` 等合法数值的规范化；P2 修复后，仓储先让 PostgreSQL 生成 JSONB 规范文本，再移除 `request_id`、稳定键序并哈希。指纹仍覆盖工作台、产品、周期、目标、策略引用、参数、规划引用、分析模式、`as_of`、预算档和父/线程字段；默认值在解析后进入指纹，因此省略默认字段与显式写默认值可重放同一任务。策略参数拒绝 NaN/Infinity，避免指纹不可复现。
5. **修订保存提交输入，线程/父任务落在任务行。** 首次解析的默认字段随修订保存；服务端生成/继承的 `thread_id` 和父任务关系保存在 `agent_runs`。因此 `RunSnapshot.thread_id` 是有效会话，`RunSnapshot.input.thread_id` 仍是客户端提交值。若客户端在一次重试中把服务端生成的线程 ID 显式写回请求体，会形成不同内容并返回冲突，这是有意的“原请求重试”语义。
6. **全局可运行容量 20。** 在 `agent_run_queue` 单例行锁内统计 `queued/running`；等待态不计入该容量。单工作台等待上限 100 的原子检查属于 T06/T07 的状态迁移，本轮只验证“100 个等待不占运行并发”。
7. **父任务必须终态且同会话。** 终态后的新工作必须显式携带 `parent_run_id`；未终态父任务不能被并行子任务借用。父任务/线程跨工作台一律按不存在处理。
8. **终态与历史不可变。** 任务终态触发器禁止任何后续 UPDATE；修订/请求/事件/证据/产物禁止 UPDATE/DELETE；任务/线程禁止 DELETE。T06/T07/T13 需在进入终态的同一条 UPDATE 中写齐完成时间、结果引用等字段，不能先置终态再补写。
9. **owner/lease 成对约束。** `running` 必须同时有 owner 和未过期租约时间；非 `running` 必须两者均为空，防止等待态残留执行所有权。实际 30/10 秒租约与 fencing 由 T07 实现。
10. **事件白名单。** T04 只发 `run.queued` 与 `revision.created`；载荷顶层键精确匹配，产品嵌套再校验。事件不含 `goal`、`parameters`、`planning` 或任何财务值。后续事件类型必须显式登记白名单，不能复用通用 JSON 载荷。
11. **证据/产物表按 C9 预留。** `agent_evidence_epochs` 与 `agent_artifacts` 在 0022 建表并受不可变触发器保护，但 T04 不写任何占位行。T08/T14 才实现实际保存、质量与投影；本轮不把“表存在”视为证据/产物能力已交付。
12. **无策略 Schema 校验。** T04 只校验输入结构和 JSON 安全性；参数与所选已发布策略 Schema 的匹配、策略精确加载属于 T08/T11/T14。T04 不读取策略目录，避免在尚未接入的消费路径中制造第二套校验真值。
13. **事件分页用序号游标。** `list_events(after_seq, limit=1..100)` 返回 `items` 与 `next_after`；`next_after` 仅在还有更晚事件时给出，避免前端按页码重放。

## 5. 接口、依赖与迁移影响

### 5.1 新增公共接口

- `RunInput`：`request_id`、可选 `thread_id/parent_run_id`、`ProductKey`、周期、目标、`VersionRef` 策略、参数、`PlanningRefs | None`、分析模式/`as_of`、预算档；`extra="forbid"`、冻结。
- `RunSnapshot`：任务/工作台/线程/父任务、修订、状态、`state_version`、不可变输入、消息水位、当前待办、结果引用、质量与 UTC 时间；不内嵌完整财务值。
- `RunStatus`：9 个状态；`TERMINAL_RUN_STATUSES` 等集合。
- `AgentRunError`：稳定原因码（请求冲突、队列满、线程/父任务错误、事件分页、完整性问题、存储不可用）。
- `AgentRunRepository`：`enqueue/get/list_events`；`AgentRunService.start`。
- `canonical_run_input_json`：生成提交输入的稳定 JSON 文本；`run_input_sha256` 改为接收 PostgreSQL JSONB 规范文本；`legacy_run_input_sha256` 仅供首轮已提交稳定数值行的兼容读取。
- `RunEvent`、`RunEventPage`、`RunEventType`、`build_enqueue_events`、`SqlAlchemyAgentRunRepository`。

### 5.2 依赖与边界

- 无新增生产/开发依赖，`uv.lock` 未改。
- `agent_runs` 不导入 `risk`、`execution`、`strategy`、`paper_trading`、模型、HTTP 或 MCP；只依赖 `shared/agent_types`、`market/contracts` 与 `trade_planning/inputs.PlanningRefs`（C1 明确引用）。
- 未修改 `main.py` 装配、API 路由、前端、Compose、配置或 `.env`；没有启动消费者或新长循环。

### 5.3 数据库迁移

新增 `backend/alembic/versions/0022_agent_tasks.py`，`down_revision=0021_planning_inputs`：

- `agent_threads`、`agent_runs`、`agent_run_revisions`、`agent_run_requests`、`agent_run_events`。
- `agent_evidence_epochs`、`agent_artifacts`（前向预留）。
- `agent_run_queue` 单例行并种入 `id=1`。
- 任务状态/修订/消息水位/owner-lease/终态/父任务/结果引用检查约束；请求/事件/证据/产物不可变触发器；终态不可重开触发器；任务/线程禁删触发器。
- 迁移头为 `0022_agent_tasks`；仅应用于专用临时测试库，未迁移业务库。`downgrade()` 明确拒绝，避免删除任务历史。
- P2 修复不新增迁移、不修改 `0022_agent_tasks`、不重写修订/请求行：仍保存 JSONB，只把指纹来源改为 PostgreSQL JSONB 规范文本。旧行兼容与限制见第 8 节。

## 6. 测试执行与证据

执行环境：`backend/`（隔离工作区）与仓库根目录（full）；专用临时 PostgreSQL 17 容器，本机回环临时端口、受限角色 `crypto_research_test_runner`；进程内仅以 `TEST_DATABASE_URL` 注入测试库，未指向业务库，未打印连接串。验证进程移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`，未修改 `.env`。

| 检查 | 目录 | 完整命令 | 退出码 | 实际结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 预期红（测试先行） | `backend/` | `uv run --locked --no-sync pytest tests/agent_runs/test_contracts.py tests/agent_runs/test_service.py tests/persistence/test_agent_runs.py -q --basetemp=../.tmp/pytest/t04-red-20261110` | 2 | 3 个 collection error：`ModuleNotFoundError: app.agent_runs`；符合测试先行预期 | 终端记录（代码已实现后不可原地复现）；提交历史与进度文档 |
| P2 预期红（真实 PostgreSQL） | `backend/` | `uv run --locked --no-sync pytest tests/persistence/test_agent_runs.py::test_jsonb_numeric_normalization_keeps_fingerprint_stable_for_reload_and_replay -q --tb=short --basetemp=../.tmp/pytest/t04-p2-red-20261111` | 1 | 1 failed：首次 `enqueue` 在 `_load_snapshot` 抛 `integrity_violation`；复现 `1e20`/`-0.0` JSONB 规范化后指纹漂移 | 终端记录 |
| 最终聚焦（契约+服务+SQL） | `backend/` | `uv run --locked --no-sync pytest tests/agent_runs tests/persistence/test_agent_runs.py -q --basetemp=../.tmp/pytest/t04-p2-focus-3` | 0 | 21 passed / 0 failed / 0 skipped；含 JSONB 数值往返、旧稳定数值兼容、旧规范化数值 fail-closed、并发同键单任务、21 并发第 21 个拒绝、等待 100 不占运行容量、事件 1..2、失败回滚无残留、终态/不可变约束 | `.tmp/quality/t04-p2-focus-3.log`（待归档；主工作区 `.tmp/quality/`） |
| 首轮阶段回归 | `backend/` | `uv run --locked --no-sync pytest tests/agent_runs tests/persistence/test_agent_runs.py tests/persistence/test_migrations.py tests/security tests/governance tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/persistence/test_planning_inputs.py tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t04-stage-2` | 0 | 315 passed / 0 failed / 0 skipped（首轮实现）；P2 修复后的完整覆盖由最终后端 full 提供 | `.tmp/quality/t04-stage-2.log` |
| 最终后端 full | 仓库根目录 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t04-p2-full-backend-final.json` | 0 | `verification=passed`；backend-tests collected 1149 / passed 1149 / failed 0 / skipped 0 / collection_errors 0；含格式/lint/类型/架构/迁移头/离线评估/研究流程 | `.tmp/quality/manual-agent-t04-p2-full-backend-final.json` |
| Ruff | `backend/` | `uv run --locked --no-sync ruff check .` | 0 | All checks passed | 同上 full 检查项 |
| 格式 | `backend/` | `uv run --locked --no-sync ruff format --check .` | 0 | 336 files already formatted | `.tmp/quality/t04-pyright.log` 同批终端记录；full 复核 |
| Pyright | `backend/` | `uv run --locked --no-sync pyright` | 0 | 0 errors / 0 warnings / 0 informations | `.tmp/quality/t04-pyright.log` |
| 架构门禁 | `backend/` | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `status=passed`，`files_scanned=38`，`findings=[]` | `.tmp/quality/t04-architecture.log` |
| 迁移链 | `backend/` | `uv run --locked --no-sync alembic heads` | 0 | `0022_agent_tasks (head)` | full 的 migration-heads 检查 |

补充说明：

- 首次阶段命令因隔离工作区尚无 `.tmp/pytest/` 父目录，在 fixture 创建临时目录时失败（47 个 setup error，非业务断言失败）；创建专属目录后以同一命令重跑，结果 315 passed。该环境问题未计入通过证据，已去除。
- 首轮 full 在补加“策略参数 NaN/Infinity”校验之前运行，同样为 1146 passed；随后 amended 实现 tip 并重跑最终 full，以上报告只引用最终 tip 的结果。
- SQL 用例均通过 `migrated_database` 夹具运行真实 Alembic 迁移并创建随机 schema；结束后清理该 schema。未用内存替身替代 SQL 行为。
- 事件安全断言使用合成财务标记 `10000.00`，验证其不出现在事件序列化中；不是真实账户数据。

## 7. 未验证项、已知风险与重点审查位置

### 7.1 未验证/未交付

- HTTP API、前端、浏览器 e2e、HTTP/数据库联合旅程（T14–T17）。
- 实际 worker 领取/续租/心跳/恢复、片段审计原子提交、旧 owner fencing（T07）。
- 人工审核、消息水位应用、取消一致性（T06）。
- 证据冻结、上下文 manifest、策略精确加载（T08/T11）；工具/MCP（T09/T10）。
- 数量/风险/保证金计算、可实施状态、单池占用与手动反馈（T12/T13）。
- 真实模型质量、真实公开规则发布、业务库迁移、部署与回滚演练。
- 真实账户、真实资金、真实订单：本轮完全未触碰。

### 7.2 已知风险/限制

1. **终态触发器较严格。** 任务一旦进入终态，任何 UPDATE 都被拒绝。T07/T13 必须把终态、完成时间、结果引用/质量等在一次 UPDATE 中提交；若后续需要“终态后补写”必须另行说明，而不是放宽触发器。
2. **请求指纹与有效输入的双层语义。** 修订保存客户端提交的规范化输入；服务端生成/继承的线程与父任务只落在任务行。重试必须复用原请求体，不能把服务端返回的线程 ID 写回同一 `request_id`。请审查这是否符合 C1“首次解析后的有效输入快照”的期望。
3. **旧行已规范化数值不可恢复。** 首轮已提交且含 `1e20`/`-0.0` 等 JSONB 规范化数值的修订，原始 Python 表示从未单独保存，兼容逻辑无法重算旧哈希；此类行仍按 `integrity_violation` fail-closed，不重写历史、不放宽校验。稳定数值（如 `0.5`）的旧行可通过精确旧哈希继续读取/重放。T04 的 0022 未应用到业务库，测试 schema 每次重建；若存在本地旧测试行，应重建或按不可恢复处理。
4. **容量口径。** 20 是全局可运行上限；等待 100 是单工作台上限但不占运行并发。T04 未在入队时拒绝“该工作台已有 100 个等待”的新任务；等待上限的原子检查留待 T06/T07 状态迁移。若产品要求入队即限制，需要另定语义。
5. **证据/产物表预留。** 0022 建表但没有服务/投影/写入；审查时请确认这不被误读为 T08/T14 能力已交付。C9 将这两个表列在 T04 迁移中，本轮按契约保留。
6. **事件载荷只做应用层白名单。** 数据库只约束 JSONB 与基本序号；绕过仓储直接 INSERT 仍可写入任意 JSON。后续所有事件写入必须经 `events.py`，SQL 权限/代码审查需继续约束。
7. **无策略 Schema 校验。** T04 不读取 `StrategyCatalog`；参数是否匹配所选已发布版本要到 T08/T11/T14 才验证。T04 的“同键异参冲突”只比较规范化 JSON 指纹，不证明策略参数合法。
8. **`result_refs` 已定型但无写入方。** 当前恒为空；T14 接入产物后需核对 `ArtifactRef` 与 `agent_artifacts` 的一致性，防止只存引用而无可读产物。
9. **无真实迁移演练。** 只验证测试库随机 schema；业务库迁移、备份/恢复、旧应用回退未执行。
10. **无前端/浏览器证据。** 本轮没有任何用户可见入口或开关；不能据此声称任务页面可用。
11. **JSONB 规范文本查询成本。** 每次新入队和快照读取各增加一次轻量 `CAST(... AS jsonb)::text` 查询/表达式；它不写业务数据，但把指纹语义绑定到 PostgreSQL 表示。若未来更换存储类型，必须重新发布指纹版本，不能沿用当前哈希。

### 7.3 建议重点审查位置

- `backend/src/app/agent_runs/contracts.py`：`canonical_run_input_json`/`run_input_sha256`/`legacy_run_input_sha256` 的边界、request_id 排除、默认值重放与 NaN/Infinity 拒绝。
- `backend/src/app/infrastructure/persistence/agent_run_repository.py`：PostgreSQL 规范文本生成、写入/读取同源、旧哈希精确兼容与 fail-closed、advisory lock 顺序、重放先于容量、父任务终态/同会话、flush/FK 顺序、跨工作台读取。
- `backend/alembic/versions/0022_agent_tasks.py`：owner/lease 成对约束、终态检查与触发器、不可变触发器、索引/复合主键、迁移回退拒绝。
- `backend/src/app/agent_runs/events.py`：白名单是否真正阻止财务/参数/目标外泄，事件分页边界。
- `backend/tests/persistence/test_agent_runs.py`：JSONB `1e20`/`-0.0`/`0.5`/嵌套参数往返、默认值重放、旧稳定哈希兼容、旧规范化数值拒绝、并发 21 个任务、100 个等待不占容量、失败回滚、终态重开与不可变约束。

## 8. P2 修复记录（请求指纹跨 JSONB 稳定性）

### 8.1 正式审查问题

- 结论：不通过，1 项 P2；待修复后复审。
- 问题：请求指纹在 PostgreSQL JSONB 往返后不稳定。首轮用 Python `json.dumps` 文本计算指纹，但修订输入保存为 JSONB；PostgreSQL 会规范化合法数值。
- 审查复现：`1e20` 经 JSONB 重读变为整数 `100000000000000000000`；`-0.0` 变为 `0.0`；`0.5` 往返一致。上述参数能通过 `RunInput` 校验，但首次入队重读、`get` 或同键重放会触发 `integrity_violation`。

### 8.2 根因

`RunInput.parameters` 允许任意合法 JSON 数值；Python `json.dumps` 保留 `1e+20`/`-0.0` 的原始文本，而 PostgreSQL JSONB 以数值本身存储，输出规范文本（如 `100000000000000000000`/`0.0`）。首轮修订行保存 JSONB，`run_input_sha256` 在读取时对 JSONB 解码后的 Python 值重新序列化，得到不同文本和哈希，完整性校验因此误报。

### 8.3 复现与修复前红

```powershell
# backend/，专用临时 PostgreSQL 17
uv run --locked --no-sync pytest tests/persistence/test_agent_runs.py::test_jsonb_numeric_normalization_keeps_fingerprint_stable_for_reload_and_replay -q --tb=short --basetemp=../.tmp/pytest/t04-p2-red-20261111
```

结果：1 failed；首次 `enqueue` 在 `_load_snapshot` 抛 `AgentRunError("integrity_violation")`，退出 1。复现了 `1e20`/`-0.0` 的 JSONB 规范化问题。

### 8.4 修复方案与取舍

采用**保留 PostgreSQL JSONB 精确规范文本**的方案，不改 schema、不新增迁移：

1. 新增 `canonical_run_input_json(data)`：把已解析的 `RunInput` 稳定序列化为提交 JSON 文本。
2. 仓储在同一事务内执行 `SELECT CAST(:payload AS jsonb)::text`，让 PostgreSQL 生成与持久化完全一致的 JSONB 规范文本。
3. `run_input_sha256(workspace_id, canonical_input_text)` 从该规范文本解析、移除 `request_id`、排序键后哈希；写入和读取使用同一来源。
4. `_load_snapshot` 通过 `cast(agent_run_revisions.input AS text)` 读取持久化 JSONB 的规范文本，再按同一算法校验；不再对 Python 首次序列化文本做假设。
5. 保留 `legacy_run_input_sha256`，仅对首轮已提交行做精确旧哈希兼容；不重写修订/请求行。

为什么不选择“在 Python 中规范化数字”：PostgreSQL JSONB 的数值输出规则（大整数、零、科学计数法、嵌套值）不应在应用层复制一份近似实现；复制会再次引入漂移风险。为什么不选择“把修订输入改成 TEXT”：那需要改 schema/迁移并处理已有 JSONB 行，超出本次最小修复范围；当前方案保持 JSONB 可查询性，且不改历史。

### 8.5 兼容性说明

- **新行**：写入 `revision.sha256`/`request_sha256` 的均为 JSONB 规范文本哈希；读取、重放、并发重放使用同一算法。读取后的 `RunSnapshot.parameters` 可能使用 JSONB 解码类型（如 `1e20` 变为整数、`-0.0` 变为 `0.0`），数值语义不变；后续消费者不得依赖 Python `float` 的具体类型。语义相同的数值（如 `1e20` 与等值大整数）在 JSONB 中不可区分，会得到同一指纹并视为同一内容。
- **首轮已提交的稳定数值行**（如 `0.5`、普通字符串/整数）：读取和同键重放接受精确旧 Python JSON 哈希，不重写行；新增测试 `test_legacy_stable_hash_rows_stay_readable_without_rewriting_history` 覆盖。
- **首轮已提交且含 JSONB 规范化数值的行**（如 `1e20`、`-0.0`）：旧原始文本未被单独保存，无法在不伪造历史的情况下恢复；读取仍按 `integrity_violation` fail-closed。新增测试 `test_legacy_normalized_numeric_rows_fail_closed_instead_of_replaying` 证明不会用重读值重算旧哈希后放行。
- **迁移/业务库**：`0022_agent_tasks` 未修改、无新迁移；未应用到业务库。若本地已有首轮测试 schema，可重建；不提供回写历史脚本。
- **接口变化**：`run_input_sha256` 参数从 `RunInput` 改为 PostgreSQL 规范文本；新增 `canonical_run_input_json` 与 `legacy_run_input_sha256`。这是 T04 审查范围内的契约调整，消费者尚未接入。

### 8.6 修复后验证

| 检查 | 命令/目录 | 结果 |
| --- | --- | --- |
| P2 专项 + 兼容回归 | `backend/`：`uv run --locked --no-sync pytest tests/persistence/test_agent_runs.py::test_jsonb_numeric_normalization_keeps_fingerprint_stable_for_reload_and_replay tests/persistence/test_agent_runs.py::test_legacy_stable_hash_rows_stay_readable_without_rewriting_history tests/persistence/test_agent_runs.py::test_legacy_normalized_numeric_rows_fail_closed_instead_of_replaying -q --basetemp=../.tmp/pytest/t04-p2-legacy` | 3 passed，退出 0 |
| 最终聚焦 | `backend/`：`uv run --locked --no-sync pytest tests/agent_runs tests/persistence/test_agent_runs.py -q --basetemp=../.tmp/pytest/t04-p2-focus-3` | 21 passed，退出 0 |
| 静态 | `backend/`：`ruff check .`、`ruff format --check .`、`pyright` | 全部通过；Pyright 0 errors / 0 warnings |
| 架构门禁 | `backend/`：`python -m scripts.check_architecture` | `files_scanned=38`，`findings=[]` |
| 最终后端 full | 仓库根目录：`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t04-p2-full-backend-final.json` | `verification=passed`；1149 collected / 1149 passed / 0 failed / 0 skipped / 0 collection errors |

### 8.7 修复提交与指纹

- P2 修复 tip：`0df86fe7bbe4dc96062822404dfe45f5f675c06f`
- P2 修复 tree：`0b99b60f684264374ae080ef321fb215217ab428`
- 复审重点范围：`2e17368..0df86fe`，5 个文件，+279 / -28
- 累计代码范围：`9e45d77..0df86fe`（排除 docs 提交），13 个文件，+2433 / -0

| 文件 | SHA-256 |
| --- | --- |
| `backend/src/app/agent_runs/__init__.py` | `a50503a5eefe5a1e541a314e2b031b11c247a5ee53d8ce565f0cfe7573b477f4` |
| `backend/src/app/agent_runs/contracts.py` | `79be26da1b5353acc00e44fe801399ca14a1245f1aba20ded1fce65d9547fadb` |
| `backend/src/app/infrastructure/persistence/agent_run_repository.py` | `f533cafba214c744c45c4df9e46cd948864dd2ef7634743df1509651e8362869` |
| `backend/tests/agent_runs/test_contracts.py` | `c1681179c073f6a4f1d059ca19f396e9d9acc0c786452bc35afc1368c4d5b076` |
| `backend/tests/persistence/test_agent_runs.py` | `f5d8801c6bc51ed53fa8c037637ef0c07b23faebd8a28bcf26023f654ae02647` |

## 9. 交回审查

请用户将本文件与 P2 修复 tip `0df86fe` 的 diff 交给此前负责方案设计的原审查助手复审，重点核对第 8 节的 JSONB 规范文本算法、旧行兼容与 fail-closed 行为。首轮范围 `9e45d77..2e17368` 的其余实现未在本轮改变。开发模型不会自行标记正式审查通过，不会在收到结论前开始 T05 或后续任务。若复审提出修复意见，下一轮将先复现/核对，再逐条修复、补充回归、记录新 tip 和验证结果后再次提交审查。
