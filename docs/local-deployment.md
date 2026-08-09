# 本地 Compose 部署指南

## 前置条件

安装并启动 Docker Desktop，确保 Docker CLI 可用。将根目录 `.env.example` 手动复制为本机未跟踪的根目录 `.env`；不要提交它，不要在文档或命令中填写连接字符串、密钥或交易所凭据。

## 首次启动与访问

在仓库根目录执行：

```powershell
docker compose up -d --build
docker compose ps
```

浏览器访问 `http://localhost:8080`。健康检查分别为 API 的 `http://localhost:8000/healthz`，以及由前端代理的 `http://localhost:8080/healthz`。

## 安全升级、停止与排障

进行安全的前向升级时，仍执行 `docker compose up -d --build`。API 启动只会向前应用 Alembic migration；若迁移失败，API 会保持停止状态，不会回退或修改迁移历史。

停止本地服务请执行：

```powershell
docker compose down
```

该操作保留命名的数据库 volume，便于后续继续使用本地数据。遇到启动或健康检查失败时，先执行 `docker compose ps`，再按需使用安全日志命令（例如 `docker compose logs api` 或 `docker compose logs frontend`）诊断；不要删除卷、编辑迁移记录或提供交易所凭据。

Docker 仅按需启动这些本地服务，未引入后台行情采集器或其他后台进程。真实下单不支持。
