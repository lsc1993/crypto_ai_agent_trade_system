# T06 F1 修复复审

- 日期：2026-11-12。
- 分支：`t06-agent-interactions`；base：`bbb4e0bc010b46e0188923c176d7334e2764b241`。
- reviewed_tip：`dea98485ac668fd740a53a7dbe8bb69960fdcefc`。
- 审查开始时 HEAD：`04744295bbed6c013cfa413653c196ca641b6409`；工作区干净，backend 内容与 reviewed_tip 完全一致，后续提交仅为文档。
- F1 代码修复范围：`1ec0a72..dea9848 -- backend`，4 个文件，+286/-5；累计代码范围：19 个文件，+4112/-7。四个修复文件的 SHA-256 与审查请求一致。
- 结论：**通过 T06 模块代码复审。原 F1（P2）关闭，未发现新的阻断问题。** 此结论来自修复代码及测试核对、本轮独立纯测试与静态检查，以及开发端 PostgreSQL/full 证据；不将开发端 verified 直接视为正式通过。

## F1 关闭依据

1. `0026_agent_interactions.py` 的更新触发器在材料、合法状态迁移、状态号 +1 检查之后，对四个阶段时间逐项检查：旧值非空时，新值必须与旧值相同。`IS DISTINCT FROM` 同时覆盖清空和改写，因此原报告的 answered→expired 清空 published_at/responded_at 路径被拒绝。
2. 每种合法推进都显式约束对应阶段时间。preparing→pending 只允许发布；pending→answered 保留发布时间并要求响应时间；answered→applied 保留发布/响应时间并要求应用时间；任何允许的 →expired 都保留已有发布/响应/应用字段，仅新增过期时间。preparing/pending 过期不能夹带新增发布或响应事实。原有单步状态迁移、状态号递增及终态禁止更新规则仍保留。
3. PostgreSQL 回归新增两类检查：answered→expired 擦除历史、pending→answered 改写发布时间都断言具体的 stage time is immutable 错误；正常发布→响应→应用逐阶段成功，并验证最终时间值保留。取消过期通过实际 respond/cancel 仓储路径，核对发布/响应时间不变、expired_at 新增。缺响应时间的推进断言具体阶段时间错误。
4. 原跳步用例已填写 responded_at/applied_at，使形状 CHECK 本可通过，再断言 invalid agent interaction transition；材料改写用例也断言具体不可变错误，避免其他约束掩盖被测逻辑。
5. `HumanInteraction` 对 expired 形状补充“已响应必须已发布”的读取校验；纯测试覆盖该非法形状拒绝和正常历史保留。读取校验不能独立证明历史未被改写，该保证仍由上述数据库触发器承担。
6. 除迁移触发器和读取形状校验外，响应/取消、消息水位、预算 reserve/mark_sent/append_authorization 等实现未变。首轮审查对这些路径的核对结论保持有效。

## 独立验证

执行目录：`D:\t06\backend`。

- `uv run --locked --no-sync pytest tests/agent_runs -q -p no:cacheprovider`：**36 passed**。
- `uv run --locked --no-sync ruff check src/app/agent_runs/interactions.py tests/agent_runs/test_interactions.py tests/persistence/test_agent_interactions.py alembic/versions/0026_agent_interactions.py`：通过。
- 同四个文件的 `ruff format --check`：通过，4 files already formatted。
- `uv run --locked --no-sync alembic heads`：唯一 head 为 **0026_agent_interactions**。
- `uv run --locked --no-sync python -m scripts.check_test_database`：**blocked**，当前进程没有显式 TEST_DATABASE_URL。

当前审查进程未独立运行 PostgreSQL 直接 SQL、行锁、触发器、迁移升级或 full，也没有为此读取凭证或连接业务库。

## 开发端证据及适用范围

已读取 `.tmp/quality/manual-agent-t06-f1-full-backend.json`：full/backend 为 passed，backend-tests 为 **1211 collected / 1211 passed / 0 failed / 0 skipped / 0 collection errors**；test-database、静态、迁移链和离线评估等检查均为 passed。JSON 是开发端运行摘要，不能单独证明每条 SQL 的具体执行过程。

审查请求记载真实 PostgreSQL 17 红测 2 failed / 13 passed、修复后聚焦 51 passed、阶段 380 passed。已核对新增测试确实使用 migrated_database，并执行真实 SQL 更新和实际仓储路径，断言与 F1 相符；上述计数及 PostgreSQL 运行结果归属开发端证据，未写成本轮独立执行结果。

0026 仍处于未合并、未应用业务库的开发阶段，因此本次直接补强原迁移可接受，迁移链不变。**已经应用旧版 0026 的数据库不会因升级到相同 head 而自动替换触发器。** 当前请求明确仅临时测试 schema 使用过旧版且已重建；若后续发现持久环境应用过旧版，需要单独前向修补，不能据本结论宣称其已获得保护。

本结论仅针对 T06 当前 reviewed_tip。T07 的 preparing→pending 原子发布、owner 释放、领取/心跳/恢复和反馈应用，T13 的计划采纳与资金占用，以及 HTTP/SSE、前端、真实传输、业务库迁移和部署仍未验收。可按项目流程转交本正式结论，后续单元须独立验收。

本轮仅新增复审报告，保留首轮报告；未修改实现、环境、进度状态，未提交、合并、推送、部署或开始 T07。
