# 工作台汇总 API 设计

**日期：** 2026-08-09
**状态：** 已确认设计，待规格审阅

## 目标与范围

为 Compose 的纯 API 前端模式补齐研究工作台所需的只读汇总接口，消除
`getDashboard()` 当前的“端点未定义”错误。接口展示 BTCUSDT、ETHUSDT 的
公开行情、最近保存的研究报告，以及空的资讯列表。

本功能不接入新的资讯服务、不会读取交易所私有信息、不会生成订单，也不会
写入数据库。资讯区域沿用前端既有的空状态。

## 接口与数据流

新增 `GET /api/v1/dashboard`：

```text
浏览器
  → /api/v1/dashboard
  → DashboardService
  ├─ MarketQueryService: BTCUSDT、ETHUSDT 公开行情
  └─ AnalysisReportRepository: 最近 5 条已保存报告
  → { markets, news: [], recentReports, generatedAt }
```

`generatedAt` 为带 UTC 时区的服务器生成时间。报告表没有数据时，
`recentReports` 为空数组而不是错误。公开行情源不可用时，接口复用既有标准
市场数据错误；报告存储不可用时复用既有报告存储错误。

## 前端集成

`HttpWorkbenchApi.getDashboard()` 请求 `/api/v1/dashboard`，并用既有
`dashboardSnapshotSchema` 解析。`DashboardPage` 的加载、错误、资讯空态与
报告空态不变。Compose 继续固定 `VITE_DATA_MODE=api`，不回退到 Mock 或
Hybrid 数据。

## 测试与验收

1. 后端路由测试验证两个市场、最近报告、空资讯和 UTC 生成时间；另验证行情
   不可用时的标准错误。
2. 前端 HTTP 客户端测试验证请求路径与响应 schema 解析。
3. Compose 运行后，通过 `http://localhost:8080/api/v1/dashboard` 验证返回
   汇总 JSON；研究工作台展示市场与报告，资讯显示空态，不显示数据加载失败。

## 安全与运行边界

- 仅访问既有公开行情网关；不添加交易所密钥、私有 API、后台任务或自动交易。
- 路由为只读，不创建报告、不写入交易或账户数据。
- 无数据库 schema 或依赖变更。

## 自检

- 范围只解决 Dashboard API 缺口，没有包含资讯采集或界面重构。
- 数据源、错误语义、返回字段和验收路径均明确，与既有前端 schema 一致。
- 没有待定项、真实凭证、外部服务新增或破坏性操作。
