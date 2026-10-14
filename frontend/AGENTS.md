# 前端开发约定

本文件补充[根目录规则](../AGENTS.md)，不放宽其中的安全边界。命令均在 `frontend/` 执行。

## 结构与契约

- React + TypeScript + Vite；Node 版本范围见 `package.json`，依赖使用 npm 与现有 lockfile。
- `src/features/` 放功能页面，`src/domain/` 放领域类型及 Zod 契约，`src/shared/api/` 放 `WorkbenchApi` 和适配器。页面不直接访问交易所、模型或数据库。
- 变更 API 字段时同步核对后端响应、前端 schema、HTTP/Mock/Hybrid 实现及测试，不用类型断言掩盖契约不一致。
- 金额、价格、数量、费用使用 `DecimalString` 和 `decimal.js`，不得用 `number` 做金融计算；只有图表显示适配允许临时数值转换。
- API 时间采用 UTC RFC3339 字符串，展示层可转换时区；分页为 `{ items, page, pageSize, total }`，错误为 `{ code, message, details }`。

## 行为边界

- 三种数据模式的现状见 [README](README.md)。`market-api` 的报告、交易日志、复盘、回测和模拟盘已委托 HTTP，不能把它们当作纯 Mock。
- 研究币种由目录和准入状态决定；切换币种时处理无效 URL、归档、空目录和迟到请求，不能静默展示另一个币种的数据。
- 动态研究币种不能扩展交易、回测与模拟盘的范围。研究报告只展示事实与有证据的分析，不提供自动执行入口。
- 明确呈现缺失、部分覆盖、失败和降级。不要把 Mock、旧快照或未披露值伪装为实时成功结果。
- 模型失败详情只展示后端提供的安全摘要；不得展示原始响应、Prompt、证据 payload 或密钥。用户输入的研究关键词也是数据，不是执行指令。
- `VITE_*` 配置会进入客户端，禁止放置模型或交易所密钥。

## 验证

功能或修复先写 Vitest/Testing Library 测试，关键交互按需补 Playwright。完成受影响测试后运行：

```powershell
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

端到端入口为 `npm run test:e2e`，配置见 `playwright.config.ts`，需要已安装 Chromium。确认 4173 端口上被复用的服务属于本任务且模式正确；截图、trace 和报告属于本地测试产物，不提交敏感数据。

可重点参考 `src/test/research-symbols.test.tsx`、`src/features/reports/` 中的测试，以及 `src/shared/api/` 的契约测试。新增或改变数据模式、页面操作和报告字段时，同步更新前端 README 与项目状态。
