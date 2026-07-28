# Binance 公开市场数据接入设计

**状态：已确认**
**日期：2026-07-28**

## 目标

在不使用 API Key、不读取账户、不保存账户信息且绝不具备交易执行能力的前提下，将 BTCUSDT、ETHUSDT 的公开 USDⓈ-M 合约市场数据安全显示到现有研究工作台。首期只替换市场和仪表盘的行情数据；报告、交易日志与复盘统计继续明确使用 Mock 研究数据。

## 方案选择

首期采用“后端只读适配器 + 前端混合数据模式”。浏览器只请求本系统的 FastAPI 服务；FastAPI 通过一个受限的 Binance USDⓈ-M 公共 REST 适配器获取数据。相比浏览器直连，后端适配器可以集中控制允许的端点、超时、缓存、限流、错误归类、数据校验与来源审计。

不在本阶段引入 CCXT、WebSocket、数据库、新闻抓取、账户 API、下单接口或任何密钥。`httpx` 已是后端生产依赖，因此本阶段不新增运行时依赖。

官方资料：

- [Binance USDⓈ-M Futures API introduction](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/Introduction)
- [Binance Futures public market-data REST API](https://developers.binance.info/docs/derivatives/usds-margined-futures/market-data/rest-api/Symbol-Price-Ticker-v2)

## 允许的外部访问

适配器的唯一上游是 `https://fapi.binance.com` 的公开 USDⓈ-M 市场数据接口。它仅允许读取下列数据类别：

- 24 小时价格、涨跌和成交量；
- 15m、1h、4h、1d K 线；
- 标记价格与资金费率；
- 未平仓量。

所有外部路径在适配器中以固定 allowlist 表示；业务层只能传递 `BTCUSDT`、`ETHUSDT` 和四个固定周期。适配器不得接受任意 URL、任意标的或任意查询参数，也不得定义、调用或暴露账户、订单、杠杆、资金、提现或私有用户数据方法。

## 架构与数据流

```text
React feature pages
        │ WorkbenchApi
        ▼
HybridWorkbenchApi
 ├── HttpWorkbenchApi（仅市场读接口）
 └── MockWorkbenchApi（报告、日志、复盘、设置）
        │ HTTP /api/v1/market…
        ▼
FastAPI route → MarketQueryService → BinanceUsdmPublicMarketGateway
                                           │ 公开 REST、无认证
                                           ▼
                                     Binance USDⓈ-M
```

`HybridWorkbenchApi` 是客户端组合层，不让页面感知数据来源差异：

- `getDashboard()` 以现有 Mock 仪表盘承载近期报告和新闻占位，仅用后端的真实市场摘要覆盖 BTCUSDT、ETHUSDT 市场卡片；
- `getMarket()` 使用后端真实行情，返回空新闻集合并显示“新闻源尚未启用”，不能填入 Mock 新闻伪装为真实内容；
- 报告、交易日志、复盘和设置仍委托 `MockWorkbenchApi`，现有 Mock 标识与重置行为不变。

新增显式模式 `VITE_DATA_MODE=market-api`。`mock` 仍为默认值，`api` 保留给未来“所有 WorkbenchApi 操作均由后端实现”的阶段。`market-api` 失败时必须展示来源不可用或过期状态，不得悄悄回退为 Mock 行情。

## 服务端契约

首期只公开下列无副作用端点：

```text
GET /api/v1/markets?symbols=BTCUSDT,ETHUSDT
GET /api/v1/market/{symbol}?timeframes=15m,1h,4h,1d
```

响应复用现有前端的 `MarketSummary`、`MarketDetail`、`CandleSeries` 和 `DataFreshness` 形状：所有金额、价格、数量、成交量、资金费率和未平仓量均为十进制字符串；所有时间均为带 `Z` 的 UTC RFC3339 字符串。每个市场响应必须包含固定来源名称、`observedAt`、`fetchedAt` 与新鲜度状态。

服务端不得返回上游原始 JSON。它先以 Pydantic 模型校验数据，再转换成公共 DTO。非法标的、非法周期和超过上限的周期数在请求进入网关前以客户端可读的错误信封拒绝。上游超时、429、5xx、无效载荷和地区不可用分别映射为稳定的 `{code, message, details}` 错误，不泄露请求头或未过滤上游正文。

## 新鲜度、缓存与降级

缓存是进程内的短时性能与防限流机制，不是持久化事实存储。缓存键由数据类别、标的和周期组成；并发相同读取必须合并为一个上游请求。每项缓存保留来源、观测时间、抓取时间和状态。

建议的首期阈值：市场摘要 10 秒、衍生品指标 30 秒、K 线 60 秒。HTTP 超时使用短且显式的预算；只对幂等的公开读取做有限次退避重试，并在 429 时遵守 `Retry-After`。缓存超过阈值可显示为 `stale`，网络或校验失败显示为 `failed` 或 `missing`；不得用旧数据冒充实时数据。

## 质量与安全验证

实现必须先用固定夹具和假网关完成测试，正常测试不得访问 Internet。最少覆盖：

- 允许标的/周期与 URL allowlist；
- 字符串到 `Decimal` 的精确转换、毫秒时间戳到 UTC 转换、K 线排序与未收盘 K 线过滤；
- 缓存命中、并发合并、过期、429、超时、5xx、无效 JSON 与地区不可用；
- API 错误信封、来源和时间字段；
- `market-api` 模式下市场真实、研究数据仍为 Mock 的组合行为；
- 页面可访问性、来源/新鲜度文本和市场数据不可用状态；
- 静态安全扫描，确保适配器没有凭证字段、私有端点或订单/账户方法。

最终验收在人工明确启动 `market-api` 时进行一次受控的公开数据连通性检查。连通性失败不修改数据、不切换默认模式，页面必须仍可在 `mock` 模式运行。

## 分阶段交付

1. 建立严格的市场领域 DTO、只读网关接口、错误类型与夹具测试。
2. 实现 Binance 公共 REST 适配器、短时缓存和限流/失败归类。
3. 提供 FastAPI 市场端点，并用假网关完成 API 集成测试。
4. 完成 `market-api` 前端组合适配器、来源标识、降级页面和端到端测试。
5. 在本地受控环境完成公开数据连通性验收，保持 Mock 为默认模式。

后续的持久化历史数据、WebSocket、新闻源、研究 Agent、账户同步或任何交易执行都属于独立设计与明确确认事项，不能由本设计隐式开启。
