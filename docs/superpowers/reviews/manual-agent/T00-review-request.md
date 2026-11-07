# T00 复审请求：治理内核与规范迁移

- 任务/模块：T00（D0）治理内核、测试与规范迁移。
- 复审轮次：第 2 轮（上一轮正式结论为“暂不放行”；本轮已通过）。
- 审查单元：仅 T00；不含 T01 及后续策略、RAG、持久任务、工具、规划或前端新功能。
- 执行环境：DeepSeek Harness；会话提供的底层模型标识为 `deepseek-flash`。精确构建/版本号未在本会话暴露：未知。
- 请求日期：2026-11-07。
- 开发自测状态：**verified**（聚焦、quick、带专用测试库 full 及旧报告/审计 SQL 回归均通过）。
- 正式审查状态：**approved**（2026-11-07 用户传回原审查助手正式通过结论，reviewed tip 为 `f870de1`）。
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0；根/后端/前端 AGENTS.md 为迁移后当前版本。

## 1. 工作区、分支与提交范围

| 项目 | 值 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main`，仍为 `4847ebc`，本轮未合并） |
| 隔离工作区 | `D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t00` |
| 分支 | `task/manual-agent-t00` |
| base | `4847ebcfc4d7530bae3f94c753c945507f5b8879` |
| 上一轮受审 tip | `63b1202fbbf918a83d1a1e895a74ea6c436454c7`（正式结论：暂不放行） |
| 复审 implementation tip | `f870de19c8c1434ce6e089e970a67a46607572c7`（`fix: preserve legacy rejection log error type`） |
| implementation tree | `89f690bb5e7850e17cb73f91e4f45e80a299c4f1` |
| 审查包文档提交 | 本复审请求、进度更新及状态注记另行提交；见交付回复，不计入 implementation tip |

复审代码范围：

```powershell
git -C D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t00 diff `
  4847ebcfc4d7530bae3f94c753c945507f5b8879..f870de19c8c1434ce6e089e970a67a46607572c7
```

该范围共 42 个文件：首轮 37 个文件 + 审查包 5 个文档；复审修复 `f870de1` 修改其中 2 个文件。首轮已受审的 `63b1202` 仅作历史锚点；复审应看完整 T00 范围及本次修复。

### 关键文件 blob 指纹

| 路径 | blob |
| --- | --- |
| `backend/src/app/governance/contracts.py` | `a2acb1a5616c14c6391e655dfb75279bababf7c6` |
| `backend/src/app/governance/runtime.py`（复审后） | `93b844d037f4f02686fdd17c5def282a31680a90` |
| `backend/src/app/governance/audit.py` | `5ddb91e6a2f9f1f49e392fbbc7172f5f23c3571a` |
| `backend/src/app/governance/policy.py` | `24fdfaf2a843dbfc0c0ebe07c766df9d2e6c4e10` |
| `backend/src/app/governance/market_research.py` | `4c9c796bbddda844b3abfb4f4a24f8f3e49de999` |
| `backend/src/app/governance/technical_research.py` | `fe266a4d765984abd6aabc623ccc305b50f855e5` |
| `backend/scripts/check_architecture.py` | `68c6e4a15d3375b4d73db2352f3decb04e9811ef` |
| `backend/tests/security/test_architecture_gate.py` | `b4ea4bb20a9766b4ca37c70abfb31abbbbd011e6` |
| `backend/tests/governance/test_contracts.py` | `d1cf826c0d6264447e17a9b26074e0993bec0849` |
| `backend/tests/governance/test_runtime.py`（复审后） | `6854e629710ea6917c6dccbfacfd0ccff7fc3ba4` |
| `AGENTS.md` | `86119be7f077528c2183ac0d2e63fbdd09065f19` |
| `docs/project-status.md` | `af41c027e20014088411321f3ae954cf7590c22b` |

## 2. 首轮审查意见处理

### P1（验收阻塞）：数据库兼容性验证

**已处理。** 启动临时 PostgreSQL 17 容器，按项目防护契约创建固定专用库 `crypto_research_test` 和受限角色 `crypto_research_test_runner`，通过 `python -m scripts.check_test_database` 的只读身份/权限预检后执行：

- 带专用测试库的根目录 `full`：`verification=passed`；后端 **1017 passed / 0 failed / 0 skipped**；前端测试和 build 均通过。
- 旧报告/审计读取 SQL 聚焦回归：**34 passed / 0 failed / 0 skipped**，覆盖 `test_harness_audit_repository.py`、`test_agent_research_repository.py`、`test_report_repository.py`、`test_technical_report_repository.py`、`test_migrations.py`、历史综合研究捕获和流程评估历史。
- 证据：`.tmp/quality/manual-agent-t00-full-with-db-final.json`、`.tmp/quality/t00-db-regression-final.json`、`.tmp/quality/pytest-f3846618cbbd4390984311fb15c52415.json`。

测试库只用于本次验证，未指向业务库；验证完成后回收临时容器。无 schema 变化，但本轮不再用“无 schema 变化”替代数据库回归。

### P2（兼容性偏差）：策略拒绝日志 error_type

**已处理。** `runtime.py` 的 `harness_run_rejected` 日志继续写入历史值 `HarnessPolicyViolation`，不随 Python 类名改为 `GovernancePolicyViolation`。新增 `test_rejection_log_keeps_historical_harness_error_type` 守护事件名、`error_type` 和 phase；先复现失败（实际 `GovernancePolicyViolation`），修复后通过。日志事件名、字段集合和值现在与旧观测协议一致；审查包不再声称“仅 Python 命名变化”，改为“Python 命名变化，持久化/线协议/观测值保持”。

### P3（证据注记）：quick 不包含前端构建

**已处理。** 复审材料将 quick 证据限定为后端测试、静态检查和前端 lint/typecheck/Vitest；前端 `build` 仅归入 full。进度文件同步更正。最终 quick 为后端 **918 passed**，final full 含前端 build。

## 3. 改动清单（相对首轮）

### 3.1 首轮已完成内容

- `backend/src/app/harness/` 的 7 个模块迁至 `app/governance/`，旧包删除；公共类型改为 `GovernanceRuntime`、`GovernancePolicy`、`GovernanceCapability`、`GovernanceRunKind`、`GovernanceRunRequest`、`GovernancePolicyViolation`、`GovernedWorkflow`，三个 `Harnessed*` 服务改为 `Governed*`。
- 更新 24 个导入/装配/API/持久化/测试消费者；仓库代码已无 `app.harness` 导入。
- 4 个治理测试迁至 `tests/governance/`；新增治理门禁拒绝测试和序列化值兼容断言。
- `HarnessAudit*` 存储类型、表名、审计事件值、运行类别值、日志事件名、HTTP 错误码保留。

### 3.2 本轮复审修复

- `backend/src/app/governance/runtime.py`：拒绝日志 `error_type` 固定为历史值 `HarnessPolicyViolation`，附兼容说明。
- `backend/tests/governance/test_runtime.py`：新增拒绝日志兼容测试；复审聚焦测试 114 passed。
- `docs/superpowers/execution/2026-11-06-manual-agent-progress.md`：记录新 tip、full/数据库回归证据、P1/P2/P3 处理及“保持 implemented”的审查指令。
- 本审查请求：更新复审范围、证据、P1/P2/P3 处理结果和剩余限制。

## 4. FR/AC/HN 映射

| 项 | 本轮关系 | 证据 |
| --- | --- | --- |
| AC-18 | 覆盖（含 SQL） | 旧 `HarnessAudit*`/表/序列化值保留；专用测试库 full 及旧报告/审计读取回归 34 passed。 |
| HN-01 | 支撑/回归 | 每次运行仍先写请求、再核验策略/标的/能力；门禁继续拒绝交易/外部 IO。 |
| HN-12 | 支撑/回归 | 安全日志、API 错误、持久化投影未扩大；拒绝日志值保持历史兼容。 |
| FR-03 / FR-12 | 仅路径支撑 | 为后续受控工具/恢复提供 `governance/` 路径；T00 不新增工具循环、恢复或运行权限。 |

## 5. 接口、依赖与迁移影响

- **Python 公共导入路径变化**：`app.harness.*` → `app.governance.*`；公共类型名改为 Governance/Governed，仓库内消费者已同步，不保留旧导入别名。
- **HTTP/持久化/观测契约**：错误码、错误消息、审计表名、审计事件值、`run_kind` 值、`harness_*` 日志事件名及拒绝日志 `error_type` 均保持原样。
- **数据库迁移**：无 schema 变更；`alembic heads` 仍为 `0018_technical_report_runs`。
- **依赖**：无新增/升级；`uv.lock` 未改。
- **装配**：`main.py`、`api/errors.py`、technical worker、technical reports route、`http_e2e_research.py` 仅更新导入/类型名；运行参数与生命周期未改。
- **回滚**：可回滚本范围；已保存的 `harness_*` 数据仍可由旧/新代码读取。

## 6. 测试执行与结果

执行环境说明：宿主进程继承了生产环境变量（仅列名：`APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`）、`NODE_ENV=production`，以及缺失键的 `GIT_CONFIG_COUNT`。验证进程内移除了这些变量并设置 `NODE_ENV=test`；数据库验证使用独立的临时 PostgreSQL 17（tmpfs、本机回环端口、临时凭据），并通过项目预检。未修改 `.env`、业务配置或业务库。

| # | 目录 | 命令 | 退出码 | 实际结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 1 | `backend/` | `uv run --locked --no-sync pytest tests/harness tests/security -q --basetemp=../.tmp/pytest/t00-baseline-20261107` | 0 | 111 passed（迁移前基线） | 控制台结果；基线提交 `4847ebc` |
| 2 | `backend/` | 首轮新测试命令（治理门禁 + 序列化值） | 1 | 2 failed，符合预期 | 控制台结果 |
| 3 | `backend/` | `uv run --locked --no-sync pytest tests/governance/test_runtime.py::test_rejection_log_keeps_historical_harness_error_type -q --basetemp=../.tmp/pytest/t00-p2-red-20261107` | 1 | 1 failed；实际日志为 `GovernancePolicyViolation`，断言历史值 | 控制台结果 |
| 4 | `backend/` | `uv run --locked --no-sync pytest tests/governance tests/security -q --basetemp=../.tmp/pytest/t00-p2-green-20261107` | 0 | 114 passed | 控制台结果 |
| 5 | `backend/` | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `files_scanned=35`，`findings=[]`，passed | 架构门禁输出 |
| 6 | `backend/` | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 0 | 全部通过；281 files already formatted；0 type errors | 控制台结果 |
| 7 | 仓库根目录 | `uv run --project backend --locked --no-sync python scripts/verify.py quick --report .tmp/quality/manual-agent-t00-quick-final.json` | 0 | `verification=passed`；后端 918 passed / 0 failed / 0 skipped；前端测试通过；**不包含前端 build** | `.tmp/quality/manual-agent-t00-quick-final.json`、`.tmp/quality/pytest-7db80fb92a3c490788cbc92ba027b310.json` |
| 8 | 仓库根目录 | `uv run --project backend --locked --no-sync python scripts/verify.py full --report .tmp/quality/manual-agent-t00-full-with-db-final.json` | 0 | `verification=passed`；后端 1017 passed / 0 failed / 0 skipped；含前端 build | `.tmp/quality/manual-agent-t00-full-with-db-final.json`、`.tmp/quality/pytest-f3846618cbbd4390984311fb15c52415.json` |
| 9 | `backend/` | 旧报告/审计 SQL 聚焦回归命令（见 §2 P1） | 0 | 34 passed / 0 failed / 0 skipped | `.tmp/quality/t00-db-regression-final.json` |
| 10 | `backend/` | `uv run --locked --no-sync alembic heads` | 0 | `0018_technical_report_runs (head)` | 控制台结果 |
| 11 | 仓库根目录 | 本地 Markdown 相对链接扫描（AGENTS/维护/运行/项目状态/复审材料） | 0 | 全部可解析 | 控制台结果 |
| 12 | 仓库根目录 | `git diff --check` | 0 | 无空白错误 | 控制台结果 |

首轮无测试库时 `full` 曾为 `blocked`；该历史结果保留在首轮材料中，已被本轮带库 `full` 的通过结果替代。首次带库运行因宿主 `GIT_CONFIG_COUNT` 残留导致 `git check-attr` 测试误失败（1015/1016），清理该变量后重跑为 1017 passed；该失败未被计为代码通过。

## 7. 未验证项、已知风险与重点审查位置

### 未验证/不在本轮范围

1. `e2e`、`http-e2e` 未执行；T00 未改前端功能，但前端文档有变更。
2. 真实模型质量、产品规则/收益不在 T00 范围，未运行也未声明通过。
3. 未执行推送、合并、部署、业务库迁移或真实交易。

### 已知风险 / 审查重点

1. **命名边界**：`HarnessAudit*` 存储类型、`harness_*` 表/事件/日志名、HTTP 错误码和拒绝日志 `error_type` 均保留历史值；请确认这符合“历史兼容”，而不是应在本轮改变的公共契约。
2. **拒绝日志值**：请复核 `runtime.py` 的 `error_type="HarnessPolicyViolation"` 与新增测试是否真正保持旧筛选规则；该值是刻意的观测协议兼容，不是遗漏重命名。
3. **旧路径完全移除**：仓库代码已无 `app.harness` 导入；历史 specs/plans 仍保留旧名。请核对当前运行文档、AST 门禁和测试是否有遗漏。
4. **门禁覆盖**：`SCOPES` 从 `harness` 改为 `governance` 后，新增测试覆盖交易/HTTP/SQL 和空扫描；请确认不存在“只改目录名但漏掉某类规则”的路径。
5. **行为不变性**：请核对 `GovernanceRuntime` 的审计先写、白名单拒绝、失败关闭、取消处理、哈希稳定值与日志字段。
6. **证据口径**：quick 不含前端 build；full 含 build 和真实测试库回归。请按 §6 的目录与证据复核，不把 quick 当作完整验收。

## 8. 复审请求与结论

请原审查助手对 `4847ebc..f870de1` 的完整 T00 范围（42 文件）及审查包文档提交做独立复审，重点确认：

- P1 的专用测试库 full 与旧报告/审计 SQL 回归是否满足 T00 Step 4；
- P2 的拒绝日志 `error_type` 是否保持历史观测协议，并有有效回归；
- P3 的 quick/full 证据口径已更正，前端 build 仅归入 full；
- 治理内核迁移、类型重命名、存储/HTTP/序列化兼容与 AST 门禁是否仍完整；
- 当前 AGENTS/维护/运行/项目状态文档与代码一致，未把后续能力写成已实现。

**结论（2026-11-07）：** 用户传回原审查助手正式通过结论，`reviewed_tip=f870de1`。T00 已放行；不自动进入 T01，等待用户指定下一审查单元。
