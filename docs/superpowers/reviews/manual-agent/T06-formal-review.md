# T06 正式代码审查

- 日期：2026-11-12。
- 分支：`t06-agent-interactions`；base：`bbb4e0b`。
- reviewed_tip：`1ec0a72e74682ef17995cfca165967b475f764d8`。
- 审查开始时 HEAD：`442cd6a0920498129b71a3d230ce4bd288e03e7e`，工作区干净；其 backend 内容与 implementation tip 完全一致，后续差异仅为审查包文档。
- 范围：19 个代码/测试文件，+3831/-7；请求见 `T06-review-request.md`。
- 结论：**当前版本不通过，需修复 F1（P2）后复审。** 开发端 verified 与 full 通过证据不替代本结论。

## F1 — P2：合法状态推进可以擦除已记录的审核阶段时间

位置：`backend/alembic/versions/0026_agent_interactions.py:250–281`，特别是状态号检查后直接返回 NEW 的部分；关联状态形状 CHECK 第 97–110 行。

`validate_agent_interaction_update()` 冻结材料、检查单步状态迁移和状态号 +1，却没有保护已存在的 `published_at`、`responded_at`。对一条正常的 answered 待办，下面的更新满足全部现有检查：

```sql
UPDATE agent_interactions
SET status = 'expired',
    state_version = state_version + 1,
    expired_at = clock_timestamp(),
    published_at = NULL,
    responded_at = NULL
WHERE id = :interaction_id AND status = 'answered';
```

expired 的形状约束仅要求 expired_at 非空、applied_at 为空；该记录的发布与响应历史因此被永久擦除。pending→answered 也能夹带任意改写 published_at。`HumanInteraction` 对 expired 的读取校验同样接受被清空的时间。终态更新又被触发器禁止，错误过期/恢复写入后不能通过正常更新修复。这是迁移宣称的数据库审计防护缺口；当前 respond/cancel 方法本身没有主动清空这些字段。

建议保护所有已经写入的阶段时间，禁止改写或清空；只允许本次合法迁移对应的时间从 NULL 首次写入，过期时保留已有发布/响应事实，也不能凭空补出未发生的阶段时间。补充直接 SQL 回归：合法推进夹带改写/清空必须拒绝，正常发布、响应、应用和取消过期仍然成功。上述 SQL 为逐分支静态推导，本轮未在 PostgreSQL 实跑。

现有 `test_interaction_trigger_rejects_skipped_state_and_material_rewrite` 的跳步用例没有填写 responded_at/applied_at，也会被形状 CHECK 拒绝；建议补齐形状并断言具体触发器错误，避免其他约束掩盖迁移检查缺失。此为测试改进建议，不另列生产发现。

## 其余重点核对结果与接缝

- 响应持队列锁→任务行锁→待办锁；取消持任务行锁→待办锁，过程中不再取队列锁。现有路径未发现反向取锁。响应与取消对同一任务串行化；取消先提交时迟到响应不能重开终态。取消采用任务状态号 CAS，响应先提交后，携带旧任务状态号的取消会返回 version_conflict，需要调用方刷新重试。现有取消/响应测试覆盖两个串行顺序，并不等于真实 worker 并发验收。
- prepare 只保存 preparing，响应要求 pending、等待态、当前待办 ID、修订、材料哈希和待办状态号全部匹配。preparing→pending 的发布、等待容量、owner 释放和事件原子性仍须由 T07 实现；本轮没有把它计为已实现或已验证。
- 单活跃待办索引覆盖 preparing/pending/answered；触发器要求合法单步迁移且状态号恰好 +1。除 F1 外未发现新的迁移阻断问题。迁移接在 0025 后，拒绝 downgrade。
- 反馈只记录并唤醒 queued，不提前采纳计划或追加预算；反馈行禁止 UPDATE/DELETE。T07 应通过 answered→applied 与 interaction.applied 表达处理，不能修改反馈行；计划采纳和资金占用还需 T13。
- 消息记录与应用分离，记录在任务行锁内分配序号，应用受当前 worker 围栏及 received 上界限制。普通消息不唤醒等待态、不替代类型化响应。完成时阻止遗漏已记录消息仍是 T07 的提交职责。
- running 取消保留 owner/租约，仅设置取消标记；reserve、mark_sent、append_authorization 均在任务行锁和当前围栏下检查取消。settle/status 保持可用。mark_sent 先于取消提交的调用已获发送准入，取消不能撤回该次准入；真实传输接线与 worker 边界仍需后续验证。
- 过期响应在事务提交 expired 后抛 review_expired；该异常不代表全部回滚。queue_full 时反馈不记录，当前重试语义与请求文档一致，未作为缺陷。

## 验证和证据边界

审查端独立运行，目录 `D:\t06\backend`：

- `uv run --locked --no-sync pytest tests/agent_runs -q -p no:cacheprovider`：**35 passed**。
- `uv run --locked --no-sync python -m scripts.check_test_database`：**blocked**，当前进程缺少显式 TEST_DATABASE_URL。
- `uv run --locked --no-sync alembic heads`：唯一 head 为 **0026_agent_interactions**，不代表已应用迁移。

已读取开发端 `.tmp/quality/manual-agent-t06-full-backend.json`：full/backend 为 passed；1208 collected、1208 passed、0 failed、0 skipped、0 collection errors。该证据属于开发端自测，不是审查端独立重跑。请求中的聚焦和阶段命令/结果亦已与测试代码核对，本轮未独立重跑 PostgreSQL、行锁、触发器、迁移升级或 full。

未验证真实 worker、HTTP/SSE、浏览器、真实模型/工具传输、业务库迁移及部署。仅新增本报告；未修改实现、环境、进度状态，未提交、合并、推送或开始 T07。
