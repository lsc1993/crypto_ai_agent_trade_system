# AI 加密货币交易系统

本地 Compose 仅用于可审计的开发与模拟验证；真实下单不支持。

## 按需市场研究

在“报告”页手动点击“抓取公开行情与英文新闻并分析”，可针对 BTCUSDT 或 ETHUSDT 生成未来 1–3 天的只读研究。输入只来自公开行情与已登记的英文来源（CoinDesk、SEC Press Releases）；报告展示市场研判、关键支撑与阻力、潜在催化事件、风险与失效条件，并链接本次冻结的证据。

DeepSeek 只在本机未跟踪运行时环境提供密钥后参与受限 JSON 格式化；没有密钥时会产生可审计的降级报告。系统不使用模型工具或私有交易所接口，也不提供投资建议、交易指令或真实下单。

## 三步启动

1. 手动从根目录的 `.env.example` 创建未跟踪的根目录 `.env`；不要提交该文件，也不要填入交易所凭据。
2. 在根目录运行：`docker compose up -d --build`
3. 打开 [http://localhost:8080](http://localhost:8080)。

详细运行、升级与排障请见 [本地部署指南](docs/local-deployment.md)，使用范围与安全边界请见[运行边界](docs/operational-boundaries.md)。

## 质量检查

后端：`cd backend` 后运行 `uv run ruff check .`、`uv run pyright`、`uv run pytest`。

前端：`cd frontend` 后运行 `npm run lint`、`npm run typecheck`、`npm run test -- --run`、`npm run build`。
