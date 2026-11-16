# T08 审查请求：冻结证据、动态上下文与输入控长

- 任务/审查单元：**T08**（D3：冻结上下文、工具守卫、真实 MCP、模型驱动 LangGraph 的首段）。
- 执行模型：DeepSeek `deepseek-flash`（`PI_PROVIDER=deepseek`、`PI_MODEL=deepseek-flash`、`PI_REASONING_LEVEL=max`）；具体模型版本/推理实现未知。
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0。
- 自测状态：`verified`（聚焦、D3 阶段回归、后端 full、Ruff/格式/Pyright/架构门禁/迁移链均完成；详见第 5 节）。
- 正式审查状态：首轮 **`changes_requested`**（R1–R4）；修复后用户于 2026-11-16 传回原审查助手复审结论 **`approved`**（`reviewed_tip=08532dc`）。通过结论不替代独立 full/数据库验收。
- 日期：2026-11-16。

## 1. 工作区、分支与提交范围

| 项目 | 记录 |
| --- | --- |
| 隔离工作区 | `D:\t08`（从 `main` 的 `f331e09` 创建） |
| 分支 | `t08-evidence-context`（未推送、未合并、未部署） |
| base | `f331e09b7d1652060dc03fb792fa65726a11a9bb`（`main`，`docs: record T07 merge into main`） |
| implementation tip | `08532dc8cf15980b70452721384a6600b016f4a0`（`fix: address T08 review findings`；首轮实现 `deec8f2`，边界加固 `96b8270`） |
| implementation tree | `78523029bf0967a377f50ee0f552cba1ddd25d2a` |
| 代码改动范围 | `f331e09..08532dc`，15 个文件，+4682 / -7（`deec8f2` 首轮实现；`96b8270` 边界加固；`08532dc` 正式审查 R1–R4 修复 7 个文件 +505/-15） |
| 审查请求/进度/计划/契约文档 | 在 implementation tip 之后单独提交；文档提交号见交付回复，不改变 implementation tip，避免用自身提交号循环引用 |
| 工作区未提交内容 | 仅本轮审查请求与进度/计划/契约文档；没有夹带其他任务改动、`.env`、凭证或业务库修改 |
| 首轮正式审查报告 | `docs/superpowers/reviews/manual-agent/T08-review-report.md`（`changes_requested`，R1–R4） |
| 复审状态 | `approved`（2026-11-16 用户传回原审查助手复审结论；`reviewed_tip=08532dc`） |
| 复审结论 | R1–R4 关闭，未发现新增阻断项；报告 `T08-review-report.md` 的 `08532dc` 复审段 |

本轮没有修改 `.env`、生产配置、业务数据库、模拟盘资金/风控配置或交易执行链路；未调用真实模型，未访问私有账户，未发起真实交易。

### 1.1 代码文件清单与 SHA-256 指纹

| 文件 | SHA-256 |
| --- | --- |
| `backend/src/app/agent/interactive/__init__.py` | `65d75af2aa009a88afb185b9d76ed58fff8541c6bbbec095ed0c3e9c765365f9` |
| `backend/src/app/agent/interactive/adapters/__init__.py` | `54a4521d81d503a67c77c25b85c799f540b3b0f47eb61075b81f8e173cd5adc1` |
| `backend/src/app/agent/interactive/adapters/research_evidence.py` | `b149c41e53ada71c0b066b43976750db0238a83334c2fad126b95f3d4a1cd3c3` |
| `backend/src/app/agent/interactive/context.py` | `dc0ccf3759150fc51be7baea7b833623ef6d89d99c364a51ec5f1e2bdea02a41` |
| `backend/src/app/agent/interactive/context_budget.py` | `89fe3280088c45c3307f14bed0d26c60d33b21023e997879abcc431593c3d9b6` |
| `backend/src/app/agent_runs/__init__.py` | `56a3dd4a8c641e58b030b9426007a195e0689db2493ea7f8a926a12841d70c3c` |
| `backend/src/app/agent_runs/contracts.py` | `e24aeb5342b05786fefeeb39f4b914d5332d6b0e595b592a9f165df5ae21567a` |
| `backend/src/app/agent_runs/evidence.py` | `cc9970e24a7e95e62be5c4245b58ed1f09050d7c46f185b8f8846ce80bd8e165` |
| `backend/src/app/infrastructure/persistence/agent_run_repository.py` | `d7bf30b3f5922021bd2733809ce846e06446ea62972b2208cbf4c66b9a56c241` |
| `backend/src/app/research/evidence.py` | `1fd66292963267d3ed062c55dcd939b7653366d13b05ac232942d1cc41e35a7e` |
| `backend/tests/agent/interactive/__init__.py` | `e629bd263d58312f20029d6cfc418dbe370ff39ec1228d03709767000ab306b5` |
| `backend/tests/agent/interactive/test_context.py` | `250b1e6f016d52d262355c5d63b31df59f7b5824aa9df5c0f93e9aea25f3b068` |
| `backend/tests/agent/interactive/test_context_budget.py` | `5cb4d9f185f2220c50ae05d52e7352de3f56dd6a365d89dac0e1cf8ebe7cbb41` |
| `backend/tests/agent/interactive/test_evidence_epochs.py` | `4f2160ad5f5c3207a80e61e3db68a418129bf296b95cf5ffdc2abdf8a765e1f8` |
| `backend/tests/persistence/test_agent_evidence.py` | `b8c3f3bad0b0c2a7203e32191996a3dfc6f00e0a10d7081b24bbd08fb1f0d894` |

## 2. 任务范围与 FR/AC/HN 映射

### 2.1 本轮范围

实现 D3 的证据/上下文基础：

- C5 `EvidenceService.freeze(context, *, refresh=False)`：经注入的 `ResearchEvidencePort` 读取受治理公开证据，按计划传输次数走 T05 预算账本，封存 `EvidenceEpoch` 并通过当前 `RunFence` 持久化。
- `ContextBuilder.build(context, evidence, *, applied_seq)`：精确加载所选 `StrategyVersion`，组织 system/task/strategy/authorization/evidence、已应用消息、已验证摘要、知识命中与成对工具轮次；以 `estimate_input(payload)=len(payload)+4096` 保守控长。
- `ContextManifest`：记录版本/引用、证据/消息水位、各块字节数、省略理由和限制码；不复制财务值或原始证据载荷。
- `agent_run_repository`：围栏校验下保存/读取不可变 `agent_evidence_epochs` 与内部 `context_manifest` artifact。
- `MarketResearchEvidencePort` / `MarketEvidenceFactProjector`：适配既有 `PublicMarketGateway.get_market`，保留公开来源质量、逐项时点，并以有界公开事实投影供模型使用。
- `research/evidence.py`：补齐 C5 逐项 `calculation_version`，缺失历史字段不改变旧 epoch 指纹。

本轮**不**实现：T09 工具注册/逐次守卫、T10 MCP/TCP、T11 模型驱动 LangGraph、T12/T13 确定性规划与计划采纳、T14 HTTP/SSE/生产装配、T15/T16 前端、浏览器/HTTP e2e、真实模型质量、业务库迁移或任何真实订单/私有账户能力。

### 2.2 映射

| 需求/不变量 | T08 证明 | 证据 |
| --- | --- | --- |
| FR-04（RAG 与知识治理） | 知识查询按声明截至时刻过滤；首次可得晚于截至的命中被丢弃并记录 `knowledge_filtered`；检索失败不丢所选策略 | `test_context.py::test_historical_context_filters_later_available_knowledge`、`test_knowledge_unavailable_preserves_strategy_and_reports_limitation` |
| FR-05（动态上下文） | 精确策略、必需/可选块优先级、消息水位、摘要证据校验、工具 call/result 整轮裁剪、manifest 版本/长度/省略理由 | `test_context.py` 全部用例；`test_context_evidence` manifest 用例 |
| FR-06（Token 与预算） | 保守输入估算 `len(payload)+4096`；单次上限 16384；初始证据逐次传输预留/发送/结算；预算不足发送前停止 | `test_context_budget.py`、`test_evidence_epochs.py::test_freeze_seals_epoch_and_accounts_for_each_planned_transport_read`、`test_budget_exhaustion_stops_before_public_read` |
| AC-04（RAG 命中/无命中/旧版本） | 无命中仍保留策略；历史不可得命中过滤；知识失败明确限制 | `test_exact_strategy_is_loaded_and_preserved_without_rag_hits`、`test_historical_context_filters_later_available_knowledge` |
| AC-05（上下文超限） | 必需块无法容纳时 `context_budget_exceeded`，不扩大模型窗口；可选块整块省略并记录 | `test_required_strategy_that_exceeds_budget_stops_context`、`test_tool_trimming_keeps_complete_call_result_pairs` |
| AC-14（过期/重大变化） | 未来证据拒绝；过期证据进入 `evidence_stale` 限制；刷新使用新动作序号区段并产生新 epoch | `test_future_evidence_epoch_is_rejected`、`test_stale_evidence_is_marked_as_limitation`、`test_refresh_allocates_new_action_sequence_band` |
| AC-16（数据缺口/模型失败/不编造） | 质量原样保留（stale/missing/invalid），不重分类；无证据旧摘要省略；投影失败记录限制 | `test_stale_quality_is_preserved_not_reclassified`、`test_summary_without_current_evidence_is_omitted` |
| HN-08（消息 recorded/applied） | 新消息必须全部出现才推进 `applied_seq`；缺消息拒绝；旧消息仅作可选上下文 | `test_new_messages_must_all_be_present_before_advancing_watermark` |
| HN-09（精确策略/外部文本不授权） | 目录返回版本与所选引用不一致即拒绝；知识/证据以 `user` 数据块进入，不进入 system 指令 | `test_strategy_version_mismatch_fails_closed`、`test_exact_strategy_is_loaded_and_preserved_without_rag_hits` |
| HN-10（来源/版本/时间） | EvidenceItem 保留 source/observed/available/fetched/quality/calculation_version；epoch 指纹覆盖这些字段；历史模式按 `as_of` 过滤 | `test_evidence_epochs.py`、`test_context.py` 历史/未来/过期用例 |
| HN-14（财务值隔离） | 模型上下文只携带规划版本引用/池代次；测试断言金额/仓位/杠杆字段与 sentinel 不出现 | `test_private_financial_values_and_fields_never_enter_model_context` |

T08 不生成 `TradeIntent`、不访问私有账户、不发送真实订单、不调用模拟订单服务。

## 3. 关键实现取舍

1. **传输预算按计划公开读取次数预留**：`MarketResearchEvidencePort.planned_transport_calls(timeframes)=1+len(timeframes)`（摘要一次、每周期一次）。缓存命中可能高估，但不会低估；T08 不声称已完成逐 HTTP 请求的精确计数，T09/T10 的模型工具/MCP 仍需逐次守卫。初始证据读取使用高位动作序号区段 `1_000_000 + 8 * epoch_count`，避免与后续模型/工具低序号步骤冲突。
2. **读取前后时钟分离**：读取前取 `requested_at` 作为端口“截止候选”，用于拒绝截止后收盘的 K 线；读取完成后重新采样 `sealed_at`，以 `analysis_as_of=sealed_at` 封存。这样不会把正常发生在读取之后的 `fetched_at` 误判为未来证据；若封存时钟早于请求时刻则明确失败。
3. **证据幂等与刷新**：同一 run/revision 已保存 epoch 默认复用，不重复读取；`refresh=True` 才新读，并按已保存 epoch 数推进动作序号区段。历史模式在当前公开端口无法证明历史可得时间时直接拒绝，不把当前行情冒充历史。
4. **Manifest 存储复用既有表**：T08 不新增迁移，`agent_evidence_epochs.document` 保存冻结 epoch，`agent_artifacts` 以 `artifact_type="context_manifest"` 保存内部 manifest。T14 的公开产物投影必须过滤该内部类型，不能把它当业务报告；这是本轮明确的接口约定。
5. **`calculation_version` 条件进入 epoch 载荷**：新证据带逐项计算版本；历史证据缺失时省略该键，保持原 `sha256`/`epoch_id` 可重验，不物化默认值后重算旧指纹。
6. **上下文裁剪只整块省略**：必需 system/task/strategy/authorization/evidence 放不下即停止；可选旧消息/摘要/知识/工具轮次仅整块丢弃并记录 `input_budget`。旧消息按最新优先筛选后插入到新消息之前，保持最终会话时间顺序；工具轮次整轮保留 assistant tool_calls + 对应 tool 结果，不产生孤立 tool 消息。
7. **旧摘要必须绑定当前证据**：`ContextSummary.evidence_ids` 必须全部属于当前 epoch，否则不进入上下文并记录 `unverified_summary`，避免旧观点变成新事实。
8. **财务值只以引用进入**：`RunInput.planning` 只投影 profile/policy/venue/costs 的 `VersionRef` 与池代次；manifest 不保存金额、仓位、杠杆、成交量或订单值。模型上下文的证据块只含公开行情/知识文本。
9. **安全门禁兼容**：当前 `test_agent_source_and_secret_safety.py` 仍把工具关键字字面量视为旧固定研究路径的禁用能力。T08 不启用工具，仅通过 `ModelContext.model_validate(...)` 返回空/已授权 Schema；未修改或放宽安全测试。T09 必须按计划细化门禁，不能把该写法当作工具循环已交付。
10. **边界加固（`96b8270`）**：历史模式检查前移到复用已保存 epoch 之前；`ExecutionContext.evidence_epoch` 改为核对当前 revision 的最新 epoch；`ContextBuilder` 拒绝调用方证据与 `ExecutionContext.evidence_epoch` 不一致、过滤未来摘要、对规划引用去重。
11. **生产历史读取端口尚未实现**：`ContextHistoryReader` 在 T08 是纯协议；`test_context.py` 使用替身验证水位/摘要/工具配对。T11/T14 必须提供 SQL 实现并接线，T08 不宣称生产上下文读取已完整交付。

### 3.1 正式审查 R1–R4 修复

首轮正式审查结论为 `changes_requested`，开发端按报告逐项复现并修复：

| 发现 | 修复与回归 |
| --- | --- |
| R1/P1 传输预算按聚合调用低估实际扇出/重试 | `MarketResearchEvidencePort.planned_transport_calls` 改为 `(3 个摘要端点 + 每周期 1 个 klines 端点) × 网关最大 2 次尝试`，单周期为 8、四周期为 14；`MAX_EVIDENCE_TRANSPORT_CALLS` 调整为 16，刷新区段随之扩大。新增真实 `BinanceUsdmPublicMarketGateway` + `httpx.MockTransport` 用例：每个端点首次 500 后重试，两周期实际 10 次请求 ≤ 预留 10；预算仅 9 次时服务在预留阶段停止，网关请求数为 0。 |
| R2/P2 必需证据投影被 4000 字符静默截断 | 删除 `projected[:4000]` 字符切片；投影器必须生成完整有界事实。事实超过单次消息安全上限时明确 `evidence_projection_too_large`，必需块超出输入预算时 `context_budget_exceeded`。新增 3990 字符后接 `price=12345.67 closeAt=...` 的完整保留测试，以及 20k 投影必须失败的测试。 |
| R3/P2 manifest 未绑定保存围栏 | 保存前比对 manifest 与 fence 的 workspace/run/revision/segment，并在事务内核对引用证据属于同一 workspace/run/revision；读取时同样核对行/文档归属、片段存在性与证据归属。新增跨工作台/运行/修订/片段、跨修订证据、错绑读取和未知片段数据库拒绝测试。 |
| R4/P2 携带已绑定 epoch 时忽略 refresh | 复用路径限定为 `context.evidence_epoch is not None and not refresh`；显式刷新继续走运行校验、新动作序号区段和重新公开读取。新增“已绑定 epoch + refresh”测试，断言新 epoch、公开读取发生、预算区段推进。 |

R1–R4 修复后聚焦 55 passed、D3 阶段回归 422 passed、后端 full `verification=passed；1300 collected / 1300 passed / 0 failed / 0 skipped / 0 collection errors`（`.tmp/quality/manual-agent-t08-fix-full-backend-1.json`）。首轮审查报告见 `docs/superpowers/reviews/manual-agent/T08-review-report.md`；该报告已追加 `08532dc` 复审段。

### 3.2 复审通过

- 2026-11-16 用户传回原审查助手复审结论：**T08 R1–R4 代码审查通过，原四项发现关闭，未发现新的阻断项**；`reviewed_tip=08532dc8cf15980b70452721384a6600b016f4a0`。
- 复审范围 `f331e09..08532dc`，重点对照 `96b8270..08532dc` 修复；报告 `docs/superpowers/reviews/manual-agent/T08-review-report.md` 的 `08532dc` 段为最新结论，首次 `changes_requested` 历史保留。
- 复审端独立运行 `pytest tests/agent/interactive -q` 为 42 passed，并复验四周期真实网关替身预留 14/实际 14；该独立结果不包含 PostgreSQL、422 阶段、1300 后端 full、Pyright 或生产装配，开发端自测记录不冒充审查端独立验收。
- T08 当前为 `verified`/`approved`；按用户指令执行仅本单元的提交、fast-forward 合并到 `main` 并推送。合并 tip `06d5ff7`；本段之后的 docs 提交记录合并/推送结果。

## 4. 公共接口、依赖与迁移影响

### 4.1 新增/修改公共接口

- `agent_runs/evidence.py`：`EvidenceDraft`、`EvidenceCollection`、`ResearchEvidencePort`、`EvidenceFactProjector`、`EvidenceRepository`、`EvidenceService.freeze(context, *, refresh=False) -> EvidenceEpoch`；`EVIDENCE_ACTION_SEQUENCE_BASE=1_000_000`、`MAX_EVIDENCE_TRANSPORT_CALLS=8`、`MAX_EVIDENCE_ITEMS=8`。
- `agent/interactive/context.py`：`ContextBuildError`、`ContextBuilder.build`、`ContextManifest`、`ModelContext`、`ModelMessage`、`ModelToolCall`、`ModelTool`、`ContextBlockKind`、`ContextBlock`、`OmittedContext`、`ContextUserMessage`、`ContextSummary`、`ToolTurn`、`ContextHistory`、`ContextHistoryReader`、`ToolCatalogReader`、`EmptyToolCatalog`、`encode_model_request`；`PROMPT_VERSION="interactive-context-v1"`、`SCHEMA_VERSION="model-context-v1"`、`MAX_EVIDENCE_AGE=15min`。
- `agent/interactive/context_budget.py`：`CONSERVATIVE_PROTOCOL_ENVELOPE=4096`、`MAX_INPUT_UNITS_PER_CALL=16384`、`estimate_input(payload: bytes) -> int`。
- `agent/interactive/adapters/research_evidence.py`：`MarketResearchEvidencePort`、`MarketEvidenceFactProjector`、`MARKET_DETAIL_CALCULATION_VERSION="market_detail_v1"`。
- `agent_runs/contracts.py`：`AgentRunErrorCode` 新增稳定码 `run_state_conflict`（调用方传入未持久化/不属于当前 run 的 EvidenceEpoch 时使用）。
- `research/evidence.py`：`EvidenceItem.calculation_version: str | None`；非空时进入 epoch 指纹，缺失时保持历史哈希。
- `infrastructure/persistence/agent_run_repository.py`：`save_evidence`、`load_evidence`、`load_latest_evidence`、`count_evidence`、`save_context_manifest`、`load_context_manifest`。

### 4.2 依赖

- **无新增生产依赖**；未修改 `pyproject.toml`、`uv.lock`、模型供应商配置或 `.env`。
- 未安装/启用 MCP、向量库、CCXT、付费数据源或真实交易所客户端。

### 4.3 数据库迁移

- **无新增迁移**；复用 `0022_agent_tasks` 已创建的 `agent_evidence_epochs`（不可变 epoch）和 `agent_artifacts`（内部 `context_manifest`）。
- 迁移 head 仍为 `0027_agent_segments`；未修改旧迁移、未回写历史报告/审计/任务、未迁移业务库。
- 读取时重算 epoch 内容/标识/指纹和 manifest 文档 SHA-256；数据库触发器继续禁止 UPDATE/DELETE 历史行。

## 5. 验证记录

### 5.1 环境与证明范围

- 执行目录：`D:\t08`（仓库根）与 `D:\t08\backend`。
- 后端锁定环境：`uv sync --project backend --locked`，Python 3.12；独立 `.venv`，锁定依赖未新增。
- 专用测试库：临时 PostgreSQL 17 容器 `t08-test-postgres`，固定测试库 `crypto_research_test` / 受限角色 `crypto_research_test_runner`；`TEST_DATABASE_URL` 只在验证进程注入，通过 `scripts.check_test_database` 只读身份预检；未指向业务库，未打印连接串。
- **首次 full 环境失败（如实记录，不计为通过）**：初版容器使用 512 MiB tmpfs，full 期间数据库写满并进入恢复失败，导致 204 个数据库用例 setup/call 失败；同时 `python -m pyright` 暴露 `run_state_conflict` 未加入 `AgentRunErrorCode`（已修复）。改用磁盘支持的临时数据目录并重建容器后，最终 full 通过。首次报告 `.tmp/quality/manual-agent-t08-full-backend-1.json` 保留为环境失败证据，未用其冒充最终通过。
- 验证进程移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`、`GIT_CONFIG_COUNT`；未修改 `.env` 或业务配置。
- 测试数据：合成任务、策略版本、知识命中、公开行情、证据和 manifest；无真实财务/账户/模型内容。
- 未调用真实模型、工具、MCP、私有账户或交易执行；未执行前端、浏览器 e2e、http-e2e 或生产 lifespan 验收。
- `.tmp/quality/` 证据是本地未提交产物，不随分支传递；上表给出完整命令，可在专用测试库重跑。首次 full 的失败报告与最终 full 报告分别保留，不能用前者冒充后者。

### 5.2 实际命令与结果

| 检查 | 目录 | 完整命令 | 退出码 | 实际结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 改动前基线 | `D:\t08\backend` | `uv run --locked --no-sync pytest tests/research/strategies tests/research/knowledge tests/agent_runs tests/security -q --basetemp=../.tmp/pytest/t08-baseline-20261113` | 0 | 142 passed | 终端记录 |
| 首轮预期红 | `D:\t08\backend` | `uv run --locked --no-sync pytest tests/agent/interactive tests/persistence/test_agent_evidence.py -q --basetemp=../.tmp/pytest/t08-red-1` | 2 | 4 个 collection error（缺少新模块/符号），退出 2；符合测试先行预期 | 终端记录 |
| 聚焦最终 | `D:\t08\backend` + 专用 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/agent/interactive/test_context.py tests/agent/interactive/test_evidence_epochs.py tests/agent/interactive/test_context_budget.py tests/persistence/test_agent_evidence.py -q --basetemp=../.tmp/pytest/t08-fix-focus-1` | 0 | **55 passed / 0 failed / 0 skipped** | 终端记录 |
| D3 阶段回归 | `D:\t08\backend` + 专用 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/agent/interactive tests/agent_runs tests/research/strategies tests/research/knowledge tests/persistence/test_agent_runs.py tests/persistence/test_agent_attempts.py tests/persistence/test_agent_interactions.py tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py tests/persistence/test_agent_evidence.py tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/persistence/test_migrations.py tests/security tests/governance tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t08-fix-stage-1` | 0 | **422 passed / 0 failed / 0 skipped** | 终端记录 |
| 后端 full（最终） | `D:\t08` + 专用 PostgreSQL 17 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t08-fix-full-backend-1.json` | 0 | `verification=passed`；1300 collected / 1300 passed / 0 failed / 0 skipped / 0 collection errors | `.tmp/quality/manual-agent-t08-fix-full-backend-1.json` |
| 首次 full（环境/类型失败） | `D:\t08` + tmpfs 测试库 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t08-full-backend-1.json` | 1 | `backend-types=1`（`run_state_conflict` 未加入错误码）；`backend-tests=1`（tmpfs 写满导致 204 个数据库用例失败）；修复/重建后最终 full 通过 | `.tmp/quality/manual-agent-t08-full-backend-1.json` |
| Ruff | `D:\t08\backend` | `uv run --locked --no-sync ruff check .` | 0 | All checks passed | 终端记录 |
| 格式 | `D:\t08\backend` | `uv run --locked --no-sync ruff format --check .` | 0 | 377 files already formatted | 终端记录 |
| Pyright | `D:\t08\backend` | `uv run --locked --no-sync python -m pyright` | 0 | 0 errors / 0 warnings | 终端记录 |
| 架构门禁 | `D:\t08\backend` | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `status=passed`，`files_scanned=44`，`findings=[]` | 终端记录 |
| 迁移链 | `D:\t08\backend` | `uv run --locked --no-sync alembic heads` | 0 | `0027_agent_segments (head)` | 终端记录 |

## 6. 未验证项、已知风险与重点审查位置

### 6.1 未验证/未执行

- 真实模型、原生 Tool Calling、LangGraph、真实 MCP/TCP、HTTP/SSE、前端/浏览器、生产 lifespan（T09–T17）。
- 确定性手动计划计算、可实施状态、AP-01/AP-06 采纳与资金池占用（T12–T13）。
- 真实公开源持续可用性、真实产品规则/费率/保证金、真实策略质量与收益。
- 业务库迁移、部署、回退演练；本轮只验证临时测试 schema。
- `ContextHistoryReader` 的 SQL 生产实现：T08 只有协议与替身；T11/T14 必须实现并接线。
- 逐 HTTP 请求的精确传输计数：T08 按公开网关固定扇出与最大重试次数做保守上界预留，缓存命中会高估；T09/T10 的模型工具/MCP 仍需逐请求守卫。
- 前端 lint/typecheck/Vitest/build、浏览器 e2e、http-e2e 均未执行；本轮 full 使用 `--component backend`。

### 6.2 重点审查位置

1. **证据预算与时钟**：`agent_runs/evidence.py` 的 `freeze` 是否在读取前完成全部 `reserve`/`mark_sent`，读取异常是否按 `unknown` 保守保留，`sealed_at` 是否在读取后采样，`refresh` 是否使用新动作序号区段，已保存 epoch 是否可被跨 run 复用。
2. **围栏与锁序**：`agent_run_repository._lock_live_fence` 是否在任务行锁后读取数据库时钟并锁片段，是否核对 owner/lease_epoch/revision/namespace/取消标记，是否与 T07 的锁序一致；证据/manifest 是否跨工作台隔离、读取时重算指纹。
3. **上下文优先级与裁剪**：`context.py` 必需块是否真的不可裁剪，新消息是否全部进入，旧消息顺序是否保持时间顺序，摘要/知识/工具轮次是否整块省略，是否存在孤立 tool 消息或超过 16384 的漏检路径。
4. **Manifest 归属与最小化**：保存/读取是否核对 workspace/run/revision/segment 与引用证据归属；`ContextManifest` 与内部 `context_manifest` artifact 是否只含引用/长度/水位/原因，是否可能泄漏金额、仓位、杠杆、原始证据或用户财务文本；T14 是否会误投影内部类型。
5. **历史/过期语义**：`EvidenceService` 是否拒绝历史模式；`ContextBuilder` 是否以 `analysis_as_of`/`sealed_at` 和声明 `as_of` 过滤知识/证据；过期证据是否只标记限制而不改写为当前事实。
6. **安全门禁兼容**：`ModelContext.model_validate(...)` 传空工具 Schema 是否只是 T08 的兼容构造，而非绕过门禁；T09 是否按计划细化 `tools=` 禁词并保留旧固定路径隔离。
7. **新增错误码**：`run_state_conflict` 是否确实用于“调用方传入未持久化/不属于当前 run 的 epoch”，是否应复用既有错误码而非新增公共枚举值。
