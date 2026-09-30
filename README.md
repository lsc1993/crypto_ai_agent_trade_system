# AI 加密货币交易系统

本地 Compose 仅用于可审计的开发与模拟验证；真实下单不支持。

## 按需市场研究

在“报告”页手动点击“抓取公开行情与英文新闻并分析”，可针对 BTCUSDT 或 ETHUSDT 生成中文的只读市场研究。报告先给出市场概况，再分别呈现短期（数天至两周）与长期（数周至数月）观点、关键支撑与阻力、潜在催化事件及风险与失效条件；每项模型观点都链接至本次冻结的证据。

输入只使用公开、只读数据：Binance USDⓈ-M 的公开行情和衍生品指标、[Alternative.me Fear & Greed Index](https://alternative.me/crypto/fear-and-greed-index/)（报告中保留归因），以及已登记的英文 RSS 标题与摘要。RSS 来源固定为 SEC Press Releases、CFTC Press Releases、Federal Reserve Press Releases、U.S. Treasury Press Releases、CoinDesk、Decrypt、Blockworks 和 The Block。单一来源失败会明确显示为部分覆盖，不会用历史数据冒充本次输入。

DeepSeek 只在本机未跟踪运行时环境提供密钥后参与受限 JSON 格式化；在根目录未跟踪的 `.env` 中设置自己的 `DEEPSEEK_API_KEY`，绝不将其复制到代码、日志或提交。没有密钥时会产生可审计的降级报告。系统不使用模型工具或私有交易所接口，也不提供投资建议、交易指令或真实下单。本地问题排查可参考[本地部署指南](docs/local-deployment.md)中的安全 DEBUG 步骤。

## Skill 技术研究

报告页另设技术分析入口，按量价、区间突破和多周期方法生成独立报告。条件满足时给出入场区间、结构止损、目标、成本调整盈亏比与有效期；数据不足或条件不成立时明确不给计划。它不生成订单或调用执行服务。方法来源、计算口径、接口和升级要求见 [Skill 技术研究报告](docs/technical-reports.md)。

## 三步启动

1. 手动从根目录的 `.env.example` 创建未跟踪的根目录 `.env`；不要提交该文件，也不要填入交易所凭据。
2. 在根目录运行：`docker compose up -d --build`
3. 打开 [http://localhost:8080](http://localhost:8080)。

详细运行、升级与排障请见 [本地部署指南](docs/local-deployment.md)，使用范围与安全边界请见[运行边界](docs/operational-boundaries.md)。

## 质量检查

后端：`cd backend` 后运行 `uv run ruff check .`、`uv run pyright`、`uv run pytest`。

前端：`cd frontend` 后运行 `npm run lint`、`npm run typecheck`、`npm run test -- --run`、`npm run build`。
