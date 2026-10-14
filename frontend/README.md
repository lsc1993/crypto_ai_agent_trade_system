# AI 加密货币研究工作台（前端）

这是一个用于公开市场研究、确定性回测、手动模拟盘和人工复盘的本地工作台。它不保存交易所凭证，不连接真实账户，也没有真实下单、撤单、资金划转或提现能力。

## 数据模式与本地启动

`VITE_DATA_MODE` 显式选择数据模式，`VITE_API_BASE_URL` 指向本地后端。不要凭模式名称推断哪些功能是假数据；当前工厂与适配器行为如下：

| 模式 | 数据来源与限制 |
| --- | --- |
| `mock` | 使用 `MockWorkbenchApi` 的本地模拟数据；不等同于已连接数据库或公开源，模拟盘提示需要本地 API 与数据库 |
| `market-api` | 行情、报告、交易日志、复盘、回测和模拟盘委托 HTTP；看板仍组合 Mock 基础内容与远端行情/报告。研究币种方法在远端具备接口时委托远端 |
| `api` | 使用 `HttpWorkbenchApi`，看板和业务功能均请求后端；完整功能需要后端、数据库及相关公开源可用 |

`VITE_MARKET_DATA_SOURCE` 独立选择 `live`（默认，公开行情查询路径）或 `research`（数据库研究快照路径）。持久化快照不是实时行情；实时路径也受后端研究目录准入约束。

完整本地运行优先参考[Compose 部署指南](../docs/local-deployment.md)。若手动启动，先确保数据库和后端运行配置已由用户配置，并按该指南完成前向迁移。在两个独立 PowerShell 窗口中，从仓库根目录分别执行：

```powershell
Set-Location backend
uv run python -m app
```

```powershell
Set-Location frontend
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
$env:VITE_DATA_MODE = "api"
npm run dev -- --host 127.0.0.1 --port 4173
```

然后打开 `http://127.0.0.1:4173`。在“研究币种”页查看或添加通过准入检查的 USDT 永续合约，等待初始同步后，再在行情、看板和报告页使用可研究的币种。报告由用户手动生成；归档保留历史。公开行情不需要交易所凭证，模型密钥仅由后端读取，绝不能放在 `VITE_*` 变量中。

上述进程环境变量会随 PowerShell 会话结束而消失。不要在前端配置中保存任何密钥。可在后端目录运行下列只读检查，确认公开源连通：

```powershell
uv run python scripts/check_public_market.py
```

## 模拟盘（本地 API 与 PostgreSQL）

模拟盘是手动触发的、本地持久化的 `BTCUSDT` 模拟账户。它要求后端、PostgreSQL 和公开 Binance 行情在**点击操作时**可用；Docker 只是可选部署方式。模拟盘没有定时策略评估或真实执行能力；研究币种同步 worker 不执行模拟交易。

先确保后端运行环境已由你安全配置 `DATABASE_URL`，然后在后端目录前向迁移数据库。`TEST_DATABASE_URL` 仅在运行数据库测试时需要；配置文件优先级见部署指南。不在文档、命令输出或提交中记录连接串和密码：

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

`api` 与 `market-api` 均通过 HTTP 调用技术报告接口，当前 v2 要求后端与已应用 `0018_technical_report_runs` 的 PostgreSQL；`mock` 提供带演示标识的模拟报告。页面展示方法来源、量价事实、条件计划、成本假设、无计划原因与降级状态。计划到期根据当前时间提示，历史触发状态保持冻结，不提供自动执行入口。完整口径见[技术报告说明](../docs/technical-reports.md)与[v2 交易计划书](../docs/technical-trading-plan.md)。

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

HTTP 实现已接入。新增功能时同步维护 `WorkbenchApi`、相关 schema 和 Mock/HTTP/Hybrid 适配器，不在特性页面中直接接入外部服务。开发与验证规则见 [AGENTS.md](AGENTS.md)，功能进展与限制见[项目状态](../docs/project-status.md)。

技术报告新增 v2 交易计划书：生成入口提交持久化后台任务，轮询阶段并通过 URL/localStorage 恢复；查询失败仅重试查询。详情先展示立场、等待条件和条件价格计划，再展示分析与审计；旧 v1 详情保留。Mock 明示规则演示，不调用模型。接口和升级说明见[技术交易计划书](../docs/technical-trading-plan.md)。

技术报告详情将当前契约的字段路径、枚举和方法标识统一为中文展示，原始引用在依据详情中保留；历史报告无需重新生成。市场结构采用多周期对照表，完整分析、结构价位和方法指纹可展开，风险与降级提示保持可见。`e2e/technical-reports.spec.ts` 另检查 390 px 手机布局及中文历史内容，不调用真实模型。
