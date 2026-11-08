# 实盘手动计划 Agent 开发进度

- 记录日期：2026-11-08
- 文档基线：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0。
- 状态口径：`implemented` 表示代码、文档和自测已落地；`verified` 表示本轮必需验证完成；`approved` 只能记录用户传回的原审查助手正式结论。T00 的 `verified` 与 `approved` 已在复审通过后据实记录；T01 只记录开发自测，不预填正式审查结论。
- 审查口径：`review_status` 由开发执行者维护；`approved` 只能由用户传回原审查助手的正式结论，不能自行填写。

## 当前工作区

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main`；T00 已于 `6f293fe` 合并） |
| 隔离工作区 | `D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t01` |
| 分支 | `task/manual-agent-t01` |
| base | `6f293fec8d47541ae001afdd3bb4295f298f0cdb`（`main`，T01 开始时工作区干净） |
| implementation tip | `8e73ace0cbdaa099190ed011d0eac7e9f7ac6d3b` |
| tree | `7c128843a51a83495d907ee3fae6362b2d4a12c1` |
| 上一轮受审 tip | `f870de19c8c1434ce6e089e970a67a46607572c7`（T00 正式通过） |

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
| 任务状态 | `verified`（实现、聚焦、SQL 迁移回归和后端 full 已完成；不等于正式审查通过） |
| review_status | `awaiting_review`（待原审查助手审查） |
| reviewed_tip | —（等待用户传回原审查助手结论） |
| 改动 | 17 个文件：新增公共类型、证据 epoch、策略契约/端口/服务、技术规则适配器、SQL 目录仓储、0019 迁移及 3 组测试；修改模型注册入口 |
| 公共接口 | `VersionRef`、`ArtifactRef`、`ProductKey`、`DecimalText`、`PageQuery`/`VersionPage`；`EvidenceEpoch`/`EvidenceItem`；`StrategyDraft`/`StrategyVersion`/`PriceCandidate`/`StrategyEvaluation`；`StrategyCatalog`/`StrategyEvaluator`/`StrategyService`；`TechnicalStrategyEvaluator`；`SqlAlchemyStrategyCatalog` |
| 依赖/迁移 | 无新增依赖；新增前向迁移 `0019_strategy_catalog`（strategy_definitions/strategy_versions/strategy_catalog_requests 与发布不可变触发器）；迁移 head 为 `0019_strategy_catalog`；未迁移业务库 |
| 验证 | 纯契约/评估器聚焦 15 passed；加既有技术引擎 63 passed；SQL 目录 5 passed；SQL+迁移 21 passed；后端 full 1037 passed / 0 failed / 0 skipped；架构门禁 38 文件 0 findings；静态检查全绿 |
| 未验证 | 前端、HTTP API、浏览器 e2e、真实模型质量、真实知识/RAG、T12+ 规划计算、T03/T18 产品规则、业务库迁移；未执行真实策略算法或收益评估 |
| 遗留 | 等待原审查助手审查；不自动开始 T02，不自行标记 `approved` |

### T01 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 基线 | `backend/` | `uv run --locked --no-sync pytest tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t01-baseline-20261108` | 48 passed，退出 0 |
| 首轮预期红 | `backend/` | `uv run --locked --no-sync pytest tests/research/strategies tests/persistence/test_strategy_catalog.py -q --basetemp=../.tmp/pytest/t01-red-20261108` | 3 collection errors（缺少新模块），退出 1；符合预期 |
| 纯契约/评估器聚焦 | `backend/` | `uv run --locked --no-sync pytest tests/research/strategies -q --basetemp=../.tmp/pytest/t01-contracts-20261108d` | 15 passed，退出 0 |
| 聚焦回归 + 既有引擎 | `backend/` | `uv run --locked --no-sync pytest tests/research/strategies tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t01-focus2-20261108` | 63 passed，退出 0 |
| SQL 目录 | `backend/` | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_strategy_catalog.py -q --basetemp=../.tmp/pytest/t01-db-20261108` | 5 passed，退出 0；含发布不可变触发器 UPDATE/DELETE、请求幂等、归档、组合冻结 |
| SQL + 迁移链 | `backend/` | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_migrations.py tests/persistence/test_strategy_catalog.py -q --basetemp=../.tmp/pytest/t01-db2-20261108` | 21 passed，退出 0 |
| 宽范围无库回归 | `backend/` | `uv run --locked --no-sync pytest tests/agent tests/research tests/security tests/governance -q --basetemp=../.tmp/pytest/t01-broad-20261108b` | 447 passed，3 errors（3 个数据库用例因未显式提供 `TEST_DATABASE_URL` 在夹具预检报错，非断言失败；随后 full 带库覆盖） |
| 后端 full（最终代码） | 仓库根目录 | 临时 PostgreSQL 17 + `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t01-full-backend-final3.json` | `verification=passed`；后端 1037 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t01-full-backend-final3.json` |
| 架构门禁 | `backend/` | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=38`，`findings=[]`，退出 0 |
| 静态检查 | `backend/` | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 全部通过，退出 0 |
| 迁移链 | `backend/` | `uv run --locked --no-sync alembic heads` | `0019_strategy_catalog (head)`，退出 0 |

### 环境说明

- 验证进程继承宿主的生产环境变量（仅列变量名：`APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`）以及缺失键的 `GIT_CONFIG_COUNT`。为复现项目测试默认值，只在验证进程内移除这些变量，未修改 `.env` 或业务配置。
- 专用测试库为临时 PostgreSQL 17 容器（tmpfs、本机回环随机端口、随机临时凭据），通过项目 `check_test_database` 身份与权限预检后使用；未指向业务库，未修改业务库。验证完成后回收容器与临时数据。
- 首次后端 full 因宿主 `CORS_ALLOWED_ORIGINS` 覆盖默认开发来源而失败 1 项；清理该变量后重跑 full 为 1037 passed。代码未因该环境覆盖修改。
- 前端未在本轮改动；本轮 full 使用 `--component backend`，未执行前端 lint/typecheck/Vitest/build，也未执行浏览器 e2e 或 http-e2e。
- 未调用真实模型、未访问私有账户、未修改业务库、未发起真实交易请求。

## 后续接续规则

1. T00 已由原审查助手正式通过，`reviewed_tip` 为 `f870de1`，并以 fast-forward 方式合并到 `main`。
2. T01 当前 `review_status=awaiting_review`，`reviewed_tip` 为空；不得自行标记正式审查通过，也不得自动开始 T02。
3. 下一审查单元须等待用户传回原审查助手对 T01 的正式结论；修复后记录新 tip、变更和验证，再次交审。
4. 后续每个审查单元继续执行“实现/自测 → 审查包 → 原审查助手正式结论 → 放行”的门槛，开发自测不能替代正式审查。
