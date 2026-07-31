# Hybrid 真实报告工作流设计

**目标：** 让 `market-api` 成为日常可用模式：公开市场行情与分析报告使用后端真实数据，同时保留手工交易日志、统计和资讯的 Mock 行为。

## 范围与边界

- 仅修改前端 API 组合层和报告创建后的导航体验；不新增后端路由、数据库迁移、依赖、定时任务或模型调用。
- 市场数据、报告列表、报告详情、报告创建、报告重试和报告 SSE 均通过既有本地后端 HTTP API。
- 交易日志、交易编辑、统计和资讯继续由 `MockWorkbenchApi` 提供，不访问账户、交易所私有接口或交易接口。
- 任何真实报告 HTTP 请求失败时显示既有安全错误状态，禁止回退或伪造 Mock 报告。

## API 组合

`HybridWorkbenchApi` 的第二个依赖从仅包含市场读取的端口扩展为市场和报告读取端口。它继续从 `MockWorkbenchApi` 取得仪表盘布局、资讯、交易日志与统计；从 `HttpWorkbenchApi` 取得市场摘要、市场详情和报告功能。

仪表盘并行读取：

1. Mock 仪表盘骨架与资讯；
2. 后端市场摘要；
3. 后端第一页报告列表（每页 20 条）。

返回的仪表盘保留 Mock 资讯，以真实市场摘要覆盖 `markets`，以真实报告列表覆盖 `recentReports`。生成时间仍由真实市场数据的 `freshness.fetchedAt` 决定。任一真实市场/报告读取失败都向页面传播错误，避免把失效的真实报告静默替换为 Mock 报告。

## 报告创建与导航

定义公共结果契约：

```ts
interface ReportRunCreated {
  analysisId: string;
  reportId?: string;
}
```

`HttpWorkbenchApi` 从既有后端创建/重试响应读取 `analysisId` 与 `reportId`；`HybridWorkbenchApi` 原样转发。`MockWorkbenchApi` 只返回现有的 `analysisId`，因此其生命周期演示不改变。

在真实模式中，后端创建请求完成时报告已持久化。市场页和报告页的生成器收到 `reportId` 后立即导航至：

```text
/reports/{encodeURIComponent(reportId)}
```

路由参数必须仅作为一个路径片段编码。详情页读取该不可变报告；不在 URL 中携带报告正文、证据、配置或凭证。没有 `reportId` 的 Mock 结果仍保留当前页面和 Mock SSE 生命周期。

## 文件边界

| 文件 | 责任 |
| --- | --- |
| `frontend/src/shared/api/workbench-api.ts` | 公开报告创建结果契约。 |
| `frontend/src/shared/api/http-workbench-api.ts` | 从真实报告 API 解析并返回报告 ID。 |
| `frontend/src/shared/api/hybrid-workbench-api.ts` | 混合真实市场/报告与 Mock 交易/资讯。 |
| `frontend/src/features/market/MarketPage.tsx` | 市场页创建成功后的安全详情导航。 |
| `frontend/src/features/reports/ReportGenerator.tsx` | 报告页创建成功后的安全详情导航；仅 Mock 结果订阅生命周期。 |
| 现有 Vitest 文件 | 验证委托、仪表盘合并、无真实回退、自动导航和 Mock 行为。 |

## 错误与验证

- 浏览器继续只调用配置的本地 API Origin；不增加第三方网络请求。
- 当报告列表/详情不可用时，沿用 `PageState` 的通用、安全错误文案，不显示后端内部错误或配置内容。
- 所有新行为测试优先：先让 Hybrid 报告委托、真实仪表盘报告和自动导航用例失败，再实现最小改动。
- 验证命令为 `npm run lint`、`npm run typecheck`、`npm run test -- --run` 和 `npm run build`。

## 非目标

- 不实现完整后端仪表盘聚合 API。
- 不改变报告内容、不可变性、降级规则或数据采集方式。
- 不接入 LLM、新闻源、交易策略、回测、模拟盘、账户、订单或真实交易。
