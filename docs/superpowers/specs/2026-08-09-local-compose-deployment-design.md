# 本地 Compose 部署设计

**日期：** 2026-08-09
**状态：** 已确认设计，待实施计划

## 目标与范围

为现有研究、回测和模拟盘工作台提供可重复的本地 Compose 启动方式。首期只编排 PostgreSQL、FastAPI API 与 React 前端；不增加常驻 `market-worker`、定时采集、任务队列、真实交易或任何交易所私有访问。

该部署面向单用户本机使用。每次模拟盘操作仍按现有逻辑在用户点击时读取公开行情，不要求 Docker 持续运行。关闭 Compose 后保留本地数据库卷；不实现数据重置、恢复或导入。

## 架构

```text
浏览器
  └─ http://localhost:8080
       └─ frontend (Nginx)
            ├─ 静态 React 文件
            ├─ /api/*     → api:8000
            └─ /healthz   → api:8000

api (FastAPI) ── PostgreSQL (Compose 内网、postgres_data 命名卷)
```

### 服务责任

| 服务 | 责任 | 主机端口 | 数据持久化 |
| --- | --- | --- | --- |
| `postgres` | 唯一事实存储；UTC 配置与健康检查 | 不默认发布 | `postgres_data` 命名卷 |
| `api` | 前向迁移、版本化 HTTP API、研究/回测/模拟盘业务 | `8000` | 不直接管理卷 |
| `frontend` | 静态页面、同源本地 API 反向代理 | `8080` | 无 |

`postgres` 仅通过 Compose 网络暴露，以避免与用户现有的 `Crypto_trade` 容器和主机端口发生冲突。API 在数据库健康后启动；启动脚本只执行 `alembic upgrade head`，迁移失败即停止，禁止任何 schema drop、reset 或数据清理逻辑。前端等待 API 健康后启动。

Nginx 只代理 `/api` 和 `/healthz` 到 Compose 内部 API，不代理 Binance、OpenAI 或其他外部服务。前端生产配置固定为 `VITE_DATA_MODE=api` 和 `VITE_API_BASE_URL=http://localhost:8080`，使浏览器始终只访问本机同源入口，不依赖容器内部 DNS 名称。

## 配置与安全边界

- 根目录 `.env.example` 只包含变量名与非敏感示例值：`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`DATABASE_URL`、`APP_ENV`、`LOG_LEVEL`、`CORS_ALLOWED_ORIGINS`。
- 用户在本地创建且不提交根目录 `.env`；本计划不创建、读取、打印或修改真实 `.env`、`backend/.env`、`frontend/.env` 或凭证。
- API 的数据库连接串仅作为容器环境变量使用，不能写入日志、测试夹具、浏览器配置或文档示例。
- 镜像构建上下文通过 `.dockerignore` 排除 `.env`、`.git`、本地虚拟环境、`node_modules`、构建测试产物及本地数据目录。
- Compose 不声明 API Key、Secret、Passphrase、私钥、交易所账户或任何真实订单/资金权限；应用仍保持仅公开行情、研究、回测与模拟盘边界。
- 文档只提供 `docker compose down` 作为停止方式，不给出带卷删除的停止命令。

## 用户操作与故障语义

常规启动为：

```powershell
docker compose up -d --build
```

前端入口为 `http://localhost:8080`；健康检查可通过 `http://localhost:8000/healthz` 和同源 `http://localhost:8080/healthz` 访问。停用服务使用：

```powershell
docker compose down
```

PostgreSQL 未就绪、迁移失败或 API 失败时，相关服务保持失败或未就绪，UI 使用既有安全错误状态显示本地 API 不可用，不能回退为虚构的 Mock 持久化数据。Compose 不会自动启动后台采集，也不会修改用户已有的独立 PostgreSQL 容器。

## 测试与验收

实现遵循测试先行：

1. 配置测试解析 Compose 与镜像定义，断言仅存在 `postgres`、`api`、`frontend`，存在命名卷和健康检查，不存在后台采集、特权挂载或交易所凭证变量。
2. 启动脚本测试断言只允许前向迁移，迁移失败不能启动 API，并且没有清库、drop 或 reset 命令。
3. 前端部署测试断言 Nginx 只提供静态文件及本地 `/api`、`/healthz` 代理，不直接连接外部市场或模型服务。
4. 本机容器冒烟验收依次执行 `docker compose config`、`docker compose build`、`docker compose up -d`、健康检查和 `docker compose ps`。测试与验收不得清除数据卷。

本阶段明确不包含 Playwright 跨功能端到端测试、只读备份导出、代码安全扫描与交付验收记录；这些将在 Compose 稳定后作为独立的第二阶段计划实施。

## 自检

- 范围仅覆盖按需的本地三服务部署；没有隐含后台运行、采集或执行能力。
- 容器网络、端口、前端构建配置与现有 API 路径一致；浏览器只经由本机前端入口访问 API。
- 数据卷保留规则与“不得删除用户数据”一致；不会触碰现有独立 PostgreSQL 容器。
- 配置、日志、镜像与文档均不包含真实凭证或连接串。
