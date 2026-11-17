# T09 PostgreSQL 独立验证

## 范围与环境

- 验证日期：2026-11-17。
- 生产实现基线：`063e8a3`；执行工作区 HEAD：`3c458ba`（后续仅文档变化）。
- 本次新增 `backend/tests/persistence/test_tool_gateway.py`，不修改生产实现、依赖、迁移、业务配置或 `.env`；新增测试尚未提交，因此本记录的验证对象是上述提交加本次测试增量。
- 使用独立 PostgreSQL 17 临时容器，数据存于 tmpfs，随机端口仅绑定本机回环地址。仅此临时实例使用 trust 认证；测试连接采用固定受限角色，不将该认证方式用于业务部署。
- 专用库 `crypto_research_test`、角色 `crypto_research_test_runner`，通过项目只读身份和权限预检。连接仅在测试进程注入，不记录连接串；各测试经既有夹具创建、迁移和清理随机 schema。
- 未连接真实模型、MCP、新闻源、交易所私有账户或交易接口；不进入 T10/T11。
- 验证结束后已停止本次临时数据库容器；tmpfs 数据不持久保存，后续复现需重新初始化测试角色和数据库。

## 独立执行结果

命令前置条件：在执行进程中注入专用 `TEST_DATABASE_URL`。以下命令不包含连接信息。

| 检查 | 执行目录与命令 | 结果 |
| --- | --- | --- |
| 数据库预检 | `backend/`：`uv run --locked --no-sync python -m scripts.check_test_database` | passed，真实身份及受限权限通过 |
| C5、片段与实际子进程恢复 | `backend/`：`uv run --locked --no-sync pytest tests/persistence/test_agent_attempts.py tests/persistence/test_agent_segments.py tests/persistence/test_agent_segment_recovery.py -q --basetemp=../.tmp/pytest/t09-sql-live-02` | 33 passed，退出 0 |
| T09 网关 SQL 集成 | `backend/`：`uv run --locked --no-sync pytest tests/persistence/test_tool_gateway.py -q --basetemp=../.tmp/pytest/t09-gateway-sql-agent-02` | 14 passed，退出 0 |
| 后端 full | 根目录：`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/t09-sql-full-20261117.json` | passed，退出 0；1366 collected / 1366 passed / 0 failed / 0 skipped / 0 collection errors；格式、lint、类型、架构、迁移链头及两组离线评估均通过 |

`.tmp/quality/` 为本地未提交产物；复现需要重新准备独立测试实例和进程授权。

## 新增集成测试证明范围

- 合成只读处理器从独立 SQL 会话确认步骤、尝试、发送时间、授权和计量记录已提交，防止未提交发送许可就执行处理器。
- 成功、输出校验失败、处理器异常及超时分支分别正确结算真实步骤/尝试/计量状态，保留关联标识和结果引用。
- 取消、旧 owner、旧 lease epoch、租约过期、修订不匹配和预算耗尽时，不调用处理器，不新增无效步骤。
- 同进程重复成功调用及缓存到期复用只占一次 TOOL 额度；到期观察降级但历史成功记录不改写。
- 网关重建后相同只读输入生成新步骤并重新计费；旧成功或 unknown 记录保留。这是当前已记录的限制，不是跨进程全局去重。
- 发送后协程取消保留 in-flight 及已占用额度；当前恢复 fence 可保守结算为 unknown，同一逻辑步骤不自动重放。
- 在真实结算事务中注入 SQLAlchemy 错误，独立会话确认步骤、尝试、结果引用及 meter 更新整体回滚。

## 证明边界与状态

- 新增网关测试的超时使用合成 `TimeoutError`，证明结算分支，不证明实际超时计时精度；中断使用协程取消，不冒充操作系统进程终止。
- 既有 `test_agent_segment_recovery.py` 单独覆盖真实子进程终止恢复；不将其解释为 T09 完整生产模型工具循环的崩溃恢复验收。
- 新闻 HTTP、真实 MCP、模型驱动图、生产装配、前端/HTTP e2e、公开 artifact 材料化和真实模型质量仍不在本次验证范围。
- 本记录不自动变更 `implemented / awaiting_review`，不代表允许进入下一开发单元。
