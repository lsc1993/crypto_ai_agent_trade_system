# AI 加密货币研究工作台（前端）

这是一个仅用于研究、回测界面验证和人工复盘的本地工作台。它不保存交易所凭证，不连接真实账户，也没有下单、撤单、资金划转或提现能力。

## 公开行情模式（推荐）

默认仍为 `mock`。若需要查看 BTCUSDT 与 ETHUSDT 的 Binance USDⓈ-M **公开**行情，可在两个独立 PowerShell 窗口中启动：

```powershell
Set-Location backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
Set-Location frontend
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
$env:VITE_DATA_MODE = "market-api"
npm run dev -- --host 127.0.0.1 --port 4173
```

然后在 Chrome 打开 `http://127.0.0.1:4173`。此模式只发出固定白名单内的公开 `GET` 请求，使用 10–60 秒短缓存；市场摘要和 K 线来自公开数据，报告、交易日志与复盘仍为 Mock。它不会读取账户、持仓或余额，不会提交订单，也不需要或使用 API Key、Secret、Passphrase 或私钥。

关闭前端后，临时环境变量会随该 PowerShell 会话结束而消失；请不要把它们或任何凭证写入 `.env`。可在后端目录运行下列只读检查，确认公开源连通：

```powershell
uv run python scripts/check_public_market.py
```

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
