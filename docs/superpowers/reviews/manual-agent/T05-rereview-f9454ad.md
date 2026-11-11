# T05 最终修复复审

- 日期：2026-11-11。
- reviewed_tip：`f9454adab111218eaa8bc5880b37987031c11bb7`。
- 当前文档提交：`3cf1185`；工作区开始时干净。
- 结论：**通过 T05 模块代码复审**。原 F1–F4 及剩余 R1 无未关闭的阻断发现。结论基于代码核对、本轮独立聚焦验证及已核对的开发端 PostgreSQL 回归证据；不表示审查端独立执行了 PostgreSQL 全量验收，也不表示后续模块已经验收。

## R1 关闭依据

1. 新增 `0025_agent_attempt_shape_fix.py`，串行接 `0024_agent_attempt_hardening`，仅前向替换同名形状 CHECK；0023/0024 没有被改写。
2. 次数 meter 的 settled 分支显式使用 `actual_amount IS NOT NULL AND actual_amount = 1`，NULL 会得到 FALSE，不再借 SQL 三值逻辑放行 INSERT。charged+actual=1 分支保留。ORM 与新迁移的完整约束表达式已通过脚本核对完全一致。
3. 直接 SQL 测试改用没有既有 meter 的合成 attempt，避免唯一键冲突掩盖形状校验；断言 SQLSTATE=23514，且错误文本包含 `ck_budget_reservation_shape`。
4. 新增真实 SQL 用例检查 settled+NULL 拒绝、settled+1 与 charged+1 合法。专用新用例直接覆盖 model_calls；tool_calls/transport_calls 共用同一约束分支，本轮另对三种 meter 的上述三种组合检查完整 SQL 表达式，共 9 组，结果符合预期。该表达式检查使用 SQLite，不冒充 PostgreSQL 集成验证。
5. 该提交的生产变更只有新迁移及 ORM 约束/注释；F1 发送准入、F2 历史回执对账、F3 发送前失败和 released 语义没有再次改变，前轮对这些修复的可接受结论保持有效。

## 验证

本轮独立运行，目录 `D:\t05\backend`：

- `uv run --locked --no-sync python -m pytest tests/agent_runs -q`：**23 passed**。
- `uv run --locked --no-sync python -m alembic heads`：唯一 head **0025_agent_attempt_shape_fix**；不等于实际升级业务库。
- `uv run --locked --no-sync ruff check src/app/infrastructure/persistence/models/agent_attempts.py tests/persistence/test_agent_attempts.py alembic/versions/0025_agent_attempt_shape_fix.py`：**All checks passed**。
- 只读脚本核对迁移/ORM 约束文本一致，并对三种次数 meter 的 settled+NULL、settled+1、charged+1 检查完整 SQL 表达式：**9 组通过**，仅 SQLite 表达式验证。

开发端证据已读取：

- `.tmp/quality/t05-r1-focus.log`：41 passed。
- `.tmp/quality/t05-r1-stage.log`：185 passed。
- `.tmp/quality/manual-agent-t05-r1-full.json`：backend full passed；1183 collected / 1183 passed / 0 failed / 0 skipped / 0 collection errors；test-database 和 migration-heads 检查均 passed。

当前审查进程仍无显式 TEST_DATABASE_URL，因此没有独立复跑 PostgreSQL、行锁、触发器或完整 full。真实 SQL 通过结果来自上述开发端记录及实际使用 migrated_database 的回归代码，不写成本轮独立实跑。

## 边界与后续

若已有库被直接 SQL 写入非法 settled+NULL 历史，新 ADD CONSTRAINT 会拒绝升级；不得自动伪造 actual 或删除审计行。当前未升级业务库。

本通过结论仅针对 T05 当前 reviewed_tip；T06 的人工审核、T07 的 claim/heartbeat/恢复枚举及真实子进程终止、实际模型/工具/MCP 发送、供应商回执真实性与请求绑定、产物持久化、HTTP/前端及业务库迁移仍按原材料列为后续未验证项。可按项目流程推进下一审查单元，不代表这些能力已完成。

本轮只新增此报告，未修改实现、配置、进度状态，未提交、合并、推送或部署。
