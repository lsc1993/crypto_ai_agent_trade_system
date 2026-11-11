# T05 修复版本复审

- 日期：2026-11-11。
- reviewed implementation tip：`bd2a59d`；当前文档 tip：`bd800e8`。
- 代码修复范围：`9c4c105..bd2a59d`；同时核对原实现 `249a8ad` 与首轮报告。
- 结论：**不通过**。F1–F3 的修复逻辑可接受；F4 原复现路径已被约束覆盖，但全部 INSERT 形状防护仍有一项 P2 缺口。未授权进入 T06/T07，也未改写进度状态。

## R1 / P2：settled 次数行的 NULL actual 绕过 INSERT CHECK

位置：`backend/alembic/versions/0024_agent_attempt_hardening.py:49`；同步 ORM：`backend/src/app/infrastructure/persistence/models/agent_attempts.py:220`。

次数 meter 的 settled 分支为 `state = 'settled' AND actual_amount = 1`，缺少显式非空判定。PostgreSQL CHECK 仅拒绝 FALSE，NULL/UNKNOWN 也会通过。当 meter=model_calls/tool_calls/transport_calls、state=settled、actual_amount=NULL 时，完整形状表达式得到 NULL，因此 INSERT 被放行。既有 `actual_amount IS NULL OR actual_amount >= 0` 约束也不会拦截。触发器中的 settled 非空校验仅作用于 UPDATE，无法补上 INSERT 路径。

复现路径（待真实 PostgreSQL 执行）：在 migrated_database 内准备有效 run、step、attempt 外键，使用尚无相同 meter 行的新 attempt，直接插入 BudgetReservationRecord：

```text
meter = 'model_calls'  # tool_calls/transport_calls 同理
state = 'settled'
reserved_amount = 1
actual_amount = NULL
attempt_id = 有效且该 meter 尚未使用的 attempt UUID
其余身份与 UTC 时间字段合法
```

预期 INSERT 被 `ck_budget_reservation_shape` 拒绝；现有 CHECK 表达式不能拒绝。聚合仍会回退使用 reserved，导致“已结算但无实际量”的非法历史与 UPDATE 行为不一致。此项属于数据库防护缺口，正常仓储结算路径当前会写 actual=1。

建议在次数 settled 分支显式要求 `actual_amount IS NOT NULL AND actual_amount = 1`，或对完整形状表达式要求 `IS TRUE`，同步 ORM，并新增无唯一键冲突的 INSERT 拒绝回归。

附带测试问题：`test_sql_rejects_actual_on_unsettled_token_reservation_and_bad_insert` 最后一次 INSERT 使用已经由 tool reserve 创建的 `(tool_attempt.attempt_id, 'tool_calls')` 唯一键，同时只断言宽泛 DBAPIError；即使移除形状约束，也可能因唯一索引失败而保持测试绿色。应使用全新且合法的外键/唯一键，并核对 SQLSTATE=23514 或实际约束名。该测试问题并入 R1 修复，不另计问题数。

## F1–F4 核对结果

- **F1：代码修复可接受。** validate_send_fits 使用严格大于比较，不再次增加 prepared 自身的预留；输入/输出恰好等于上限允许，越限拒绝；活动安全余量仍独立检查。mark_sent 在 run 锁内调用，拒绝会回滚并保持 prepared。新增纯测试覆盖恰好等于、输入/输出超限与活动边界；SQL 测试覆盖原 98560 复现、保持 prepared、追加后发送。
- **F2：代码修复可接受。** _lock_fenced_run 仍先校验当前 workspace/run/revision/owner/epoch/租约。仅 settle 使用 allow_historical，mark_sent 仍限定当前 revision；历史 in_flight/unknown 必须有非空回执及已核验断言才能进入终态结算。旧 worker 不因该改动恢复写权限。历史 prepared 的结算被拒绝为 invalid_attempt_transition，而发送被拒绝为 attempt_not_found；材料若声称两者均为 attempt_not_found，应澄清，但不构成权限放开。
- **F3：代码修复可接受。** 当前修订 prepared 仅可无 usage/回执地结算为 failed，sent_at 保持 NULL，写 settled_at；所有预留转 released，预算聚合及 sent 计数排除发送前失败。历史 attempt 行保留，重试仍用 len(attempts) 实施每逻辑步骤最多两次限制。两次预检失败不会因释放预算获得第三次同键尝试。
- **F4：部分完成。** reserved/charged/unknown/released Token 的 actual 必须 NULL，INSERT 与 UPDATE 均受 CHECK 限制；charged 次数 actual=1 合法。原 actual=0 复现已被代码覆盖；R1 的 settled 次数 NULL 分支仍需补齐。

## 迁移及范围

已核对 0023 相对原 implementation tip 无变化。0024 串行接 0023，仅前向修改约束与 reservation 触发器函数，无删除历史行操作。0025/0026/0027 是尚未实现的 T06/T07/T13 计划编号，顺延可接受；两份计划/契约中的对应名称已同步。既有资料说明的未验证边界继续有效，包括 T07 恢复枚举/子进程终止、T06 人工审核、实际发送、供应商回执真实性、真实产物持久化、HTTP/前端及业务库迁移。

## 本轮验证与证据限制

本轮独立执行（目录 `D:\t05\backend`）：

- `uv run --locked --no-sync python -m pytest tests/agent_runs -q`：**23 passed**。
- `uv run --locked --no-sync python -m alembic heads`：唯一 head 为 **0024_agent_attempt_hardening**；这是迁移链静态发现，不是数据库升级验证。
- `uv run --locked --no-sync python -m scripts.check_test_database`：**退出 1，blocked，缺少显式 TEST_DATABASE_URL**。未从 .env 读取授权，因此本轮没有独立运行真实 SQL、行锁或触发器复现，R1 是 SQL 三值逻辑与完整约束静态核对结论。

已读取开发端 `.tmp/quality/t05-review-focus.log`（40 passed）、`t05-review-stage.log`（184 passed）及 `manual-agent-t05-review-fix-full.json`（1182 collected/passed、0 failed/skipped/collection errors，测试数据库检查 passed）。测试使用 migrated_database，夹具会执行显式数据库预检及迁移，失败会 fail 而非 skip；这些材料与真实 PostgreSQL 执行相符，但日志没有完整逐项 SQL 跟踪，本报告不能把开发端记录写成审查端独立复跑通过。

本轮只新增此复审报告，未修改实现、迁移、凭证或进度文件。修复 R1 后请提供新 tip 与聚焦真实 SQL 回归证据，再申请复审。
