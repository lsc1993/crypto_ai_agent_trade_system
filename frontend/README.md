# AI 加密货币研究工作台（前端）

这是一个仅用于研究、回测界面验证和人工复盘的本地工作台。它不保存交易所凭证，不连接真实账户，也没有下单、撤单、资金划转或提现能力。

## 公开行情模式（推荐）

默认仍为 `mock`。若需要查看 BTCUSDT 与 ETHUSDT 的 Binance USDⓈ-M **公开**行情，可在两个独立 PowerShell 窗口中启动：

```powershell
Set-Location backend
uv run python -m app
```

```powershell
Set-Location frontend
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
$env:VITE_DATA_MODE = "market-api"
npm run dev -- --host 127.0.0.1 --port 4173
```

然后在 Chrome 打开 `http://127.0.0.1:4173`。此模式的市场摘要和 K 线来自公开数据，使用短缓存；综合报告、技术报告、交易日志、复盘、回测和模拟盘均委托本地 HTTP API，各功能仍需相应后端与数据库。它不会读取真实交易所账户，也不需要交易所 API Key、Secret、Passphrase 或私钥。

关闭前端后，临时环境变量会随该 PowerShell 会话结束而消失；请不要把它们或任何凭证写入 `.env`。可在后端目录运行下列只读检查，确认公开源连通：

```powershell
uv run python scripts/check_public_market.py
```

## 模拟盘（本地 API 与 PostgreSQL）

模拟盘是手动触发的、本地持久化的 `BTCUSDT` 模拟账户。它要求后端、PostgreSQL 和公开 Binance 行情在**点击操作时**可用；不需要 Docker 或后台任务持续运行。没有任何自动轮询、定时策略评估或真实执行能力。

先确保后端的 `.env` 已由你在本地安全配置 `DATABASE_URL` 与 `TEST_DATABASE_URL`，然后在后端目录前向迁移数据库（不在文档、命令输出或提交中记录连接串和密码）：

```powershell
Set-Location backend
uv run alembic upgrade head
uv run python -m app
```

在另一个 PowerShell 窗口启动前端。`api` 与 `market-api` 都会把模拟盘请求委托给本地 HTTP API；`mock` 模式会明确提示“模拟盘需要本地 API 与数据库”。

```powershell
Set-Location frontend
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
$env:VITE_DATA_MODE = "api"
npm run dev -- --host 127.0.0.1 --port 4173
```

在浏览器打开 `http://127.0.0.1:4173/paper-trading`，创建初始资金为正十进制数的账户后，才可以手动开多、手动平多或运行一次 SMA 策略评估。每次点击都会先生成结构化意图，再经过确定性风控，并使用一次冻结的**公开**行情快照模拟成交；页面保留订单、成交、账本、快照和审计事件。

模拟盘即时使用快照价格、固定滑点和手续费成交；历史回测仍是“收盘决策、下一根开盘成交”。两者的结果不可直接比较，也不能代表真实盘口、流动性、资金费率、实际部分成交或交易所规则。

该功能不读取交易所账户、余额或持仓，不需要 API Key、Secret、Passphrase 或私钥，也没有真实下单、撤单、资金划转或提现接口。归档仅允许空仓的活动模拟账户，并保留所有历史审计记录。

## Skill 技术研究报告

在报告页进入技术分析，或访问 `/technical-reports`，选择已就绪币种并手动生成。历史详情位于 `/technical-reports/:reportId`，归档币种保留历史读取。新旧报告分别生成和保存。

`api` 与 `market-api` 均通过 HTTP 调用技术报告接口，要求后端与已应用 `0017_technical_reports` 的 PostgreSQL；`mock` 提供带演示标识的模拟报告。页面展示方法来源、量价事实、条件计划、成本假设、无计划原因与降级状态。计划到期根据当前时间提示，历史触发状态保持冻结，不提供自动执行入口。完整口径见[技术报告说明](../docs/technical-reports.md)。

## 本地验证

```powershell
Set-Location frontend
npm run typecheck
npm run lint
npm run test -- --run
npm run build
```

首次运行端到端测试时，安装 Chromium 测试运行时，然后执行：

```powershell
npx playwright install chromium
npm run test:e2e
```

端到端测试会在 1280 px 与 1440 px 两种桌面视口下运行，并将截图保存在被 Git 忽略的 `test-results/` 中，供人工检查。

## 冻结的客户端契约

- 金额、数量、价格、费用和统计指标均为规范的 `DecimalString`；只有图表显示适配器可以临时转换为 `number`。
- 所有时间均为带 `Z` 的 UTC RFC3339 字符串。
- 分页响应固定为 `{ items, page, pageSize, total }`。
- HTTP 错误信封固定为 `{ code, message, details }`，页面不得展示原始上游异常细节。
- 报告流事件使用 `queued`、`running`、`completed`、`degraded`、`failed` 状态。
- 交易日志仅通过 `WorkbenchApi` 的 Mock/HTTP 契约读写；策略、界面和测试均不得调用交易所或真实下单接口。

后续接入 HTTP 实现时，应保持上述契约不变，只替换 API 工厂与 HTTP 适配器，而不是在特性页面中直接接入外部服务。
