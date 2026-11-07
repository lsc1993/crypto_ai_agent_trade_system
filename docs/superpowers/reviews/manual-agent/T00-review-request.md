# T00 审查请求：治理内核与规范迁移

- 任务/模块：T00（D0）治理内核、测试与规范迁移。
- 审查单元：仅 T00；不含 T01 及后续策略、RAG、持久任务、工具、规划或前端新功能。
- 执行环境：DeepSeek Harness；会话提供的底层模型标识为 `deepseek-flash`。精确构建/版本号未在本会话暴露：未知。
- 请求日期：2026-11-07。
- 开发自测状态：**implemented**（聚焦与 quick 通过；full 的数据库部分阻塞，尚未达到 verified）。
- 正式审查状态：**awaiting_review**；未预填通过，开发模型不自行作出正式审查结论。
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0；根/后端/前端 AGENTS.md 为迁移后当前版本。

## 1. 工作区、分支与提交范围

| 项目 | 值 |
| --- | --- |
| 主工作区 | `D:\project_git\crypto_ai_agent_trade_system`（`main`，仍为 `4847ebc`，本轮未合并） |
| 隔离工作区 | `D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t00` |
| 分支 | `task/manual-agent-t00` |
| base | `4847ebcfc4d7530bae3f94c753c945507f5b8879` |
| implementation tip | `63b1202fbbf918a83d1a1e895a74ea6c436454c7`（`refactor: rename research governance kernel`） |
| implementation tree | `9fab0b2557dd2831da25847b06e29aa8366f4be4` |
| 审查包文档提交 | 生成本文件、进度文件及契约/计划/设计状态注记后另行提交；不把它算入 implementation tip，避免自引用；准确记录见交付回复 |

审查代码范围严格为：

```powershell
git -C D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t00 diff 4847ebcfc4d7530bae3f94c753c945507f5b8879..63b1202fbbf918a83d1a1e895a74ea6c436454c7
```

`63b1202` 只包含 T00；主工作区没有其他未提交改动被纳入。T00 开始时主工作区干净。

### 关键文件 blob 指纹（`git rev-parse 63b1202:<path>`）

| 路径 | blob |
| --- | --- |
| `backend/src/app/governance/contracts.py` | `a2acb1a5616c14c6391e655dfb75279bababf7c6` |
| `backend/src/app/governance/runtime.py` | `fbb3f91d7ae06608bd50a8d8d9fed20bb70f1b89` |
| `backend/src/app/governance/audit.py` | `5ddb91e6a2f9f1f49e392fbbc7172f5f23c3571a` |
| `backend/src/app/governance/policy.py` | `24fdfaf2a843dbfc0c0ebe07c766df9d2e6c4e10` |
| `backend/src/app/governance/market_research.py` | `4c9c796bbddda844b3abfb4f4a24f8f3e49de999` |
| `backend/src/app/governance/technical_research.py` | `fe266a4d765984abd6aabc623ccc305b50f855e5` |
| `backend/scripts/check_architecture.py` | `68c6e4a15d3375b4d73db2352f3decb04e9811ef` |
| `backend/tests/security/test_architecture_gate.py` | `b4ea4bb20a9766b4ca37c70abfb31abbbbd011e6` |
| `backend/tests/governance/test_contracts.py` | `d1cf826c0d6264447e17a9b26074e0993bec0849` |
| `AGENTS.md` | `86119be7f077528c2183ac0d2e63fbdd09065f19` |
| `docs/project-status.md` | `af41c027e20014088411321f3ae954cf7590c22b` |

完整 37 个文件的增删状态见 `git show --stat --summary 63b1202`；renames 使用 `-M`。

## 2. 改动清单

### 2.1 后端治理内核迁移

- `backend/src/app/harness/{__init__,audit,contracts,policy,runtime,market_research,technical_research}.py` 迁至 `backend/src/app/governance/` 同名文件；旧包删除，不保留兼容 shim。
- 公共类型重命名：
  - `HarnessRuntime` → `GovernanceRuntime`
  - `HarnessPolicy` / `HarnessCapability` / `HarnessRunKind` / `HarnessRunRequest` / `HarnessPolicyViolation` → `Governance*`
  - `HarnessWorkflow` → `GovernedWorkflow`
  - `HarnessedMarketResearchService` / `HarnessedTechnicalResearchService` / `HarnessedTechnicalPlanExecutor` → `Governed*`
- `GovernanceRuntime.run(request: GovernanceRunRequest) -> ResultT` 行为沿用原运行时；审批、失败关闭、审计顺序、日志字段和哈希输入未改。
- 存储/线协议兼容：`HarnessAudit*` 类型名、`HarnessEventDetails`、`HarnessEvaluation*`、`HarnessInitiatorKind`、`SqlAlchemyHarnessAuditRepository`、数据库表/事件值、`harness_*` 日志名、`harness_policy_rejected`/`harness_audit_unavailable` HTTP 错误码全部保留。

### 2.2 导入、装配与测试

- 更新 24 个实际导入/装配/持久化/API/测试文件，代码中已无 `app.harness` 导入。
- `tests/harness/{test_audit,test_contracts,test_market_research,test_runtime}.py` 迁至 `tests/governance/`，更新导入、类型名和测试注释。
- `tests/security/test_architecture_gate.py`：门禁扫描范围改为 `governance`；合成违规路径改为 `governance/...`；新增 `test_governance_gate_rejects_trade_io_and_empty_scan`，验证交易/HTTP/SQL 三类违规仍被拒绝、空树不通过。
- `tests/governance/test_contracts.py` 新增序列化兼容断言：`GovernanceRunKind.MARKET_RESEARCH.value == "market_research"`、`TECHNICAL_RESEARCH.value == "technical_research"`。

### 2.3 安全门禁与文档

- `backend/scripts/check_architecture.py`：`SCOPES`、必检文件、规则键由 `harness` 改为 `governance`；ARCH001–ARCH006 规则不变。
- `tests/security/test_agent_dependency_boundary.py`、`test_agent_source_and_secret_safety.py`：扫描目录、测试名和装配断言改为治理内核；仍禁止交易、SQL、HTTP、MCP、模型工具表面。
- 同步 `AGENTS.md`、`backend/AGENTS.md`、`frontend/AGENTS.md`、`docs/ai-maintenance.md`、`docs/operational-boundaries.md`、`docs/project-status.md`：当前路径改为 `governance/`，明确系统级 Harness 与治理内核的区别，并声明 `HarnessAudit*`/`harness_*` 仅为历史兼容值。
- 在实施契约、实施计划和架构设计上补充“T00 已迁移/待审查”的当前状态注记；不改写设计方案或后续任务接口。

## 3. FR/AC/HN 映射与结论

| 项 | 本轮关系 | 证据/说明 |
| --- | --- | --- |
| AC-18 | 覆盖（非 SQL 部分） | 旧 `HarnessAudit*`/表/序列化值保留；非数据库、API、装配与安全测试通过。**PostgreSQL 上的旧报告/审计读取未执行**。 |
| HN-01 | 支撑/回归 | 每次运行仍先写请求、再核验策略/标的/能力；门禁继续拒绝交易/外部 IO。 |
| HN-12 | 支撑/回归 | 安全日志、API 错误、持久化投影未扩大；`HarnessAudit*` 历史值不泄露载荷。 |
| FR-03 / FR-12 | 仅路径支撑 | 为后续受控工具/恢复提供 `governance/` 路径；T00 不新增工具循环、恢复或运行权限，不宣称这些 FR 已交付。 |

T00 不新增用户可见业务功能，不改变审核 AP、交易边界或 research Agent 的隔离范围。

## 4. 接口、依赖与迁移影响

- **Python 公共导入路径变化**：`app.harness.*` → `app.governance.*`；`HarnessRuntime` 等公共类型名改为 Governance/Governed。仓库内消费者已同步；不保留旧导入别名。
- **HTTP/序列化契约**：未改。错误码、错误消息、审计表名、审计事件值、`run_kind` 值、日志事件名保持原样，避免破坏已有客户端、历史审计与观测规则。
- **数据库迁移**：无 schema 变更；`alembic heads` 实测仍为 `0018_technical_report_runs`。
- **依赖**：无新增/升级；`uv.lock` 未改。
- **装配**：`main.py`、`api/errors.py`、technical worker、technical reports route、`http_e2e_research.py` 仅更新导入和类型名；运行参数与生命周期未改。
- **回滚**：可回滚本提交；已保存的 `harness_*` 数据仍可由旧/新代码读取，不存在降级迁移。

## 5. 测试执行与结果

执行环境注意事项：宿主进程继承了生产环境变量（仅列名：`APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`）和 `NODE_ENV=production`。为了按项目测试默认值运行，验证进程内移除了上述后端变量并设置 `NODE_ENV=test`；未修改 `.env`、业务配置或数据库。未设置 `TEST_DATABASE_URL`。

| # | 目录 | 命令 | 退出码 | 实际结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 1 | `backend/` | `uv run --locked --no-sync pytest tests/harness tests/security -q --basetemp=../.tmp/pytest/t00-baseline-20261107` | 0 | 111 passed（迁移前基线） | 控制台结果；基线提交 `4847ebc` |
| 2 | `backend/` | `uv run --locked --no-sync pytest tests/security/test_architecture_gate.py::test_governance_gate_rejects_trade_io_and_empty_scan tests/harness/test_contracts.py::test_governance_run_kind_serialized_values_remain_stable -q --basetemp=../.tmp/pytest/t00-red-20261107` | 1 | 2 failed，符合预期：门禁未扫描 `governance`，`app.governance` 尚未实现 | 控制台结果 |
| 3 | `backend/` | `uv run --locked --no-sync pytest tests/governance tests/security -q --basetemp=../.tmp/pytest/t00-focused-final-20261107` | 0 | 113 passed | 控制台结果 |
| 4 | `backend/` | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `files_scanned=35`，`findings=[]`，`status=passed` | 架构门禁输出 |
| 5 | `backend/` | `uv run --locked --no-sync ruff check .` | 0 | All checks passed | 控制台结果 |
| 6 | `backend/` | `uv run --locked --no-sync ruff format --check .` | 0 | 281 files already formatted | 控制台结果 |
| 7 | `backend/` | `uv run --locked --no-sync pyright` | 0 | 0 errors，0 warnings | 控制台结果 |
| 8 | 仓库根目录 | `uv run --project backend --locked --no-sync python scripts/verify.py quick --report .tmp/quality/manual-agent-t00-quick.json` | 0 | `verification=passed`；后端 917 passed / 0 failed / 0 skipped；前端 332 passed；lint/typecheck/build 通过 | `.tmp/quality/manual-agent-t00-quick.json`、`.tmp/quality/pytest-916befc62be2459b8372a2946160ddd8.json` |
| 9 | 仓库根目录 | `uv run --project backend --locked --no-sync python scripts/verify.py full --report .tmp/quality/manual-agent-t00-full.json` | 1 | `verification=blocked`；`test-database=blocked(environment_not_ready)`；`backend-tests=blocked(prerequisite_not_passed)`；其余检查（含前端 build）通过 | `.tmp/quality/manual-agent-t00-full.json` |
| 10 | `backend/` | `uv run --locked --no-sync alembic heads` | 0 | `0018_technical_report_runs (head)` | 控制台结果 |
| 11 | 仓库根目录 | 本地 Markdown 相对链接扫描（AGENTS/维护/运行/项目状态） | 0 | 全部可解析 | 控制台结果 |
| 12 | 仓库根目录 | `git diff --check` | 0 | 无空白错误 | 控制台结果 |

`.tmp/` 为本地忽略目录，不进入提交；上述证据路径位于隔离工作区。未执行、跳过、阻塞严格区分：本表没有把 blocked 写成 passed。

## 6. 未验证项、已知风险与重点审查位置

### 未验证/阻塞

1. **专用测试库上的 full 数据库部分未执行**：本机 Docker daemon 未运行，无本地 PostgreSQL，也未提供显式 `TEST_DATABASE_URL`；因此 `backend-tests` 在 full 中被阻塞，`tests/persistence/*`、迁移测试、API+SQL 联验、AC-18 的旧报告/审计读取 SQL 证据均为**未验证**。
2. `http-e2e`、`e2e` 未执行；T00 未改前端功能，但 `frontend/AGENTS.md` 与跨端验证说明有文档变更。
3. 真实模型质量、产品规则/收益均不在 T00 范围，未运行也未声明通过。
4. 未执行推送、合并、部署、业务库迁移或真实交易。

### 已知风险 / 审查重点

1. **命名边界**：请重点确认哪些名称应保留。当前保留 `HarnessAudit*` 存储类型、`harness_*` 表/事件/日志名、HTTP 错误码和错误消息，理由是历史兼容；如果审查认为这些也属于本轮应改的公共契约，请指出影响面。
2. **旧路径完全移除**：仓库已无 `app.harness` 导入，但历史 specs/plans 仍保留旧名。请核对当前运行文档、AST 门禁和测试是否有遗漏或误导性路径。
3. **门禁覆盖**：`SCOPES` 从 `harness` 改为 `governance` 后，新增测试证明交易/HTTP/SQL 与空扫描仍被拒绝；请确认不存在“只改目录名但漏掉某类规则”的路径。
4. **行为不变性**：请核对 `GovernanceRuntime` 的审计先写、白名单拒绝、失败关闭、取消处理、哈希稳定值与日志字段是否与原实现一致；聚焦测试已覆盖，但正式审查应复核。
5. **文档一致性**：`AGENTS.md` 和运行/维护文档现在区分“系统级 Harness”和“治理内核”；请确认没有把后续工具循环/规划能力写成已实现。
6. **全量验证缺口**：由于 full 数据库部分阻塞，本轮不能宣称 `verified`。请决定是否要求开发模型在具备专用测试库的环境补跑后再作正式结论。

## 7. 供转交的审查请求

请原审查助手对 `4847ebc..63b1202` 的 T00 改动做独立审查，重点检查：

- 治理内核迁移、公共类型重命名、导入/装配消费者是否完整；
- `HarnessAudit*` 存储契约、错误码、日志名和序列化值的兼容性；
- AST 门禁的规则覆盖与新增空扫描/交易/外部 IO 拒绝测试；
- 当前 AGENTS/维护/运行/项目状态文档与实际代码的一致性；
- 上述未验证项（特别是测试库上的 full 数据库部分）是否构成本轮放行阻塞。

本轮开发自测为 `implemented`，不是正式审查通过；在收到正式结论前不进入 T01。
