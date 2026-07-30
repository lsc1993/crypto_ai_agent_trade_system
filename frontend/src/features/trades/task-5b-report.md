# Task 5b — 交易日志实现报告

## 范围

- 变更仅位于 `frontend/src/features/trades/**`。
- 未修改 router、styles、domain、shared API/Mock、依赖或其他功能目录。
- 页面只记录人工研究与复盘，不包含下单、开仓、自动交易或真实执行入口。

## TDD 证据

- RED：生产组件缺失时，三个测试文件因模块无法导入而失败。
- GREEN（2026-07-23 21:04）：
  - `TradeListPage.test.tsx`
  - `TradeEditorPage.test.tsx`
  - `TradeForm.test.tsx`
  - 共 3 个测试文件、27 个测试全部通过。
- 审查补充覆盖：
  - 编辑查询键包含已解析的交易 ID。
  - 同一挂载树内切换交易 ID 会重新查询并重置表单。
  - 列表提供安全的新建入口、关联报告 ID 与交易腿数。
  - 客户端 accounting 校验明确标注为即时提示，后端仍为最终权威。

## 实现摘要

- 列表页严格解析已知查询参数，忽略未知参数，并解析 API 分页响应。
- 编辑页通过 `listTrades({ page: 1, pageSize: 100 })` 查找记录，不引入不存在的 `getTrade`。
- `linkedAnalysisReportId` 仅映射到 `TradeDraft.linkedReportId`；重复值、无效值及其他参数不会进入草稿。
- 表单边界先进行严格 envelope 校验，再由 `tradeDraftSchema` 校验 DecimalString、UTC 时间、唯一交易腿 ID 与仓位 accounting。
- `decimal.js` 只用于显示预览，提交保留原始 DecimalString。
- 新建、更新及列表 API 返回值都经过运行时 schema 解析。

## 门禁说明

- `npm run typecheck`：通过。
- `npm run lint`：本功能发现的异步事件绑定错误和热更新警告均已修正；最近一次运行无诊断。
- `git diff --check -- frontend/src/features/trades`：通过。
- 后续 Vitest 重试遭遇共享工作区并发进程争用 Vite `.vite-temp`（EPERM / 超时）；未删除缓存，也未放宽测试超时。完整串行 `test/typecheck/lint/build` 由根任务在并行子任务结束后统一复验。

TRADES_GREEN_READY
