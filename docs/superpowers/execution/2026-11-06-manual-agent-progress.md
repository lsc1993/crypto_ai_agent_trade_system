# 实盘手动计划 Agent 开发进度

- 记录日期：2026-11-07
- 文档基线：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0。
- 状态口径：`implemented` 表示代码、文档和自测已落地，但正式审查尚未通过；本轮即使 full 已通过，也按审查指令保持 `implemented`，不自行标记 `verified` 或 `approved`。
- 审查口径：`review_status` 由开发执行者维护；`approved` 只能由用户传回原审查助手的正式结论，不能自行填写。

## 当前工作区

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main`，未合并本轮改动） |
| 隔离工作区 | `D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t00` |
| 分支 | `task/manual-agent-t00` |
| base | `4847ebcfc4d7530bae3f94c753c945507f5b8879`（`main`，T00 开始时工作区干净） |
| implementation tip | `f870de19c8c1434ce6e089e970a67a46607572c7` |
| tree | `89f690bb5e7850e17cb73f91e4f45e80a299c4f1` |
| 上一轮受审 tip | `63b1202fbbf918a83d1a1e895a74ea6c436454c7`（正式结论：暂不放行） |

## T00：治理内核与规范迁移（D0）

| 项目 | 记录 |
| --- | --- |
| 任务 | T00；后端 `app/harness/` → `app/governance/`，公共类型改为 Governance/Governed 命名 |
| FR/AC/HN | AC-18；HN-01、HN-12（门禁仍拒绝交易/外部 IO/空扫描）；支撑 FR-03/FR-12 的治理内核路径，不宣称新增业务能力 |
| 时间 | 2026-11-07；初始实现 `63b1202`，复审修复 `f870de1` |
| 任务状态 | `implemented`（按审查指令保持；full 与数据库回归已通过，正式复审未完成） |
| review_status | `awaiting_review`（复审） |
| reviewed_tip | `63b1202`（上一轮获“暂不放行”，非通过） |
| 改动 | 7 个治理模块迁移；4 个测试迁移；24 个导入/装配/安全测试文件更新；3 份 AGENTS、3 份运行/维护/状态文档同步；契约/实施计划/设计的当前实施状态注记；新增治理门禁、序列化兼容及拒绝日志兼容测试 |
| 公共接口 | 仅 Python 导入路径和公共类型名改变；HTTP 错误码、审计表/事件值、`HarnessAudit*` 类型、`harness_*` 日志事件名与拒绝日志 `error_type` 值保持不变 |
| 依赖/迁移 | 无新增依赖；无 schema 变更；迁移 head 仍为 `0018_technical_report_runs` |
| 验证 | 治理/安全聚焦 114 passed；架构门禁 35 文件 0 findings；quick 全绿（后端 918 passed，前端 332 passed）；带专用测试库 full 全绿（后端 1017 passed）；旧报告/审计 SQL 聚焦回归 34 passed |
| 未验证 | 浏览器 e2e/http-e2e、真实模型质量、产品规则/收益 |
| 遗留 | 等待原审查助手复审 `f870de1`；复审通过前不进入 T01，不自行升级 `verified` |

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

## 后续接续规则

1. 等待用户把 `docs/superpowers/reviews/manual-agent/T00-review-request.md` 的复审材料转交原审查助手。
2. 收到意见后先核对/复现，再逐条修复并补回归；有新提交时更新本文件的 implementation tip、验证结果和 `review_status`。
3. 只有正式审查通过且本轮必需验证完成后，才把 T00 标记为放行并进入 T01；本轮不自行标记 `verified` 或 `approved`。
