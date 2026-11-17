# T10 审查请求：官方 MCP SDK、受控 HTTP 和本地只读服务

- 任务/审查单元：**T10**（D3：冻结上下文、工具守卫、真实 MCP、模型驱动 LangGraph 的第三段）。
- 执行模型：DeepSeek `deepseek-flash`（`PI_PROVIDER=deepseek`、`PI_MODEL=deepseek-flash`、`PI_REASONING_LEVEL=max`）；具体模型版本、推理实现和供应商侧版本未知。
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0；质量验证说明与当前仓库版本。
- 自测状态：**`verified`**（实现、聚焦、阶段、quick、独立 PostgreSQL full、Ruff/格式/Pyright/架构/迁移链完成；不等于正式审查通过）。
- 正式审查状态：**`awaiting_review`**（未预填通过；等待用户转交原审查助手）。
- 日期：2026-11-17。

## 1. 工作区、分支与提交范围

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:/project_git/crypto_ai_agent_trade_system`（`main` tip `b80071c`，工作区干净；T09 已合并） |
| 隔离工作区 | `D:/project_git/t10`（从 `main` 的 `b80071c` 创建） |
| 分支 | `t10-mcp-transport`（未推送、未合并、未部署） |
| base | `b80071c`（`main`，`docs: record T09 merge into main`） |
| T10 implementation tip | `690d726892ea6deaf14c77a705ca06539fb7cd0a`（`fix: harden MCP result handling and protocol pinning`；首轮实现 `a9d3b24`） |
| T10 implementation tree | `6221e3f0d03721883a6dc713d49143ddfc94d62a` |
| 辅助测试提交 | `619fe2c429cb40de401154dc2aa82af48cf5395f`（`test: anchor interaction lifetime fixture to repository clock`；1 个文件 +2/-1，非 T10 生产代码） |
| T10 代码范围 | `b80071c..690d726`，22 个文件，+2789/-14（含新增代码、测试、依赖锁定与同步文档） |
| 辅助修复范围 | `a9d3b24..619fe2c`，1 个文件，+2/-1 |
| T10 加固范围 | `619fe2c..690d726`，2 个文件，+50/-22（结果处理/协议钉死） |
| 审查请求 docs 提交 | 生成后另行提交；不把自身提交号写入 `implementation tip` |
| review_status | `awaiting_review` |
| reviewed_tip | —（尚未收到正式结论） |

本轮没有修改 `.env`、生产配置、业务数据库、模拟盘资金/风控配置或交易执行链路；未调用真实模型、外部 MCP、私有账户或交易接口。

### 1.1 代码/测试文件与 SHA-256 指纹

以下指纹按 worktree 最终文件计算；提交后代码/测试未再修改。

| 文件 | SHA-256 |
| --- | --- |
| `backend/src/app/infrastructure/mcp/__init__.py` | `beb6ee614d03324a7c13bc45ab1b9bf5eb38904e768b655e4379d44dd5b31da2` |
| `backend/src/app/infrastructure/mcp/registry.py` | `d9a010ca79b041287c8c8f25819d80e6051ac72ec10567f57541e7cf932165c8` |
| `backend/src/app/infrastructure/mcp/transport.py` | `5e75c11117278895eccefe939b5df3c17d4d29282e0ddf4c1313d464a50b8006` |
| `backend/src/app/infrastructure/mcp/client.py` | `befaa7555fcc8ce531ebd0f76fb914535b88d8a5c22326e55a8880c0ce5bc505` |
| `backend/src/app/infrastructure/mcp/server.py` | `96778cfc7b36ef1390c8e36ec3920f26bd48fc71e440bb477e20c279d6811e66` |
| `backend/src/app/agent/interactive/tools/research_tools.py` | `f5322cb9f05391133de33ee1867702b6311e3a58d692fe1ae7a03a926251243a` |
| `backend/tests/mcp/support.py` | `a79b4e3090ebd4e7135243ffdc4ec3679849a17b318052b5a50901a1ba05c345` |
| `backend/tests/mcp/test_compatibility.py` | `1c8b7d1b78b6c1dcd49f5f95c8c3990d4bb245ec15a05206f53d38de8a9f6634` |
| `backend/tests/mcp/test_guarded_transport.py` | `03626c306758e4a2700634430313405e3b798aa1b599377edfbd542e82bac4a1` |
| `backend/tests/mcp/test_local_http.py` | `0e2d0e4606ad08457a0e4d803ed1db1abfb4798d9cd74b3399be2eed717de92d` |
| `backend/tests/tooling/test_mcp_lifespan.py` | `fc8b219664679bdf1374d0cfca3fd41b17e16717495b5bcc10aefb2bd9ac49dc` |
| `backend/tests/security/test_agent_dependency_boundary.py` | `cdd742da07f8d42234fdf1dc370b23d1a4dd0c603db1de4f784d570c4034785a` |
| `backend/tests/persistence/test_agent_interactions.py` | `f2eb67bbdf8147b0ef01229f28b059df056f7b4ca83d256d7e557bc1c7ed4fed`（辅助修复文件） |
| `backend/pyproject.toml` | `174a6c74120e0abc24699ed7ed5be0d73153fbb1672213c9941b0dda59d86086` |

同步文档（包含在 T10 代码/测试提交或后续 docs 提交中）：`AGENTS.md`、`backend/AGENTS.md`、`docs/ai-maintenance.md`、`docs/operational-boundaries.md`、`docs/project-status.md`、实施计划、实施契约、进度文件。

## 2. 任务范围与 FR/AC/HN 映射

### 2.1 本轮范围

实现 D3 的官方 MCP SDK、受控 HTTP 和本地只读服务：

- `infrastructure/mcp/registry.py`：固定 loopback 端点、协议版本、工具输入/输出 Schema 指纹、进程内服务凭据、不可变端点登记。
- `infrastructure/mcp/transport.py`：自有 httpx2 有界传输；在 SDK 前拒绝未登记目标与所有 3xx，按实际 HTTP 请求计数并限制每次工具调用 64 次；非 SSE 响应增量读取并在 64 KiB 处中止；SSE 单事件上限交给 SDK 的 `max_sse_event_size`。
- `infrastructure/mcp/client.py`：官方 `Client` + Streamable HTTP；`mode="auto"` 协商必须得到 `2026-07-28`，核对 `tools/list` 集合与 Schema 指纹，再调用固定 `read_strategy_definition`。实现 T09 `ToolHandler`，必须由 `ToolGateway` 在预算/目录/fence 检查后调用；公共 `call` 未绑定网关时失败。
- `infrastructure/mcp/server.py`：官方 `MCPServer.streamable_http_app()`，只登记 `read_strategy_definition`；固定 loopback mount、进程内 Bearer 认证、显式 session manager lifespan、公开描述符不含凭据。
- 新增 `mcp==2.3.0`、`httpx2>=2.10.0,<3` 生产依赖并锁定传递依赖；同步依赖安全测试、根/后端规范、维护/运行边界、项目状态、实施计划与契约。
- 测试使用真实 loopback TCP 的临时 stub/uvicorn 服务，覆盖 SDK 兼容、协议协商、重定向、JSON/SSE 上限、未登记 Host、真实工具调用、凭据/协议/Schema 漂移、lifespan 启动/关闭。

本轮**不**实现：T11 模型驱动 LangGraph、T12/T13 确定性规划与计划采纳、T14 HTTP/SSE/生产 lifespan 装配、T15/T16 前端、真实外部 MCP、真实模型质量、业务库迁移或任何订单/私有账户能力。当前生产固定研究路径仍不能调用工具。

### 2.2 映射

| 需求/不变量 | T10 证明 | 证据 |
| --- | --- | --- |
| FR-03（Tool Calling/MCP） | 固定端点/协议/Schema 登记、真实 TCP MCP 调用、认证、逐请求传输上限、超时/失败降级、结果安全投影 | `test_local_http.py`、`test_guarded_transport.py`、`test_compatibility.py` |
| AC-02（登记工具经真实 TCP MCP 调用） | 正常路径经 `McpToolClient`（T09 网关）真实 POST 到本地 `read_strategy_definition`，服务端读取冻结策略并返回有界摘要；`last_request_count==3` 证明 discover/list/call 都发生 | `test_registered_tool_is_called_through_real_tcp_mcp` |
| AC-03（未登记/越权/注入拒绝） | 客户端拒绝非固定工具名；服务只暴露一个工具；错误/缺失凭据、Schema/协议漂移、未登记 Host、重定向均在读取策略或跟随目标前拒绝；T09 网关继续承担模型参数/范围/注入拒绝 | `test_client_rejects_unregistered_tool_names`、`test_missing_service_credential_...`、`test_tool_schema_mismatch_...`、`test_protocol_mismatch_...`、`test_internal_endpoint_rejects_unregistered_host_header`、`test_redirect_...` |
| AC-17（安全轨迹，模块边界） | 观察只含固定原因码、摘要、时间、版本引用；不返回 URL、令牌、上游正文或财务值；未接入 SSE/前端，完整事件重读仍待 T14 | `test_strategy_definition_summary_has_no_financial_values`、`test_local_http.py` |
| HN-01（每次调用核对授权） | `McpToolClient` 每次读取当前 `ExecutionContext` 的 workspace/策略版本；`ToolGateway` 每次重读运行快照/目录/fence；未绑定网关的 `call` 失败 | `test_local_http.py` 全流程、`test_client_rejects_...`、T09 网关回归 |
| HN-04（成功复用、未知不重放） | MCP 适配器每个 `handle` 最多一次发送；失败返回降级观察，不在内部重试/重放；SDK 内部请求逐次计数但无业务重试循环 | `test_guarded_transport.py`、`McpToolClient.handle` 实现、本地失败用例 |
| HN-05（发送累计计数） | 每次实际 HTTP 请求先检查/增加 64 次上限；SDK discover/list/call/后台请求都经过同一 transport；每次工具调用仍由 C5 网关预留一个 TOOL 尝试 | `test_transport_counts_each_request_and_caps_hidden_retries`、`test_registered_tool_...`；任务级传输预算接线待 T11/T14 |
| HN-12（网络/依赖/载荷/投影） | 只允许登记 loopback 主机/端口/路径；拒绝所有 3xx；64 KiB JSON/SSE；8 KiB 模型摘要；未登记 Host 421；凭据不进公开 descriptor；无 stdio/sampling/roots/elicitation | `test_guarded_transport.py`、`test_sdk_sse_event_limit_is_enforced`、`test_internal_endpoint_requires_service_credential`、`test_public_descriptor_...`、依赖安全测试 |
| AC-29（财务/私有/订单边界） | MCP 源码无交易/风控/执行/私有账户导入；只读策略定义；测试断言摘要无金额/仓位/杠杆哨兵；无下单/签名接口 | `test_mcp_infrastructure_is_read_only_...`、`test_strategy_definition_summary_has_no_financial_values` |
| AC-18（旧行为兼容） | 无迁移、无 schema 变更；全量后端回归 1394 passed；旧报告/审计/研究路径未修改 | full 证据、`alembic heads=0027_agent_segments` |

T10 不生成 `TradeIntent`、不访问私有账户、不调用模拟/真实订单服务，也不宣称模型 Tool Calling、真实外部 MCP 或生产工具循环已交付。

## 3. 改动清单与关键取舍

### 3.1 改动清单

**新增源码**
- `backend/src/app/infrastructure/mcp/__init__.py`：包职责说明，不做重导出以避免装配期循环导入。
- `backend/src/app/infrastructure/mcp/registry.py`：端点/协议/工具 Schema 指纹/凭据登记。
- `backend/src/app/infrastructure/mcp/transport.py`：有界 httpx2 transport 与固定 HTTP 客户端构造。
- `backend/src/app/infrastructure/mcp/client.py`：官方 SDK 客户端 + T09 handler + 受控 `call`。
- `backend/src/app/infrastructure/mcp/server.py`：官方 MCP 只读服务、认证、lifespan 与描述符。

**新增测试**
- `backend/tests/mcp/support.py`：真实 loopback uvicorn 启动/关闭与 TCP readiness。
- `backend/tests/mcp/test_compatibility.py`：SDK/协议/依赖锁定、服务只暴露一个工具、上限值。
- `backend/tests/mcp/test_guarded_transport.py`：目标/重定向/计数/JSON/SSE 边界与真实 SDK 路径。
- `backend/tests/mcp/test_local_http.py`：真实 TCP 工具调用、凭据/协议/Schema 漂移、Host、重定向、长文本与财务隔离。
- `backend/tests/tooling/test_mcp_lifespan.py`：session manager 单次生命周期、uvicorn 启停与任务回收。

**修改**
- `backend/pyproject.toml`、`backend/uv.lock`：新增 MCP/httpx2 及传递依赖。
- `backend/src/app/agent/interactive/tools/research_tools.py`：新增公开 `strategy_definition_tool()`，保证 MCP 适配器与 T09 目录描述完全一致。
- `backend/tests/security/test_agent_dependency_boundary.py`：允许 `mcp`/`httpx2`，继续禁止交易/交易所客户端；新增 MCP 源码只读/无交易/无 stdio/sampling/roots/elicitation 断言。
- 根 `AGENTS.md`、`backend/AGENTS.md`、`docs/ai-maintenance.md`、`docs/operational-boundaries.md`、`docs/project-status.md`、实施计划/契约：同步真实边界与未接入状态。

**辅助测试修复**
- `backend/tests/persistence/test_agent_interactions.py`：`_draft()` 的 `expires_at` 从真实当前时间改为仓储固定 `NOW + expires_in`。这是 full 首轮发现的 T06 测试夹具时间炸弹（7 天窗口边界后自发失败），仅测试代码，单独提交 `619fe2c`，未修改生产实现。请审查该辅助提交是否可接受，或要求由 T06 任务独立处理。

### 3.2 关键实现取舍

1. **`McpToolClient.call` 的语义**：计划接口写的是 `McpToolClient.call -> ToolObservation`；T09 最终契约把预算/fence/目录守卫放在 `ToolGateway`。为避免再造一条未守卫路径，`McpToolClient` 的实际 MCP 调用位于 `handle`（T09 `ToolHandler`），公共 `call` 只委托已绑定的 `ToolGateway`，未绑定则抛 `tool_gateway_required`；SDK 使用集中在 `_call_mcp`。这是对计划接口的收敛，不改变 `ToolGateway.call -> ToolObservation` 的公共入口。
2. **固定单工具**：服务只登记 `read_strategy_definition`；`McpToolClient` 构造时拒绝其他工具名，避免成为通用远端工具路由。`build_manual_trade_plan` 仍未登记（待 T14）。
3. **传输层先于 SDK**：SDK 会自行跟随同源 307/308，因此 `BoundedMcpTransport` 在 httpx2 transport 层拒绝所有 3xx；`follow_redirects=False` 只是补充。JSON 响应增量读取，超限立即中止；SSE 单事件通过 SDK `max_sse_event_size` 限制，长连接流仍保持流式。
4. **逐请求计数**：每次实际 `handle_async_request` 检查/增加上限；正常 discover/list/call 计 3 次。这是“每次工具调用”的局部上限，**尚未**接入 C5 任务级传输预算；T11/T14 必须把实际 MCP 请求计入任务总预算。
5. **凭据与描述符分离**：`McpServiceCredential` 用 `SecretStr`；`LocalMcpServiceDescriptor` 不含令牌；`ResearchMcpRuntime` 不公开 credential 属性，提供 `build_client_registry()` 在进程内装配。宿主仍须确保不把 registry/凭据序列化到能力接口或日志。
6. **Host/认证**：服务使用进程内 Bearer 认证中间件，并依赖 SDK `host="127.0.0.1"` 的 DNS rebinding 保护；测试覆盖无凭据 401、未登记 Host 421。内部服务不依赖浏览器会话/CSRF。
7. **lifespan**：`runtime.app` 自带 Starlette lifespan，便于独立 uvicorn 测试；挂载到宿主时宿主必须显式调用 `runtime.lifespan()`（Mount 不会自动运行子应用 lifespan）。SDK manager 每个实例只允许启动一次，重复进入显式失败。
8. **错误降级**：协议/Schema/凭据/传输失败都返回固定安全原因（`mcp_protocol_mismatch`、`mcp_tool_catalog_mismatch`、`mcp_unavailable`、`mcp_redirect_rejected`、`mcp_payload_too_large`、`mcp_transport_limit`、`mcp_timeout`、`mcp_invalid_result`），不向模型/日志回显 URL、令牌或上游正文；未把失败伪装成成功。
9. **依赖边界**：`mcp`/`httpx2` 只用于该适配器，现有 `httpx` 继续服务公开源/模型；未安装 CLI/extras 或遥测 exporter。MCP 传递依赖包含 `opentelemetry-api`（SDK 依赖），但没有配置 exporter、遥测上报或外部连接。
10. **未改 T09 契约**：只在 `research_tools.py` 增加公开工厂，六个工具描述/版本/指纹保持不变；T09 回归继续通过。
11. **协议钉死与异常分级**：`McpToolClient` 在创建 transport 前拒绝任何非 `2026-07-28` 的登记（`last_request_count==0`），协商后再次核对；载荷解析失败映射 `mcp_invalid_result`，未识别异常不再统一降级，而是交给 T09 网关按 `UNKNOWN` 结算；HTTP/SDK 认证/连接错误仍映射 `mcp_unavailable`。

## 4. 公共接口、依赖与迁移影响

### 4.1 新增/修改公共接口

- `registry.py`：`McpServiceCredential`（`from_token`/`generate`/`authorization_header`/`is_authorized`）、`McpToolDescriptor`、`LocalMcpServiceDescriptor`、`McpEndpoint`、`McpEndpointRegistry`、`McpRegistryError`、`mcp_tool_schema_sha256`；常量 `MCP_PROTOCOL_VERSION="2026-07-28"`、`MCP_SERVICE_PATH="/internal/agent-mcp/mcp"`、`MAX_MCP_JSON_BODY_BYTES=65536`、`MAX_MCP_SSE_EVENT_BYTES=65536`、`MAX_MCP_SUMMARY_BYTES=8192`、`MAX_MCP_TRANSPORT_REQUESTS=64`。
- `transport.py`：`BoundedMcpTransport`、`McpTransportError`、`build_http_client`。
- `client.py`：`McpToolClient`（`tool` 属性、`bind_gateway`、`call`、`handle`、`last_request_count`）、`GuardedToolCaller`。
- `server.py`：`ResearchMcpRuntime`（`app`、`lifespan`、`describe`、`build_client_registry`、`server_id`、`port`）、`build_research_mcp(reader, *, port=8000, credential=None, server_id="local_research", clock=None)`。
- `research_tools.py`：新增 `strategy_definition_tool()` 公开工厂；不改变 `RESEARCH_TOOL_NAMES` 或现有目录条目。

### 4.2 依赖

- 新增顶层生产依赖：`mcp==2.3.0`、`httpx2>=2.10.0,<3`。
- 实际锁定：`mcp==2.3.0`、`mcp-types==2.3.0`、`httpx2==2.16.2`、`httpcore2==2.16.2`、`sse-starlette==3.7.0`、`cryptography==50.0.2`、`pyjwt==2.15.1`、`opentelemetry-api==1.45.2`、`pywin32==312` 等；对比 `b80071c` 的 `uv.lock` 仅新增包，LangGraph 1.2.10、checkpoint-postgres 3.1.2、langchain-core 1.5.3 版本未变。
- 未安装 `mcp[cli]`/`mcp[rich]` extras，未新增交易所客户端、CCXT、浏览器或外部 MCP 服务。
- `httpx2` 只限 MCP 适配器；现有 `httpx` 继续服务公开源/模型。

### 4.3 数据库迁移

- **无新增迁移**；未修改旧迁移、业务库或历史报告/审计。
- 迁移 head 仍为 `0027_agent_segments`；`alembic heads` 已核验。
- T10 使用既有 C5 账本/运行快照/fence 进行工具调用；未新增表或字段。full 使用临时 PostgreSQL 17 验证既有迁移链和数据库回归，不迁移业务库。

## 5. 验证记录

### 5.1 环境与证明范围

- 执行目录：`D:/project_git/t10`（根）与 `D:/project_git/t10/backend`。
- 后端锁定环境：`uv sync --locked`，Python 3.12.12；隔离 `.venv`。
- 专用测试库：临时 PostgreSQL 17 容器（Docker 可用），本机回环随机端口、临时数据目录、固定测试库 `crypto_research_test` / 受限角色 `crypto_research_test_runner`；通过 `scripts.check_test_database` 只读身份/权限预检；`TEST_DATABASE_URL` 只在验证进程注入，不记录连接串；验证后停止并删除容器。未指向、迁移或修改任何业务库。
- 验证进程移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`、缺失键的 `GIT_CONFIG_COUNT`；未修改 `.env` 或业务配置。
- 前端未改动；本轮 quick/full 使用 `--component backend`，未执行前端 lint/typecheck/Vitest/build、浏览器 e2e、HTTP e2e 或完整生产 lifespan 装配。
- 未调用真实模型、外部 MCP、私有账户或交易执行；测试使用合成策略/工作台/端口。

### 5.2 测试执行

| 检查 | 目录 | 完整命令 | 退出码 | 实际结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 首轮预期红（缺依赖/模块） | `D:/project_git/t10/backend` | `uv run --locked --no-sync pytest tests/mcp tests/tooling/test_mcp_lifespan.py -q` | 2 | 4 个 collection error（`httpx2`/新模块不存在），符合测试先行预期 | 终端记录 |
| MCP 聚焦（最终） | `D:/project_git/t10/backend` | `uv run --locked --no-sync pytest tests/mcp tests/tooling/test_mcp_lifespan.py -q --basetemp=../.tmp/pytest/t10-focus-final3` | 0 | **27 passed / 0 failed / 0 skipped** | `.tmp/pytest/t10-focus-final3` |
| MCP/安全/交互式阶段（最终） | `D:/project_git/t10/backend` | `uv run --locked --no-sync pytest tests/mcp tests/tooling/test_mcp_lifespan.py tests/security tests/agent/interactive -q --basetemp=../.tmp/pytest/t10-focus-final3` | 0 | **178 passed / 0 failed / 0 skipped** | `.tmp/pytest/t10-focus-final3` |
| 后端 quick（最终） | `D:/project_git/t10` | `uv run --project backend --locked --no-sync python scripts/verify.py quick --component backend --report .tmp/quality/t10-quick-backend-final3.json` | 0 | `verification=passed`；1155 collected / 1155 passed / 0 failed / 0 skipped / 0 collection errors | `.tmp/quality/t10-quick-backend-final3.json` |
| 后端 full 首次（专用 PostgreSQL） | `D:/project_git/t10` | `TEST_DATABASE_URL` 进程注入；`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/t10-full-backend-1.json` | 1 | 1393 collected / 1390 passed / 3 failed；失败均为 `tests/persistence/test_agent_interactions.py` 的 T06 固定时钟夹具问题（非 T10 生产代码） | `.tmp/quality/t10-full-backend-1.json` |
| T06 夹具辅助回归（修复后） | `D:/project_git/t10/backend` | `uv run --locked --no-sync pytest tests/persistence/test_agent_interactions.py -q --basetemp=../.tmp/pytest/t10-interactions-fix` | 0 | 15 passed / 0 failed | `.tmp/pytest/t10-interactions-fix` |
| 后端 full（最终，专用 PostgreSQL） | `D:/project_git/t10` | `TEST_DATABASE_URL` 进程注入；`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/t10-full-backend-final3.json` | 0 | `verification=passed`；1394 collected / 1394 passed / 0 failed / 0 skipped / 0 collection errors | `.tmp/quality/t10-full-backend-final3.json` |
| Ruff / 格式 | `D:/project_git/t10/backend` | `uv run --locked --no-sync ruff check .`；`ruff format --check .` | 0 | All checks passed；395 files already formatted | 终端记录 |
| Pyright | `D:/project_git/t10/backend` | `uv run --locked --no-sync python -m pyright` | 0 | 0 errors / 0 warnings | 终端记录 |
| 架构门禁 | `D:/project_git/t10/backend` | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `status=passed`，`files_scanned=82`，`findings=[]` | 终端记录 |
| 迁移链 | `D:/project_git/t10/backend` | `uv run --locked --no-sync alembic heads` | 0 | `0027_agent_segments (head)` | 终端记录 |
| 文档空白/差异 | `D:/project_git/t10` | `git diff --check` | 0 | 无输出 | 终端记录 |

### 5.3 真实 TCP / SDK 专项覆盖

- **SDK 兼容**：`test_compatibility.py` 断言 `mcp==2.3.0`、`mcp-types==2.3.0`、`httpx2` 2.x、`2026-07-28` 属于 SDK modern protocol 集合；锁定文件检查既有框架版本未变。
- **真实 loopback TCP**：`test_local_http.py` 使用 uvicorn 临时端口；正常路径断言工具实际执行、策略目录读取一次、结果引用绑定当前策略、摘要含方法文本、传输请求数 3。
- **认证/漂移/失败**：错误凭据 401 → 降级 `mcp_unavailable`；Schema 指纹错误 → `mcp_tool_catalog_mismatch` 且不读取策略；协议 2025-11-25 → `mcp_protocol_mismatch` 且 `last_request_count==0`（发送前拒绝）；未登记 Host → 421；重定向 → `mcp_redirect_rejected` 且目标零调用。
- **载荷边界**：默认 JSON 64 KiB 精确通过/多 1 字节拒绝；SSE 单事件超过登记值由 SDK 拒绝；3xx/未登记目标/64 请求上限直接测试。
- **生命周期**：`test_mcp_lifespan.py` 断言 manager 只能启动一次、uvicorn 启停无残留任务、未认证请求 401。

### 5.4 证明边界

- 未执行真实外部 MCP、真实模型、HTTP/SSE 前端、完整生产 `create_app` lifespan、浏览器/HTTP e2e 或业务库迁移。
- T11 模型图、T14 产物/API/生产装配、T15/T16 前端未实现；T10 的真实 TCP 只证明本地只读服务与适配器边界。
- SDK 后台 SSE 重连/重列没有单独构造真实断流场景；每个实际 HTTP 请求的计数和上限由 transport 直接测试，正常路径 3 次请求由真实 TCP 测试证明。若审查要求，可在后续增加断流注入测试。
- 传输上限是每次工具调用的局部上限，**不是** C5 任务级 64 次传输预算；T11/T14 必须接线并补充任务级证据。
- 真实模型质量、抗注入语义、策略收益和产品手动规划均不在 T10 范围。

## 6. 未验证项、已知风险与重点审查位置

### 6.1 未验证/未执行

- T11 模型驱动 LangGraph、原生 Tool Calling、等待/恢复。
- T14 HTTP/SSE API、生产 lifespan/MCP mount、前端投影与完整产物持久化。
- 真实外部 MCP、真实模型、真实模型语义质量、真实新闻 HTTP。
- C5 任务级 MCP 传输预算接线与“实际请求计入任务总预算”的证明。
- SDK 后台 SSE 断流重连的独立故障注入。
- 浏览器 e2e、HTTP e2e、完整 Compose 生产验收。
- 业务库迁移（本轮无迁移）、真实资金/账户/订单。

### 6.2 重点审查位置

1. **`McpToolClient.call` 设计**：确认 `call` 委托已绑定 `ToolGateway`、实际 SDK 调用在 `handle` 是否满足计划接口意图；是否存在未绑定/晚绑定导致绕过预算/fence 的装配风险。
2. **任务级预算**：`max_transport_requests=64` 是每次调用的局部上限；T11/T14 必须把 discover/list/call/重连计入 C5 任务总传输预算，不能只依赖该局部上限。
3. **SDK 内部重试/重连**：transport 是否真的在 SDK 每次实际发送前计数；SSE 后台 GET/重连/重列是否都经过该 transport；正常路径 3 次 POST 的断言是否足以作为证据。
4. **JSON/SSE 边界**：非 SSE 增量读取是否会在异常 content-type/编码下退化为无限缓冲；SSE 总流是否仍缺少总时长/总字节上限；64 KiB 是解码后还是原始字节。
5. **凭据与 Host**：`SecretStr`、公开 descriptor、`build_client_registry` 是否足以避免令牌进入日志/能力接口；内部 Bearer + SDK Host 保护是否覆盖 T14 的 FastAPI mount/Origin 场景。
6. **Schema 指纹**：输入/输出 Schema + 描述进入指纹；SDK 升级或 MCP 输出字段变化会拒绝。确认这是期望的 fail-closed 行为，且 T14 不自动重建目录绕过。
7. **错误映射**：`BaseExceptionGroup` 提取、`CancelledError` 传播、超时/HTTP/协议错误的降级原因是否稳定；是否会把已发送的工具调用误报为“未发送”。
8. **辅助测试修复**：`test_agent_interactions.py` 的 `NOW + expires_in` 是否可接受，或应退回让 T06 独立修复；该提交不在 T10 生产代码内。
9. **文档一致性**：根/后端规范、维护/运行边界、project-status、计划/契约是否准确反映“真实 TCP 模块已实现但未接入模型图/HTTP/生产 lifespan”，不把模块能力写成生产工具循环。
10. **依赖安全**：`mcp`/`httpx2` 允许列表、`mcp` extras/交易所客户端禁止、`opentelemetry-api` 无 exporter、`httpx` 仍在公开源/模型侧使用。

## 7. 自测状态与正式审查状态

- **自测状态：`verified`**。实现与测试已落地；首轮实现 `a9d3b24`、结果/协议加固 `690d726`、辅助测试修复 `619fe2c`；最终 MCP 聚焦 27、MCP/安全/交互式阶段 178、quick 后端 1155、full 后端 1394（专用 PostgreSQL 17）均通过；Ruff/格式/Pyright/架构/迁移链完成。full 首次 3 个失败已定位为 T06 测试夹具固定时钟问题，并以单独测试提交 `619fe2c` 修复；不是 T10 生产逻辑失败。
- **正式审查状态：`awaiting_review`**。尚未收到原审查助手对 T10 当前版本的正式结论；`reviewed_tip` 为空。开发自测、本审查请求和后续子 Agent/本地检查均不能替代该正式结论。
- 本轮不自动进入 T11，不推送、不合并、不部署；等待用户转交审查意见或修复要求。
