# 实盘手动计划 Agent 开发进度

- 记录日期：2026-11-17
- 文档基线：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0。
- 状态口径：`implemented` 表示代码、文档和自测已落地；`verified` 表示本轮必需验证完成；`approved` 只能记录用户传回的原审查助手正式结论。T00–T05 的 `verified` 与 `approved` 已按用户传回的正式审查结论记录；T06 已完成实现、F1 修复、聚焦/SQL/阶段/静态检查和后端 full，自测为 `verified`；用户于 2026-11-12 传回原审查助手正式通过结论（`reviewed_tip=dea9848`），当前为 `approved`。T07 首轮正式审查 R1/P1 不通过（worker 取消后执行器未停止）；R1 修复后原审查助手于 2026-11-12 复审通过（`reviewed_tip=ec3e8e5`），当前为 `verified`/`approved`。T08 已实现冻结证据、动态上下文、内部 manifest 持久化与公开行情证据适配器；首轮正式审查 `changes_requested`（R1–R4），修复后聚焦 55、D3 阶段 422、后端 full 1300 passed，自测为 `verified`；2026-11-16 用户传回原审查助手复审通过，当前为 `approved`（`reviewed_tip=08532dc`）。T09 已实现 C6 工具契约、不可变目录、逐次网关与六个只读研究工具；首轮正式审查提出 1 P1 + 4 P2，修复 tip `063e8a3` 后开发聚焦 108、交互式 87、阶段 307、quick 后端 1127 passed；审查阶段独立 PostgreSQL 验证 C5/片段/恢复 33、SQL 网关 14、后端 full 1366 passed。2026-11-17 用户传回原审查助手正式通过结论（`reviewed_tip=063e8a3`），当前为 `verified`/`approved`。T10 首轮 `690d726` 判定 `changes_requested`；R1/R2 修复到 `b5509ac` 后用户于同日传回复审通过结论（`reviewed_tip=b5509ac`），当前为 `verified`/`approved`。T11 已实现模块级原生 Tool Calling、C5 预算包装、T09 工具观察回路、准备态人工等待与 `AnalysisArtifactStager` 协议；首轮 `changes_requested` 3 项及二次复审 R1/R2 剩余问题均已修复，原审查助手于 2026-11-17 复审通过（`reviewed_tip=7c1f336`、`reviewed_tree=dacff63`），当前为 `verified`/`approved`；不自动进入 T12。
- 审查口径：`review_status` 由开发执行者维护；`approved` 只能由用户传回原审查助手的正式结论，不能自行填写。T07/T08 已批准；T09 首轮审查的 1 P1 + 4 P2 已修复，用户于 2026-11-17 传回正式通过结论（`reviewed_tip=063e8a3`），当前为 `approved`。T10 首轮正式审查对象 `690d726` 结论为 `changes_requested`（R1/P1 参数化 Content-Type 绕过上限、R2/P2 非 ASCII 鉴权头 500）；R1/R2 修复到 `b5509ac` 后，用户于 2026-11-17 传回原审查助手正式通过结论（`reviewed_tip=b5509ac`），当前 `verified`/`approved`。T11 的 `review_status` 为 `approved`（2026-11-17 用户传回原审查助手正式通过结论；`reviewed_tip=7c1f336`、`reviewed_tree=dacff63`）；开发自测不替代正式审查。

## 当前工作区（T11）

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:/project_git/crypto_ai_agent_trade_system`（`main` 已 fast-forward 合并 T11，合并 tip `6a9ed12`；本 docs 提交记录结果） |
| 隔离工作区 | `D:/project_git/t11`（分支 `t11-model-graph`，从 `main` 的 `c45640e` 创建；已 fast-forward 合并到 `main`，未推送/部署） |
| base | `c45640e51b6473f42126ac3dea9ae76536124fef`（`main`，`docs: record T10 merge into main`） |
| implementation tip | `7c1f33660f91e0df8c170533ee8f17f222836249`（`fix: close remaining T11 activity and response bounds`；前序修复 `e0bc26e`，首轮受审 `d1e3560` / tree `5c78429`） |
| implementation tree | `dacff63ed8deee4e707c4a32826c82a90cb3e987` |
| 合并 tip | `6a9ed12a1742f21c8dd3c8dc2bfda11c89716ff7`（`docs: record T11 approval`；fast-forward 到 `main`，本 docs 提交记录结果） |
| 累计代码/文档范围 | `c45640e..7c1f336`，19 个文件，+4098/-26（含 T11 代码、测试、规范/计划/状态同步） |
| self_test | `verified`（新增 36；交互式/安全/治理 242；SQL/恢复 250；T07 恢复 15；quick 后端 1196；D3 full 1435 passed） |
| review_status | `approved`（2026-11-17 原审查助手复审通过） |
| reviewed_tip | `7c1f33660f91e0df8c170533ee8f17f222836249` |
| reviewed_tree | `dacff63ed8deee4e707c4a32826c82a90cb3e987` |
| 审查请求 | `docs/superpowers/reviews/manual-agent/T11-review-request.md`（本次 docs 提交生成） |
| 文档提交 | 见最终交付回复；不把 docs 自身提交号写入 implementation tip |
| 证据 | `.tmp/quality/manual-agent-d3-full.json`、`.tmp/quality/t11-final-quick-backend.json`、`.tmp/pytest/t11-*` |

### T09 工作区（历史）

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main` 已合并 T09；合并 tip `2df4bf0`，本 docs 提交记录合并结果；工作区干净） |
| 隔离工作区 | `D:\t09`（从 `main` 的 `36cda45` 创建） |
| 分支 | `t09-tool-gateway`（未推送、未部署；已合并到 `main`） |
| base | `36cda455670713f3ffaee18655c4d59113a90b22`（`main`，`docs: record T08 merge into main`） |
| 首轮受审 tip | `2674f1692d09217daea008a6999d49b291383914`（`feat: guard registered agent tool calls`） |
| implementation tip | `063e8a3a8f099540e89dce890b76748cd7fcb02c`（`fix: address T09 review findings`） |
| tree | `1fca46491d2e39ccb4649357c0ce40b32d851258` |
| 修复范围 | `81018be..063e8a3` 5 个文件，+310/-31（1 P1 + 4 P2） |
| 累计代码范围 | `36cda45..063e8a3` 21 个文件，+4668/-40（含首轮代码、docs 包与修复） |
| self_test | `verified`（开发聚焦 108、交互式 87、阶段 307、quick 1127；独立 PostgreSQL 33+14、后端 full 1366 passed） |
| review_status | `approved`（2026-11-17 用户传回原审查助手正式结论） |
| reviewed_tip | `063e8a3a8f099540e89dce890b76748cd7fcb02c`（首轮 R1–R5 修复版本） |
| SQL 验证 tip | `a9d19dfab7991d319c5dcc35e0312ef39e6f5980`（`test: record T09 postgres gateway verification`） |
| 合并 tip | `2df4bf0f0922032da9bc9e43a067283ad931aa5b`（fast-forward 到 `main`；本 docs 提交记录结果） |
| 审查请求 | `docs/superpowers/reviews/manual-agent/T09-review-request.md` |
| 文档提交 | 首轮审查包 `81018be`；修复复审包 `3c458ba`；SQL 验证测试提交 `a9d19df`；审批文档提交号见最终交付回复 |
| quick 证据 | `.tmp/quality/t09-review-fix-quick-backend.json`（开发环境 `verification=passed`，1127 passed） |
| SQL/full 证据 | `docs/superpowers/reviews/manual-agent/T09-sql-verification.md`、`.tmp/quality/t09-sql-full-20261117.json`（独立 PostgreSQL 环境，full 1366 passed） |
| T10 隔离工作区 | `D:/project_git/t10`（从 `main` 的 `b80071c` 创建；分支 `t10-mcp-transport`；未推送/合并/部署） |

## T00：治理内核与规范迁移（D0）

| 项目 | 记录 |
| --- | --- |
| 任务 | T00；后端 `app/harness/` → `app/governance/`，公共类型改为 Governance/Governed 命名 |
| FR/AC/HN | AC-18；HN-01、HN-12（门禁仍拒绝交易/外部 IO/空扫描）；支撑 FR-03/FR-12 的治理内核路径，不宣称新增业务能力 |
| 时间 | 2026-11-07；初始实现 `63b1202`，复审修复 `f870de1` |
| 任务状态 | `verified`（实现、full、数据库回归及复审均完成） |
| review_status | `approved` |
| reviewed_tip | `f870de1`（用户于 2026-11-07 传回原审查助手正式通过结论） |
| 改动 | 7 个治理模块迁移；4 个测试迁移；24 个导入/装配/安全测试文件更新；3 份 AGENTS、3 份运行/维护/状态文档同步；契约/实施计划/设计的当前实施状态注记；新增治理门禁、序列化兼容及拒绝日志兼容测试 |
| 公共接口 | 仅 Python 导入路径和公共类型名改变；HTTP 错误码、审计表/事件值、`HarnessAudit*` 类型、`harness_*` 日志事件名与拒绝日志 `error_type` 值保持不变 |
| 依赖/迁移 | 无新增依赖；无 schema 变更；迁移 head 仍为 `0018_technical_report_runs` |
| 验证 | 治理/安全聚焦 114 passed；架构门禁 35 文件 0 findings；quick 全绿（后端 918 passed，前端 332 passed）；带专用测试库 full 全绿（后端 1017 passed）；旧报告/审计 SQL 聚焦回归 34 passed |
| 未验证 | 浏览器 e2e/http-e2e、真实模型质量、产品规则/收益 |
| 遗留 | T00 已通过正式复审并放行；不自动进入 T01，等待用户指定下一审查单元 |

### T00 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 迁移前基线 | `backend/` | `uv run --locked --no-sync pytest tests/harness tests/security -q --basetemp=../.tmp/pytest/t00-baseline-20261107` | 111 passed，退出 0 |
| 首轮预期红 | `backend/` | `uv run --locked --no-sync pytest tests/security/test_architecture_gate.py::test_governance_gate_rejects_trade_io_and_empty_scan tests/harness/test_contracts.py::test_governance_run_kind_serialized_values_remain_stable -q --basetemp=../.tmp/pytest/t00-red-20261107` | 2 failed，退出 1；失败原因符合预期 |
| 复审 P2 预期红 | `backend/` | `uv run --locked --no-sync pytest tests/governance/test_runtime.py::test_rejection_log_keeps_historical_harness_error_type -q --basetemp=../.tmp/pytest/t00-p2-red-20261107` | 1 failed，退出 1；实际日志为 `GovernancePolicyViolation`，断言要求历史值 |
| 聚焦绿 | `backend/` | `uv run --locked --no-sync pytest tests/governance tests/security -q --basetemp=../.tmp/pytest/t00-p2-green-20261107` | 114 passed，退出 0 |
| 架构门禁 | `backend/` | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=35`，`findings=[]`，退出 0 |
| 静态检查 | `backend/` | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 全部通过 |
| quick（最终代码） | 仓库根目录 | `uv run --project backend --locked --no-sync python scripts/verify.py quick --report .tmp/quality/manual-agent-t00-quick-final.json` | `verification=passed`；后端 918 passed / 0 failed / 0 skipped；前端测试通过；**quick 不执行前端构建** |
| full（专用测试库） | 仓库根目录 | `uv run --project backend --locked --no-sync python scripts/verify.py full --report .tmp/quality/manual-agent-t00-full-with-db-final.json` | `verification=passed`；后端 1017 passed / 0 failed / 0 skipped；含前端 build；证据 `.tmp/quality/manual-agent-t00-full-with-db-final.json` |
| 旧报告/审计 SQL 聚焦回归 | `backend/` | `uv run --locked --no-sync pytest tests/persistence/test_harness_audit_repository.py tests/persistence/test_agent_research_repository.py tests/persistence/test_report_repository.py tests/persistence/test_technical_report_repository.py tests/persistence/test_migrations.py tests/persistence/test_comprehensive_research_capture_history.py tests/persistence/test_research_flow_evaluation_history.py -q --basetemp=../.tmp/pytest/t00-db-regression-final-20261107 -p scripts.pytest_summary --quality-summary ../.tmp/quality/t00-db-regression-final.json` | 34 passed / 0 failed / 0 skipped；证据 `.tmp/quality/t00-db-regression-final.json` |
| 迁移链 | `backend/` | `uv run --locked --no-sync alembic heads` | `0018_technical_report_runs (head)`，退出 0 |
| 文档链接 | 仓库根目录 | 本地 Markdown 相对链接扫描（AGENTS/维护/运行/项目状态/复审材料） | 全部可解析 |

### 环境说明

- 验证进程继承宿主的生产环境变量（仅列变量名：`APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`）以及缺失键的 `GIT_CONFIG_COUNT`。为复现项目测试默认值，只在验证进程内移除这些变量，未修改 `.env` 或业务配置。
- 前端测试另设 `NODE_ENV=test`；宿主默认的 `production` 会让 React `test-utils` 走生产构建并报 `React.act is not a function`。
- 专用测试库为临时 PostgreSQL 17 容器（tmpfs、本机回环端口、随机/临时凭据），通过项目 `check_test_database` 身份与权限预检后使用；未指向业务库，未修改业务库。验证完成后回收容器与临时数据。
- 首轮带库 full 曾因宿主残缺的 `GIT_CONFIG_COUNT` 让 `git check-attr` 测试误失败；清理该变量后重跑为 1017 passed，代码本身未因该测试失败修改。
- 未调用真实模型、未访问私有账户、未修改业务库、未发起真实交易请求。

## T01：策略包版本与已有规则评估（D1）

| 项目 | 记录 |
| --- | --- |
| 任务 | T01；公共版本引用/证据 epoch、版本化策略目录、参数白名单、只读评估器端口与既有技术规则适配 |
| FR/AC/HN | FR-10；支撑 FR-09 的候选/版本绑定；AC-07、AC-08、AC-09、AC-28；HN-09、HN-10。未实现 FR-04/FR-14/FR-15/FR-16，不宣称完整规划或知识检索 |
| 时间 | 2026-11-08 |
| 任务状态 | `verified`（实现、复审修复、聚焦、SQL 并发回归和后端 full 已完成；不等于正式审查通过） |
| review_status | `approved`（用户于 2026-11-08 传回原审查助手正式通过结论） |
| reviewed_tip | `159a43be3822e6f0fcbd314da67719187c06e610` |
| 改动 | 首轮 17 个文件；复审修复 8 个文件（并发 request_id 串行化、嵌套输入快照/重验、根 Schema object 校验及回归测试） |
| 公共接口 | `VersionRef`、`ArtifactRef`、`ProductKey`、`DecimalText`、`PageQuery`/`VersionPage`；`EvidenceEpoch`/`EvidenceItem`；`StrategyDraft`/`StrategyVersion`/`PriceCandidate`/`StrategyEvaluation`；`StrategyCatalog`/`StrategyEvaluator`/`StrategyService`；`TechnicalStrategyEvaluator`；`SqlAlchemyStrategyCatalog` |
| 依赖/迁移 | 无新增依赖；新增前向迁移 `0019_strategy_catalog`（strategy_definitions/strategy_versions/strategy_catalog_requests 与发布不可变触发器）；迁移 head 为 `0019_strategy_catalog`；未迁移业务库 |
| 验证 | 修复前纯回归 6 failed / 15 passed、SQL 并发 3 failed / 7 passed；修复后纯+既有引擎 69 passed；SQL+迁移 27 passed；后端 full 1049 passed / 0 failed / 0 skipped；架构门禁 38 文件 0 findings；静态检查全绿 |
| 未验证 | 前端、HTTP API、浏览器 e2e、真实模型质量、真实知识/RAG、T12+ 规划计算、T03/T18 产品规则、业务库迁移；未执行真实策略算法或收益评估 |
| 遗留 | T01 已通过正式复审并以 fast-forward 合并到 `main`；不自动开始 T02，等待用户指定下一审查单元 |

### T01 复审修复（第 2 轮）

| 审查问题 | 修复与回归 |
| --- | --- |
| P1 并发相同 request_id 未可靠返回原成功结果 | 四个写方法在业务读取前获取 `pg_advisory_xact_lock(hashtextextended(request_id, 0))` 事务锁，同请求串行化后重读幂等记录；请求结果与业务变更同事务提交。新增真实 PostgreSQL 双会话 + 外部行锁同步点的 publish/update/archive/create 并发测试，以及同键不同内容/操作/工作台拒绝测试。 |
| P1 封存证据/发布策略嵌套内容可修改且旧指纹继续生效 | 证据内容、epoch items、策略 Schema、组成参数在模型边界深拷贝；新增 `EvidenceEpoch.validated_snapshot()` 与 `StrategyVersion.validated_snapshot()` 重验内容/epoch/正文哈希；服务和适配器在消费前取隔离快照；`from_draft` 深拷贝并重校验。新增内容篡改、原始输入/草稿修改隔离、服务拒绝被改发布版本的回归。 |
| P2 参数 Schema 根节点未强制为 object | `validate_parameter_schema()` 根入口强制 `type == "object"`；string/array/decimal/integer/boolean 根均拒绝，合法 object 根和嵌套类型继续通过。 |


### T01 复审结论

- 2026-11-08 用户传回原审查助手正式通过结论；`reviewed_tip` 为 `159a43be3822e6f0fcbd314da67719187c06e610`，审查请求中的正式状态已改为 `approved`。
- T01 代码与复审文档以 fast-forward 从 `e12de3a` 合并到 `main`；本条状态记录是合并后的 docs 提交，具体 hash 见最终回复。
- T01 状态为 `verified`/`approved`。不自动开始 T02；下一审查单元须等待用户明确指定。

### T01 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 首轮基线 | `backend/` | `uv run --locked --no-sync pytest tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t01-baseline-20261108` | 48 passed，退出 0 |
| 首轮预期红（缺模块） | `backend/` | `uv run --locked --no-sync pytest tests/research/strategies tests/persistence/test_strategy_catalog.py -q --basetemp=../.tmp/pytest/t01-red-20261108` | 3 collection errors（缺少新模块），退出 1；符合预期 |
| 修复前纯回归红 | `backend/` | `uv run --locked --no-sync pytest tests/research/strategies/test_catalog.py tests/research/strategies/test_evaluator.py -q --basetemp=../.tmp/pytest/t01-fix-red-pure-20261108` | 6 failed / 15 passed，退出 1；根 Schema、嵌套可变性、服务快照用例失败，符合预期 |
| 修复前 SQL 并发红 | `backend/` | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_strategy_catalog.py -q --basetemp=../.tmp/pytest/t01-fix-red-db-20261108` | 3 failed / 7 passed，退出 1；publish/update/archive 并发重放失败，符合预期 |
| 修复后纯契约/评估器 + 既有引擎 | `backend/` | `uv run --locked --no-sync pytest tests/research/strategies tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t01-fix-pure3-20261108` | 69 passed，退出 0 |
| 修复后 SQL 目录 + 迁移链 | `backend/` | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_strategy_catalog.py tests/persistence/test_migrations.py -q --basetemp=../.tmp/pytest/t01-fix-db4-20261108` | 27 passed，退出 0；含双会话并发、内容篡改、根 Schema、发布不可变 |
| 后端 full（修复后最终代码） | 仓库根目录 | 临时 PostgreSQL 17 + `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t01-fix-full-backend-final.json` | `verification=passed`；后端 1049 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t01-fix-full-backend-final.json` |
| 架构门禁 | `backend/` | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=38`，`findings=[]`，退出 0 |
| 静态检查 | `backend/` | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 全部通过，退出 0 |
| 迁移链 | `backend/` | `uv run --locked --no-sync alembic heads` | `0019_strategy_catalog (head)`，退出 0 |

### 环境说明

- 验证进程继承宿主的生产环境变量（仅列变量名：`APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`）以及缺失键的 `GIT_CONFIG_COUNT`。为复现项目测试默认值，只在验证进程内移除这些变量，未修改 `.env` 或业务配置。
- 专用测试库为临时 PostgreSQL 17 容器（tmpfs、本机回环随机端口、随机临时凭据），通过项目 `check_test_database` 身份与权限预检后使用；未指向业务库，未修改业务库。验证完成后回收容器与临时数据。
- 首次后端 full 因宿主 `CORS_ALLOWED_ORIGINS` 覆盖默认开发来源而失败 1 项；清理该变量后重跑修复前 full 为 1037 passed、修复后 full 为 1049 passed。代码未因该环境覆盖修改。
- 前端未在本轮改动；本轮 full 使用 `--component backend`，未执行前端 lint/typecheck/Vitest/build，也未执行浏览器 e2e 或 http-e2e。
- 未调用真实模型、未访问私有账户、未修改业务库、未发起真实交易请求。

## T02：可用的关键词 RAG（D1）

| 项目 | 记录 |
| --- | --- |
| 任务 | T02；版本化关键词知识库、确定性分块/词项/评分、GIN 检索、请求幂等、归档与历史可得性 |
| FR/AC/HN | FR-04；AC-04、AC-05（本轮只交付检索与引用基础，上下文裁剪/预算在 T08/T09）；HN-09、HN-10。未实现 FR-05 的上下文管理、T08/T09 工具循环或真实知识质量评估 |
| 时间 | 2026-11-09；首轮实现 `ed8e887`，复审修复 `8835a1d` |
| 任务状态 | `verified`（实现、复审修复、聚焦、迁移/并发回归、静态检查和后端 full 已完成） |
| review_status | `approved`（用户于 2026-11-09 传回原审查助手正式通过结论） |
| reviewed_tip | `8835a1deb5e4056a98a6e1a2a5f6e2f3e39e0bb9` |
| 改动 | 首轮 13 个文件，+3067 / -0；复审修复 5 个文件，+744 / -33（分块 INSERT 防护、锁后时间采样、发布/检索一致性校验及回归测试） |
| 公共接口 | `KnowledgeImport`、`KnowledgeVersion`、`KnowledgeQuery`、`KnowledgeHit`、`KnowledgeStatus`、`KnowledgeAccess`；`KnowledgeIndex`、`KnowledgeService`；`tokenize`、`chunk_text`、`chunk_at`、`chunk_id_for`、`prepare_chunks`、`score_chunk`；`SqlAlchemyKnowledgeIndex` |
| 依赖/迁移 | 无新增依赖；新增前向迁移 `0020_research_knowledge`（knowledge_documents/versions/chunks/index_requests、词项 GIN、正文/分块 UPDATE/DELETE 与 INSERT 防护触发器）；迁移 head 为 `0020_research_knowledge`；未迁移业务库 |
| 验证 | 复审修复前 7 failed / 15 passed（新回归精确暴露 P1/P2）；修复后聚焦 40 passed；阶段回归 136 passed；后端 full 1089 passed / 0 failed / 0 skipped；架构门禁 38 文件 0 findings；静态检查全绿 |
| 未验证 | 前端、HTTP API、浏览器 e2e、真实模型质量、真实知识库召回质量、T08/T09 上下文与工具接入、T03/T18 产品规则、业务库迁移；未执行真实策略算法或收益评估；未宣称严格数据库提交时可得 |
| 遗留 | T02 已通过正式复审并以 fast-forward 合并到 `main`；不自动开始 T03，等待用户指定下一审查单元 |

### T02 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 首轮预期红（缺模块） | `backend/` | `uv run --locked --no-sync pytest tests/research/knowledge tests/persistence/test_knowledge_index.py -q --basetemp=../../.tmp/pytest/t02-red-20261109` | 3 collection errors（缺少新模块），退出 1；符合预期 |
| 纯契约首轮（测试断言修正） | `backend/` | `uv run --locked --no-sync pytest tests/research/knowledge -q --basetemp=../../.tmp/pytest/t02-pure1-20261109` | 12 passed / 3 failed，退出 1；失败为中文双字词计数、分块长度和 4:1 评分期望写错，已修正测试断言，非实现缺陷 |
| 纯契约复跑 | `backend/` | `uv run --locked --no-sync pytest tests/research/knowledge -q --basetemp=../../.tmp/pytest/t02-pure2-20261109` | 15 passed，退出 0 |
| 聚焦绿（含真实 SQL） | `backend/` | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/research/knowledge tests/persistence/test_knowledge_index.py -q --basetemp=../../.tmp/pytest/t02-fourth-green-20261109` | 30 passed，退出 0；首轮实现证据，含请求并发、历史时点、范围/工作台、六块上限、内容去重 |
| 复审修复前红 | `backend/` | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_knowledge_index.py -q --tb=short --basetemp=../../.tmp/pytest/t02-fix-red-20261109` | 7 failed / 15 passed，退出 1；发布后追加、锁等待时间、伪造命中、插入/发布并发和缺失分块集合用例失败，符合预期 |
| 复审修复后聚焦 | `backend/` | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/research/knowledge tests/persistence/test_knowledge_index.py -q --basetemp=../../.tmp/pytest/t02-fix-green5-20261109` | 40 passed，退出 0；含追加拒绝、触发器等锁、伪造命中拒绝、分块集合校验和锁后时间采样 |
| 复审修复后阶段回归 | `backend/` | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/research/knowledge tests/research/strategies tests/persistence/test_knowledge_index.py tests/persistence/test_migrations.py tests/persistence/test_strategy_catalog.py tests/agent/test_technical_engine.py -q --basetemp=../../.tmp/pytest/t02-fix-stage2-20261109` | 136 passed，退出 0；含 T01 策略目录、迁移链和既有技术引擎回归 |
| 复审修复后后端 full | 仓库根目录 | 临时 PostgreSQL 17 + `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t02-fix2-full-backend.json` | `verification=passed`；后端 1089 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t02-fix2-full-backend.json` |
| 架构门禁 | `backend/` | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=38`，`findings=[]`，退出 0 |
| 静态检查 | `backend/` | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 全部通过，退出 0 |
| 迁移链 | `backend/` | `uv run --locked --no-sync alembic heads` | `0020_research_knowledge (head)`，退出 0 |

### T02 复审修复（第 2 轮）

| 审查问题 | 根因 | 修复与回归 |
| --- | --- | --- |
| P1 已发布版本仍可追加分块 | `knowledge_chunks` 触发器只覆盖 UPDATE/DELETE；发布路径未核对完整分块集合；检索只校验分块自身哈希，没有绑定版本正文切片和稳定块 ID | 新增 `BEFORE INSERT` 防护：先对父版本 `FOR KEY SHARE`（与 publish 的 `FOR UPDATE` 串行化），拒绝非 draft 父版本、跨工作台、越界序号、与版本正文切片不一致的正文和不匹配 SHA-256。publish 在版本行锁内执行 `_verify_chunk_set`，逐块核对数量、序号、稳定 ID、正文、指纹、词项、标题词项和工作台；search 的 `_row_to_hit` 重新核对版本正文切片、块 ID、工作台和词项。回归覆盖发布后追加、强制发布后未占用范围内序号、插入等待发布锁、并发插入后缺失集合、以及触发器被绕过时伪造命中拒绝。 |
| P2 锁等待之前采样发布时间 | import/publish/archive 在事务和业务行锁之前调用 `_now()`，等锁时间被保存为可得/发布/归档时间 | 把时间采样移到请求锁、版本/文档行锁和分块集合校验之后、首次状态写入之前；`first_available_at`、`published_at`、`archived_at` 均使用锁后时间。回归用受控版本/文档行锁等待 5 分钟：等待期间的历史截止点不得在发布后追溯命中，import/archive 时间同样验证。`published_at` 是发布决策时间而非 PostgreSQL 提交时间；采样到提交的极短窗口不宣称严格提交时可得。 |

迁移兼容：`0020_research_knowledge` 仍在 T02 未合并分支，未应用到任何业务库；审查方此前也未进行数据库实测。因此复审修复直接补齐 `0020` 的分块 INSERT 防护，不新增 `0021`、不改变迁移 head。若某个临时 schema 已执行旧版 `0020`，重建该临时 schema 即可；业务库没有需要前向修补的已应用迁移。

### T02 复审结论

- 2026-11-09 用户传回原审查助手正式通过结论；`reviewed_tip` 为 `8835a1deb5e4056a98a6e1a2a5f6e2f3e39e0bb9`，审查请求中的正式状态已改为 `approved`。
- T02 代码与复审文档以 fast-forward 从 `fed38bd` 合并到 `main`；本条状态记录是合并后的 docs 提交，具体 hash 见最终回复。
- T02 状态为 `verified`/`approved`。不自动开始 T03；下一审查单元须等待用户明确指定。

### 环境说明

- 验证进程继承宿主的生产环境变量（仅列变量名：`APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`）以及缺失键的 `GIT_CONFIG_COUNT`。为复现项目测试默认值，只在验证进程内移除这些变量，未修改 `.env` 或业务配置。
- 专用测试库为临时 PostgreSQL 17 容器（tmpfs、本机回环随机端口、仅容器内 trust 认证、受限角色 `crypto_research_test_runner`），通过项目 `check_test_database` 身份与权限预检后使用；未指向业务库，未修改业务库。验证完成后回收容器与临时数据。
- 前端未在本轮改动；本轮 full 使用 `--component backend`，未执行前端 lint/typecheck/Vitest/build，也未执行浏览器 e2e 或 http-e2e。
- 未调用真实模型、未访问私有账户、未修改业务库、未发起真实交易请求；未接收真实用户知识资料。

## T03：规划资料、政策与受支持产品规则（D1）

| 项目 | 记录 |
| --- | --- |
| 任务 | T03；C3 本地财务资料/风险政策/成本/保证金证据/公开规则快照、单池 generation、请求幂等、BTC/ETH USDT 线性永续逐仓支持目录与 `0021_planning_inputs` 迁移 |
| FR/AC/HN | FR-14、FR-15；AC-21 至 AC-25、AC-29、AC-30 的输入/规则/时效基础；HN-13、HN-14、HN-15。T03 不实现完成数量/风险/保证金计算、可实施状态、采纳占用或释放流程，这些仍由 T12/T13 完成 |
| 时间 | 2026-11-09 至 2026-11-10 |
| 任务状态 | `verified`（实现、三轮修复、聚焦、阶段回归、迁移/并发回归、静态检查、后端 full 和正式复审均已完成） |
| review_status | `approved`（用户于 2026-11-10 传回原审查助手正式通过结论） |
| reviewed_tip | `8d75a7a14471c36e4a168c166e3f94b659ceb9e7` |
| implementation tip | `8d75a7a14471c36e4a168c166e3f94b659ceb9e7`（`fix: replay legacy T03 profile requests`） |
| tree | `f19f00022a4c7aabb5cfe145e73afedbd0534b3d` |
| 改动 | 首轮 17 个文件，+4108 / -15；第二轮修复 9 个文件，+508 / -51（`efae1dd..4f0e7ae`）；历史兼容修复 7 个文件，+235 / -7（`127c247..023e5a2`）；旧请求重放修复 6 个文件，+301 / -19（`6592f98..8d75a7a`，含 2 个首轮/第二轮实际生成的请求 fixture）；新增 `trade_planning/` 五个模块、`market_rules/binance_usdm.py`、规划输入 ORM/仓储、`0021_planning_inputs.py` 及四组测试；修改公开行情网关和模型注册 |
| 公共接口 | `PlanningProfileDraft`（历史形态读取与 `require_current_semantics()`）/`PlanningProfileSnapshot`（版本感知读取与 `versioned_payload()`）、`PlanningRiskPolicyDraft`/`PlanningRiskPolicy`、`CostAssumptionsDraft`/`CostAssumptions`、`MarginEvidenceDraft`/`MarginEvidence`、`VenueRuleSnapshot`、`PlanningRefs`、`MarginMode`/`PositionMode`/`QuantityUnit`/`CooldownStatus`、规划错误码；`PlanningInputService.create_profile/create_policy/refresh_venue_rules/resolve_refs/get_pool`；`PlanningInputRepository`（含 `replay_venue_rules`）、`PublicRuleReader`；`BinanceUsdmPublicRuleReader`；`SqlAlchemyPlanningInputRepository`；公开网关新增 `PublicExchangeFilter`/`PublicExchangeSymbol`（含 `fetched_at`）/`get_exchange_symbol_rules` |
| 依赖/迁移 | 无新增依赖；新增前向迁移 `0021_planning_inputs`（planning_pools、planning_profiles、planning_risk_policies、planning_costs、planning_venue_rules、planning_input_requests、唯一工作台池、版本/请求不可变触发器）；迁移 head 为 `0021_planning_inputs`；未迁移业务库；冷却状态、历史字段集合和请求格式兼容均存于 JSONB 文档/请求记录，无 schema 变更 |
| 验证 | 首轮纯契约预期红 3 collection errors、SQL 预期红 1 collection error；首轮 green 15 + 9、阶段 168、full 1113；第二轮修复前 11 项纯契约/规则失败、旧 tip 重放红基线 1 failed，修复后 17 + 12、阶段 176、full 1121；历史兼容修复前纯契约 2 failed、SQL 旧行 1 failed，修复后 23 + 13、阶段 180、full 1125；旧请求重放修复前纯契约 1 failed、SQL 2 failed，修复后纯契约/规则 23、SQL 16、阶段 183、full 1128；架构门禁 38 文件 0 findings；静态检查全绿；迁移链 head `0021_planning_inputs` |
| 未验证 | 前端、HTTP API、浏览器 e2e、真实模型质量、真实公开源持续可用性、真实产品规则发布/官方复验、业务库迁移；未实现 T12/T13 的数量/风险/保证金计算、可实施状态、采纳互斥和未知占用释放 |
| 遗留 | T03 已通过正式复审并以 fast-forward 合并到 `main`；不自动开始 T04，等待用户指定下一审查单元 |

### T03 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 首轮纯契约预期红 | `backend/`（隔离工作区） | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py tests/trade_planning/test_product_support.py tests/market/test_planning_rules.py -q --basetemp=../.tmp/pytest/t03-red-pure-20261109` | 3 collection errors（缺少 `app.trade_planning`/`app.infrastructure.market_rules`），退出 1；符合测试先行预期 |
| 首轮 SQL 预期红 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py -q --basetemp=../.tmp/pytest/t03-red-db-20261109` | 1 collection error（缺少 `models.planning_inputs`），退出 1；符合测试先行预期 |
| 最终纯契约/规则聚焦 | `backend/`（隔离工作区） | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py tests/trade_planning/test_product_support.py tests/market/test_planning_rules.py -q --basetemp=../.tmp/pytest/t03-final-pure-20261109` | 15 passed，退出 0；含十进制拒绝、未知占用、时效、嵌套指纹、产品目录、tick/step/最小名义额解析 |
| 最终 SQL 聚焦 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py -q --basetemp=../.tmp/pytest/t03-final-db-20261109` | 9 passed，退出 0；含单池代次、请求重放、并发首建、资料/政策/规则/成本组合、规则刷新重放、过期/跨日与不可变触发器 |
| 复审修复前纯契约/规则红 | `backend/`（隔离工作区） | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py tests/market/test_planning_rules.py -q --tb=short --basetemp=../.tmp/pytest/t03-fix-red-20261109` | 11 failed / 5 passed，退出 1；失败覆盖冷却未知、抓取时间、网关异常转换和规则重放前置缺陷 |
| 复审修复前旧 tip 重放红基线 | 旧 tip `144e501` 临时工作树 + 临时 PostgreSQL 17 | `python -m pytest tests/persistence/test_t03_red_replay.py -q --tb=short --basetemp=../.tmp/pytest/t03-red-replay-20261109` | 1 failed，退出 1；同一 request_id 第二次刷新在上游失败时直接抛 `PlanningRuleUnavailableError`，未进入重放。临时测试仅用于旧 tip 复现，不进入交付分支；当前等价回归为 `test_rule_refresh_replay_precedes_public_reader` |
| 复审修复后纯契约/规则聚焦 | `backend/`（隔离工作区） | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py tests/market/test_planning_rules.py -q --basetemp=../.tmp/pytest/t03-fix-green3-20261109` | 17 passed，退出 0；含冷却三态、缓存来源时间、60 分钟边界、网关异常转换及服务捕获 |
| 复审修复后 SQL 聚焦 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py -q --basetemp=../.tmp/pytest/t03-fix-db2-20261109` | 12 passed，退出 0；含未知冷却阻断、规则重放先于公开源、同键并发单次提交及既有代次/触发器回归 |
| 复审修复后阶段回归 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/persistence/test_planning_inputs.py tests/persistence/test_migrations.py tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t03-fix-stage-20261109` | 176 passed，退出 0；含 T01/T02、行情网关、迁移链和技术引擎回归 |
| 复审修复后后端 full | 仓库根目录（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t03-review-fix-full-backend-tip.json` | `verification=passed`；后端 1121 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t03-review-fix-full-backend-tip.json` |
| 历史兼容修复前纯契约红 | `backend/`（隔离工作区） | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py -q --tb=short --basetemp=../.tmp/pytest/t03-legacy-red-20261110` | 2 failed / 10 passed，退出 1；旧快照读取报“规划版本指纹与内容不一致” |
| 历史兼容修复前 SQL 红 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py::test_legacy_profile_and_request_replay_are_version_aware -q --tb=short --basetemp=../.tmp/pytest/t03-legacy-db-red2-20261110` | 1 failed，退出 1；`get_profile` 解析旧资料行抛 `planning_integrity_violation` |
| 历史兼容修复后纯契约/规则聚焦 | `backend/`（隔离工作区） | `uv run --locked --no-sync pytest tests/trade_planning tests/market/test_planning_rules.py -q --basetemp=../.tmp/pytest/t03-legacy-pure-green3-20261110` | 23 passed，退出 0；含旧快照原 ref、带截止时间旧载荷、序列化重读、篡改拒绝及新版三态 |
| 历史兼容修复后 SQL 聚焦 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py -q --tb=short --basetemp=../.tmp/pytest/t03-legacy-db-green2-20261110` | 13 passed，退出 0；含旧 profile 行读取、`resolve_current`/`resolve_refs`、旧请求结果重放与 generation 不变 |
| 历史兼容修复后阶段回归 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/persistence/test_planning_inputs.py tests/persistence/test_migrations.py tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t03-legacy-stage-20261110` | 180 passed，退出 0；含 T01/T02、行情网关、迁移链和技术引擎回归 |
| 历史兼容修复后后端 full | 仓库根目录（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t03-legacy-full-backend-tip.json` | `verification=passed`；后端 1125 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t03-legacy-full-backend-tip.json` |
| 旧请求重放修复前纯契约红 | `backend/`（隔离工作区） | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py::test_cooldown_state_must_be_explicit -q --tb=short --basetemp=../.tmp/pytest/t03-req-red-pure-20261110` | 1 failed，退出 1；首轮“未知状态 + 截止时间”Draft 仍被严格校验提前拒绝 |
| 旧请求重放修复前 SQL 红 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py::test_v1_request_with_cooldown_deadline_replays_then_strictly_rejects_new_key tests/persistence/test_planning_inputs.py::test_v2_request_with_explicit_null_status_replays_and_conflicts -q --tb=short --basetemp=../.tmp/pytest/t03-req-red-sql3-20261110` | 2 failed，退出 1；首轮 Draft 构造失败，第二轮显式 null 被误判 `request_conflict` |
| 旧请求重放修复后纯契约/规则聚焦 | `backend/`（隔离工作区） | `uv run --locked --no-sync pytest tests/trade_planning tests/market/test_planning_rules.py -q --basetemp=../.tmp/pytest/t03-req-green-pure2-20261110` | 23 passed，退出 0；历史 Draft 可读、严格首次写入拒绝、新版三态保持 |
| 旧请求重放修复后 SQL 聚焦 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py -q --tb=short --basetemp=../.tmp/pytest/t03-req-green-sql2-20261110` | 16 passed，退出 0；含首轮带截止时间重放、第二轮显式 null 重放、冲突、新键严格校验与并发重放 |
| 旧请求重放修复后阶段回归 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/persistence/test_planning_inputs.py tests/persistence/test_migrations.py tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t03-req-stage-20261110` | 183 passed，退出 0；含 T01/T02、行情网关、迁移链和技术引擎回归 |
| 旧请求重放修复后后端 full | 仓库根目录（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t03-request-compat-full-backend-tip.json` | `verification=passed`；后端 1128 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t03-request-compat-full-backend-tip.json` |
| D1 阶段回归 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/persistence/test_planning_inputs.py tests/persistence/test_migrations.py tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t03-stage2-20261109` | 168 passed，退出 0；含 T01 策略目录、T02 知识索引、迁移链和既有技术引擎回归 |
| 后端 full（tip） | 仓库根目录（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t03-full-backend-tip2.json` | `verification=passed`；后端 1113 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t03-full-backend-tip2.json` |
| 架构门禁 | `backend/`（隔离工作区） | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=38`，`findings=[]`，退出 0 |
| 静态检查 | `backend/`（隔离工作区） | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 全部通过，退出 0；pyright 0 errors / 0 warnings |
| 迁移链 | `backend/`（隔离工作区） | `uv run --locked --no-sync alembic heads` | `0021_planning_inputs (head)`，退出 0 |

### T03 复审修复（第 2 轮）

| 审查问题 | 根因 | 修复与回归 |
| --- | --- | --- |
| P2 未知冷却状态被判为资料完整 | `cooldown_until=None` 同时表示“未声明”和“确认无冷却”，`missing_fields` 未要求冷却状态 | 新增 `CooldownStatus` 三态（未知为 `None`、`none`、`active`）；未知不入完整资料，`none` 不得带截止时间，`active` 必须有截止时间且快照要求截止时间晚于声明时间。`missing_fields` 增加 `cooldown_status`；草稿、快照、服务和测试同步。历史缺失状态保持未知/不完整，不推断为安全、不回写旧版本。 |
| P2 规则刷新重试在幂等重放前依赖公开源 | `refresh_venue_rules` 先调用 reader，后进入仓储重放 | 增加仓储 `replay_venue_rules`：在请求 advisory lock 和参数冲突检查下读取已提交结果；服务先重放，未命中才重新采集，随后仍由 `record_venue_rules` 的请求锁、池行锁和事务完成首次写入。回归覆盖首次成功后上游失败的同键重试、同键不同产品冲突、并发同键单次提交和新请求键刷新。 |
| P2 缓存命中重置规则观测时间并延长有效期 | 网关缓存不保存 HTTP 抓取时间，规则适配器按本地读取时钟重算 `observed_at` | `PublicExchangeSymbol` 增加 `fetched_at`，网关在真实 HTTP 返回后采样并在缓存命中时沿用；规则适配器使用 `fetched_at` 作为来源时间，60 分钟有效期按来源时间计算。MockTransport 回归覆盖 4:59 缓存命中不刷新、5:01 重新抓取后推进、60 分钟整点失效。 |
| P2 网关异常未转换为规划领域错误 | 规则适配器未捕获 `MarketDataUnavailableError`，异常穿透 `PlanningInputService` | 在适配器边界只捕获 `MarketDataUnavailableError` 并转换为 `PlanningRuleUnavailableError`（稳定 `planning_rule_unavailable`），不回显上游正文；真实网关 + MockTransport 覆盖结构异常、网络失败，并验证服务调用方可用 `PlanningServiceError` 捕获。 |

迁移兼容：第二轮未新增 schema；`cooldown_status` 位于不可变 profile JSONB 文档。`0021_planning_inputs` 仍未合并、未应用到业务库。第三轮历史快照兼容按字段集合读取旧 ref，缺少 `cooldown_status` 时保持未知/不完整；旧载荷带 `cooldown_until` 但无状态时保留截止时间、状态仍未知，不自动推断为无冷却或 active，也不回写历史版本。

### T03 历史快照兼容修复（第 3 轮）

| 审查问题 | 根因 | 修复与回归 |
| --- | --- | --- |
| P2 新增 `cooldown_status` 导致合法历史快照指纹失效 | 首轮快照没有该字段，原 ref 按旧字段集合计算；新模型读取时补默认 `None`，`content_sha256()` 把新字段纳入哈希 | `PlanningProfileSnapshot` 用 `model_fields_set` 判定历史载荷是否实际包含 `cooldown_status`；历史分支按旧字段集合（排除 `cooldown_status`）校验原指纹，并允许旧载荷只有 `cooldown_until`；新增 `versioned_payload()` 用 `exclude_unset=True` 保留历史字段集合，仓储资料快照持久化使用该方法。第三轮未完成请求指纹双格式兼容，由第四轮补齐。 |
| 历史读取/重放整条路径 | 旧 snapshot 解析失败会穿透 `get_profile`/`resolve_current`/请求重放 | 使用首轮 tip `144e501` 实际生成的 3 个 fixture（普通快照、带 `cooldown_until` 快照、create_profile 请求结果）验证：原 ref 不变、缺失状态保持未知/不完整、`resolve_refs` 返回 `None`、序列化重读仍匹配、旧请求同键重放 generation 不变；修改财务或嵌套保证金仍拒绝旧指纹。 |

迁移兼容：本轮无 schema 变更；旧快照不重写 `version_id`/`sha256`。旧请求 draft 若带 `cooldown_until` 但无状态，第四轮允许读取并重放已提交请求；首次新写仍严格拒绝。

### T03 旧请求重放兼容修复（第 4 轮）

| 审查问题 | 根因 | 修复与回归 |
| --- | --- | --- |
| P2 首轮带冷却截止时间的旧请求无法进入重放 | Draft 严格冷却校验在构造阶段拒绝“未知状态 + 截止时间”，尚未进入仓储重放 | Draft 允许读取该历史形态；仓储在请求锁内先按旧/新格式候选指纹重放，命中后直接返回原结果；重放未命中才调用 `draft.require_current_semantics()` 执行新版严格校验。新增首轮 tip `144e501` 实际生成的带截止时间请求 fixture，覆盖同键重放、原 ref/generation 不变、新请求键严格拒绝。 |
| P2 第二轮显式 null 请求被误判冲突 | 上一轮只移除 `cooldown_status:null` 按首轮缺字段格式计算，未匹配第二轮已保存指纹 | `create_profile` 同时计算“显式 null”和“缺字段”两种历史候选指纹，按已保存记录匹配；新写入使用显式字段格式。回归覆盖第二轮 `4f0e7ae` 实际请求 fixture、财务/嵌套/显式状态变化冲突、跨工作台/操作冲突、并发同键重放单次提交。 |

迁移兼容：无 schema 变更；历史请求记录、结果和快照不重写。已提交首轮/第二轮请求按原格式重放；不存在已提交映射时仍执行新版严格冷却校验。

### T03 复审结论

- 2026-11-10 用户传回原审查助手正式通过结论；`reviewed_tip` 为 `8d75a7a14471c36e4a168c166e3f94b659ceb9e7`，审查请求中的正式状态已改为 `approved`。
- T03 代码与复审文档以 fast-forward 从 `6fb08b5` 合并到 `main`；本条状态记录是合并后的 docs 提交，具体 hash 见最终回复。
- T03 状态为 `verified`/`approved`。不自动开始 T04；下一审查单元须等待用户明确指定。

### T03 环境说明

- 隔离工作区从 `main` 的 `6fb08b5` 创建；初始代码改动复制到工作区后 `main` 恢复干净。工作区使用独立 `.venv`（锁定依赖 68 包）和专用临时 PostgreSQL 17 容器；`TEST_DATABASE_URL` 仅指向固定测试库/受限角色，通过 `check_test_database` 身份与权限预检，未指向业务库。
- 验证进程内移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`、`GIT_CONFIG_COUNT`，未修改 `.env` 或业务配置。
- 前端未在本轮改动；full 使用 `--component backend`，未执行前端 lint/typecheck/Vitest/build、浏览器 e2e 或 http-e2e。
- 未调用真实模型、未访问私有账户、未修改业务库、未发起真实交易请求；测试资金/费率/保证金/规则全部为合成资料。

## T04：持久任务、修订与安全事件（D2）

| 项目 | 记录 |
| --- | --- |
| 任务 | T04；C4 `RunInput`/`RunSnapshot`/`RunStatus`、请求幂等、不可变修订、单工作台/全局队列容量、任务内安全事件分页、owner/lease 字段与 `0022_agent_tasks` 迁移 |
| FR/AC/HN | FR-01、FR-12；AC-07、AC-18；HN-02、HN-08、HN-11、HN-12。T04 只建立持久任务与事件基础，不实现消费者、领取/心跳、人工审核、消息应用、证据冻结或产物提交 |
| 时间 | 2026-11-10 |
| 任务状态 | `verified`（实现、P2 修复、聚焦、SQL、阶段、静态、迁移链和最终后端 full 均完成） |
| review_status | `approved`（用户于 2026-11-10 传回原审查助手正式通过结论） |
| reviewed_tip | `0df86fe7bbe4dc96062822404dfe45f5f675c06f` |
| 合并 tip | `35617bfe55370b1369525adcb0d214a5147490cf`（fast-forward 到 `main`） |
| implementation tip | `0df86fe7bbe4dc96062822404dfe45f5f675c06f`（`fix: stabilize agent request fingerprints across jsonb`，P2 修复 tip） |
| 首轮实现 tip | `2e173680a86184c4ea4e6d528e275f1fec3c34a7`（`feat: persist versioned agent tasks and events`） |
| base | `9e45d77b1771efbc1e45eca9a1a414c623991c81`（`main`） |
| 改动 | 累计代码 13 个文件，+2433 / -0；P2 修复 `2e17368..0df86fe` 为 5 个文件，+279 / -28。新增 `agent_runs/` 契约、事件、端口与服务；`agent_run_repository.py`；`models/agent_runs.py` 与模型注册；`0022_agent_tasks.py`；三组 T04 测试 |
| 公共接口 | `RunInput`、`RunSnapshot`、`RunStatus`、`AgentRunError`、`canonical_run_input_json`、`run_input_sha256`（按 JSONB 规范文本）、`legacy_run_input_sha256`；`AgentRunRepository.enqueue/get/list_events`；`AgentRunService.start`；`RunEvent`、`RunEventPage`、`RunEventType`；`SqlAlchemyAgentRunRepository` |
| 依赖/迁移 | 无新增依赖；`0022_agent_tasks` 未修改、无新迁移（修复不改变 schema）；迁移 head 仍为 `0022_agent_tasks`；未迁移业务库 |
| 验证 | 首轮预期红 3 个 collection error；P2 预期红 1 failed（`integrity_violation`）；最终聚焦 21 passed；最终后端 full collected 1149 / passed 1149 / failed 0 / skipped 0 / collection_errors 0；Ruff、格式、Pyright、架构门禁（38 文件 0 findings）全部通过 |
| 未验证 | 前端、HTTP API、浏览器 e2e、实际 worker/租约/心跳（T07）、交互与消息（T06）、证据/上下文（T08）、产物与规划（T12–T14）、真实模型质量、业务库迁移；T04 未写入 evidence/artifacts 行 |
| 遗留 | T04 已通过正式复审并以 fast-forward 合并到 `main`；不自动开始 T05，等待用户指定下一审查单元 |

### T04 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 预期红 | `backend/`（隔离工作区） | `uv run --locked --no-sync pytest tests/agent_runs/test_contracts.py tests/agent_runs/test_service.py tests/persistence/test_agent_runs.py -q --basetemp=../.tmp/pytest/t04-red-20261110` | 3 collection errors（缺少 `app.agent_runs`），退出 2；符合测试先行预期 |
| P2 预期红 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/persistence/test_agent_runs.py::test_jsonb_numeric_normalization_keeps_fingerprint_stable_for_reload_and_replay -q --tb=short --basetemp=../.tmp/pytest/t04-p2-red-20261111` | 1 failed：首次 enqueue 在 `_load_snapshot` 抛 `integrity_violation`，退出 1；复现 JSONB 数值规范化导致指纹漂移 |
| 最终聚焦 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/agent_runs tests/persistence/test_agent_runs.py -q --basetemp=../.tmp/pytest/t04-p2-focus-3` | 21 passed，退出 0；含 JSONB 数值往返、旧稳定数值兼容、旧规范化数值 fail-closed、请求重放/冲突/并发、默认值重放、线程/父任务、容量 20、等待 100 不占并发、事件分页、回滚无残留、终态/不可变约束 |
| 阶段回归 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/agent_runs tests/persistence/test_agent_runs.py tests/persistence/test_migrations.py tests/security tests/governance tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/persistence/test_planning_inputs.py tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t04-stage-2` | 315 passed，退出 0；首轮实现证据，P2 后完整覆盖由最终 full 提供；证据 `.tmp/quality/t04-stage-2.log` |
| 最终后端 full | 仓库根目录（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t04-p2-full-backend-final.json` | `verification=passed`；1149 collected / 1149 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t04-p2-full-backend-final.json` |
| 静态检查 | `backend/`（隔离工作区） | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 全部通过；Pyright 0 errors / 0 warnings |
| 架构门禁 | `backend/`（隔离工作区） | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=38`，`findings=[]`，退出 0 |
| 迁移链 | `backend/`（隔离工作区） | `uv run --locked --no-sync alembic heads` | `0022_agent_tasks (head)`，退出 0 |

### T04 关键实现结果

- 请求键按 `(workspace_id, request_id)` 隔离；相同请求键和相同规范化输入重放原任务，内容不同返回 `request_conflict`；不同请求键即使币种/策略参数一致也建立新任务，不复用旧按币种合并队列。
- 请求指纹覆盖工作台和除 `request_id` 外的全部输入；Pydantic 解析后的默认值进入指纹，因此隐式默认字段与显式默认值重试可复用同一任务。策略参数拒绝 NaN/Infinity，避免指纹不可复现。
- 全局可运行任务容量为 20，在同一队列单例行锁内检查；请求重放先于容量检查，满队列时仍可安全重试原请求；等待态不计入运行容量。线程/父任务必须同工作台，父任务必须终态且同一会话，终态后的新工作通过 `parent_run_id` 关联。
- 修订、请求映射、事件、证据与产物行由触发器禁止 UPDATE/DELETE；任务终态禁止重新打开，任务/线程禁止删除；owner/lease 字段只允许在 `running` 状态下成对存在。
- T04 事件只有 `run.queued` 与 `revision.created`，载荷按类型精确白名单校验，不内嵌目标原文、策略参数或财务值；事件按任务内 `seq=1..n` 排序并支持游标分页。
- `agent_evidence_epochs` 与 `agent_artifacts` 按 C9 在 0022 预留，但 T04 不写占位成功行；T08/T14 再实现实际保存和投影，避免把“表已存在”误报为能力已交付。

### T04 P2 修复：请求指纹跨 JSONB 稳定性

| 项目 | 记录 |
| --- | --- |
| 审查问题 | 正式审查判定 1 项 P2：请求指纹在 PostgreSQL JSONB 往返后不稳定（`1e20` → 整数、`-0.0` → `0.0`），导致首次入队重读、`get`、同键重放可能误报 `integrity_violation` |
| 根因 | 首轮 `run_input_sha256` 基于 Python 首次 `json.dumps` 文本；修订列是 JSONB，PostgreSQL 会规范化数值，重读后 Python 表示与首次文本不同 |
| 修复 | 仓储在同一事务内用 `SELECT CAST(:payload AS jsonb)::text` 取得 PostgreSQL 规范文本；`run_input_sha256` 从该文本解析、移除 `request_id`、稳定键序后哈希。读取时从 `agent_run_revisions.input::text` 使用同一算法校验。不修改 schema/迁移、不回写历史 |
| 兼容性 | 新行使用 JSONB 规范文本哈希；旧稳定数值行接受精确旧 Python JSON 哈希；旧行含已规范化数值时原文本不可恢复，仍 fail-closed。新增 `legacy_run_input_sha256`，未新增迁移；`0022_agent_tasks` 不变 |
| 接口 | `run_input_sha256` 参数由 `RunInput` 改为规范文本；新增 `canonical_run_input_json`（提交 JSON 文本）和 `legacy_run_input_sha256`（旧行兼容） |
| 修复 tip | `0df86fe7bbe4dc96062822404dfe45f5f675c06f`（`fix: stabilize agent request fingerprints across jsonb`）；修复 tree `0b99b60f684264374ae080ef321fb215217ab428` |
| 修复范围 | `2e17368..0df86fe`，5 个文件，+279 / -28 |
| 验证 | P2 专项+兼容 3 passed；最终聚焦 21 passed；最终后端 full 1149 passed / 0 failed / 0 skipped；Ruff/格式/Pyright/架构门禁通过 |

P2 专项命令（`backend/` + 临时 PostgreSQL 17）：

```powershell
uv run --locked --no-sync pytest tests/persistence/test_agent_runs.py::test_jsonb_numeric_normalization_keeps_fingerprint_stable_for_reload_and_replay tests/persistence/test_agent_runs.py::test_legacy_stable_hash_rows_stay_readable_without_rewriting_history tests/persistence/test_agent_runs.py::test_legacy_normalized_numeric_rows_fail_closed_instead_of_replaying -q --basetemp=../.tmp/pytest/t04-p2-legacy
```

结果：3 passed，退出 0。读取后的 `RunSnapshot.parameters` 可能采用 JSONB 解码类型（如 `1e20` 变整数、`-0.0` 变 `0.0`），数值语义不变；下游不得依赖 Python 具体数值类型。

### T04 复审结论

- 2026-11-10 用户传回原审查助手正式通过结论：T04 P2 修复版本通过，`reviewed_tip` 为 `0df86fe7bbe4dc96062822404dfe45f5f675c06f`。
- T04 首轮审查的 1 项 P2 已按第 2 轮记录修复；复审通过后任务状态为 `verified`，正式审查状态为 `approved`。
- T04 代码/复审文档以 fast-forward 从 `9e45d77` 合并到 `main`，合并 tip 为 `35617bfe55370b1369525adcb0d214a5147490cf`；本 approval/merge 记录为合并后的 docs 提交。
- 不自动开始 T05；下一审查单元须等待用户明确指定。

### T04 环境说明

- 隔离工作区从 `main` 的 `9e45d77` 创建；`main` 工作区保持干净。工作区使用独立 `.venv`（锁定依赖 68 包）和专用临时 PostgreSQL 17 容器（本机回环临时端口、受限角色、只读身份预检通过），未指向业务库。
- 验证进程内移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`，未修改 `.env` 或业务配置；未打印连接串。
- 前端未改动；full 使用 `--component backend`，未执行前端 lint/typecheck/Vitest/build、浏览器 e2e 或 http-e2e。
- 未调用真实模型、未访问私有账户、未修改业务库、未发起真实交易请求；测试只使用合成 UUID/币种/参数和临时 schema。

## T05：步骤账本、预算与未知调用（D2）

| 项目 | 记录 |
| --- | --- |
| 任务 | T05；C4 `RunFence`/`ExecutionContext`/`SegmentOutcome`/`CompletionDecision`/`PlanAdoptionProposal` 纯类型；C5 `AttemptRequest`/`StepAttempt`/`AttemptResult`/`BudgetLedger`/`BudgetStatus`、meter 预算账本、未知调用与 `0023_agent_attempts`/`0024_agent_attempt_hardening`/`0025_agent_attempt_shape_fix` 迁移 |
| FR/AC/HN | FR-06、FR-12；AC-06、AC-11（仅追加授权原语）、AC-15（账本层）；HN-04、HN-05（账本层）、HN-14（预算/资金隔离测试） |
| 时间 | 2026-11-11（首轮实现 + 正式审查 F1–F4 + 复审 R1） |
| 任务状态 | `verified`（实现、F1–F4 与 R1 修复、聚焦、SQL、阶段、静态、迁移链和最终后端 full 均完成） |
| review_status | `approved`（用户于 2026-11-11 传回原审查助手正式通过结论） |
| reviewed_tip | `f9454adab111218eaa8bc5880b37987031c11bb7` |
| 合并 | `cbffb4f530fdcb4009ae7b2946633188f8bd120e`（fast-forward 到 `main`；本 docs 提交记录合并/推送） |
| implementation tip | `f9454adab111218eaa8bc5880b37987031c11bb7`（`fix: reject settled call counts without actual amount`，R1 修复 tip） |
| 首轮 implementation tip | `249a8adc3769c9576015c7ff4a4edaa3e1798a6b`（`feat: account for agent attempts and cumulative budgets`） |
| 上轮修复 tip | `bd2a59df2e323248046db33ac929cd5d5d8c1063`（`fix: harden agent attempts and budget settlement`） |
| base | `4d1af68fc704f50b21b9f9b0619b446f315f66d6`（`main`） |
| 改动 | 累计代码 `4d1af68..f9454ad`，16 个文件，+4407 / -6；R1 修复 `bd2a59d..f9454ad`，3 个文件，+189 / -13；上轮修复 `249a8ad..bd2a59d`，9 个文件，+567 / -22；新增 `segments.py`、`attempts.py`、`budget.py`、`agent_attempt_repository.py`、`models/agent_attempts.py`、`0023_agent_attempts.py`、`0024_agent_attempt_hardening.py`、`0025_agent_attempt_shape_fix.py` 和三组纯/SQL 测试 |
| 公共接口 | `RunFence`、`ExecutionContext`、`SegmentOutcome`、`CompletionDecision`、`PlanAdoptionProposal`；`AttemptCategory`/`AttemptStatus`、`AttemptRequest`、`AttemptResult`、`StepAttempt`、`TokenUsage`、`logical_step_id`、`attempt_transition_allowed`；`BudgetLimits`、`BudgetStatus`、`BudgetLedger`、initial/hard/effective/validate 函数；`SqlAlchemyBudgetLedger`；复审修复新增 `validate_send_fits` 与 `released` meter 状态 |
| 依赖/迁移 | 无新增依赖；`0023_agent_attempts` 建立四表与基础触发器，`0024_agent_attempt_hardening` 前向加固发送前 failed 时间约束与 meter/state 形状，`0025_agent_attempt_shape_fix` 前向收紧次数 settled 非空；迁移 head 为 `0025_agent_attempt_shape_fix`；未迁移业务库；T06/T07/T13 计划迁移号顺延为 `0026`/`0027`/`0028` |
| 验证 | R1 修复后聚焦 41 passed；阶段回归 185 passed；后端 full `verification=passed`，1183 collected / 1183 passed / 0 failed / 0 skipped / 0 collection errors；Ruff/格式/Pyright/架构门禁通过；迁移 head `0025_agent_attempt_shape_fix` |
| 未验证 | T07 实际领取/心跳/租约恢复/子进程终止；T06 AP-05 用户审核与差异展示；T09/T10/T11 工具、MCP、模型实际发送接线；T14 产物持久化与 HTTP；T16 前端；真实供应商 usage/回执真实性、真实模型质量；业务库迁移；完整 Compose/浏览器/HTTP e2e |
| 遗留 | T05 代码/批准文档待本次合并/推送；T06/T07 的材料与真实回执、产物、HTTP/前端、业务库迁移仍未验证 |

### T05 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 首轮预期红 | `backend/`（隔离工作区） | `uv run --locked --no-sync pytest tests/agent_runs/test_segments.py tests/agent_runs/test_attempts.py tests/agent_runs/test_budget.py tests/persistence/test_agent_attempts.py -q` | 4 collection errors（缺少 `app.agent_runs.segments/attempts/budget` 等），退出 1；符合测试先行预期 |
| F1–F4 预期红 | `D:\t05\backend` + 临时 PostgreSQL 17 | F1–F4 新增回归直接执行 | F1 `mark_sent` 未拒绝；F2 新围栏返回 `attempt_not_found`；F3 `settle` 返回 `invalid_attempt_transition`；F4 直接 SQL 未报错；4 failed，退出 1；已按真实 SQL 复现 |
| R1 预期红 | `D:\t05\backend` + 临时 PostgreSQL 17 | `pytest ...::test_sql_count_settled_requires_non_null_actual_but_allows_one` | 次数 settled + `actual_amount=NULL` 直接 INSERT 未报错（DID NOT RAISE）；同时修正后的直接 SQL 测试断言 SQLSTATE 23514/约束名，退出 1 |
| R1 修复后聚焦 | `D:\t05\backend` + 临时 PostgreSQL 17 | `uv run --locked --no-sync python -m pytest tests/agent_runs tests/persistence/test_agent_attempts.py -q --basetemp=..\.tmp\pytest\t05-r1-focus` | 41 passed，退出 0；证据 `D:\t05\.tmp\quality\t05-r1-focus.log` |
| R1 修复后阶段回归 | `D:\t05\backend` + 临时 PostgreSQL 17 | `uv run --locked --no-sync python -m pytest tests/agent_runs tests/persistence/test_agent_attempts.py tests/persistence/test_agent_runs.py tests/persistence/test_migrations.py tests/security tests/governance -q --basetemp=..\.tmp\pytest\t05-r1-stage` | 185 passed，退出 0；证据 `D:\t05\.tmp\quality\t05-r1-stage.log` |
| R1 修复后后端 full | `D:\t05` + 临时 PostgreSQL 17 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t05-r1-full.json` | `verification=passed`；1183 collected / 1183 passed / 0 failed / 0 skipped / 0 collection errors；证据 `D:\t05\.tmp\quality\manual-agent-t05-r1-full.json` |
| 静态检查 | `D:\t05\backend` | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`python -m pyright` | 全部通过；Pyright 0 errors / 0 warnings |
| 架构门禁 | `D:\t05\backend` | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=38`，`findings=[]`，退出 0 |
| 迁移链 | `D:\t05\backend` | `uv run --locked --no-sync python -m alembic heads` | `0025_agent_attempt_shape_fix (head)`，退出 0 |

首轮 full 的 1175 passed、上轮修复 full 的 1182 passed 证据仍保留；R1 修复后以 1183 passed 报告为准。首轮 full 曾受宿主环境变量和 Windows 长路径临时目录影响，最终在隔离环境与短路径下通过；两次失败已保留记录，未删改，不计入最终通过证据。

### T05 关键实现结果

- 逻辑步骤在发送前由 `(run_id, revision, action_sequence, input_sha256, category)` 派生稳定 UUID；同一逻辑键重入复用步骤，成功结果直接复用，prepared 可被新片段接管，in_flight 拒绝重复发送，unknown 拒绝自动重放。
- `agent_steps` 保存逻辑状态和成功结果引用；`agent_attempts` 每次真实发送独立一行，身份字段不可变，prepared 发送后 segment/owner/lease_epoch 冻结；数据库触发器拒绝终态回写和删除。
- 预算 meter 行使用 `COALESCE(actual_amount, reserved_amount)` 计算已占用：未发送/未知调用保留最坏预留，已知 usage 才替换为实际值；发送前失败把全部次数/Token meter 置为 `released` 并从累计中排除；初始档 8/12/98304/32768/600/64，部署硬上限 32/48/393216/131072/1800/256。
- 每次 reserve/settle/status/activity/append 都在 `agent_runs` 行锁内，用数据库 `clock_timestamp()` 判断租约；不信任客户端时间。`mark_sent` 只检查当前累计是否越限，不重复加 prepared 自身预留。T05 只消费 `RunFence`，claim/heartbeat 仍归 T07。
- 失败重试创建新的 attempt（最多 2 次），第三次返回 `attempt_limit`；成功逻辑键的再次 reserve 不新增次数或 Token，直接返回已保存结果。发送前 failed 不消耗次数/Token，但仍占用一次 attempt；不伪造 `sent_at`。
- 未知调用：in_flight 可由当前有效 fence 保守标记 unknown；只有供应商可验证回执才能结算为 succeeded/failed；unknown 同逻辑键不带新动作序号时拒绝重放。修订推进后，当前有效 owner/fence 可凭可验证回执对账同 run 的历史已发送尝试；旧 worker/旧 prepared 不能借此取得发送权。
- AP-05 追加授权使用绝对值、逐维度不减、至少一项增加、授权引用幂等，硬上限在数据库与应用双重校验；只改 Agent 预算，不触碰规划资金池，测试用合成 `planning_pools.generation` 不变验证隔离。
- 活动时间按片段唯一记录，15 秒安全余量在 reserve 与 mark_sent 前检查；重放同片段同秒数幂等，不同秒数拒绝；超时实际值如实记录并阻塞后续新调用。
- 成功结果引用是 `ArtifactRef` 不透明引用；T05 不创建产物行，实际内容持久化/授权投影仍由 T14 负责，T11/T14 接线时必须提供真实引用。

### T05 复审修复（第 2 轮，F1–F4）

| 问题 | 复现 | 修复 |
| --- | --- | --- |
| F1：实际 Token 超限后 prepared 仍可发送 | 6 个大预留加 1 个待发送预留；前 4 个按 16384 实际输入结算后累计 98560 > 98304；`mark_sent` 仍成功 | 新增 `validate_send_fits`：只检查当前累计是否越限，不再加已有预留；越限返回 `budget_exhausted`，prepared 保持；追加授权后同一 prepared 才能发送 |
| F2：revision 推进后旧 unknown 无法用有效回执结算 | revision 1 下 reserve→mark_sent→unknown；推进 revision 2 后新围栏 settle 返回 `attempt_not_found`，旧围栏返回 `lease_lost` | `_load_attempt` 增加 `allow_historical`；settle 允许当前有效 owner/fence 读取同 run/workspace 的历史 in_flight/unknown；历史对账必须有可验证回执；旧 worker、旧 revision 和旧 prepared 的发送仍拒绝 |
| F3：prepared→failed 契约、仓储、数据库不一致 | reserve 后直接 settle(failed) 返回 `invalid_attempt_transition`；数据库强制 failed 有 sent_at | 发送前失败成为显式分支：保持 `sent_at=NULL`、不保存 usage/回执、写 settled_at；次数/Token meter 全部置 `released`；attempt 仍占用该逻辑步骤两次尝试之一；新增 `0024` 放宽 failed 时间约束 |
| F4：数据库允许未结算 Token 提前写 actual | 直接 UPDATE prepared 的 input/output reservation `actual_amount=0` 不报错；直接 INSERT unknown+actual=0 也不报错 | `0024` 增加 INSERT/UPDATE 共用的 `ck_budget_reservation_shape`，按 meter/state 约束 actual；released 只允许 actual NULL；次数 meter 在 charged 时保留合法 actual=1；触发器允许 reserved→released，已发送 charged 不得释放 |

复审修复提交：`bd2a59df2e323248046db33ac929cd5d5d8c1063`（`fix: harden agent attempts and budget settlement`），范围 `249a8ad..bd2a59d`，9 个文件，+567 / -22；累计代码范围 `4d1af68..bd2a59d`，15 个文件，+4231 / -6。复审修复后聚焦 40 passed、阶段回归 184 passed、后端 full 1182 passed / 0 failed / 0 skipped，迁移 head 为 `0024_agent_attempt_hardening`。正式审查状态仍为 `awaiting_review`，`reviewed_tip=—`。

### T05 复审剩余问题 R1（第 3 轮）

| 项目 | 记录 |
| --- | --- |
| 问题 | 次数 meter 的 settled 分支只有 `state = 'settled' AND actual_amount = 1`；actual 为 NULL 时整个形状表达式得到 NULL，PostgreSQL CHECK 放行“已结算但无实际量”的直接 INSERT。 |
| 复现 | 在真实 PostgreSQL 上，用无既有 `(attempt_id, meter)` 行的合成模型尝试直接 INSERT `meter='model_calls', state='settled', actual_amount=NULL`；0024 约束未拒绝（DID NOT RAISE）。原直接 INSERT 测试还复用了已存在的 `(attempt_id, meter)` 唯一键，宽泛 DBAPIError 不能证明形状约束。 |
| 修复 | 新增前向 `0025_agent_attempt_shape_fix`，替换同一 `ck_budget_reservation_shape`，次数 settled 改为 `actual_amount IS NOT NULL AND actual_amount = 1`；同步 ORM。0023/0024 不改写。兼容性：合法历史行（settled 次数 actual=1）不受影响；若升级库已存在 direct-SQL 写入的非法 settled+NULL 行，`ADD CONSTRAINT` 会 fail-closed，要求先审计/修复，不自动改写账本历史。 |
| 回归 | 使用合法且不冲突的合成模型尝试：settled+NULL INSERT 拒绝并核对 SQLSTATE 23514 与约束名；settled+1 合法；charged+1 合法；修正既有直接 INSERT 测试，避免唯一键干扰。 |
| 提交 | `f9454adab111218eaa8bc5880b37987031c11bb7`（`fix: reject settled call counts without actual amount`），范围 `bd2a59d..f9454ad`，3 个文件，+189 / -13；累计代码 `4d1af68..f9454ad`，16 个文件，+4407 / -6。 |
| 验证 | R1 修复后聚焦 41 passed、阶段回归 185 passed、后端 full 1183 passed / 0 failed / 0 skipped，迁移 head `0025_agent_attempt_shape_fix`。 |
| 状态 | 自测 `verified`；正式审查 `approved`，`reviewed_tip=f9454ad`（见下方复审通过记录）。 |

### T05 复审通过

- 2026-11-11 用户传回原审查助手最终复审结论：**通过 T05 模块代码复审**，`reviewed_tip=f9454adab111218eaa8bc5880b37987031c11bb7`；报告 `docs/superpowers/reviews/manual-agent/T05-rereview-f9454ad.md`。
- 原 F1–F4 与 R1 无未关闭阻断发现；通过结论基于代码核对、审查端独立纯测试 23 passed 及开发端 PostgreSQL 证据，不表示审查端独立执行了 PostgreSQL 全量验收，也不表示 T06/T07 或业务库迁移已验收。
- T05 当前状态为 `verified`/`approved`；代码/批准文档将按用户指令以 fast-forward 合并到 `main` 并推送远端。

### T05 环境说明

- 隔离工作区从 `main` 的 `4d1af68` 创建，分支 `t05-agent-attempts-budget`；合并前未修改 `main`，未推送、未部署。
- 使用独立 `.venv`（锁定依赖 68 包）和临时 PostgreSQL 17 容器；`TEST_DATABASE_URL` 只在进程环境注入，地址为固定测试库/受限角色，通过 `check_test_database` 只读身份预检，未指向业务库；未打印连接串。
- 验证进程内移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`，未修改 `.env` 或业务配置；pytest 临时根使用工作区内目录，避免不可写用户临时目录。
- 前端未改动；full 使用 `--component backend`，未执行前端 lint/typecheck/Vitest/build、浏览器 e2e 或 http-e2e；未调用真实模型、未访问私有账户、未修改业务库、未发起真实交易请求；测试资金/用量/回执均为合成资料。

## T06：人工审核、连续消息与取消一致性（D2）

| 项目 | 记录 |
| --- | --- |
| 任务 | T06；C5 人工审核/反馈、连续消息、AP 分类、取消幂等与 `0026_agent_interactions` 迁移 |
| FR/AC/HN | FR-01、FR-11、FR-12；AC-10 至 AC-14、AC-17（T06 只提供持久待办、记录/应用水位、取消和过期基础，完整恢复/应用需 T07/T13）；HN-06、HN-07、HN-08、HN-11（T06 侧）、HN-12 |
| 时间 | 2026-11-12 |
| 任务状态 | `verified`（实现、测试、阶段、静态、迁移链和后端 full 已完成；不等于正式审查通过） |
| review_status | `approved`（2026-11-12 原审查助手 F1 复审通过） |
| reviewed_tip | `dea98485ac668fd740a53a7dbe8bb69960fdcefc` |
| implementation tip（当前修复） | `dea98485ac668fd740a53a7dbe8bb69960fdcefc`（`fix: protect agent interaction stage times`） |
| 首轮 implementation tip | `1ec0a72e74682ef17995cfca165967b475f764d8`（`feat: persist human review and task feedback`） |
| base | `bbb4e0bc010b46e0188923c176d7334e2764b241`（`main`） |
| tree（当前修复） | `bd5637770e3c9e530d1ec376af34ce7d2ee13d58` |
| 改动范围 | 首轮 19 个文件、+3831/-7；F1 修复 `1ec0a72..dea9848`，4 个文件、+286/-5；累计代码 19 个文件、+4112/-7。新增 `decisions.py`、`interactions.py`、`messages.py`、交互 ORM/仓储、`0026_agent_interactions.py` 和三组测试；修改 `contracts.py`、`ports.py`、`service.py`、`events.py`、任务/预算仓储、模型注册与既有服务测试 |
| 公共接口 | `ControlAction`/`ControlProposal`/`ProposalDiff`/`DecisionPolicy`/`GuardAction`/`GuardDecision`/`ApprovalKind`；`HumanInteraction`/`InteractionDraft`/`InteractionResponse`/`InteractionChange`/`InteractionStatus`/`InteractionDecision`/`FeedbackReceipt`；`InteractionRepository`/`InteractionService`/`MessageRepository`/`MessageService`；`RunSnapshot.cancel_requested_at`、`RunSnapshot.messages_pending`；`AgentRunService.cancel`；`RunEventType` 新增消息/交互/取消安全事件 |
| 依赖/迁移 | 无新增依赖；新增前向 `0026_agent_interactions`（agent_interactions、agent_interaction_feedback、agent_user_messages、agent_run_cancel_requests、`agent_runs.cancel_requested_at`，单活跃待办部分唯一索引与不可变/状态迁移触发器）；迁移 head 为 `0026_agent_interactions`；未迁移业务库 |
| 验证 | 首轮红测 3 collection errors；F1 修复前 SQL 红测 2 failed / 13 passed（真实 PostgreSQL 复现擦除阶段时间）；最终聚焦 51 passed；阶段回归 380 passed；后端 full `verification=passed`，1211 collected / 1211 passed / 0 failed / 0 skipped / 0 collection errors；Ruff/格式/Pyright/架构门禁全绿；迁移 head `0026_agent_interactions` |
| 未验证 | T07 的 preparing→pending 原子发布、claim/heartbeat/租约恢复、终态提交和 worker；T13 的反馈应用、计划采纳/资金池占用；HTTP API、前端、浏览器；真实模型/工具/MCP、真实供应商回执、真实用户消息；业务库迁移和实盘可实施性 |
| 遗留 | 原审查助手已于 2026-11-12 复审通过当前 tip `dea9848`；代码/批准文档已 fast-forward 合并到 `main`（合并 tip `2b4cd78`）并推送。T07/T13、HTTP/前端、真实传输、业务库迁移和部署仍未验收 |

### T06 关键实现结果

- `DecisionPolicy` 为纯函数：只读研究返回 `allow`，澄清返回 `clarify`，AP-01 至 AP-06 返回对应审批类型，缺少类型化差异/材料时要求澄清；模型自批、真实下单、私有账户访问直接拒绝；AP-07 在监控未实现时返回 `monitoring_unavailable`，不把未交付能力伪装为可审核。
- 待办严格区分 `preparing` 与 `pending`：只有 `pending` 可响应；`answered` 只表示响应已记录，`applied` 才表示后续协调器应用完成。单任务部分唯一索引同时阻止第二个 `preparing/pending/answered` 项，保证顺序反馈。
- 响应事务固定顺序为队列锁 → 任务行锁 → 待办/反馈行锁；核对工作台、任务、修订、当前待办、材料 SHA-256、待办状态号和数据库当前时刻，同请求键同内容重放、异内容冲突；任务转回 `queued` 只表示待 worker 重验，`FeedbackReceipt` 固定 `recorded` 且 `adoption_applied=False`。
- 过期响应不会默认批准：在事务内把待办和等待任务置为 `expired` 并追加安全事件，提交后返回 `review_expired`。`expire_due` 提供同口径维护扫描。
- 消息在任务行锁内分配单调 `seq`，同请求键幂等；`received_message_seq` 只在记录时推进，`applied_message_seq` 只能由当前 worker 围栏推进且不得超过 received；消息事件和回执只含序号/水位，不含正文。
- `running` 取消只写 `cancel_requested_at`，端口在取消后拒绝新的预算预留和 `mark_sent`，已发送尝试仍允许结算真实/未知用量；`queued/waiting_*` 直接原子取消并过期活跃待办；终态任务迟到取消只返回当前快照，不重开。
- 审核反馈、取消请求、消息正文和历史待办材料均有不可变/状态迁移数据库触发器；迁移保留既有 T04/T05 表、审计和报告，不修改历史。
- F1 修复后，`published_at/responded_at/applied_at/expired_at` 的已写入值不可改写或清空；preparing→pending、pending→answered、answered→applied、任意→expired 只能首次写入各自阶段时间。`HumanInteraction` 读取侧拒绝“expired 但 responded_at 存在而无 published_at”的异常形状。

### T06 F1 正式审查修复（第 2 轮）

| 项目 | 记录 |
| --- | --- |
| 正式审查发现 | F1（P2）：合法状态推进可改写或擦除已记录的 `published_at`/`responded_at`；审查版本 `1ec0a72`，报告 `T06-formal-review.md` |
| 复现 | 在临时 PostgreSQL 17 上直接 SQL：`answered→expired` 清空发布/响应时间成功（测试 `DID NOT RAISE`）；`pending→answered` 改写 `published_at` 成功；缺少 `responded_at` 被形状 CHECK 而非触发器拒绝；2 failed / 13 passed |
| 修复 | 直接补强未合并的 0026 触发器：旧阶段时间非空时 `IS DISTINCT FROM` 即拒绝；每个合法迁移只允许对应阶段时间首次写入，过期保留历史；读取侧补 expired 形状不变量 |
| 回归 | 跳步测试补齐 responded_at/applied_at 并断言具体错误；新增直接 SQL 覆盖擦除、改写、正常发布/响应/应用、取消过期；修复后聚焦 51 passed、阶段 380 passed、full 1211 passed |
| 迁移兼容 | 0026 未合并、未应用到业务库，按 T02 先例直接补强，不新增 0027；旧版 0026 仅可能存在临时测试 schema，需重建 |
| 提交 | `dea98485ac668fd740a53a7dbe8bb69960fdcefc`（`fix: protect agent interaction stage times`），范围 `1ec0a72..dea9848`，4 个文件，+286/-5 |

### T06 复审结论

- 2026-11-12 用户传回原审查助手正式通过结论：**通过 T06 模块代码复审**，`reviewed_tip=dea98485ac668fd740a53a7dbe8bb69960fdcefc`；报告 `docs/superpowers/reviews/manual-agent/T06-rereview-dea9848.md`。
- 原 F1（P2）关闭，未发现新的阻断问题；F1 阶段时间保护、合法迁移首次写入、正常发布/响应/应用/取消过期均已核对。审查端独立纯测试 36 passed，但未独立连接 PostgreSQL；开发端真实 SQL/full 证据作为补充，不冒充审查端独立验收。
- T06 当前状态为 `verified`/`approved`；代码/批准文档已以 fast-forward 合并到 `main`（合并 tip `2b4cd7831030a42bd68c36ff1bc69a17a67dad05`），本 docs 提交记录合并/推送。通过结论仅针对 T06 当前 tip，不表示 T07/T13、HTTP/前端、真实传输、业务库迁移或部署已验收。

### T06 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 首轮预期红 | `backend/`（隔离工作区） | `uv run --locked --no-sync pytest tests/agent_runs/test_interactions.py tests/agent_runs/test_messages.py tests/persistence/test_agent_interactions.py -q --basetemp=../.tmp/pytest/t06-red` | 3 collection errors（缺少 `decisions/interactions/messages`），退出 2；符合测试先行预期 |
| F1 修复前 SQL 红测 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `pytest tests/persistence/test_agent_interactions.py -q --tb=short --basetemp=../.tmp/pytest/t06-f1-red` | 2 failed / 13 passed，退出 1；擦除阶段时间 `DID NOT RAISE`，缺 responded_at 被形状 CHECK 拒绝；符合复现 F1 预期 |
| F1 修复后最终聚焦 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `pytest tests/agent_runs tests/persistence/test_agent_interactions.py -q --basetemp=../.tmp/pytest/t06-f1-final-focus` | 51 passed，退出 0 |
| F1 修复后阶段回归 | `backend/`（隔离工作区）+ 临时 PostgreSQL 17 | `pytest tests/agent_runs tests/persistence/test_agent_runs.py tests/persistence/test_agent_attempts.py tests/persistence/test_agent_interactions.py tests/persistence/test_migrations.py tests/security tests/governance tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/persistence/test_planning_inputs.py tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t06-f1-stage` | 380 passed，退出 0；含 T01–T05、迁移链、安全/治理与既有技术引擎回归 |
| F1 修复后后端 full | 仓库根目录（隔离工作区）+ 临时 PostgreSQL 17 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t06-f1-full-backend.json` | `verification=passed`；1211 collected / 1211 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t06-f1-full-backend.json` |
| 静态检查 | `backend/`（隔离工作区） | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 全部通过；Pyright 0 errors / 0 warnings |
| 架构门禁 | `backend/`（隔离工作区） | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=38`，`findings=[]`，退出 0 |
| 迁移链 | `backend/`（隔离工作区） | `uv run --locked --no-sync alembic heads` | `0026_agent_interactions (head)`，退出 0 |

### T06 环境说明

- 隔离工作区从 `main` 的 `bbb4e0b` 创建，分支 `t06-agent-interactions`；`main` 保持干净，未修改其他任务文件。
- 使用独立 `.venv`（锁定依赖）和临时 PostgreSQL 17 容器；`TEST_DATABASE_URL` 只在验证进程内注入，指向固定测试库/受限角色，通过 `check_test_database` 只读身份预检；未指向或迁移业务库，未打印连接串。
- 验证进程内移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`、`GIT_CONFIG_COUNT`，未修改 `.env` 或业务配置。
- 首轮阶段命令曾因工作区缺少 `.tmp/pytest` 父目录出现 47 个 setup error，补齐测试临时目录后重跑；`test_migrations` 曾因手工调试 schema `debug_t06` 残留而失败，删除该临时 schema 后 16 passed；这两次环境/测试资源诊断不计入最终通过，代码未因它们放宽测试。
- F1 修复使用新建临时 PostgreSQL 17 容器重新执行迁移和直接 SQL，避免旧版 0026 的残留 schema；0026 未合并、未应用到业务库，本次直接补强迁移而不是新增 0027，旧版 0026 仅存在于临时测试 schema。
- 前端未改动；本轮未执行前端 lint/typecheck/Vitest/build、浏览器 e2e 或 HTTP e2e。未调用真实模型、未访问私有账户、未发起真实交易；测试消息、审核材料和财务引用均为合成数据。

## T07：带租约的执行片段、统一审计提交与 worker（D2）

| 项目 | 记录 |
| --- | --- |
| 任务 | T07；PostgreSQL 片段租约（claim/heartbeat/recover_expired）、`interactive_planning` 四阶段审计、协调器原子提交、`InteractiveAgentWorker` 与 `0027_agent_segments` 迁移 |
| FR/AC/HN | FR-12 主交付；支撑 FR-01/FR-06/FR-11；AC-12、AC-13、AC-15；HN-02、HN-03、HN-04、HN-06、HN-07、HN-11。不实现 T08–T13 的上下文、工具、模型、规划采纳或 HTTP |
| 时间 | 2026-11-12 |
| 任务状态 | `verified`（R1 修复后聚焦 44、阶段 419、后端 full、静态/迁移链/架构门禁均完成） |
| review_status | `approved`（2026-11-12 原审查助手 R1 复审通过） |
| reviewed_tip | `ec3e8e541aad7e36b0f247f5ac2c4c3c8e0c8885` |
| 首轮 implementation tip | `f5091f5805121353f67fa16eb0651ba3e05b6a80`（`feat: fence agent segments and atomic lifecycle commits`） |
| R1 修复 tip（当前） | `ec3e8e541aad7e36b0f247f5ac2c4c3c8e0c8885`（`fix: stop executor when worker is cancelled`） |
| tree | `61abc0331b8f4f6bb456bac700630b9d7e07550e` |
| base | `231d938454834b7f3ecd54180d433c499bcf76ce`（`main`） |
| 改动 | 首轮 22 个文件 +4377/-11；R1 修复 2 个文件 +70/-5（worker 取消清理与两条回归）；新增片段纯类型/端口、治理包装、SQL 租约仓储、提交协调器、ORM/迁移与测试；修改事件/端口/策略/契约/模型注册及既有测试 |
| 公共接口 | `LEASE_SECONDS`/`HEARTBEAT_SECONDS`/`EMPTY_TOOL_CATALOG_SHA256`、`SegmentStatus`、`AgentSegment`、`graph_namespace`；`AgentRunReader`、`SegmentRepository`；`SegmentRunner`/`SegmentExecutor`/`SegmentExecution`；`InteractiveAgentWorker`；`GovernanceRunKind.INTERACTIVE_PLANNING`、知识/策略/规划/工具能力枚举、`INTERACTIVE_PLANNING_POLICY`；`SegmentAuditCoordinator`/`SegmentAuditAdapter`/`InteractivePlanningWorkflow`/`GovernedSegmentExecutor`；`AgentSegmentRecord`、`SqlAlchemyAgentSegmentRepository`、`SqlAlchemyAgentCommitCoordinator`；事件 `run.started/waiting/terminated/requeued` |
| 依赖/迁移 | 无新增生产依赖；新增 `0027_agent_segments`（`agent_segments` 表、唯一 running 片段/namespace、身份/终态触发器；扩展 `harness_runs` 的 interactive_planning 检查）；迁移 head `0027_agent_segments`；未迁移业务库 |
| 验证 | 改动前基线 213 passed；首轮预期红 5 collection errors；首轮聚焦 42、阶段 417、full 1243 passed；R1 预期红 2 failed / 8 passed；R1 修复后聚焦 44、阶段 419、full `0`/`verification=passed；1245 collected / 1245 passed / 0 failed / 0 skipped / 0 collection errors`；Ruff/格式/Pyright 0 errors；架构门禁 41 文件 0 findings；迁移 head `0027_agent_segments` |
| 未验证 | 真实模型/工具/MCP/LangGraph（T08–T11）、规划采纳/资金池（T12–T13）、HTTP/前端/生产装配（T14–T17）、真实模型质量、产品规则、收益、业务库迁移/部署；30 秒真实墙钟、100 个等待任务容量、图 checkpoint 级复用、完整多进程生产 worker |
| 遗留 | 原审查助手已复审通过（`reviewed_tip=ec3e8e5`）；已 fast-forward 合并到 `main`（合并 tip `953cd90`）并推送；T08 及后续任务仍须按依赖与审查单元推进 |

### T07 关键实现结果

- `agent_segments` 保存每个片段唯一 Harness run、图 namespace、owner/lease_epoch、心跳/租约/结束时间和结果；同一 run 只有一个 running 片段，终态不可重开。
- claim 在队列单例锁内领取 queued 任务；复用/创建 T05 初始预算授权，递增 lease_epoch，写入 `run.started` 事件。租约 30 秒、心跳 10 秒，合法性一律使用行锁后的数据库 `clock_timestamp()`。
- 治理运行时为每片段写 requested/authorized/started（seq0–2）审计前缀；协调器在同一事务写业务等待/终态、片段结果、合法 seq3、业务事件和 owner 释放。缺 started 前缀的成功/等待 fail-closed，异常 seq3 只经协调器。
- 等待发布先 preparing，图结束后才原子转 pending；用户仅能响应已发布的 pending 项。等待容量与可运行容量共用队列锁，锁序为队列 → 任务 → 待办。
- 未应用消息阻止 completed/degraded/等待提交，转 `messages_pending` 重排；取消标记优先于消息重排和等待发布。心跳发现取消后停止续租，worker 获取最新快照并提交取消终态。
- 恢复器对过期 running 片段在行锁后重采样数据库时间；只有已 started 的旧片段追加 seq3 失败终态，缺前缀保留真实中断事实；随后 requeue 或按取消标记终态化，不清空 step/attempt/预算/preparing 材料。
- 治理审计适配器不把 `CancelledError` 写成业务失败；preparing 审核材料过期时不发布，安全失败并记录 `review_expired`。
- 片段数据库触发器拒绝身份改写、未释放租约的结束和删除；旧 `harness_runs` 历史类别/策略值不变。

### T07 R1 正式审查修复（第 2 轮）

| 项目 | 记录 |
| --- | --- |
| 审查问题 | R1/P1：`worker.py:172–174` `_run_with_heartbeat` 的 `finally` 只取消心跳任务；外层取消 `run_once()` 时 `asyncio.wait` 不会取消 `create_task` 启动的执行器，导致 worker 退出后旧执行器继续运行 |
| 复现 | 原审查报告命令；修复前 `executor_cancelled=False pending_tasks=1`；新增回归在修复前 2 failed / 8 passed |
| 修复 | `finally` 无条件下取消并 `await gather(runner_task, heartbeat_task, return_exceptions=True)`；执行器与心跳退出后才让 `CancelledError` 继续上抛，清理阶段不提交业务状态 |
| 回归 | `test_cancelling_run_once_stops_executor_without_commit`、`test_cancelling_run_forever_stops_executor_without_commit`；断言执行器收到取消、无遗留 task、无 commit、`CancelledError` 传播 |
| 修复后复现 | 原脚本输出 `executor_cancelled=True pending_tasks=0` |
| 修复 tip | `ec3e8e541aad7e36b0f247f5ac2c4c3c8e0c8885`（`fix: stop executor when worker is cancelled`），范围 `f5091f5..ec3e8e5`，2 个文件 +70/-5 |
| 状态 | 自测 `verified`；原审查助手 2026-11-12 复审通过，`review_status=approved`，`reviewed_tip=ec3e8e5` |

### T07 复审通过

- 2026-11-12 用户传回原审查助手复审结论：**R1/P1 已关闭，T07 本轮代码复审通过，未发现新增阻断问题**；`reviewed_tip=ec3e8e541aad7e36b0f247f5ac2c4c3c8e0c8885`。
- 复审报告更新于 `docs/superpowers/reviews/manual-agent/T07-review.md` 的“最新结论：R1/P1 复审通过”；首轮不通过记录保留为历史。
- 复审依据：修复差异审查、独立原取消复现（`executor_cancelled=True pending_tasks=0 CancelledError_propagated=True commits=0`）、新回归红绿反向验证、`tests/agent_runs/test_worker.py` 10 passed、相关纯回归 29 passed、Ruff/格式通过。审查端未设置 `TEST_DATABASE_URL`，未独立重跑数据库/迁移/D2/full；开发端 44/419/1245 passed 记录不冒充审查端独立数据库验收。
- 通过结论仅针对 `reviewed_tip=ec3e8e5`；T07 当前为 `verified`/`approved`。按用户指令执行分支提交、合并到 `main` 并推送；合并后记录合并 tip。

### T07 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 改动前基线 | `D:\t07\backend` | `uv run --locked --no-sync pytest tests/agent_runs tests/governance tests/security tests/persistence/test_agent_runs.py tests/persistence/test_agent_attempts.py tests/persistence/test_agent_interactions.py tests/persistence/test_migrations.py -q --basetemp=../.tmp/pytest/t07-baseline` | 213 passed，退出 0 |
| 首轮预期红 | `D:\t07\backend` | `uv run --locked --no-sync pytest tests/agent_runs/test_worker.py tests/agent_runs/test_segments.py tests/governance/test_interactive_planning.py tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py -q --collect-only --basetemp=../.tmp/pytest/t07-red-1` | 5 个 collection error（缺少新模块/符号），退出 1；符合测试先行预期 |
| 首轮聚焦最终 | `D:\t07\backend` + 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/agent_runs/test_worker.py tests/agent_runs/test_segments.py tests/agent_runs/test_contracts.py tests/governance/test_interactive_planning.py tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py -q --basetemp=../.tmp/pytest/t07-focus-final` | 42 passed，退出 0；含真实 SQL、并发 claim/commit、子进程终止恢复；未覆盖 worker 取消窗口 | `.tmp/quality/t07-focus.log` |
| 首轮 D2 阶段回归 | `D:\t07\backend` + 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/agent_runs tests/persistence/test_agent_runs.py tests/persistence/test_agent_attempts.py tests/persistence/test_agent_interactions.py tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py tests/persistence/test_migrations.py tests/persistence/test_harness_audit_repository.py tests/security tests/governance tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/persistence/test_planning_inputs.py tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t07-stage-final2` | 417 passed，退出 0 | `.tmp/quality/t07-stage-final2.log` |
| 首轮后端 full | `D:\t07` + 临时 PostgreSQL 17 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t07-full-backend-final.json` | `0` / `verification=passed；1243 collected / 1243 passed / 0 failed / 0 skipped / 0 collection errors` | `.tmp/quality/manual-agent-t07-full-backend-final.json` |
| R1 预期红 | `D:\t07\backend` | `uv run --locked --no-sync pytest tests/agent_runs/test_worker.py -q --basetemp=../.tmp/pytest/t07-r1-red` | 2 failed / 8 passed，退出 1；两条新用例复现执行器未取消和 pending task | 终端记录 |
| R1 聚焦最终 | `D:\t07\backend` + 临时 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/agent_runs/test_worker.py tests/agent_runs/test_segments.py tests/agent_runs/test_contracts.py tests/governance/test_interactive_planning.py tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py -q --basetemp=../.tmp/pytest/t07-r1-focus-final2` | 44 passed，退出 0 | `.tmp/quality/t07-r1-focus.log` |
| R1 D2 阶段回归 | `D:\t07\backend` + 临时 PostgreSQL 17 | 同首轮阶段命令，`--basetemp=../.tmp/pytest/t07-r1-stage` | 419 passed，退出 0 | `.tmp/quality/t07-r1-stage.log` |
| R1 后端 full | `D:\t07` + 临时 PostgreSQL 17 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t07-r1-full-backend-final.json` | `0` / `verification=passed；1245 collected / 1245 passed / 0 failed / 0 skipped / 0 collection errors` | `.tmp/quality/manual-agent-t07-r1-full-backend-final.json` |
| 静态检查 | `D:\t07\backend` | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 全部通过；Pyright 0 errors / 0 warnings | 终端记录 |
| 架构门禁 | `D:\t07\backend` | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=41`，`findings=[]`，退出 0 | 终端记录 |
| 迁移链 | `D:\t07\backend` | `uv run --locked --no-sync alembic heads` | `0027_agent_segments (head)`，退出 0 | 终端记录 |

> 环境说明：首轮一次阶段运行因测试库残留 `harness_test_*` schema 导致迁移隔离用例 1 failed / 416 passed；清理本次临时 schema 后同命令 417 passed。R1 修复后聚焦 44 passed、D2 阶段 419 passed、后端 full 1245 passed / 0 failed / 0 skipped / 0 collection errors。失败为测试环境残留，不是代码缺陷；未放宽或删除该测试。

### T07 环境说明

- 隔离工作区 `D:\t07` 从 `main` 的 `231d938` 创建，分支 `t07-agent-segments`；主工作区保持干净，未修改其他任务文件。
- 使用独立 `.venv`（锁定依赖）与临时 PostgreSQL 17 容器 `t07-test-postgres`（tmpfs、回环随机端口、固定测试库/受限角色）；`TEST_DATABASE_URL` 只在验证进程注入，通过 `check_test_database` 只读身份预检；未指向或迁移业务库，未打印连接串。
- 验证进程内移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`、`GIT_CONFIG_COUNT`，未修改 `.env` 或业务配置。
- 前端未改动；未执行前端 lint/typecheck/Vitest/build、浏览器 e2e 或 HTTP e2e。未调用真实模型、未访问私有账户、未发起真实交易；测试输入/材料/产物均为合成数据。

## T08：冻结证据、动态上下文与输入控长（D3）

| 项目 | 记录 |
| --- | --- |
| 任务 | T08；C5 `EvidenceService.freeze`、`ContextBuilder.build`、`ContextManifest`、保守输入估算与公开行情证据适配器 |
| FR/AC/HN | FR-04、FR-05、FR-06；AC-04、AC-05、AC-14、AC-16；HN-08、HN-09、HN-10、HN-14。T08 不实现真实模型/工具/MCP/LangGraph、HTTP/前端或确定性手动计划计算 |
| 时间 | 2026-11-16 |
| 任务状态 | `verified`（实现、聚焦、阶段回归、后端 full、静态/架构/迁移链均完成；正式审查未完成） |
| review_status | `awaiting_review`（待用户转交原审查助手；不得自行填写 approved） |
| 隔离工作区 | `D:\t08`（从 `main` 的 `f331e09` 创建，分支 `t08-evidence-context`，未推送/合并/部署） |
| base | `f331e09b7d1652060dc03fb792fa65726a11a9bb`（`main`，`docs: record T07 merge into main`） |
| implementation tip | `08532dc8cf15980b70452721384a6600b016f4a0`（`fix: address T08 review findings`；首轮实现 `deec8f2`，边界加固 `96b8270`） |
| implementation tree | `e422f6ed91c98c6673305ccb85c6017779aaa45c` |
| 代码改动范围 | `f331e09..96b8270`，15 个文件，+4192 / -7（`deec8f2` 首轮 +4130/-7；`96b8270` 边界加固 3 个文件 +72/-10） |
| 改动 | 新增 `agent_runs/evidence.py`、`agent/interactive/context.py`、`context_budget.py`、`adapters/research_evidence.py` 与四组测试；扩展 `research/evidence.py` 的逐项计算版本、`agent_runs/contracts.py` 的稳定错误码；`agent_run_repository.py` 增加带围栏的证据 epoch 与内部 context manifest 持久化；包入口注释同步 |
| 公共接口 | `EvidenceDraft`/`EvidenceCollection`/`ResearchEvidencePort`/`EvidenceFactProjector`/`EvidenceRepository`/`EvidenceService.freeze(context, *, refresh=False)`；`ContextBuilder.build(context, evidence, *, applied_seq)`；`ContextManifest`/`ModelContext`/`ModelMessage`/`ModelTool`/`ToolTurn`/`ContextHistory`/`ContextHistoryReader`；`estimate_input(payload: bytes)` 与 `encode_model_request`；`MarketResearchEvidencePort`/`MarketEvidenceFactProjector`；`AgentRunErrorCode` 新增 `run_state_conflict` |
| 依赖/迁移 | 无新增依赖；无新增迁移；复用 `0022_agent_tasks` 的 `agent_evidence_epochs` 与 `agent_artifacts`（内部 `context_manifest`）；迁移 head 仍为 `0027_agent_segments`；未迁移业务库 |
| 验证 | R1–R4 修复后聚焦 55 passed；D3 相关阶段回归 422 passed；后端 full `verification=passed；1300 collected / 1300 passed / 0 failed / 0 skipped / 0 collection errors`；Ruff/格式/Pyright/架构门禁（44 文件 0 findings）/迁移链全绿 |
| 未验证 | 真实模型、原生 Tool Calling、LangGraph、真实 MCP/TCP、HTTP/SSE、前端/浏览器、生产 lifespan、业务库迁移、真实公开源持续可用性、真实产品规则/策略质量；T08 未生成可实施计划或交易请求 |
| 遗留 | 已复审通过，按用户指令 fast-forward 合并到 `main` 并推送（合并 tip `06d5ff7`）；T09 工具守卫、T10 MCP、T11 图仍未实现 |

### T08 关键实现结果

- **证据冻结**：`EvidenceService.freeze` 先读取当前运行快照并检查修订/状态/取消，拒绝历史模式（当前公开端口不能证明历史可得时间）；按 `1 + len(timeframes)` 计划传输次数逐次 `reserve`/`mark_sent`，读取完成后重新采样 `sealed_at`，再封存并保存。已保存 epoch 默认复用；`refresh=True` 使用已保存 epoch 数推进新的高位动作序号区段。
- **预算语义**：初始证据读取使用 `AttemptCategory.TRANSPORT` 与高位序号区段（`1_000_000 + 8 * epoch_count`），不占用模型 Token/交易资金；读取异常可能已发送时按 `unknown` 保留最坏占用，成功保存后逐次成功结算，单个结算失败不丢弃已保存证据但向 worker 报错。
- **上下文构建**：必需块固定为 system/task/strategy/authorization/evidence，必需块超预算直接 `context_budget_exceeded`；新消息全部进入，旧消息按最新优先筛选后插入到新消息之前保持时间顺序；摘要仅当引用证据全部属于当前 epoch 时纳入；知识命中按截至时间过滤、按 chunk 去重、按分数排序、最多 6 块；工具轮次整轮保留/整轮丢弃。
- **Manifest**：只保存引用、版本、字节数、水位、省略理由和限制码，不保存金额、仓位、杠杆、完整证据载荷或原始用户财务文本；`save_context_manifest` 以内部 `artifact_type="context_manifest"` 写入既有 `agent_artifacts`，读取时重算文档 SHA-256。
- **公开行情适配器**：`MarketResearchEvidencePort` 只调用既有 `PublicMarketGateway.get_market`，校验标的/周期覆盖/已收盘时间，保留来源质量与逐项时点；`MarketEvidenceFactProjector` 只渲染公开摘要与每周期最近两根已收盘 K 线。
- **安全门禁兼容**：当前 `test_agent_source_and_secret_safety.py` 仍把工具关键字字面量视为旧固定研究路径的禁用能力；T08 不启用任何工具，仅通过 `model_validate` 返回空/已授权 Schema，未修改或放宽安全测试；T09 按计划细化门禁。

### T08 正式审查 R1–R4 修复

| 发现 | 根因 | 修复与回归 |
| --- | --- | --- |
| R1/P1 传输预算低计 | `planned=1+len(timeframes)` 未覆盖摘要的 ticker/premiumIndex/openInterest 三个端点及各请求重试 | 改为 `(3 + 每周期 1) × 网关最大 2 次尝试`；单周期 8、四周期 14；`MAX_EVIDENCE_TRANSPORT_CALLS` 改为 16（刷新区段同步扩大）。新增真实 `BinanceUsdmPublicMarketGateway` + `httpx.MockTransport`：每端点首次 500 后重试，两周期实际 10 次 ≤ 预留 10；预算 9 次时服务在预留阶段停止，网关请求为 0。 |
| R2/P2 必需证据被字符截断 | `projected[:4000]` 在预算校验前切断数字/时间/限制说明且不记录省略 | 删除字符切片；投影器负责完整有界事实。超过单条消息上限明确 `evidence_projection_too_large`，必需块超出输入预算明确 `context_budget_exceeded`。新增 3990 字符后接 `price=12345.67 closeAt=...` 完整保留测试与 20k 投影失败测试。 |
| R3/P2 manifest 未绑定保存围栏 | 只验证 fence 活性，未比对 manifest 的 workspace/run/revision/segment 或引用证据归属 | 保存/读取均校验四项归属和证据属于同一 workspace/run/revision；读取还校验片段存在。新增跨工作台/运行/修订/片段、跨修订证据、错绑读取和未知片段真实 SQL 拒绝测试。 |
| R4/P2 已绑定 epoch 忽略显式刷新 | `context.evidence_epoch` 非空时先于 `refresh` 直接复用 | 限定为 `context.evidence_epoch is not None and not refresh`；显式刷新继续运行校验、新预算区段和重新采集。新增已绑定 epoch + refresh 测试，断言新 epoch、公开读取和序号推进。 |

修复 tip `08532dc`（7 个文件，+505/-15）；修复后聚焦 55 passed、D3 阶段 422 passed、后端 full 1300 passed（`.tmp/quality/manual-agent-t08-fix-full-backend-1.json`）。首轮审查报告见 `docs/superpowers/reviews/manual-agent/T08-review-report.md`。

### T08 复审通过

- 2026-11-16 用户传回原审查助手复审结论：**T08 R1–R4 代码审查通过，原四项发现关闭，未发现新的阻断项**；`reviewed_tip=08532dc8cf15980b70452721384a6600b016f4a0`。
- 复审范围 `f331e09..08532dc`，重点对照 `96b8270..08532dc` 修复；`docs/superpowers/reviews/manual-agent/T08-review-report.md` 已追加 `08532dc` 复审段，首次 `changes_requested` 历史保留。
- 复审端独立运行 `pytest tests/agent/interactive -q` 为 42 passed，并复验四周期真实网关替身预留 14/实际 14；该结果不包含 PostgreSQL、422 阶段、1300 后端 full、Pyright 或生产装配。开发端 55/422/1300 记录不代表审查端独立数据库/full 验收。
- 通过结论仅针对 `reviewed_tip=08532dc`；T08 为 `verified`/`approved`，按用户指令执行分支提交、fast-forward 合并到 `main` 并推送，合并 tip `06d5ff7`。

### T08 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 改动前基线 | `D:\t08\backend` | `uv run --locked --no-sync pytest tests/research/strategies tests/research/knowledge tests/agent_runs tests/security -q --basetemp=../.tmp/pytest/t08-baseline-20261113` | 142 passed，退出 0 |
| 首轮预期红 | `D:\t08\backend` | `uv run --locked --no-sync pytest tests/agent/interactive tests/persistence/test_agent_evidence.py -q --basetemp=../.tmp/pytest/t08-red-1` | 4 个 collection error（缺少 `context.py`/`context_budget.py`/`agent_runs.evidence`），退出 2；符合测试先行预期 |
| 聚焦最终 | `D:\t08\backend` + 专用 PostgreSQL 17 | `uv run --locked --no-sync pytest tests/agent/interactive/test_context.py tests/agent/interactive/test_evidence_epochs.py tests/agent/interactive/test_context_budget.py tests/persistence/test_agent_evidence.py -q --basetemp=../.tmp/pytest/t08-fix-focus-1` | 55 passed / 0 failed / 0 skipped，退出 0；含真实网关扇出/重试预算、完整事实投影、manifest 归属拒绝与已绑定 epoch 刷新 |
| D3 阶段回归 | `D:\t08\backend` + 专用 PostgreSQL 17 | `pytest tests/agent/interactive tests/agent_runs tests/research/strategies tests/research/knowledge tests/persistence/test_agent_runs.py tests/persistence/test_agent_attempts.py tests/persistence/test_agent_interactions.py tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py tests/persistence/test_agent_evidence.py tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/persistence/test_migrations.py tests/security tests/governance tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t08-fix-stage-1` | 422 passed / 0 failed / 0 skipped，退出 0 |
| 后端 full（R1–R4 修复后） | `D:\t08` + 专用 PostgreSQL 17 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t08-fix-full-backend-1.json` | 退出 0；`verification=passed`；1300 collected / 1300 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t08-fix-full-backend-1.json` |
| 首次 full（环境失败，不冒充通过） | `D:\t08` + tmpfs 测试库 | `... --report .tmp/quality/manual-agent-t08-full-backend-1.json` | 退出 1；`backend-types` 先暴露 `run_state_conflict` 未加入错误码，修复后通过；`backend-tests` 因 512 MiB tmpfs 测试库写满而 204 setup/call 失败。重建为磁盘支持的专用 PostgreSQL 17 后复跑最终 full 通过；首次报告保留为环境失败证据 |
| Ruff / 格式 | `D:\t08\backend` | `uv run --locked --no-sync ruff check .`；`ruff format --check .` | 全部通过，退出 0 |
| Pyright | `D:\t08\backend` | `uv run --locked --no-sync python -m pyright` | 0 errors / 0 warnings，退出 0 |
| 架构门禁 | `D:\t08\backend` | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=44`，`findings=[]`，退出 0 |
| 迁移链 | `D:\t08\backend` | `uv run --locked --no-sync alembic heads` | `0027_agent_segments (head)`，退出 0 |

### T08 环境说明

- 隔离工作区 `D:\t08` 从 `main` 的 `f331e09` 创建，分支 `t08-evidence-context`；主工作区未改动、未合并/推送/部署。
- 使用独立 `.venv`（锁定依赖）与专用 PostgreSQL 17 容器 `t08-test-postgres`；容器使用磁盘支持的临时数据目录（首次 512 MiB tmpfs 在 full 期间写满，导致数据库恢复失败；该次 full 记录为环境失败，未计为通过）。最终容器使用回环随机端口、固定测试库 `crypto_research_test` / 受限角色 `crypto_research_test_runner`，`TEST_DATABASE_URL` 只在验证进程注入，通过 `check_test_database` 只读身份预检；未指向或迁移业务库，未打印连接串。
- 验证进程内移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`、`GIT_CONFIG_COUNT`，未修改 `.env` 或业务配置。
- 前端未改动；未执行前端 lint/typecheck/Vitest/build、浏览器 e2e 或 HTTP e2e。未调用真实模型、未访问私有账户、未发起真实交易；公开行情/证据/任务/策略/知识均为合成或既有测试夹具。

### T08 重点审查位置与已知风险

1. `EvidenceService.freeze` 的预算顺序、读取前后时钟采样、`unknown` 结算与证据保存后单次结算失败路径。
2. `ContextBuilder` 必需块/可选块优先级、新消息水位、旧消息顺序、摘要证据校验、知识截至过滤与工具轮次配对裁剪。
3. `ContextManifest` 是否仅含引用/长度/水位/原因；内部 `context_manifest` artifact 是否会被 T14 误当业务报告投影。
4. `agent_run_repository._lock_live_fence` 的任务→片段锁序、owner/lease_epoch/DB 时钟校验与跨工作台隔离。
5. `EvidenceItem.calculation_version` 对历史 epoch 指纹的兼容：缺失字段不进入载荷，保持旧哈希可重验。
6. 当前安全门禁用 `model_validate` 传递空工具 Schema 的兼容取舍；T09 必须按计划细化门禁，不能把该写法当作工具循环已交付。

## T09：逐次工具守卫与内部研究工具（D3）

| 项目 | 记录 |
| --- | --- |
| 任务 | T09；C6 `RegisteredTool`/`ToolRequest`/`ToolResult`/`ToolObservation`、不可变目录、逐次 `ToolGateway` 与六个只读研究工具 |
| FR/AC/HN | FR-02/FR-03；AC-01/AC-03/AC-06/AC-29；HN-01/HN-05/HN-09/HN-12。工具还消费 T08 证据/上下文与 T01/T02 策略/知识端口，但不实现 T10 MCP、T11 模型图、T12/T13 规划或 T14 HTTP/装配 |
| 时间 | 2026-11-17 |
| 任务状态 | `verified`（首轮 1 P1 + 4 P2 已修复；开发聚焦/阶段/quick 与独立 SQL/full 均完成） |
| review_status | `approved`（2026-11-17 用户传回原审查助手正式通过结论；`reviewed_tip=063e8a3`） |
| 隔离工作区 | `D:\t09`（`t09-tool-gateway`，未推送/合并/部署） |
| base | `36cda455670713f3ffaee18655c4d59113a90b22`（`main`） |
| 首轮受审 tip | `2674f1692d09217daea008a6999d49b291383914`（`feat: guard registered agent tool calls`） |
| implementation tip | `063e8a3a8f099540e89dce890b76748cd7fcb02c`（`fix: address T09 review findings`） |
| implementation tree | `1fca46491d2e39ccb4649357c0ce40b32d851258` |
| 修复范围 | `81018be..063e8a3`，5 个文件，+310/-31 |
| 累计代码范围 | `36cda45..063e8a3`，21 个文件，+4668/-40 |
| SQL 验证增量 | `a9d19df`：新增 `tests/persistence/test_tool_gateway.py` 与 `T09-sql-verification.md`；独立 full 1366 passed |
| 改动 | 新增 `agent/interactive/tools/contracts.py`、`registry.py`、`gateway.py`、`research_tools.py` 与两组测试；扩展架构门禁到 `agent_runs`/`research`/`trade_planning` 的适用隔离；新增工具源码只读/无执行安全测试；同步根/后端规范、维护/运行边界与项目状态 |
| 公共接口 | `RegisteredTool`/`ToolRegistry`/`ToolCatalog`、`ToolRequest`/`ToolResult`/`ToolObservation`、`ToolGateway.call`、`RESEARCH_TOOL_NAMES`、`ResearchToolService.handlers`、`ApprovedNewsReader`/`ApprovedNewsSummary`；`TOOL_ACTION_SEQUENCE_BASE=2_000_000`、8 KiB 摘要上限、六个工具固定版本 |
| 依赖/迁移 | 无新增依赖；无新增迁移；迁移 head 仍为 `0027_agent_segments`；未迁移业务库 |

### T09 关键实现结果

- **目录与版本**：`RegisteredTool` 冻结输入/输出 Schema、只读能力、范围、超时和结果上限；模型可见版本由“基础版本 + 完整目录条目哈希”组成，因此 Schema/能力/范围/超时任一变化都会改变 `tool_catalog_sha256`。`ToolRegistry` 拒绝重复名称、非法 Schema 和非只读能力，处理器集合必须与目录一一对应。
- **逐次守卫**：`ToolGateway.call` 每次读取运行快照，核对修订/取消/策略；随后经 C5 `BudgetLedger.status` 验证当前 fence，并核对策略版本、目录指纹、工具登记、参数 Schema、当前币种/周期和刷新模式。拒绝路径不预留预算、不调用处理器。
- **先预留后发送**：预检通过后，按 `status.tool_calls` 分配高位 TOOL 动作序号，`reserve` 成功并 `mark_sent` 后才调用处理器；预算/租约/存储错误交由 worker 停止，不伪装成可继续观察。
- **结果校验与结算**：处理器结果必须通过 `ToolResult`、目录输出 Schema、8 KiB 摘要、未来/到期时间检查；成功以证据/策略引用为准，缺少时用逻辑步骤身份与结果摘要生成引用；失败/未知不携带结果引用；过期结果降级为 `stale/result_expired`。工具固定串行执行，进程内只缓存已成功观察；重启后的重复步骤只复用持久化引用并降级。
- **六个只读工具**：`read_market_evidence` 复用 T08 冻结 epoch/refresh；`read_approved_news_factors` 默认明确 `news_source_unavailable`；`compute_technical_facts` 复用既有技术引擎；`evaluate_selected_strategy` 精确绑定当前策略版本/参数/评估器；`search_research_knowledge` 以证据截至时刻检索并标注外部不可信文本；`read_strategy_definition` 精确读取所选版本并截断长方法摘要。`build_manual_trade_plan` 尚未登记。
- **安全门禁**：保留旧 `tools=`/`tool_choice`/交易关键字断言；新增工具源码禁止交易执行/HTTP/SQL/模型客户端/凭证关键词的测试；AST 新增 `agent_runs`/`trade_planning` 禁止 Agent/交易/模拟执行依赖、`research` 禁止 LLM 依赖；`governance/` 仍未导入工具/MCP/HTTP/SQL。
- **未接入**：T10 MCP、T11 模型驱动 LangGraph、T12/T13 确定性规划、T14 HTTP/生产装配、前端和真实模型/MCP/TCP 均未实现；现有固定研究路径仍不向模型提供工具。

### T09 首轮审查 R1–R5 修复

首轮正式审查提出 1 项 P1 + 4 项 P2；开发端先补失败回归再修复，修复范围 `81018be..063e8a3`（5 个文件，+310/-31）。

| 发现 | 修复与回归 |
| --- | --- |
| R1/P1 结果时间使用调用前时刻 | 发送时刻 `sent_at` 在 `mark_sent` 后采样；处理器完成后重新采样 `result_checked_at` 用于未来/到期检查。新增执行期间时钟推进的当前观测、真正未来结果、执行期间到期回归。 |
| R2/P2 成功缓存未重新检查到期 | 复用前重新采样 `checked_at`；过期缓存返回 `DEGRADED/STALE/result_expired` 并保留引用，不重新发送；新增同输入到期前后回归。 |
| R3/P2 嵌套 Schema 可修改且指纹不变 | 构造和 `get()`/`tools`/`model_tools()`/`authorized()` 全部深隔离；新增构造输入和四个访问路径改写回归，并用真实网关验证改写后仍拒绝 integer 参数。 |
| R4/P2 追加提示超出 8 KiB | 新增 `_append_note` 预留提示字节与 `_finalize_summary` 最终 UTF-8 限长，六个处理器统一使用；新增中文多字节、证据 ID、limitations、截断提示组合回归。 |
| R5/P2 带点/横线基础版本无法登记 | 基础版本确定性编码为 `[a-z0-9_]` 后再拼接目录哈希；新增 `1.0`、`v1-beta`、32 字符版本回归。 |

修复前失败证据：`t09-review-red-1`（3 failed / 28 passed）、`t09-review-red-2`（5 failed / 28 passed）、`t09-review-red-3`（1 failed / 11 passed）。修复后计数见下表。

### T09 正式审查通过

- 2026-11-17 用户传回原审查助手正式通过结论：首轮 **1 P1 + 4 P2 全部关闭**，修复版本 `reviewed_tip=063e8a3`，未提出新的阻断项。
- 审查阶段新增真实 PostgreSQL 独立验证：C5/片段/进程恢复 34 passed、网关与真实 SQL 账本集成 14 passed、后端 full 1366 collected / 1366 passed / 0 failed / 0 skipped；记录见 `docs/superpowers/reviews/manual-agent/T09-sql-verification.md`。
- 新增 SQL 测试只证明网关与既有账本/仓储的集成边界，不修改生产实现；超时为合成分支，取消为协程取消，不冒充操作系统进程终止或 T10/T11 能力。
- T09 当前 `verified`/`approved`；按用户指令提交并 fast-forward 合并到 `main`，合并 tip `2df4bf0`。正式审查通过不改变自动交易限制、默认审核或后续审查门槛。

### T09 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 改动前基线 | `D:\t09\backend` | `uv run --locked --no-sync pytest tests/agent/interactive tests/agent_runs tests/research/strategies tests/research/knowledge tests/security tests/governance -q --basetemp=../.tmp/pytest/t09-baseline-3` | 248 passed，退出 0 |
| 首轮预期红 | `D:\t09\backend` | `uv run --locked --no-sync pytest tests/agent/interactive/test_tool_gateway.py tests/agent/interactive/test_research_tools.py -q --basetemp=../.tmp/pytest/t09-red-1` | 2 个 collection error（缺少 `app.agent.interactive.tools`），退出 2；符合测试先行预期 |
| 工具+安全聚焦（修复后） | `D:\t09\backend` | `uv run --locked --no-sync pytest tests/agent/interactive/test_tool_gateway.py tests/agent/interactive/test_research_tools.py tests/security -q --basetemp=../.tmp/pytest/t09-review-fix-focus-1` | **108 passed / 0 failed / 0 skipped**（45 工具 + 63 安全），退出 0 |
| 交互式模块（修复后） | `D:\t09\backend` | `uv run --locked --no-sync pytest tests/agent/interactive -q --basetemp=../.tmp/pytest/t09-review-green-6` | 87 passed，退出 0 |
| D3 阶段回归（非数据库，修复后） | `D:\t09\backend` | `uv run --locked --no-sync pytest tests/agent/interactive tests/agent_runs tests/research tests/security tests/governance -q --basetemp=../.tmp/pytest/t09-review-fix-stage-1` | 307 passed / 0 failed / 0 skipped，退出 0 |
| 后端 quick（修复后） | `D:\t09` | `uv run --project backend --locked --no-sync python scripts/verify.py quick --component backend --report .tmp/quality/t09-review-fix-quick-backend.json` | 退出 0；`verification=passed`；1127 collected / 1132 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/t09-review-fix-quick-backend.json` |
| 开发机 full（阻塞，历史证据） | `D:\t09` | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/t09-review-fix-full-blocked.json` | 退出 2；开发机无专用测试库，未执行数据库/后端 full；保留为环境阻塞证据 |
| 独立 PostgreSQL 验证（审查阶段） | `D:\t09\backend` + 临时 PostgreSQL 17 | 预检后分别运行 C5/片段/恢复 33 项、`tests/persistence/test_tool_gateway.py` 14 项；根目录 full | 全部通过；full 1366 passed / 0 failed / 0 skipped；证据 `docs/superpowers/reviews/manual-agent/T09-sql-verification.md`、`.tmp/quality/t09-sql-full-20261117.json` |
| Ruff / 格式 | `D:\t09\backend` | `uv run --locked --no-sync ruff check .`；`ruff format --check .` | 全部通过，退出 0；384 files already formatted |
| Pyright | `D:\t09\backend` | `uv run --locked --no-sync python -m pyright` | 0 errors / 0 warnings，退出 0 |
| 架构门禁 | `D:\t09\backend` | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=82`，`findings=[]`，退出 0 |
| 迁移链 | `D:\t09\backend` | `uv run --locked --no-sync alembic heads` | `0027_agent_segments (head)`，退出 0 |

### T09 环境说明

- 隔离工作区 `D:\t09` 从 `main` 的 `36cda45` 创建；主工作区保持干净。未推送、合并、部署或迁移业务库。
- 使用独立 `.venv`（锁定依赖）；开发执行机没有运行中的 Docker/PostgreSQL，因此开发侧只能完成非数据库检查；审查阶段另用临时 PostgreSQL 17 完成 C5/SQL/full 独立验证，记录见 `T09-sql-verification.md`。开发侧 quick/聚焦不替代该独立验收。
- 前端未改动；未执行前端 lint/typecheck/Vitest/build、浏览器 e2e 或 HTTP e2e。未调用真实模型、MCP、私有账户或交易执行；工具/测试数据均为合成值。

### T09 重点审查位置与已知风险

1. **动作序号与幂等**：`ToolGateway._reserve_step` 用 C5 `status.tool_calls` + 进程内输入指纹映射分配序号；进程重启后同一工具输入可能生成新逻辑步骤（只读工具仍安全，但不是跨进程持久幂等）。是否接受该折衷、是否需要 T14 提供持久 sequencer，请重点审查。
2. **合成结果引用**：处理器没有提供证据/版本引用时，网关用 `ArtifactRef(artifact_id=step_id, sha256=结果摘要)` 结算；该引用指向逻辑步骤而非 `agent_artifacts` 行，T14 不能把它当可读取产物。是否需要立即增加持久结果 artifact 端口，请审查。
3. **工具级预算与传输预算**：市场 refresh 经 T08 `EvidenceService` 逐次传输预算；新闻读取器默认不可用，生产读取器访问公开源时必须自行使用 C5 传输预算。T09 未证明任何新闻 HTTP 或 MCP 发送。
4. **结果摘要与过期**：`ToolResult` 允许最多 64 KiB 以便网关校验，网关再按登记/8 KiB 上限拒绝；处理器完成后重新采样校验时间，过期结果/缓存结果降级为 `stale/result_expired`。新闻/知识摘要按块截断并经最终字节限长，完整内容仍在本地引用。
5. **策略版本**：网关默认 `policy_version="interactive_planning_v1"`，与 T07 当前默认一致；基础工具版本中的点/横线已编码为模型安全版本，T14 装配时仍须显式传入生产值。
6. **目录指纹**：模型可见版本嵌入了完整目录条目哈希，`ContextBuilder` 的输入 Schema 摘要测试已覆盖；T11/T14 必须使用同一个 `ToolRegistry` 实例/指纹，不能另建目录。
7. **工具输出安全投影**：六个处理器只读取公开/用户已选策略数据；测试断言无金额/仓位/杠杆/凭证。但 `read_strategy_definition` 会返回用户策略方法与参数 Schema 的有界摘要，是否满足产品最小化要求需审查。
8. **验证边界**：SQL `agent_steps`/`agent_attempts` 真实预留/结算、失败触发器、并发/恢复已由审查阶段独立 PostgreSQL 验证覆盖；T10 MCP/TCP、T11 模型图、T14 HTTP/生产 lifespan、前端、业务库迁移、真实模型质量/抗注入仍未执行。

## T10：官方 MCP SDK、受控 HTTP 和本地只读服务（D3）

| 项目 | 记录 |
| --- | --- |
| 任务 | T10；`infrastructure/mcp/` 固定端点登记、有界 Streamable HTTP 传输、官方 SDK 客户端与同进程只读 `read_strategy_definition` 服务 |
| FR/AC/HN | FR-03（Tool Calling/MCP、权限/传输拒绝）；AC-02（登记工具经真实 TCP MCP 调用）、AC-03（未登记/越权/注入拒绝）、AC-17（安全轨迹，仅模块边界）；HN-01、HN-04、HN-05、HN-12。T10 不实现 T11 模型图、T12/T13 规划、T14 HTTP/生产 lifespan、前端或真实模型质量 |
| 时间 | 2026-11-17 |
| 任务状态 | `verified`（实现、聚焦、阶段、quick、独立 PostgreSQL full、静态检查均完成；不等于正式审查通过） |
| review_status | `approved`（2026-11-17 用户传回原审查助手正式结论） |
| reviewed_tip | `b5509ac876462820a0850d424d19f4c5fe23b557`（复审通过版本） |
| 隔离工作区 | `D:/project_git/t10`（`t10-mcp-transport`） |
| 合并 tip | `53913d4`（fast-forward 到 `main`；本 docs 提交记录结果） |
| base | `b80071c`（`main`，`docs: record T09 merge into main`） |
| implementation tip | `b5509ac876462820a0850d424d19f4c5fe23b557`（`fix: reject non-ascii MCP service credentials`；首轮实现 `a9d3b24`，首轮加固 `690d726`） |
| implementation tree | `c2f50474aac062311c8dba408396960d96dfc769` |
| 辅助提交 | `619fe2c429cb40de401154dc2aa82af48cf5395f`（`test: anchor interaction lifetime fixture to repository clock`；1 个文件 +2/-1，非 T10 生产代码；见下） |
| 首轮加固提交 | `690d726892ea6deaf14c77a705ca06539fb7cd0a`（`fix: harden MCP result handling and protocol pinning`；2 个文件 +50/-22；首轮受审版本） |
| R1 修复 | `6df36e4`（`fix: bound parameterized JSON MCP responses`；2 个文件 +129/-2） |
| R2 修复 | `b5509ac`（`fix: reject non-ascii MCP service credentials`；2 个文件 +45/-1） |
| 代码范围 | `b80071c..b5509ac`，24 个文件，+3251/-17（T10 代码、测试、加固、R1/R2 修复与同步文档）；辅助测试修复 `a9d3b24..619fe2c`，1 个文件 +2/-1；首轮加固 `619fe2c..690d726`，2 个文件 +50/-22；R1/R2 `690d726..b5509ac`，8 个文件，+466/-7（含已提交文档） |
| 改动 | 新增 `backend/src/app/infrastructure/mcp/{__init__,registry,transport,client,server}.py` 与 `backend/tests/mcp/{support,test_compatibility,test_guarded_transport,test_local_http}.py`、`backend/tests/tooling/test_mcp_lifespan.py`；修改 `backend/pyproject.toml`/`uv.lock`、`research_tools.strategy_definition_tool()`、依赖安全测试；同步根/后端规范、维护/运行边界、项目状态、实施计划与契约 |
| 公共接口 | `McpServiceCredential`/`McpToolDescriptor`/`LocalMcpServiceDescriptor`/`McpEndpoint`/`McpEndpointRegistry`、`BoundedMcpTransport`/`build_http_client`、`McpToolClient`（T09 `ToolHandler`，`call` 需绑定 `ToolGateway`）、`ResearchMcpRuntime`/`build_research_mcp`、`strategy_definition_tool()` |
| 依赖/迁移 | 新增顶层生产依赖 `mcp==2.3.0` 与 `httpx2>=2.10.0,<3`；锁定 `mcp-types==2.3.0`、`httpx2==2.16.2` 及传递依赖；LangGraph 1.2.10、checkpoint-postgres 3.1.2、langchain-core 1.5.3 未变；无新增迁移，迁移 head 仍为 `0027_agent_segments`；未迁移业务库 |

### T10 关键实现结果

- **固定端点与凭据**：`McpEndpointRegistry` 只接受 `127.0.0.1` 固定端口/路径、`2026-07-28` 协议和工具输入/输出 Schema 指纹；`McpServiceCredential` 使用 `SecretStr`，进程启动时生成，公开 descriptor 和 `repr(runtime)` 不含令牌。`runtime.build_client_registry()` 在进程内创建客户端登记，宿主不需要直接持有令牌。
- **有界传输**：`BoundedMcpTransport` 在 SDK 前核对目标、拒绝所有 3xx、按每次工具调用最多 64 个实际 HTTP 请求计数；非 SSE 响应增量读取，超过 64 KiB 立即中止，SSE 单事件通过 SDK `max_sse_event_size` 使用同一登记值。未登记 Host 由 SDK 的 transport security 拒绝（测试为 421）。
- **SDK 客户端**：`McpToolClient` 使用官方 `Client` + `streamable_http_client`，`mode="auto"` 协商后必须为 `2026-07-28`；`tools/list` 必须与登记工具集合/输入输出 Schema 指纹一致，之后才调用固定 `read_strategy_definition`。工具参数只包含当前工作台/策略版本/指纹，模型不能指定 URL、端点或服务。
- **守卫绑定**：`McpToolClient` 实现 T09 `ToolHandler`，由 `ToolGateway` 先完成运行快照/目录/策略/参数/预算/fence 检查并 `mark_sent` 后才调用；公共 `call` 未绑定网关时直接失败。MCP 传输内部的 discover/list/call 每个 POST 都被计数（正常路径 3 次）。
- **只读服务**：`build_research_mcp` 使用官方 `MCPServer.streamable_http_app()`，只登记 `read_strategy_definition`，返回有界安全摘要/质量/原因/版本引用；`json_response=True`、`stateless_http=True`、`host="127.0.0.1"`。`runtime.app` 可独立由 uvicorn 运行并自带 lifespan；挂载到宿主时由宿主显式调用 `runtime.lifespan()`，关闭顺序由宿主控制。
- **安全边界**：无 stdio、外部服务发现、sampling、roots、动态 elicitation、任意 URL/命令、SQL/代码、私有账户、订单或资金操作；未登记工具名在客户端构造时拒绝，`build_manual_trade_plan` 未登记。
- **未接入**：T11 模型驱动 LangGraph、T12/T13 确定性规划/计划采纳、T14 HTTP/前端/生产 lifespan、真实模型质量、真实外部 MCP、业务库迁移均未实现或未验证。当前生产固定研究路径仍不能调用工具。

### T10 验证证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 首轮预期红 | `D:/project_git/t10/backend` | `uv run --locked --no-sync pytest tests/mcp tests/tooling/test_mcp_lifespan.py -q` | 4 个 collection error（缺少 `httpx2`/新模块），退出 2；符合测试先行预期 |
| MCP 聚焦 | `D:/project_git/t10/backend` | `uv run --locked --no-sync pytest tests/mcp tests/tooling/test_mcp_lifespan.py -q --basetemp=../.tmp/pytest/t10-review-focus` | 32 passed / 0 failed / 0 skipped，退出 0 |
| MCP/安全/交互式阶段 | `D:/project_git/t10/backend` | `uv run --locked --no-sync pytest tests/mcp tests/tooling/test_mcp_lifespan.py tests/security tests/agent/interactive -q --basetemp=../.tmp/pytest/t10-review-focus` | 183 passed / 0 failed / 0 skipped，退出 0 |
| 后端 quick | `D:/project_git/t10` | `uv run --project backend --locked --no-sync python scripts/verify.py quick --component backend --report .tmp/quality/t10-review-quick.json` | `verification=passed`；1160 collected / 1160 passed / 0 failed / 0 skipped / 0 collection errors；退出 0 |
| 后端 full（专用 PostgreSQL 17） | `D:/project_git/t10` | `TEST_DATABASE_URL` 进程注入；`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/t10-review-full.json` | `verification=passed`；1399 collected / 1399 passed / 0 failed / 0 skipped / 0 collection errors；退出 0 |
| Ruff / 格式 | `D:/project_git/t10/backend` | `uv run --locked --no-sync ruff check .`；`ruff format --check .` | 全部通过，退出 0；395 files already formatted |
| Pyright | `D:/project_git/t10/backend` | `uv run --locked --no-sync python -m pyright` | 0 errors / 0 warnings，退出 0 |
| 架构门禁 | `D:/project_git/t10/backend` | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=82`，`findings=[]`，退出 0 |
| 迁移链 | `D:/project_git/t10/backend` | `uv run --locked --no-sync alembic heads` | `0027_agent_segments (head)`，退出 0 |
| 依赖差异 | `D:/project_git/t10` | 对比 `b80071c` 与当前 `backend/uv.lock` 的包名/版本 | 只新增 MCP/httpx2 及传递依赖；既有框架版本未变 |

### T10 环境说明与验证边界

- 使用隔离工作区 `D:/project_git/t10` 的独立 `.venv`（`uv sync --locked`）；未修改主工作区、`.env`、业务配置或业务库。
- 专用 PostgreSQL 17 临时容器使用本机回环随机端口、临时数据目录、固定测试库 `crypto_research_test` / 受限角色 `crypto_research_test_runner`；通过项目 `check_test_database` 只读身份/权限预检；验证后停止并删除容器。未打印连接串。
- 真实 TCP 测试只连接本机临时端口；未访问外部 MCP、真实模型、私有账户或交易接口。
- 前端未改动；本轮 quick/full 使用 `--component backend`，未执行前端 lint/typecheck/Vitest/build、浏览器 e2e、HTTP e2e 或完整生产 lifespan 装配。
- **辅助测试修复**：后端 full 首次运行时 3 个 T06 测试因 `_draft()` 使用真实当前时间、而仓储使用固定 `NOW`，在 7 天审核窗口边界后自发失败；以最小测试夹具修改改为 `NOW + expires_in`，不修改生产实现。该修复单独提交并在审查请求中披露，避免把它当作 T10 生产能力。

### T10 首轮正式审查结论与 R1/R2 修复

首轮正式审查对象 `690d726`（tree `6221e3f`）结论为 `changes_requested`，发现 2 项必须修复；审查结论见 `docs/superpowers/reviews/manual-agent/T10-review-result.md`。

| 发现 | 根因与复现 | 修复与回归 |
| --- | --- | --- |
| R1/P1 参数化 Content-Type 绕过 JSON 上限 | `transport.py` 对完整 Content-Type 做子串判断；`application/json; profile="text/event-stream"` 被误判为 SSE，官方 SDK 按 JSON 完整读取 100126 字节，128 字节上限失效 | 解析媒体类型，仅精确 `text/event-stream` 走 SSE；新增直接 transport 与真实 loopback TCP + SDK 大/小参数化 JSON 回归；大响应在解析前被拒绝，小响应成功。 |
| R2/P2 非 ASCII Authorization 头返回 500 | `hmac.compare_digest` 字符串参数含非 ASCII 时抛 `TypeError`；原始 `Bearer 0xFF` 经 Starlette latin-1 解码后进入鉴权中间件 | 候选头先按 latin-1 还原 bytes，非 latin-1 字符直接失败，再做常量时间比较；新增单元和原始 socket 回归，断言 401 且策略读取器零调用。 |

修复前回归 4 failed；修复后 MCP 聚焦 32 passed、阶段 183 passed、quick 后端 1160 passed、full 后端 1399 passed（专用 PostgreSQL 17）。首轮审查的辅助测试提交 `619fe2c` 被接受，未改动。2026-11-17 用户传回原审查助手正式通过结论：`review_status=approved`、`reviewed_tip=b5509ac`、`reviewed_tree=c2f504`；复审未提出新的阻断项。

### T10 已知风险与重点审查位置

1. **`McpToolClient.call` 的网关绑定**：`call` 必须由宿主先 `bind_gateway`，否则抛 `tool_gateway_required`；需确认 T14 装配不会绕过或忘记绑定。
2. **单次调用传输上限**：`max_transport_requests=64` 是每次工具调用的局部上限，尚未接入 C5 任务级传输预算；T11/T14 必须把实际 MCP 请求纳入任务总预算，不能以局部 64 次替代任务 64 次。
3. **SDK 内部请求**：正常 discover/list/call 计 3 次；SDK 后台 SSE 重连未单独触发真实场景，传输层逐请求计数/上限由直接测试覆盖，是否足够需审查。
4. **JSON/SSE 边界**：非 SSE 响应增量读取，超 64 KiB 立即中止；SSE 单事件上限依赖 SDK `max_sse_event_size`，总 SSE 流仍按长连接处理。需确认是否还需要总时长/总字节上限。
5. **服务凭据**：`SecretStr` 与公开 descriptor 已隔离，但 `runtime.build_client_registry()` 在进程内持有凭据；需确认 T14 不把 registry/凭据序列化到能力接口或日志。
6. **Host/Origin**：服务依赖 SDK 的 transport security 做 Host/Origin 检查（测试覆盖未登记 Host 421）；本地部署的 Origin 头策略仍需 T14/部署验收。
7. **Schema 指纹**：输入/输出 Schema 和描述都进入指纹；SDK 版本升级若改变生成的 Schema，会按预期拒绝，需在升级时重新登记而非自动放行。
8. **服务端策略读取**：MCP 服务只按 `workspace_id + VersionRef` 读取策略，未额外校验调用者工作台会话；内部服务凭据是当前边界，T14 必须保证只有同进程/受信任装配能取得客户端登记。

## T11：原生 Tool Calling 与有限 LangGraph（D3）

| 项目 | 记录 |
| --- | --- |
| 任务 | T11；`agent/interactive/model_port.py`、`deepseek.py`、`prompt.py`、`graph.py`、`state.py`，以及 `worker.py` 的 `SegmentRunner` 注入路径 |
| FR/AC/HN | FR-02/FR-03/FR-07（FR-07 仅安全 trace 元数据）；AC-01/AC-03/AC-10/AC-12/AC-15/AC-16；HN-01/HN-04/HN-05/HN-06/HN-07/HN-09/HN-10/HN-11/HN-12 的模块边界。AC-02 的真实 TCP MCP 证明仍归 T10；T11 证明图只消费已授权工具端口 |
| 时间 | 2026-11-17 |
| 任务状态 | `verified`（实现、聚焦/阶段/SQL/quick/full/静态检查完成）；正式审查 `approved` |
| review_status | `approved`（2026-11-17 原审查助手复审通过） |
| reviewed_tip | `7c1f33660f91e0df8c170533ee8f17f222836249` |
| reviewed_tree | `dacff63ed8deee4e707c4a32826c82a90cb3e987` |
| base | `c45640e51b6473f42126ac3dea9ae76536124fef`（`main`） |
| implementation tip | `7c1f33660f91e0df8c170533ee8f17f222836249`（`fix: close remaining T11 activity and response bounds`；前序修复 `e0bc26e`，首轮受审 `d1e3560` / tree `5c78429`） |
| implementation tree | `dacff63ed8deee4e707c4a32826c82a90cb3e987` |
| 改动 | 新增 `model_port.py`（ToolBatch/ModelControlDecision/FinalAnalysis/ModelPort/AnalysisArtifactStager）、`deepseek.py`（固定端点原生 Tool Calling）、`prompt.py`、`graph.py`（GraphDependencies/有限 LangGraph/SegmentRunner）、`state.py`（仅阶段/计数/引用）；修改 `worker.py` 支持 `runner`+`audit_coordinator`；新增 `test_deepseek.py`、`test_graph.py`、`test_graph_segments.py`、`graph_fixtures.py`；同步根/后端规范、维护/运行边界、项目状态、实施计划与契约 |
| 公共接口 | `ToolBatch`/`ModelControlDecision`/`FinalAnalysis`/`ModelDecision`；`ModelPort`（`decide`、`available`、`requested_model`、`estimate_request`）；`ModelCallTrace`/`ModelCallError`；`AnalysisArtifactStager`/`AnalysisStagingError`；`GraphDependencies`/`build_interactive_graph(...)->SegmentRunner`/`not_executed_tool_message`；`InteractiveAgentWorker(..., runner=..., audit_coordinator=...)` |
| 依赖/迁移 | 无新增依赖；无新增迁移；迁移 head 仍为 `0027_agent_segments`；未迁移业务库 |
| 验证 | 新增 36 passed；交互式/安全/治理/agent_runs 242 passed；SQL/恢复聚焦 250 passed；T07 恢复 15 passed；quick 后端 1196 collected/passed；D3 full 1435 collected/passed；Ruff/格式/Pyright/架构门禁 87 文件/迁移链通过 |
| 未验证 | 真实 DeepSeek 调用与语义质量、真实 MCP 发送、生产 lifespan/HTTP/SSE/前端、T12/T13 规划与计划采纳、业务库迁移、浏览器 e2e、完整生产装配 |

### T11 关键实现结果

- **模型端口与适配器**：`DeepSeekToolCallingModel` 使用注入的 httpx 客户端向固定 DeepSeek 端点发送 `messages`、原生工具 Schema、显式禁用 thinking、`max_tokens=4096`；工具观察以原生 `tool_call_id` 回填。响应按异步字节流逐块读取，超过 256 KiB 在越限块关闭响应；结束原因只接受 `stop`/`tool_calls` 且必须与形状一致。工具调用超过 4 项、参数不是 JSON object、缺失模型名、无效 finish/content 都转为固定 `ModelCallError`；供应商自动重试关闭，不依赖 `reasoning_content`。usage 缺失保持 `None`，trace 只记录 requested/returned model、Prompt/Schema/工具目录指纹、供应商标识和已知用量。
- **预算与结算**：每次模型决策和每个工具调用前，用账本活动时间 + 本片段已耗时 + 15 秒安全余量做准入；片段正常/异常/取消均在 `finally` 记录一次活动时间。每次模型决策先读取 C5 状态分配独立 MODEL 动作序号，按 `estimate_request` 保守预留输入、4096 输出和 60 秒超时；`mark_sent` 成功后才调用模型。失败/超时分别按 failed/unknown 结算；`mark_sent` 前失败按发送前 failed 释放预留；每次重试都不复用已发送结果，也不自动重放未知调用。
- **工具回路**：ToolBatch 最多四项，逐个经 T09 `ToolGateway`；观察的状态/质量/原因/摘要作为原生 tool 消息回灌，下一次请求保留完整 assistant call/result 配对。硬预算/租约错误停止后续调用并向未执行项写入 `not_executed` 工具消息；未执行项不伪造发送或结果引用。
- **控制与等待**：ControlProposal 经 T06 `DecisionPolicy` 分类；禁止交易/自批/私有账户动作拒绝，需要澄清/审核时只准备 `preparing` 待办并立即结束片段；等待期间没有模型轮询。`ModelControlDecision` 是 T06 `ControlProposal` 的薄包装，额外携带 usage/供应商标识，不改变审核材料类型。
- **最终分析与 AP-01**：FinalAnalysis 只接受当前 manifest 的证据 ID；`AnalysisArtifactStager` 暂存后，无计划为 COMPLETED，有 `plan_ref` 时必须绑定候选且计划引用已包含在暂存产物中，再经 `DecisionPolicy` 形成 AP-01 `WAIT_APPROVAL`。图不设置可实施状态、不创建计划采纳提案，T13 才处理采纳/占用。
- **图状态与等待语义**：图状态仅保存阶段、模型/工具计数、结果类型、安全原因、产物引用和 preparing 待办；live tool turn 只保存在片段内存，不进入 checkpoint。等待由片段 END 后的 T07 协调器原子发布；worker 的 `runner` 注入仍由 `GovernedSegmentExecutor` 完成四阶段审计/提交。
- **未接入**：生产 lifespan/HTTP/SSE/前端、真实模型、真实 MCP 发送、T12/T13 规划/采纳、T14 报告投影、业务库迁移。固定研究路径仍不向模型提供工具。

### T11 首轮正式审查与 R1–R3 修复

首轮正式审查对前序 `d1e3560`（tree `5c78429`）判定 `changes_requested`，提出 3 项必须修复；本轮已在 `e0bc26e`（tree `362489a`）修复首轮问题；修复前新增 30、阶段 236、SQL 244、quick 1190、full 1429，首轮修复后新增 34、阶段 240、SQL 248、quick 1194、full 1433。二次复审的 R1/R2 剩余问题见下节。

| 发现 | 根因/复现 | 修复与回归 |
| --- | --- | --- |
| R1/P1 活动时间预算不能阻止片段内继续调用 | 原实现只在片段正常结束后 `record_activity`；调用前账本不含本片段已耗时。复现：账本 570 秒，首模型 20 秒后仍执行工具/第二次模型，累计 610 秒。 | 每次模型/工具外部调用前用 `active_seconds + elapsed + 15` 检查；超限停止并写未执行观察；reserve 后 mark_sent 前再次检查并释放 prepared；`run` 在 finally 记录一次活动时间，覆盖正常/异常/取消，且不掩盖原异常。新增 570+20 停止和异常路径记录 20 秒回归。 |
| R2/P1 响应大小限制在完整缓冲后检查 | 原实现 `AsyncClient.post()` 后检查 `response.content`，越限前已完整进入内存。 | 改为 `AsyncClient.stream()` 逐块累计；越限立即退出上下文并关闭响应，不消费后续块。新增计数异步流回归，断言只消费 2 个块且已关闭。 |
| R3/P2 非成功 finish reason 仍可触发工具执行 | 原实现只特殊处理 `length`，随后接受任意非空 `tool_calls`；`content_filter`、缺失/未知原因或不一致形状可形成 ToolBatch。 | 结束原因白名单限定 `stop`/`tool_calls`：`tool_calls` 必须有非空调用，`stop` 不能携带工具调用；过滤/缺失/未知返回 `model_finish_reason_unsupported`，形状不一致返回 `model_invalid_response`，保留已观察 usage/provider id。新增过滤、stop+工具、缺失原因回归。 |

当时仍未执行 PostgreSQL/full 以外的真实模型/MCP/HTTP/前端/生产装配验证；首轮修复后重新执行了专项 SQL 248、quick 1194 和 D3 full 1433，但当时尚未取得原审查助手对修复版本的正式结论；二次复审及最终通过见下节。

### T11 二次复审与 R1/R2 修复

二次复审确认 R3 已关闭，但 R1/R2 各有一处剩余问题：R1 的最后活动检查在 `mark_sent` 前；R2 的压缩响应在 HTTPX 解压后才按 256 KiB 检查。修复提交 `7c1f336`（tree `dacff63`，`4bde392..7c1f336` 8 个文件 +116/-7）。

| 发现 | 修复与回归 |
| --- | --- |
| R1/P1 `mark_sent` 等待耗尽安全余量 | 在 `mark_sent` 返回后、实际模型请求前再次检查活动预算；账本已 sent 时以 `failed` 结算并记录 `budget_exhausted_before_request`，不按 prepared 释放，不发送模型请求。新增 584+2 秒回归：模型零调用、failed 结算、finally 记录 2 秒。 |
| R2/P1 压缩响应先解压再检查 | 请求 `Accept-Encoding: identity`；读取前拒绝非 identity `Content-Encoding`（`model_content_encoding_unsupported`），使用 `aiter_raw` 按原始字节流计数。新增 gzip 回归：读取前拒绝、消费 0 块、响应关闭。 |
| R3/P2 finish reason | 二次复审确认已关闭，未修改；保留过滤/缺失/未知/形状不一致回归。 |

T07 提交边界未变：未修改 worker/审计协调器；活动时间在返回 `SegmentOutcome` 前记录，正常路径记账失败阻止结果返回，等待/终态仍由治理执行器和协调器提交。

### T11 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 改动前基线 | `D:/project_git/t11/backend` | `uv run --locked --no-sync pytest tests/agent/interactive tests/agent_runs tests/governance/test_interactive_planning.py tests/mcp -q --basetemp=../.tmp/pytest/t11-baseline` | 171 passed，退出 0 |
| 首轮预期红（缺模块） | `D:/project_git/t11/backend` | `uv run --locked --no-sync pytest tests/agent/interactive/test_deepseek.py tests/agent/interactive/test_graph.py tests/agent/interactive/test_graph_segments.py -q --basetemp=../.tmp/pytest/t11-red-1` | 3 个 collection error（`deepseek`/`graph`/`model_port` 不存在），退出 2；符合测试先行预期 |
| 新增聚焦最终 | `D:/project_git/t11/backend` | `uv run --locked --no-sync pytest tests/agent/interactive/test_deepseek.py tests/agent/interactive/test_graph.py tests/agent/interactive/test_graph_segments.py -q --basetemp=../.tmp/pytest/t11-review2-focused-2` | 36 passed / 0 failed / 0 skipped，退出 0 |
| 交互式/安全/治理/agent_runs 阶段 | `D:/project_git/t11/backend` | `uv run --locked --no-sync pytest tests/agent/interactive tests/agent_runs tests/governance/test_interactive_planning.py tests/security -q --basetemp=../.tmp/pytest/t11-review2-stage-1` | 242 passed / 0 failed / 0 skipped，退出 0 |
| SQL/恢复聚焦（专用 PostgreSQL 17） | `D:/project_git/t11/backend` | `TEST_DATABASE_URL` 进程注入；`uv run --locked --no-sync pytest tests/agent/interactive tests/agent_runs tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py tests/persistence/test_agent_attempts.py tests/persistence/test_agent_interactions.py tests/persistence/test_agent_runs.py tests/persistence/test_migrations.py -q --basetemp=../.tmp/pytest/t11-review2-sql-1` | 250 passed / 0 failed / 0 skipped，退出 0 |
| T07 恢复专项（专用 PostgreSQL 17） | `D:/project_git/t11/backend` | `TEST_DATABASE_URL` 进程注入；`uv run --locked --no-sync pytest tests/persistence/test_agent_segment_recovery.py tests/persistence/test_agent_segments.py -q --basetemp=../.tmp/pytest/t11-t07-recovery` | 15 passed / 0 failed / 0 skipped，退出 0 |
| 后端 quick | `D:/project_git/t11` | `uv run --project backend --locked --no-sync python scripts/verify.py quick --component backend --report .tmp/quality/t11-final-quick-backend.json` | `verification=passed`；1196 collected / 1196 passed / 0 failed / 0 skipped / 0 collection errors；退出 0 |
| 后端 full（D3 阶段，专用 PostgreSQL 17） | `D:/project_git/t11` | `TEST_DATABASE_URL` 进程注入；`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-d3-full.json` | `verification=passed`；1435 collected / 1435 passed / 0 failed / 0 skipped / 0 collection errors；退出 0 |
| Ruff / 格式 | `D:/project_git/t11/backend` | `uv run --locked --no-sync ruff check .`；`ruff format --check .` | All checks passed；404 files already formatted；退出 0 |
| Pyright | `D:/project_git/t11/backend` | `uv run --locked --no-sync pyright` | 0 errors / 0 warnings，退出 0 |
| 架构门禁 | `D:/project_git/t11/backend` | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=87`，`findings=[]`，退出 0 |
| 迁移链 | `D:/project_git/t11/backend` | `uv run --locked --no-sync alembic heads` | `0027_agent_segments (head)`，退出 0 |
| 文档链接/差异 | `D:/project_git/t11` | 本地 Markdown 相对链接扫描；`git diff --check` | 0 broken links；无输出，退出 0 |

### T11 环境说明

- 隔离工作区 `D:/project_git/t11` 从 `main` 的 `c45640e` 创建；主工作区未改动、未合并/推送/部署。
- 使用独立 `.venv`（`uv sync --locked`）；专用 PostgreSQL 17 临时容器使用本机回环端口、临时数据目录、固定测试库 `crypto_research_test` / 受限角色 `crypto_research_test_runner`，通过 `scripts.check_test_database` 只读身份/权限预检；未指向或迁移业务库，验证后回收容器。
- 验证进程未继承业务 `DATABASE_URL`、`APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`NODE_ENV`、`GIT_CONFIG_COUNT`；未修改 `.env` 或业务配置。
- 前端未改动；本轮 quick/full 使用 `--component backend`，未执行前端 lint/typecheck/Vitest/build、浏览器 e2e、HTTP e2e 或完整生产 lifespan。
- 未调用真实模型、真实 MCP、私有账户或交易执行；模型/工具/证据/财务值均为合成测试资料。

### T11 重点审查位置与已知风险

1. **契约细化**：`ModelControlDecision` 是 T06 `ControlProposal` 的薄包装，`ModelDecision` 仍为三类联合；`ModelPort` 增加 `available`/`requested_model`/`estimate_request`。请确认该细化是否可接受，或要求回到严格三元联合并另设用量记录方式。
2. **live tool turn 的作用域**：assistant call/tool 结果只保存在片段内存，图状态/checkpoint 不含它们；进程重启后需要 T14/T17 用持久化历史重建上下文。当前没有跨进程同片段恢复证明。
3. **活动时间与 T09 网关窗口**：本轮已改为每次模型/工具调用前用账本活动时间 + 本片段已耗时 + 15 秒安全余量做准入，并在正常/异常/取消路径的 finally 记录一次活动时间；仍需审查 T09 网关内部 reserve→mark_sent→handler 的短窗口，以及取消时 activity 写入的 best-effort 处理。
4. **计划/材料引用**：图只校验 `plan_ref` 属于已暂存产物，并准备 AP-01；计划数量/资金/规则/采纳/占用和真实产物读取由 T13/T14 校验。模型传入的控制提案材料引用也由 T13/T14 复核。
5. **事实引用完整性**：T11 只校验 FinalAnalysis 的证据 ID 属于当前 manifest；`ClaimFactRef` 的目标/事实目录、数值渲染和报告语义由 T14 校验，T11 不能声称报告质量已通过。
6. **模型 trace 的落盘**：`DeepSeekToolCallingModel` 通过可选 `trace_recorder` 暴露安全 trace；T11 只测试回调，不写数据库/事件。T14 必须接线并防止原始 Prompt/隐藏思考/财务值进入事件或页面。
7. **worker 组合**：`worker.py` 为 T11 增加 `runner`+`audit_coordinator` 注入，内部构造 `GovernedSegmentExecutor`；已有 `executor` 注入保持兼容。请确认该组合不削弱 T07 的审计/提交边界。
8. **未验证边界**：真实模型协议/能力/语义质量、真实 MCP 发送、生产 lifespan/HTTP/SSE/前端、T12/T13 规划与采纳、业务库迁移、浏览器 e2e 均未执行；不能据此宣称产品手动计划闭环或收益。

### T11 复审通过

- 2026-11-17 用户传回原审查助手正式通过结论：首轮 3 项及二次复审 R1/R2 剩余问题全部关闭，`reviewed_tip=7c1f336`（tree `dacff63`）；复审未提出新的阻断项。
- 二次复审确认 R3 已关闭；R1 的 `mark_sent` 等待期活动准入和 R2 的压缩响应解码前拒绝已由修复提交关闭；T07 提交边界未改变。
- 当前 T11 为 `verified`/`approved`。按用户指令整理并 fast-forward 合并到 `main`，合并 tip `6a9ed12`；本 docs 提交记录结果，不自动进入 T12。

## T12：确定性数量、成本、保证金和操作分支（D4-P）

| 项目 | 记录 |
| --- | --- |
| 任务 | T12；`trade_planning/contracts.py`、`sizing.py`、`order_rules.py`、`margin.py`、`risk_checks.py`、`checklist.py` |
| FR/AC/HN | FR-09/FR-14/FR-15/FR-16；AC-21 至 AC-26；HN-13。软件数值正确性不代表策略盈利或计划可实施 |
| 时间 | 2026-11-20 |
| 任务状态 | `verified`（实现、聚焦/阶段/SQL 依赖/quick/full/静态检查完成）；正式审查 `awaiting_review` |
| review_status | `awaiting_review`（待原审查助手审查） |
| base | `c33613d2c081e95df64b90fa7f09a8bc5f6d9240`（`main`，T11 合并记录） |
| implementation tip | `ef198f871da811cb29894a19580cb04f76ac99af`（`feat: calculate deterministic manual trade plans`） |
| implementation tree | `136c688be9bcb811acffb9b933b13573c9fcfef2` |
| 改动 | 新增 C7 纯契约/数量求解/价格数量规则/保证金/逐项检查/人工清单和 53 项合成测试；同步根/后端规范、维护/运行边界、项目状态、实施计划与契约 |
| 公共接口 | `PlanningRequest`/`PlanningQuote`/`PlanningReason`/`SizingResult`/`ValidationCheck`/`PriceGeometry`/`ManualChecklist`；`calculate_size(request)->SizingResult`、`evaluate_planning_risk(request,size)->tuple[ValidationCheck,...]`、`build_manual_checklist(request,size,checks)->ManualChecklist`；均为纯函数 |
| 依赖/迁移 | 无新增依赖；无新增迁移；迁移 head 仍为 `0027_agent_segments`；未迁移业务库 |
| 验证 | T12 聚焦 53 passed；阶段（trade_planning/策略目录/规划资料 SQL/安全）180 passed；quick 后端 1249 passed；独立 PostgreSQL full 1488 passed / 0 failed / 0 skipped；Ruff/格式/Pyright/架构门禁/迁移链通过 |
| 未验证 | `ManualPlanningService`/readiness/采纳/资金池占用、`ManualPlanRepository`、HTTP/SSE/前端、生产 lifespan、真实公开规则持续可用性、真实用户资料、真实模型语义质量、任何实盘成交或收益 |

### T12 关键实现结果

- **契约与材料指纹**：`PlanningRequest` 冻结候选、精确策略 ref、C3 refs/正文、报价、评估时刻和订单操作；校验 refs/正文/资金池代次/产品一致，拒绝未来声明/报价。`material_sha256` 只绑定候选、版本引用、报价引用/时刻/价格和操作，不含评估时钟；按 18 位结算量化，风险/保证金向上、收益/比率向下。
- **数量与成本**：风险额度 R 取政策单笔/日损/组合上限与资料剩余单笔/日损/组合风险的最小值。单单位止损损失 L/目标净收益 W 使用成本上界；出场价按滑点+价差不利调整，入场费、止损/目标退出费和持有成本各计一次；限价入场用限价，市价入场用最大不利成交价，不重复叠加第二次入场滑点。数量上限同时考虑 R/L、政策名义额/数量、规则数量、可用保证金与产品过滤；只按 step 向下取整，最小数量/名义额冲突直接 blocked，不向上加量或移动结构。
- **价格/订单**：入场带按 tick 向内取整（下界 ceil、上界 floor），触发价必须落在可执行区间；止损/目标在 `strict` 下必须对齐，在 `conservative_one_tick` 下只向风险不利方向移动一格。市价单必须有位于入场带、与当前报价和声明滑点/价差上界一致的最大不利成交价；基础资产数量单位要求合约乘数为 1。
- **保证金/强平**：初始保证金 = 名义额/声明杠杆，向上量化；用户保证金预览必须与本次名义额和初始保证金完全一致，否则 unknown/fail。强平检查只验证止损位于预览参考价的安全一侧，明确不代表真实强平公式、账户核实或不会强平；维持保证金档位/强平参考缺失为 unknown。
- **逐项检查**：输出唯一名称的 required/非 required 检查，覆盖资料/政策完整、资料/成本/规则/报价/候选/保证金时效、UTC 跨日损益声明、冷却/熔断、产品/模式、已有仓位/挂单、杠杆、价格格点、订单类型/TIF、市价上界、数量/最小订单/上限、风险、净盈亏比、保证金预览/强平方向、退出分配。缺失/无法证明为 unknown，只有实际确定性冲突才 fail。
- **人工清单**：输出程序已验证/用户声明/人工核对分层，覆盖入场、数量/名义额、保护性止损、目标退出、到期/取消和反馈；异常分支覆盖未成交、部分成交、跳价、超时、到期、成本/规则变化、保证金/仓位变化。固定 `execution_mode=manual`，不含 TradeIntent、订单号或自动发/撤单入口；阻断项与检查集合一致。
- **边界**：T12 不读写数据库、不调用模型/工具/MCP/私有账户/订单服务；未接入 HTTP/前端/生产 lifespan，不实现 readiness/采纳/资金池占用。`SizingResult` 只是本请求材料下的确定性数值，不等于可实施、已采纳或收益。

### T12 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 预期红（缺模块） | `D:/project_git/t12/backend` | `uv run --locked --no-sync pytest tests/trade_planning/test_sizing.py tests/trade_planning/test_risk_checks.py tests/trade_planning/test_margin.py tests/trade_planning/test_order_rules.py tests/trade_planning/test_checklist.py -q --basetemp=../.tmp/pytest/t12-red-1` | 5 个 collection error（缺少 contracts/sizing/risk_checks/margin/order_rules/checklist），退出 2；符合测试先行预期 |
| T12 聚焦 | `D:/project_git/t12/backend` | 同命令，`--basetemp=../.tmp/pytest/t12-green-15` | 68 passed（含既有 T03 trade_planning 15 项；T12 新增 53 项），退出 0 |
| 阶段（T01/T03 SQL + 安全） | `D:/project_git/t12/backend` | `TEST_DATABASE_URL` 进程注入；`uv run --locked --no-sync pytest tests/trade_planning tests/research/strategies tests/persistence/test_strategy_catalog.py tests/persistence/test_planning_inputs.py tests/security -q --basetemp=../.tmp/pytest/t12-final-stage-1` | 180 passed / 0 failed / 0 skipped，退出 0 |
| 后端 quick | `D:/project_git/t12` | `uv run --project backend --locked --no-sync python scripts/verify.py quick --component backend --report .tmp/quality/t12-final-quick-backend.json` | `verification=passed`；1249 collected / 1249 passed / 0 failed / 0 skipped / 0 collection errors；退出 0 |
| 独立 PostgreSQL full | `D:/project_git/t12` | `TEST_DATABASE_URL` 进程注入；`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/t12-final-full-backend.json` | `verification=passed`；1488 collected / 1488 passed / 0 failed / 0 skipped / 0 collection errors；退出 0 |
| Ruff / 格式 / Pyright / 架构 | `D:/project_git/t12/backend` | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright`；`python -m scripts.check_architecture` | Ruff/格式通过；Pyright 0 errors/0 warnings；architecture `status=passed`、`files_scanned=93`、`findings=[]`；退出 0 |
| 迁移链 | `D:/project_git/t12/backend` | `uv run --locked --no-sync alembic heads` | `0027_agent_segments (head)`，退出 0 |

### T12 环境与审查请求

- 隔离工作区 `D:/project_git/t12` 从 `main` 的 `c33613d` 创建；主工作区未改动、未合并/推送/部署。
- 使用独立 `.venv`（`uv sync --locked`）；专用 PostgreSQL 17 临时容器使用本机回环端口 55433、固定测试库 `crypto_research_test` / 受限角色 `crypto_research_test_runner`，通过 `scripts.check_test_database` 只读身份/权限预检；未指向或迁移业务库，验证后回收容器。
- 未修改 `.env`、凭证或业务配置；未调用真实模型、真实 MCP、私有账户或交易执行；所有财务/规则/费率均为合成资料。
- 本轮未执行前端 lint/typecheck/Vitest/build、浏览器 e2e、HTTP e2e 或完整生产 lifespan；原因是 T12 未接入 HTTP/前端/生产装配。
- 审查请求：`docs/superpowers/reviews/manual-agent/T12-review-request.md`。本轮标记为**待原审查助手审查**（`awaiting_review`）；开发自测不能替代原审查助手正式结论，不自行标记 approved，不进入 T13。

## 后续接续规则

1. T00 已由原审查助手正式通过，`reviewed_tip` 为 `f870de1`，并以 fast-forward 方式合并到 `main`。
2. T01 已由原审查助手正式通过，`reviewed_tip` 为 `159a43b`，代码/复审文档已 fast-forward 合并到 `main`；当前状态为 `verified`/`approved`。
3. T02 已由原审查助手正式通过，`reviewed_tip` 为 `8835a1d`，代码/复审文档已 fast-forward 合并到 `main`；当前状态为 `verified`/`approved`。
4. T03 经三轮 P2 修复后，用户于 2026-11-10 传回正式通过结论（`reviewed_tip=8d75a7a`）；代码/复审文档以 fast-forward 合并到 `main`，当前为 `verified`/`approved`。
5. T04 首轮审查 P2 修复后，用户于 2026-11-10 传回原审查助手正式通过结论（`reviewed_tip=0df86fe`）；代码/复审文档以 fast-forward 合并到 `main`，合并 tip 为 `35617bf`，当前为 `verified`/`approved`。
6. T05 经首轮 F1–F4 和复审 R1 修复后，用户于 2026-11-11 传回原审查助手正式通过结论（`reviewed_tip=f9454ad`，报告 `T05-rereview-f9454ad.md`）；当前为 `verified`/`approved`，代码/批准文档按用户指令 fast-forward 合并到 `main` 并推送。
7. T06 首轮正式审查对 `1ec0a72` 判定不通过（F1），修复 tip 为 `dea9848`，F1 修复范围 `1ec0a72..dea9848`（4 个文件、+286/-5）；修复后聚焦 51、阶段 380、后端 full 1211 passed。用户于 2026-11-12 传回原审查助手正式通过结论（`reviewed_tip=dea9848`，报告 `T06-rereview-dea9848.md`），当前为 `verified`/`approved`；代码/批准文档已 fast-forward 合并到 `main`（合并 tip `2b4cd78`）并推送。T07/T13、HTTP/前端、真实传输、业务库迁移和部署仍须独立验收。
8. T07 已实现片段租约、`interactive_planning` 四阶段审计、统一提交/恢复与 `0027_agent_segments`；首轮审查 R1/P1 不通过，R1 修复 tip `ec3e8e5`（`f5091f5..ec3e8e5`，2 个文件 +70/-5），修复后聚焦 44、阶段 419、后端 full 1245 passed。2026-11-12 原审查助手复审通过（`reviewed_tip=ec3e8e5`，报告 `T07-review.md` 最新结论），当前为 `verified`/`approved`；已按用户指令 fast-forward 合并到 `main`（合并 tip `953cd90`）并推送，本 docs 提交记录合并/推送结果。
9. T08 已实现证据冻结、动态上下文、输入控长与公开行情证据适配器；实现 tip `08532dc`（15 个文件，+4682/-7；首轮 `deec8f2`、加固 `96b8270`、审查修复 `08532dc`），聚焦 55、阶段 422、后端 full 1300 passed。2026-11-16 用户传回原审查助手复审通过（`reviewed_tip=08532dc`），当前为 `verified`/`approved`；审查请求 `docs/superpowers/reviews/manual-agent/T08-review-request.md`，复审报告 `T08-review-report.md`。按用户指令 fast-forward 合并到 `main` 并推送（合并 tip `06d5ff7`）；不自动进入 T09。
10. T09 首轮 1 P1 + 4 P2 已修复，修复 tip `063e8a3`；用户于 2026-11-17 传回原审查助手正式通过结论（`reviewed_tip=063e8a3`），当前 `verified`/`approved`。SQL 验证增量 `a9d19df`，独立 full 1366 passed；复审请求 `docs/superpowers/reviews/manual-agent/T09-review-request.md`。按用户指令 fast-forward 合并到 `main`（合并 tip `2df4bf0`），不自动进入 T10/T11。
11. T10 首轮正式审查 `690d726` 结论为 `changes_requested`；R1/R2 修复到 `b5509ac` 后，用户于 2026-11-17 传回原审查助手正式通过结论（`reviewed_tip=b5509ac`，`reviewed_tree=c2f504`），当前 `verified`/`approved`。审查请求见 `docs/superpowers/reviews/manual-agent/T10-review-request.md`，正式结论见 `T10-review-result.md`。按用户指令 fast-forward 合并到 `main`（合并 tip `53913d4`），本轮不自动进入 T11。
12. T11 首轮 `changes_requested`（3 项）及二次复审 `changes_requested`（R1/R2）均已关闭；修复到 `7c1f336`（tree `dacff63`，19 个文件 +4098/-26），新增 36、阶段 242、SQL/恢复 250、T07 恢复 15、quick 1196、D3 full 1435 passed。2026-11-17 原审查助手复审通过（`reviewed_tip=7c1f336`、`reviewed_tree=dacff63`），当前 `verified`/`approved`；审查请求 `docs/superpowers/reviews/manual-agent/T11-review-request.md`。按用户指令整理并 fast-forward 合并到 `main`（合并 tip `6a9ed12`），本 docs 提交记录结果；不自动进入 T12。
13. T12 已实现 C7 纯契约、确定性数量/成本/保证金/风险检查与人工清单；聚焦 53、阶段 180、quick 1249、独立 PostgreSQL full 1488 passed，静态检查通过。实现 tip `ef198f8`（tree `136c688`），当前 `verified`/`awaiting_review`；审查请求 `docs/superpowers/reviews/manual-agent/T12-review-request.md`。未取得正式结论，不进入 T13。
14. 后续每个审查单元继续执行“实现/自测 → 审查包 → 原审查助手正式结论 → 放行”的门槛，开发自测不能替代正式审查。
