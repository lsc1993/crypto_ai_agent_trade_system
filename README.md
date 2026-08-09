# AI 加密货币交易系统

本地 Compose 仅用于可审计的开发与模拟验证；真实下单不支持。

## 三步启动

1. 手动从根目录的 `.env.example` 创建未跟踪的根目录 `.env`；不要提交该文件，也不要填入交易所凭据。
2. 在根目录运行：`docker compose up -d --build`
3. 打开 [http://localhost:8080](http://localhost:8080)。

详细运行、升级与排障请见 [本地部署指南](docs/local-deployment.md)，使用范围与安全边界请见[运行边界](docs/operational-boundaries.md)。

## 质量检查

后端：`cd backend` 后运行 `uv run ruff check .`、`uv run pyright`、`uv run pytest`。

前端：`cd frontend` 后运行 `npm run lint`、`npm run typecheck`、`npm run test -- --run`、`npm run build`。
