# 实盘手动计划 Agent 开发进度

- 记录日期：2026-11-11
- 文档基线：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0。
- 状态口径：`implemented` 表示代码、文档和自测已落地；`verified` 表示本轮必需验证完成；`approved` 只能记录用户传回的原审查助手正式结论。T00 的 `verified` 与 `approved` 已在复审通过后据实记录；T01 的 `verified` 与 `approved` 已按用户 2026-11-08 传回的正式复审结论记录；T02 的 `verified` 与 `approved` 已按用户 2026-11-09 传回的正式复审结论记录；T03 经首轮 4 项、第二轮 1 项、第三轮 1 项 P2 修复后，用户于 2026-11-10 传回正式通过结论（`reviewed_tip=8d75a7a`），当前为 `verified`/`approved`；T04 已完成实现、P2 修复、聚焦/SQL/阶段/静态检查和后端 full；用户于 2026-11-10 传回原审查助手正式通过结论（`reviewed_tip=0df86fe`），T04 当前为 `verified`/`approved`；T05 首轮实现后正式审查判定 4 项 P2 不通过，已完成 F1–F4 复现、修复和 `0024_agent_attempt_hardening` 迁移；修复后聚焦 40、阶段回归 184、后端 full 1182 passed，当前自测 `verified`、正式审查 `awaiting_review`（修复 tip `bd2a59d`），尚未取得原审查助手对修复版本的正式结论。
- 审查口径：`review_status` 由开发执行者维护；`approved` 只能由用户传回原审查助手的正式结论，不能自行填写。

## 当前工作区

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main`；T04 approval/merge 文档提交之后 tip `4d1af68`，工作区干净） |
| 隔离工作区 | `D:\t05`（短路径；为规避 Windows 260 字符路径上限，从 `.worktrees\manual-agent-t05-20261111` 移动，内容与分支不变） |
| 分支 | `t05-agent-attempts-budget`（未合并） |
| base | `4d1af68fc704f50b21b9f9b0619b446f315f66d6`（`main`，T04 复审/合并文档之后） |
| implementation tip | `bd2a59df2e323248046db33ac929cd5d5d8c1063`（`fix: harden agent attempts and budget settlement`，复审修复 tip） |
| 首轮 implementation tip | `249a8adc3769c9576015c7ff4a4edaa3e1798a6b`（`feat: account for agent attempts and cumulative budgets`） |
| tree | `6a099ed2ca604cad77d9706e5badb395b922aa70`（复审修复 tip） |
| 改动范围 | 累计代码 `4d1af68..bd2a59d`，15 个文件，+4231 / -6；复审修复 `249a8ad..bd2a59d`，9 个文件，+567 / -22 |
| review_status | `awaiting_review`（等待用户转交原审查助手对修复版本的复审；开发自测不替代正式审查） |
| reviewed_tip | `—`（尚未取得正式结论） |
| 合并 tip | `—`（未合并到 `main`） |
| 审查请求 | `docs/superpowers/reviews/manual-agent/T05-review-request.md` |

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
| 任务 | T05；C4 `RunFence`/`ExecutionContext`/`SegmentOutcome`/`CompletionDecision`/`PlanAdoptionProposal` 纯类型；C5 `AttemptRequest`/`StepAttempt`/`AttemptResult`/`BudgetLedger`/`BudgetStatus`、meter 预算账本、未知调用与 `0023_agent_attempts`/`0024_agent_attempt_hardening` 迁移 |
| FR/AC/HN | FR-06、FR-12；AC-06、AC-11（仅追加授权原语）、AC-15（账本层）；HN-04、HN-05（账本层）、HN-14（预算/资金隔离测试） |
| 时间 | 2026-11-11（首轮实现 + 正式审查修复） |
| 任务状态 | `verified`（实现、F1–F4 修复、聚焦、SQL、阶段、静态、迁移链和最终后端 full 均完成） |
| review_status | `awaiting_review`（等待用户转交原审查助手对修复版本的复审；本行不是正式通过） |
| reviewed_tip | `—` |
| implementation tip | `bd2a59df2e323248046db33ac929cd5d5d8c1063`（`fix: harden agent attempts and budget settlement`，复审修复 tip） |
| 首轮 implementation tip | `249a8adc3769c9576015c7ff4a4edaa3e1798a6b`（`feat: account for agent attempts and cumulative budgets`） |
| base | `4d1af68fc704f50b21b9f9b0619b446f315f66d6`（`main`） |
| 改动 | 累计代码 `4d1af68..bd2a59d`，15 个文件，+4231 / -6；复审修复 `249a8ad..bd2a59d`，9 个文件，+567 / -22；新增 `segments.py`、`attempts.py`、`budget.py`、`agent_attempt_repository.py`、`models/agent_attempts.py`、`0023_agent_attempts.py`、`0024_agent_attempt_hardening.py` 和三组纯/SQL 测试 |
| 公共接口 | `RunFence`、`ExecutionContext`、`SegmentOutcome`、`CompletionDecision`、`PlanAdoptionProposal`；`AttemptCategory`/`AttemptStatus`、`AttemptRequest`、`AttemptResult`、`StepAttempt`、`TokenUsage`、`logical_step_id`、`attempt_transition_allowed`；`BudgetLimits`、`BudgetStatus`、`BudgetLedger`、initial/hard/effective/validate 函数；`SqlAlchemyBudgetLedger`；复审修复新增 `validate_send_fits` 与 `released` meter 状态 |
| 依赖/迁移 | 无新增依赖；`0023_agent_attempts` 建立四表与基础触发器，`0024_agent_attempt_hardening` 前向加固发送前 failed 时间约束与 meter/state 形状；迁移 head 为 `0024_agent_attempt_hardening`；未迁移业务库；T06/T07/T13 计划迁移号顺延为 `0025`/`0026`/`0027` |
| 验证 | 复审修复后聚焦 40 passed；阶段回归 184 passed；后端 full `verification=passed`，1182 collected / 1182 passed / 0 failed / 0 skipped / 0 collection errors；Ruff/格式/Pyright/架构门禁通过；迁移 head `0024_agent_attempt_hardening` |
| 未验证 | T07 实际领取/心跳/租约恢复/子进程终止；T06 AP-05 用户审核与差异展示；T09/T10/T11 工具、MCP、模型实际发送接线；T14 产物持久化与 HTTP；T16 前端；真实供应商 usage/回执真实性、真实模型质量；业务库迁移；完整 Compose/浏览器/HTTP e2e |
| 遗留 | T05 停止在修复复审门槛；未取得原审查助手对修复版本的正式通过前不开始 T06/T07 |

### T05 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 首轮预期红 | `backend/`（隔离工作区） | `uv run --locked --no-sync pytest tests/agent_runs/test_segments.py tests/agent_runs/test_attempts.py tests/agent_runs/test_budget.py tests/persistence/test_agent_attempts.py -q` | 4 collection errors（缺少 `app.agent_runs.segments/attempts/budget` 等），退出 1；符合测试先行预期 |
| 复审修复预期红 | `D:\t05\backend` + 临时 PostgreSQL 17 | F1–F4 新增回归直接执行 | F1 `mark_sent` 未拒绝；F2 新围栏返回 `attempt_not_found`；F3 `settle` 返回 `invalid_attempt_transition`；F4 直接 SQL 未报错；4 failed，退出 1；已按真实 SQL 复现 |
| 复审修复聚焦 | `D:\t05\backend` + 临时 PostgreSQL 17 | `uv run --locked --no-sync python -m pytest tests/agent_runs tests/persistence/test_agent_attempts.py -q --basetemp=..\.tmp\pytest\t05-review-focus` | 40 passed，退出 0；证据 `D:\t05\.tmp\quality\t05-review-focus.log` |
| 复审修复阶段回归 | `D:\t05\backend` + 临时 PostgreSQL 17 | `uv run --locked --no-sync python -m pytest tests/agent_runs tests/persistence/test_agent_attempts.py tests/persistence/test_agent_runs.py tests/persistence/test_migrations.py tests/security tests/governance -q --basetemp=..\.tmp\pytest\t05-review-stage` | 184 passed，退出 0；证据 `D:\t05\.tmp\quality\t05-review-stage.log` |
| 复审修复后端 full | `D:\t05` + 临时 PostgreSQL 17 | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t05-review-fix-full.json` | `verification=passed`；1182 collected / 1182 passed / 0 failed / 0 skipped / 0 collection errors；证据 `D:\t05\.tmp\quality\manual-agent-t05-review-fix-full.json` |
| 静态检查 | `D:\t05\backend` | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`python -m pyright` | 全部通过；Pyright 0 errors / 0 warnings |
| 架构门禁 | `D:\t05\backend` | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=38`，`findings=[]`，退出 0 |
| 迁移链 | `D:\t05\backend` | `uv run --locked --no-sync python -m alembic heads` | `0024_agent_attempt_hardening (head)`，退出 0 |

首轮 full 的 1175 passed 证据仍保留在 `manual-agent-t05-full-backend-final.json`；复审修复后以 1182 passed 报告为准。首轮 full 曾受宿主环境变量和 Windows 长路径临时目录影响，最终在隔离环境与短路径下通过；两次失败已保留记录，未删改，不计入最终通过证据。

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

复审修复提交：`bd2a59df2e323248046db33ac929cd5d5d8c1063`（`fix: harden agent attempts and budget settlement`），范围 `249a8ad..bd2a59d`，9 个文件，+567 / -22；累计代码范围 `4d1af68..bd2a59d`，15 个文件，+4231 / -6。复审修复后聚焦 40 passed、阶段回归 184 passed、后端 full 1182 passed / 0 failed / 0 skipped，迁移 head 为 `0024_agent_attempt_hardening`。正式审查状态仍为 `awaiting_review`，`reviewed_tip=—`；尚未取得原审查助手对修复版本的正式通过结论。

### T05 环境说明

- 隔离工作区从 `main` 的 `4d1af68` 创建，分支 `t05-agent-attempts-budget`；未修改 `main`，未推送、未合并、未部署。
- 使用独立 `.venv`（锁定依赖 68 包）和临时 PostgreSQL 17 容器；`TEST_DATABASE_URL` 只在进程环境注入，地址为固定测试库/受限角色，通过 `check_test_database` 只读身份预检，未指向业务库；未打印连接串。
- 验证进程内移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`，未修改 `.env` 或业务配置；pytest 临时根使用工作区内目录，避免不可写用户临时目录。
- 前端未改动；full 使用 `--component backend`，未执行前端 lint/typecheck/Vitest/build、浏览器 e2e 或 http-e2e；未调用真实模型、未访问私有账户、未修改业务库、未发起真实交易请求；测试资金/用量/回执均为合成资料。

## 后续接续规则

1. T00 已由原审查助手正式通过，`reviewed_tip` 为 `f870de1`，并以 fast-forward 方式合并到 `main`。
2. T01 已由原审查助手正式通过，`reviewed_tip` 为 `159a43b`，代码/复审文档已 fast-forward 合并到 `main`；当前状态为 `verified`/`approved`。
3. T02 已由原审查助手正式通过，`reviewed_tip` 为 `8835a1d`，代码/复审文档已 fast-forward 合并到 `main`；当前状态为 `verified`/`approved`。
4. T03 经三轮 P2 修复后，用户于 2026-11-10 传回正式通过结论（`reviewed_tip=8d75a7a`）；代码/复审文档以 fast-forward 合并到 `main`，当前为 `verified`/`approved`。
5. T04 首轮审查 P2 修复后，用户于 2026-11-10 传回原审查助手正式通过结论（`reviewed_tip=0df86fe`）；代码/复审文档以 fast-forward 合并到 `main`，合并 tip 为 `35617bf`，当前为 `verified`/`approved`。
6. T05 首轮正式审查判定 4 项 P2 不通过；已完成 F1–F4 复现、修复和 `0024_agent_attempt_hardening` 迁移，修复聚焦 40、阶段回归 184、后端 full 1182 passed，当前自测 `verified`、正式审查 `awaiting_review`（`implementation tip=bd2a59d`，审查请求 `docs/superpowers/reviews/manual-agent/T05-review-request.md`）。取得原审查助手对修复版本的正式通过前不开始 T06/T07，也不自行标记正式通过。
7. 后续每个审查单元继续执行“实现/自测 → 审查包 → 原审查助手正式结论 → 放行”的门槛，开发自测不能替代正式审查。
