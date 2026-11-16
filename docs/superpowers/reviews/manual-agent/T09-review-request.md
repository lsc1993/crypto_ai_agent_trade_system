# T09 审查请求：逐次工具守卫与内部研究工具

- 任务/审查单元：**T09**（D3：冻结上下文、工具守卫、真实 MCP、模型驱动 LangGraph 的第二段）。
- 执行模型：DeepSeek `deepseek-flash`（`PI_PROVIDER=deepseek`、`PI_MODEL=deepseek-flash`、`PI_REASONING_LEVEL=max`）；具体模型版本/推理实现未知。
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0；质量验证说明与当前仓库版本。
- 自测状态：**`implemented`**（模块、聚焦/阶段/quick 后端和静态/架构门禁完成；后端 full 因本机无专用 PostgreSQL 阻塞，不能标 `verified`）。
- 正式审查状态：**`awaiting_review`**（待用户转交原审查助手；开发端不预填 `approved`）。
- 日期：2026-11-17。

## 1. 工作区、分支与提交范围

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main` tip `36cda455670713f3ffaee18655c4d59113a90b22`，工作区干净；T08 已合并） |
| 隔离工作区 | `D:\t09`（从 `main` 的 `36cda45` 创建） |
| 分支 | `t09-tool-gateway`（未推送、未合并、未部署） |
| base | `36cda455670713f3ffaee18655c4d59113a90b22`（`main`，`docs: record T08 merge into main`） |
| implementation tip | `2674f1692d09217daea008a6999d49b291383914`（`feat: guard registered agent tool calls`） |
| implementation tree | `3d8c02cfff6e40171baf2cf4b1fb5337c85783a0` |
| 代码改动范围 | `36cda45..2674f16`，19 个文件，+4115 / -20 |
| 工作区未提交内容 | 仅本审查请求与进度更新；实现代码、测试、安全门禁和同步文档已在 implementation tip 中提交。未夹带其他任务改动、`.env`、凭证或业务库修改 |
| docs 提交 | 本审查请求/进度在 implementation tip 之后单独提交；提交号见最终交付回复，不用自身提交号循环引用 |
| 复审状态 | 尚未发生；等待原审查助手正式结论 |

本轮没有修改 `.env`、生产配置、业务数据库、模拟盘资金/风控配置或交易执行链路；未调用真实模型、MCP、私有账户或交易接口。

### 1.1 代码/测试文件与 SHA-256 指纹

| 文件 | SHA-256 |
| --- | --- |
| `backend/src/app/agent/interactive/tools/__init__.py` | `216d50d6340602dd6783bd11b83130d458df7575cbd78bd356873b3badb3166a` |
| `backend/src/app/agent/interactive/tools/contracts.py` | `b57729a2c84e4ccaea876057fdfaf4930dd1dbce5bedd1c6327bf2c3b0e3a988` |
| `backend/src/app/agent/interactive/tools/registry.py` | `1290dbf8ac5c230ba36ebde347b35a0947b04bb2de5170d3333fb8aa79e63fa7` |
| `backend/src/app/agent/interactive/tools/gateway.py` | `59bd70f1160f7878de45a1428a3c73642587888b872e55d103ece7990771b9c6` |
| `backend/src/app/agent/interactive/tools/research_tools.py` | `df63c4146eab36cfd00d16f11464e8265910de698294b7fc1ab65efcc566bc8a` |
| `backend/src/app/agent/interactive/__init__.py` | `c35f15741229ecfd30eab164f7dd80786633df8925b5ef6ab218e5d5aeccb905` |
| `backend/tests/agent/interactive/test_tool_gateway.py` | `bbf3bf0457a8ff5de5c042608a30d15e6e28f1bc8e1dd31692136006f6c9183c` |
| `backend/tests/agent/interactive/test_research_tools.py` | `8da9ae2cf93394251e51c7f8a409b1ab359f531476fc306563a169f6a0abdce8` |
| `backend/scripts/check_architecture.py` | `4b78e99ed9864190dbd4d31500a3604050432629a9eb6bb3fd3c121ec2404355` |
| `backend/tests/security/test_architecture_gate.py` | `1c5284896bd922e95d7349d7da2b8edc54e182a572f72d652e78beee4547c378` |
| `backend/tests/security/test_agent_source_and_secret_safety.py` | `0c60d294642ff763bfa9a1778dc00a0c94dbefae14a0b42ce78594ca1a3a58fe` |
| `backend/tests/security/test_agent_dependency_boundary.py` | `ea4ff4907c93f93a19ee8c64c848dccbf2dda79f608bac9e933644b584ba2ce6` |

同步文档（已包含在 implementation tip）：`AGENTS.md`、`backend/AGENTS.md`、`docs/ai-maintenance.md`、`docs/operational-boundaries.md`、`docs/project-status.md`、`docs/superpowers/plans/2026-11-06-manual-trading-agent-implementation.md`、`docs/superpowers/plans/2026-11-06-manual-trading-agent-contracts.md`。

## 2. 任务范围与 FR/AC/HN 映射

### 2.1 本轮范围

实现 D3 的逐次工具守卫与内部领域工具基础：

- C6 `RegisteredTool`/`ToolRequest`/`ToolResult`/`ToolObservation` 纯契约、受限 JSON Schema 校验和只读能力类型。
- 不可变 `ToolRegistry`/`ToolCatalog`：服务端登记、Schema/能力/范围/超时/结果上限冻结、完整目录指纹和模型可见投影。
- `ToolGateway.call(context, request)`：每次调用重新读取运行快照，核对修订/取消/所选策略/C5 fence、策略版本、目录指纹、工具登记、参数 Schema、当前币种/周期/刷新模式；通过后预留并提交 TOOL 尝试，才调用处理器；校验输出 Schema、8 KiB 摘要、未来/到期时间后结算；固定串行。
- 六个只读研究工具：`read_market_evidence`、`read_approved_news_factors`、`compute_technical_facts`、`evaluate_selected_strategy`、`search_research_knowledge`、`read_strategy_definition`。`build_manual_trade_plan` 不登记，留待 T14。
- 架构/安全门禁同步：新增 `agent_runs`/`trade_planning` 对 Agent/交易/模拟执行的隔离、`research` 对 LLM 的隔离；新增工具源码无交易/HTTP/SQL/模型客户端/凭证的能力断言。

本轮**不**实现：T10 MCP/真实 TCP、T11 模型驱动 LangGraph、T12/T13 确定性规划与计划采纳、T14 HTTP/生产装配、T15/T16 前端、SQL 工具结果 artifact、真实模型质量、业务库迁移或任何真实订单/私有账户能力。现有生产固定研究路径仍不向模型提供工具。

### 2.2 映射

| 需求/不变量 | T09 证明 | 证据 |
| --- | --- | --- |
| FR-02（模型驱动研究循环） | 工具网关可接收/拒绝工具请求、返回带 step/attempt 的安全观察，支持后续模型循环根据观察继续；T09 不运行模型循环 | `test_tool_gateway.py`、`test_research_tools.py`；T11 仍需真实图 |
| FR-03（Tool Calling/MCP） | 服务端登记、输入/输出 Schema、权限/范围/时间/预算、超时、并发 1、结果引用和调用审计；MCP/TCP 不在本轮 | `test_tool_gateway.py::test_budget_reservation_is_committed_before_handler_and_result_is_settled`、`test_handlers_are_serialized_to_concurrency_one`、`test_tool_versions_and_registry_metadata_are_frozen_into_model_catalog` |
| FR-04/FR-05/FR-06（支撑） | 行情/知识工具复用 T08 冻结证据与截至过滤；工具结果摘要、预算预留和未知结算 | `test_read_market_evidence_returns_frozen_epoch_reference_and_public_facts`、`test_search_research_knowledge_uses_evidence_cutoff_and_treats_text_as_data`、`test_handler_failure_settles_unknown_and_keeps_audit_ids` |
| AC-01（证据不足后选择工具） | 网关可返回结构化的成功/降级/失败/未知观察，工具输出带引用和原因；真实模型选择仍待 T11 | 同上 |
| AC-03（未登记/越权/注入拒绝） | 未知工具、目录/策略版本漂移、跨币种/周期、历史刷新、注入字段和工具描述注入均在预留/处理器前拒绝 | `test_unknown_tool_is_rejected_before_reservation_or_handler`、`test_catalog_fingerprint_mismatch_rejects_without_send`、`test_policy_version_mismatch_rejects_without_send`、`test_out_of_scope_arguments_are_rejected_before_reservation`、`test_invalid_arguments_and_injection_fields_are_rejected`、`test_tool_description_injection_does_not_create_authority` |
| AC-06（预算临界/未知） | 每次调用先经 C5 `status` 校验 fence；预留/`mark_sent` 先于处理器；预算不足、失租、取消不调用处理器；处理器控制错误按未知结算并上抛 | `test_budget_exhaustion_stops_before_handler_execution`、`test_stale_budget_fence_stops_before_handler_execution`、`test_invalid_fence_or_cancel_never_reserves_or_sends`、`test_handler_control_error_is_not_hidden_as_tool_success` |
| AC-29（财务/私有/订单边界） | 工具目录无交易/私有账户能力；测试断言摘要无金额/仓位/杠杆/凭证；源码/架构门禁拒绝交易执行、HTTP/SQL 和模型客户端下沉 | `test_tool_summaries_never_include_private_financial_values`、`test_interactive_tool_sources_are_read_only_and_have_no_execution_surface`、`test_interactive_tool_modules_cannot_import_trade_execution_or_model_clients`、`check_architecture` |
| HN-01（每次调用核对授权） | `ToolGateway.call` 每次重新读取快照、`BudgetLedger.status`、策略/目录版本、工具版本和范围；拒绝不发送 | `test_policy_version_mismatch...`、`test_catalog_fingerprint_mismatch...`、`test_out_of_scope...`、`test_invalid_fence...` |
| HN-05（所有发送累计预留/计数） | TOOL 尝试先 `reserve`/`mark_sent`；市场 refresh 经 T08 传输预算；新闻生产读取器契约要求自行使用 C5 传输预算 | `test_budget_reservation...`、`test_budget_exhaustion...`、`EvidenceService` T08 回归；新闻 HTTP 未执行 |
| HN-09（精确策略、知识不授权） | 评估/策略定义使用 `context.strategy_ref` 和运行参数；知识命中作为外部不可信文本展示，不改变目录/权限 | `test_evaluate_selected_strategy_binds_exact_version_and_parameters`、`test_read_strategy_definition_bounds_long_method_text`、`test_search_research_knowledge_uses_evidence_cutoff_and_treats_text_as_data` |
| HN-12（网络/依赖/载荷/投影） | 受限 Schema（object/string/integer/boolean/array，无 `$ref`/正则/代码）、8 KiB 摘要、64 KiB 内部结果上限、未来/到期检查；工具层无 HTTP/SQL/交易依赖 | `test_registry_rejects...`、`test_oversized_summary...`、`test_output_schema_violation_and_future_observation...`、`test_expired_handler_result_is_degraded_not_current_success`、`check_architecture` |

T09 不生成 `TradeIntent`、不访问私有账户、不调用模拟/真实订单服务，也不宣称 MCP 或真实模型 Tool Calling 已交付。

## 3. 改动清单与关键取舍

### 3.1 改动清单

**新增源码**
- `backend/src/app/agent/interactive/tools/__init__.py`：包入口只导出契约、目录、网关和服务类型。
- `backend/src/app/agent/interactive/tools/contracts.py`：C6 类型、受限 Schema 校验、摘要/结果上限、错误码。
- `backend/src/app/agent/interactive/tools/registry.py`：不可变目录、目录指纹、模型可见版本、处理器绑定。
- `backend/src/app/agent/interactive/tools/gateway.py`：逐次守卫、预算预留/发送、结果校验、结算和观察。
- `backend/src/app/agent/interactive/tools/research_tools.py`：六个只读处理器、证据/策略/知识/新闻端口适配。

**新增测试**
- `backend/tests/agent/interactive/test_tool_gateway.py`：守卫顺序、拒绝路径、预算/fence、串行、幂等、输出校验、审计标识。
- `backend/tests/agent/interactive/test_research_tools.py`：六工具、真实技术引擎/策略服务/RAG 服务、新闻不可用/未批准来源、长定义截断和财务隔离。

**修改安全/架构**
- `backend/scripts/check_architecture.py`：新增 `agent_runs`/`research`/`trade_planning` scope 与 `ARCH007`/`ARCH008` 规则。
- `backend/tests/security/test_architecture_gate.py`：违规/合法反向样例和 required files。
- `backend/tests/security/test_agent_source_and_secret_safety.py`：工具源码只读/无执行/无凭证与六工具白名单断言。
- `backend/tests/security/test_agent_dependency_boundary.py`：工具模块禁止交易执行/LLM 客户端导入。

**文档**
- 根 `AGENTS.md`、`backend/AGENTS.md`：明确模块级工具守卫尚未等于生产模型工具循环。
- `docs/ai-maintenance.md`、`docs/operational-boundaries.md`：工具守卫、只读/预算/结果边界和未装配状态。
- `docs/project-status.md`、实施计划、实施契约：T09 实现/验证/未验证记录。

### 3.2 关键实现取舍

1. **目录指纹覆盖完整条目**：`ToolRegistry` 用“基础版本 + `catalog_entry` 哈希”构造模型可见版本；输入/输出 Schema、能力、范围、超时或结果上限变化都会改变 `tool_catalog_sha256`，避免只改输出 Schema 不触发目录拒绝。`test_catalog_fingerprint_matches_context_projection` 验证与 T08 `ContextBuilder` 的投影哈希一致。
2. **每次调用重新核对 C5 fence**：除了运行快照，`ToolGateway` 在拒绝/参数检查前调用 `BudgetLedger.status`；这样旧 owner、失效 lease 即使快照仍显示 running 也不会获得观察，也不会调用处理器。
3. **先预留后发送**：`_reserve_step` 用 C5 `status.tool_calls` 分配高位 TOOL 序号；`reserve` 成功并 `mark_sent` 后才调用处理器。预算不足/失租/取消在处理器前停止。处理器抛出的 `AgentRunError`（预算/租约/存储）按未知结算并上抛，不伪装成可继续的普通观察。
4. **幂等与重启折衷**：同一 run/revision/工具输入在进程内复用逻辑步骤和已成功观察；进程重启后同一输入可能生成新的逻辑步骤（只读工具仍安全，但不是跨进程持久幂等）。这是本轮明确的限制，未声称恰好一次。
5. **结果引用**：处理器能提供证据 epoch/策略版本引用时优先使用；搜索/新闻等没有现成 artifact 时，网关用 `ArtifactRef(artifact_id=step_id, sha256=结果摘要)` 结算。该引用绑定已持久化逻辑步骤和摘要，但不是可读取的 `agent_artifacts` 行；T14 需要材料化/投影时不能误当完整产物。
6. **结果校验/过期**：`ToolResult` 允许最多 64 KiB 以便网关统一拒绝；网关注册工具的 `max_result_bytes` 与 8 KiB 模型摘要上限取较小值。结果未来时间、到期时间早于观测、输出 Schema 不符、摘要超限均在结算前拒绝；过期结果降级为 `stale/result_expired`。
7. **新闻默认不可用**：T09 未装配生产新闻读取器；`UnavailableApprovedNewsSource` 明确返回 `news_source_unavailable`，不伪造“无新闻”。生产读取器访问真实公开源时必须自行使用同一 C5 传输预算；T09 未证明新闻 HTTP。
8. **工具串行**：`asyncio.Lock` 固定并发 1，测试用处理器 spy 证明 `max_active == 1`；不引入并行图分支的恢复复杂度。
9. **安全门禁不删旧断言**：保留旧 `tools=`/`tool_choice`/交易关键字字符串检查；新增工具源码和导入边界断言，不把“工具目录存在”当作生产工具循环已交付。

## 4. 公共接口、依赖与迁移影响

### 4.1 新增/修改公共接口

- `agent/interactive/tools/contracts.py`：`RegisteredTool`、`ToolRequest`、`ToolResult`、`ToolObservation`、`ToolObservationStatus`、`ToolResultStatus`、`ToolQuality`、`ToolCapability`、`ToolScope`、`ToolHandler`、`ToolContractError`/`ToolSchemaError`/`ToolArgumentsError`；`TOOL_RESULT_SCHEMA`、`TOOL_ACTION_SEQUENCE_BASE=2_000_000`、`MAX_TOOL_SUMMARY_BYTES=8_192`、`MAX_TOOL_RESULT_BYTES=65_536`、`TOOL_TIMEOUT_SECONDS=30`。
- `agent/interactive/tools/registry.py`：`ToolRegistry`/`ToolCatalog`；`catalog_sha256`、`model_tools()`、`model_version(name)`、`bind_handlers(...)`、`authorized(context)`。
- `agent/interactive/tools/gateway.py`：`ToolGateway.call(context, request) -> ToolObservation`；构造需 `runs`、`budget`、`catalog`、`handlers`，可选 `policy_version`/`clock`。
- `agent/interactive/tools/research_tools.py`：`RESEARCH_TOOL_NAMES`、`ResearchToolService.handlers()`、`EvidenceToolService`、`StrategyEvaluationService`、`ApprovedNewsReader`、`ApprovedNewsSummary`、`UnavailableApprovedNewsSource`。
- `backend/scripts/check_architecture.py`：`SCOPES` 增加 `agent_runs`/`research`/`trade_planning`；`ARCH007`（规划/任务层交易隔离）、`ARCH008`（研究/规划层 LLM 隔离）。

### 4.2 依赖

- **无新增生产依赖**；未修改 `pyproject.toml`、`uv.lock`、模型供应商配置或 `.env`。
- 未安装/启用 MCP、httpx2、向量库、CCXT、浏览器或交易所客户端；T10 才评估 MCP 依赖。

### 4.3 数据库迁移

- **无新增迁移**；未修改旧迁移、业务库或历史报告/审计。
- 迁移 head 仍为 `0027_agent_segments`；`alembic heads` 已核验。
- T09 的真实 TOOL 步骤/尝试依赖既有 `agent_steps`/`agent_attempts`/meter 表；本轮测试使用预算替身，未在专用 PostgreSQL 上重跑真实预留/结算/恢复。

## 5. 验证记录

### 5.1 环境与证明范围

- 执行目录：`D:\t09`（根）与 `D:\t09\backend`。
- 后端锁定环境：`uv sync --project backend --locked`，Python 3.12；独立 `.venv`。
- 本机 Docker/PostgreSQL 不可用：`TEST_DATABASE_URL` 未设置，`docker` 守护进程未运行；`test-database` 预检 blocked，后端 full 未执行。未指向、迁移或修改任何业务库。
- 验证进程未修改 `.env`、凭证、生产配置或业务数据；未调用真实模型、MCP、私有账户或交易执行。
- 测试数据：合成任务/策略/知识/公开行情/新闻摘要/工具结果；财务哨兵仅用于断言不泄漏。
- `.tmp/quality/` 证据是本地未提交产物，不随分支传递；上表命令可在有专用测试库环境重跑。

### 5.2 实际命令与结果

| 检查 | 目录 | 完整命令 | 退出码 | 实际结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 改动前基线 | `D:\t09\backend` | `uv run --locked --no-sync pytest tests/agent/interactive tests/agent_runs tests/research/strategies tests/research/knowledge tests/security tests/governance -q --basetemp=../.tmp/pytest/t09-baseline-3` | 0 | 248 passed | 终端记录 |
| 首轮预期红 | `D:\t09\backend` | `uv run --locked --no-sync pytest tests/agent/interactive/test_tool_gateway.py tests/agent/interactive/test_research_tools.py -q --basetemp=../.tmp/pytest/t09-red-1` | 2 | 2 个 collection error（缺少 `app.agent.interactive.tools`），符合测试先行预期 | 终端记录 |
| 工具+安全聚焦（最终） | `D:\t09\backend` | `uv run --locked --no-sync pytest tests/agent/interactive/test_tool_gateway.py tests/agent/interactive/test_research_tools.py tests/security -q --basetemp=../.tmp/pytest/t09-focus-final-4` | 0 | **101 passed / 0 failed / 0 skipped**（38 工具 + 63 安全） | 终端记录 |
| 交互式模块（最终） | `D:\t09\backend` | `uv run --locked --no-sync pytest tests/agent/interactive -q --basetemp=../.tmp/pytest/t09-interactive-final-4` | 0 | 80 passed | 终端记录 |
| D3 阶段回归（非数据库，最终） | `D:\t09\backend` | `uv run --locked --no-sync pytest tests/agent/interactive tests/agent_runs tests/research tests/security tests/governance -q --basetemp=../.tmp/pytest/t09-stage-final-4` | 0 | 300 passed / 0 failed / 0 skipped | 终端记录 |
| 后端 quick（最终） | `D:\t09` | `uv run --project backend --locked --no-sync python scripts/verify.py quick --component backend --report .tmp/quality/t09-quick-backend-final.json` | 0 | `verification=passed`；1120 collected / 1120 passed / 0 failed / 0 skipped / 0 collection errors | `.tmp/quality/t09-quick-backend-final.json` |
| 后端 full（阻塞，不计为通过） | `D:\t09` | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/t09-full-backend-final-blocked-2.json` | 2 | `verification=blocked`；`test-database=blocked(environment_not_ready)`；`backend-tests=blocked(prerequisite_not_passed)`；数据库/后端 full 未执行 | `.tmp/quality/t09-full-backend-final-blocked-2.json` |
| Ruff | `D:\t09\backend` | `uv run --locked --no-sync ruff check .` | 0 | All checks passed | 终端记录 |
| 格式 | `D:\t09\backend` | `uv run --locked --no-sync ruff format --check .` | 0 | 384 files already formatted | 终端记录 |
| Pyright | `D:\t09\backend` | `uv run --locked --no-sync python -m pyright` | 0 | 0 errors / 0 warnings | 终端记录 |
| 架构门禁 | `D:\t09\backend` | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `status=passed`，`files_scanned=82`，`findings=[]` | 终端记录 |
| 迁移链 | `D:\t09\backend` | `uv run --locked --no-sync alembic heads` | 0 | `0027_agent_segments (head)` | 终端记录 |
| 文档空白/差异 | `D:\t09` | `git diff --check` | 0 | 无输出 | 终端记录 |

## 6. 未验证项、已知风险与重点审查位置

### 6.1 未验证/未执行

- 专用 PostgreSQL：`test-database`、真实 `agent_steps`/`agent_attempts` 预留/发送/结算、meter 释放、失败触发器、并发/恢复和数据库 full。
- 后端 full、前端 lint/typecheck/Vitest/build、Playwright/HTTP e2e、生产 lifespan 装配。
- T10 MCP 官方 SDK、真实 TCP/HTTP、64 KiB 原始结果、协议协商和关闭回收。
- T11 模型驱动 LangGraph、原生 Tool Calling、真实请求/观察回灌、等待/恢复。
- 真实模型质量、抗注入、真实新闻 HTTP、真实策略/知识质量、业务库迁移和部署回退。
- T14 的公开 artifact 投影/持久化；合成 step 结果引用不是可读取 artifact。
- T09 工具循环没有接入现有固定研究路径；生产研究仍不能调用工具。

### 6.2 重点审查位置

1. **动作序号/幂等**：`ToolGateway._reserve_step` 的 `status.tool_calls` + 进程内映射是否足够；重启后的重复输入生成新步骤是否可接受；是否需要持久 sequencer。
2. **fence/预算顺序**：`budget.status` 每次调用是否足以证明 owner/lease；`reserve`→`mark_sent`→处理器→`settle` 的顺序、`AgentRunError` 未知结算和 `mark_sent` 异常保留 prepared 的语义。
3. **结果引用**：无 artifact 时合成 `step_id + 摘要` 是否可接受；`ToolObservation.result_ref` 是否会被 T11/T14 误当可读取产物；是否需要新增持久结果端口。
4. **目录指纹**：模型可见版本嵌入完整条目哈希与 T08 `ContextBuilder` 投影是否一致；目录/策略/工具版本变化是否都能拒绝旧运行。
5. **输出边界**：64 KiB 内部 `ToolResult` 与 8 KiB 模型摘要的分层、未来/过期/输出 Schema/URL/来源校验是否完整；新闻读取器把传输预算委托给生产适配器是否足够。
6. **安全门禁**：新增 `ARCH007`/`ARCH008` 是否覆盖 `agent_runs`/`research`/`trade_planning` 的适用边界而不误伤 `research/backtests` 合法模拟依赖；工具源码字符串断言是否会漏过动态导入/反射（已知不是任意代码安全证明）。
7. **工具处理器**：`read_strategy_definition` 的方法/参数摘要是否满足模型最小化；`read_approved_news_factors` 默认不可用是否会被误认为“无新闻”；知识片段注入文本是否只在数据角色展示。
8. **策略版本默认值**：`policy_version="interactive_planning_v1"` 是否应在 T14 显式注入；不同策略版本是否会被错误拒绝。

## 7. 自测状态与正式审查状态

- **自测状态：`implemented`**。实现、聚焦、阶段、quick 后端、Ruff/格式/Pyright/架构/迁移链完成；后端 full 因本机无专用 PostgreSQL 阻塞，未完成必需全量验证，因此不标 `verified`。
- **正式审查状态：`awaiting_review`**。等待用户把本请求和 implementation tip `2674f16` 交回原审查助手；开发端不自行填写 `approved`，也不进入 T10/T11。
- 若原审查助手要求修复，开发端先核对/复现，再逐条修复并补回归，记录新 tip 与验证结果后再次交审。
