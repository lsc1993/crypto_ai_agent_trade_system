# T10 正式审查结论

- 审查日期：2026-11-17。
- review_status：`changes_requested`。
- reviewed_tip：`690d726892ea6deaf14c77a705ca06539fb7cd0a`。
- reviewed_tree：`6221e3f0d03721883a6dc713d49143ddfc94d62a`。
- base：`b80071c`；包括辅助测试提交 `619fe2c`，参考审查包 `dad1515` / `dcf6326`。
- 结论：当前版本不通过正式审查；修复并复审前不进入 T11。开发 self_test=verified 与本结论分开记录。

## 必须修复

### R1 / P1：Content-Type 参数可绕过 JSON 响应上限

位置：`backend/src/app/infrastructure/mcp/transport.py:63`。

`_bounded_response` 只要 Content-Type 包含 `text/event-stream` 就跳过限长。合法的 `application/json; profile="text/event-stream"` 因而被当成 SSE；官方 SDK 则按 `application/json` 前缀进入 JSON 路径并调用 `response.aread()`，在校验前完整缓冲正文。64 KiB 保证由此失效，异常本地端点可造成超额内存消耗。

独立真实 loopback TCP 复现：官方 Client 的 modern 协议模式下，将 JSON 和 SSE 上限都设为 128 字节，返回上述 Content-Type 和 100126 字节的合法 tools/list JSON（`_meta.padding` 长 100000）；`list_tools()` 正常返回全部 padding，实际请求计数为 1。降低上限只是缩小复现，不改变绕过机制。

要求：解析媒体类型，仅对精确的 `text/event-stream` 使用 SSE 路径，其余响应仍增量限长；补充带参数的 JSON 成功/错误响应与真实 SDK 回归，证明超限在完整缓冲前被拒绝。

### R2 / P2：非 ASCII 鉴权头触发异常而非拒绝认证

位置：`backend/src/app/infrastructure/mcp/registry.py:75`。

`hmac.compare_digest` 的字符串参数只接受 ASCII。HTTP 原始头可以携带高位字节，Starlette 将其解码成字符串；例如 `is_authorized('Bearer ÿ')` 会抛出 `TypeError: comparing strings with non-ASCII characters is not supported`。鉴权中间件未捕获该错误，请求会进入服务器异常路径，而不是约定的 401；未认证请求可反复制造错误日志。

要求：在常量时间比较前将非 ASCII 候选视为认证失败，或使用明确的字节比较；补充原始非 ASCII Authorization 头的 HTTP 测试，断言 401 且策略读取器未被调用。

## 验证与范围

- 工作区起始干净；提交范围、22 文件差异和 implementation tree 已核对。
- 在 `backend/` 独立执行：`uv run --locked --no-sync pytest tests/mcp tests/tooling/test_mcp_lifespan.py tests/security tests/agent/interactive -q --basetemp=../.tmp/pytest/t10-review-independent`，178 passed。
- 首次使用系统默认临时目录时有 52 个夹具权限错误、126 passed；更换工作区临时目录后全部通过。该环境问题不列为实现缺陷。
- 已读取 `.tmp/quality/t10-full-backend-final3.json`：记录 full 1394 passed、0 skipped。此次审查未独立重跑数据库 full、前端或生产装配验收，不能将历史报告视为本次独立执行。
- `619fe2c` 将测试过期时间与仓储固定 NOW 对齐，范围仅测试夹具，接受该辅助修复。
- `call` 委托网关、`handle` 实现既有处理器协议的取舍可接受；生产装配仍须保证只由网关进入处理器。
- 任务级传输预算、SDK 断流重连故障注入、模型图及生产 lifespan 尚未证明；保留审查请求所列 T11/T14 接线与验收义务，本结论不认可生产工具循环已经交付。

本次仅新增审查结论，不修改实现、不合并、不部署、不进入 T11。
