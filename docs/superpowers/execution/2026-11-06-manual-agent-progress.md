# 实盘手动计划 Agent 开发进度

- 记录日期：2026-11-07
- 文档基线：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0。
- 状态口径：`implemented` 表示代码与文档已落地但部分必需验证未完成；`verified` 还需要专用测试库、故障和阶段验证的真实证据。本文件不把自测写成正式审查通过。
- 审查口径：`review_status` 由开发执行者维护；`approved` 只能由用户传回原审查助手的正式结论，不能自行填写。

## 当前工作区

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main`，未合并本轮改动） |
| 隔离工作区 | `D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t00` |
| 分支 | `task/manual-agent-t00` |
| base | `4847ebcfc4d7530bae3f94c753c945507f5b8879`（`main`，T00 开始时工作区干净） |
| implementation tip | `63b1202fbbf918a83d1a1e895a74ea6c436454c7` |
| tree | `9fab0b2557dd2831da25847b06e29aa8366f4be4` |

## T00：治理内核与规范迁移（D0）

| 项目 | 记录 |
| --- | --- |
| 任务 | T00；后端 `app/harness/` → `app/governance/`，公共类型改为 Governance/Governed 命名 |
| FR/AC/HN | AC-18；HN-01、HN-12（门禁仍拒绝交易/外部 IO/空扫描）；支撑 FR-03/FR-12 的治理内核路径，不宣称新增业务能力 |
| 开始/结束 | 2026-11-07；实现提交 `63b1202` |
| 任务状态 | `implemented`（实现完成；full 因专用测试库缺失而阻塞，未达到 `verified`） |
| review_status | `awaiting_review` |
| reviewed_tip | 未填写（等待原审查助手对 `63b1202` 的正式结论） |
| 改动 | 7 个治理模块迁移；4 个测试迁移；24 个导入/装配/安全测试文件更新；3 份 AGENTS、3 份运行/维护/状态文档同步；契约/实施计划/设计的当前实施状态注记；新增治理门禁与序列化兼容测试 |
| 公共接口 | 仅 Python 导入路径和公共类型名改变；HTTP 错误码、审计表/事件值、`HarnessAudit*` 类型、`harness_*` 日志名保持不变 |
| 依赖/迁移 | 无新增依赖；无 schema 变更；迁移 head 仍为 `0018_technical_report_runs` |
| 验证 | 治理/安全聚焦 113 passed；架构门禁 35 文件 0 findings；quick 全绿（后端 917 passed，前端 332 passed）；full 阻塞于 `test-database`，其余检查通过 |
| 未验证 | 专用测试库上的持久化/迁移/旧报告与审计读取（AC-18 的 SQL 证据）、`.tmp` 中的 full 后端测试、e2e/http-e2e、真实模型质量 |
| 遗留 | 需要在具备显式 `TEST_DATABASE_URL` 的专用 PostgreSQL 环境补跑 full 的数据库部分，并在审查请求列明后才能把任务状态改为 `verified` |

### T00 测试证据

| 检查 | 目录 | 命令 | 结果 |
| --- | --- | --- | --- |
| 迁移前基线 | `backend/` | `uv run --locked --no-sync pytest tests/harness tests/security -q --basetemp=../.tmp/pytest/t00-baseline-20261107` | 111 passed，退出 0 |
| 预期红 | `backend/` | `uv run --locked --no-sync pytest tests/security/test_architecture_gate.py::test_governance_gate_rejects_trade_io_and_empty_scan tests/harness/test_contracts.py::test_governance_run_kind_serialized_values_remain_stable -q --basetemp=../.tmp/pytest/t00-red-20261107` | 2 failed，退出 1；失败原因分别为新路径未扫描/`app.governance` 尚不存在，符合预期 |
| 聚焦绿 | `backend/` | `uv run --locked --no-sync pytest tests/governance tests/security -q --basetemp=../.tmp/pytest/t00-focused-final-20261107` | 113 passed，退出 0 |
| 架构门禁 | `backend/` | `uv run --locked --no-sync python -m scripts.check_architecture` | `status=passed`，`files_scanned=35`，`findings=[]`，退出 0 |
| 静态检查 | `backend/` | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 全部通过 |
| quick | 仓库根目录 | `uv run --project backend --locked --no-sync python scripts/verify.py quick --report .tmp/quality/manual-agent-t00-quick.json` | `verification=passed`；后端 917 passed / 0 failed / 0 skipped；前端 332 passed；证据 `.tmp/quality/manual-agent-t00-quick.json` |
| full | 仓库根目录 | `uv run --project backend --locked --no-sync python scripts/verify.py full --report .tmp/quality/manual-agent-t00-full.json` | `verification=blocked`；`test-database=blocked(environment_not_ready)`，`backend-tests=blocked(prerequisite_not_passed)`，其余检查通过；退出 1（阻塞） |
| 迁移链 | `backend/` | `uv run --locked --no-sync alembic heads` | `0018_technical_report_runs (head)`，退出 0 |
| 文档链接 | 仓库根目录 | 本地 Markdown 相对链接扫描（AGENTS/维护/运行/项目状态） | 全部可解析 |

### 环境说明

- 验证进程继承宿主的生产环境变量（仅列变量名：`APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`）。为复现测试默认值，只在测试进程内移除这些变量，未修改 `.env` 或业务配置。
- 前端测试另设 `NODE_ENV=test`；宿主默认的 `production` 会让 React `test-utils` 走生产构建并报 `React.act is not a function`。
- 本机 Docker daemon 未运行，且无可用本地 PostgreSQL 或 `TEST_DATABASE_URL`；因此不能执行数据库测试，不能把全量 `full` 称为通过。
- 未调用真实模型、未访问私有账户、未修改业务库、未发起真实交易请求。

## 后续接续规则

1. 等待用户把 `docs/superpowers/reviews/manual-agent/T00-review-request.md` 转交原审查助手。
2. 收到意见后先核对/复现，再逐条修复并补回归；有新提交时更新本文件的 implementation tip、验证结果和 `review_status=changes_requested → awaiting_review`。
3. 只有正式审查通过且本轮必需验证（含专用测试库上的 full 数据库部分）完成后，才把 T00 标记为放行并进入 T01。
