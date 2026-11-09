# 实盘手动计划 Agent 开发进度

- 记录日期：2026-11-09
- 文档基线：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0。
- 状态口径：`implemented` 表示代码、文档和自测已落地；`verified` 表示本轮必需验证完成；`approved` 只能记录用户传回的原审查助手正式结论。T00 的 `verified` 与 `approved` 已在复审通过后据实记录；T01 的 `verified` 与 `approved` 已按用户 2026-11-08 传回的正式复审结论记录；T02 的 `verified` 与 `approved` 已按用户 2026-11-09 传回的正式复审结论记录；T03 首轮正式审查 4 项 P2 不通过，修复后自测为 `verified`、正式审查为 `awaiting_review`，未获复审通过前不得进入 T04。
- 审查口径：`review_status` 由开发执行者维护；`approved` 只能由用户传回原审查助手的正式结论，不能自行填写。

## 当前工作区

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main`；T02 代码/复审文档已 fast-forward 合并，合并前 tip `26e5741`；T03 未合并） |
| 隔离工作区 | `D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t03` |
| 分支 | `task/manual-agent-t03` |
| base | `6fb08b5d455cfb6bca40e636a932e1edc46c855c`（`main`，T02 合并后；T03 开始时工作区干净） |
| implementation tip | `4f0e7ae76a86c2281a47e1cb4bad52b008e9b842`（`fix: harden T03 planning inputs and venue rule snapshots`） |
| tree | `61b1d07f057cf68ef4c16c44a453d2dcc519a956` |
| review_status | `awaiting_review`（首轮正式审查 4 项 P2 不通过；修复后等待复审） |
| reviewed_tip | 未填写（开发模型不得预填正式通过） |
| 首轮受审 tip | `144e5019b904a7194d42bac9eaf55dab4d8c6162`（4 项 P2 不通过） |
| 上一轮受审 tip | `8835a1deb5e4056a98a6e1a2a5f6e2f3e39e0bb9`（T02 正式通过） |

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
| 时间 | 2026-11-09 |
| 任务状态 | `verified`（实现、聚焦、阶段回归、迁移/并发回归、静态检查和后端 full 已完成；不等于正式审查通过） |
| review_status | `awaiting_review`（首轮正式审查 4 项 P2 不通过；修复后等待复审） |
| implementation tip | `4f0e7ae76a86c2281a47e1cb4bad52b008e9b842`（`fix: harden T03 planning inputs and venue rule snapshots`） |
| tree | `61b1d07f057cf68ef4c16c44a453d2dcc519a956` |
| 改动 | 首轮 17 个文件，+4108 / -15；复审修复 9 个文件，+508 / -51（`efae1dd..4f0e7ae`）；新增 `trade_planning/` 五个模块、`market_rules/binance_usdm.py`、规划输入 ORM/仓储、`0021_planning_inputs.py` 及四组测试；修改公开行情网关和模型注册 |
| 公共接口 | `PlanningProfileDraft`/`PlanningProfileSnapshot`、`PlanningRiskPolicyDraft`/`PlanningRiskPolicy`、`CostAssumptionsDraft`/`CostAssumptions`、`MarginEvidenceDraft`/`MarginEvidence`、`VenueRuleSnapshot`、`PlanningRefs`、`MarginMode`/`PositionMode`/`QuantityUnit`/`CooldownStatus`、规划错误码；`PlanningInputService.create_profile/create_policy/refresh_venue_rules/resolve_refs/get_pool`；`PlanningInputRepository`（含 `replay_venue_rules`）、`PublicRuleReader`；`BinanceUsdmPublicRuleReader`；`SqlAlchemyPlanningInputRepository`；公开网关新增 `PublicExchangeFilter`/`PublicExchangeSymbol`（含 `fetched_at`）/`get_exchange_symbol_rules` |
| 依赖/迁移 | 无新增依赖；新增前向迁移 `0021_planning_inputs`（planning_pools、planning_profiles、planning_risk_policies、planning_costs、planning_venue_rules、planning_input_requests、唯一工作台池、版本/请求不可变触发器）；迁移 head 为 `0021_planning_inputs`；未迁移业务库；冷却状态存于 JSONB 文档，无 schema 变更 |
| 验证 | 首轮纯契约预期红 3 collection errors、SQL 预期红 1 collection error；首轮 green 15 + 9、阶段 168、full 1113；复审修复前 11 项纯契约/规则回归失败（含 4 项 P2 复现）、旧 tip 重放红基线 1 failed；修复后纯契约/规则 17 passed、SQL 12 passed、D1 阶段回归 176 passed、后端 full 1121 passed / 0 failed / 0 skipped；架构门禁 38 文件 0 findings；静态检查全绿；迁移链 head `0021_planning_inputs` |
| 未验证 | 前端、HTTP API、浏览器 e2e、真实模型质量、真实公开源持续可用性、真实产品规则发布/官方复验、业务库迁移；未实现 T12/T13 的数量/风险/保证金计算、可实施状态、采纳互斥和未知占用释放 |
| 遗留 | T03 等待原审查助手复审；未获通过前不开始 T04。审查请求见 `docs/superpowers/reviews/manual-agent/T03-review-request.md` |

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

迁移兼容：本轮未新增 schema；`cooldown_status` 位于不可变 profile JSONB 文档。`0021_planning_inputs` 仍未合并、未应用到业务库。历史载荷缺少 `cooldown_status` 时解析为未知并保持不完整；若旧载荷带截止时间但无状态则拒绝，不自动推断为无冷却，也不回写历史版本。

### T03 环境说明

- 隔离工作区从 `main` 的 `6fb08b5` 创建；初始代码改动复制到工作区后 `main` 恢复干净。工作区使用独立 `.venv`（锁定依赖 68 包）和专用临时 PostgreSQL 17 容器；`TEST_DATABASE_URL` 仅指向固定测试库/受限角色，通过 `check_test_database` 身份与权限预检，未指向业务库。
- 验证进程内移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`、`GIT_CONFIG_COUNT`，未修改 `.env` 或业务配置。
- 前端未在本轮改动；full 使用 `--component backend`，未执行前端 lint/typecheck/Vitest/build、浏览器 e2e 或 http-e2e。
- 未调用真实模型、未访问私有账户、未修改业务库、未发起真实交易请求；测试资金/费率/保证金/规则全部为合成资料。

## 后续接续规则

1. T00 已由原审查助手正式通过，`reviewed_tip` 为 `f870de1`，并以 fast-forward 方式合并到 `main`。
2. T01 已由原审查助手正式通过，`reviewed_tip` 为 `159a43b`，代码/复审文档已 fast-forward 合并到 `main`；当前状态为 `verified`/`approved`。
3. T02 已由原审查助手正式通过，`reviewed_tip` 为 `8835a1d`，代码/复审文档已 fast-forward 合并到 `main`；当前状态为 `verified`/`approved`。
4. T03 首轮正式审查 4 项 P2 不通过；修复 tip 为 `4f0e7ae`，当前为 `verified`/`awaiting_review`，等待原审查助手复审。未获通过前不得启动 T04 或后续依赖开发。
5. 后续每个审查单元继续执行“实现/自测 → 审查包 → 原审查助手正式结论 → 放行”的门槛，开发自测不能替代正式审查。
