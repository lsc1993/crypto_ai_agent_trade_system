# 本地 Compose 部署指南

## 前置条件

安装并启动 Docker Desktop，确保 Docker CLI 可用。将根目录 `.env.example` 手动复制为本机未跟踪的根目录 `.env`；不要提交它，不要在文档或命令中填写连接字符串、密钥或交易所凭据。

如需启用 DeepSeek 研究，在这个未跟踪的本地环境文件中提供 `DEEPSEEK_API_KEY`；仅写入自己的密钥值，绝不把它复制到代码、日志、截图、测试、数据库报告或 Git 提交。模型仅允许 `deepseek-v4-flash` 或 `deepseek-v4-pro`。密钥缺失时，手动研究会保存可审计的降级报告，不会回退到其他模型，也不会发起模型网络请求。

## 首次启动与访问

在仓库根目录执行：

```powershell
docker compose up -d --build
docker compose ps
```

浏览器访问 `http://localhost:8080`。健康检查分别为 API 的 `http://localhost:8000/healthz`，以及由前端代理的 `http://localhost:8080/healthz`。

进入“研究币种”页查看目录。预置币种为 BTCUSDT、ETHUSDT；新增币种需通过公开 USDT 永续合约及数据能力检查，并等待初始同步状态。同步 worker 随 API 启动，在后台处理队列；同步失败或尚未达到研究条件时，页面会显示状态，不能假定币种已经可研究。当前没有独立的手动同步/重试 API，未实现的恢复流程见[项目状态](project-status.md)。归档保留历史报告。

进入“报告”页后，选择已启用且可研究的币种，并点击“抓取公开行情与英文新闻并分析”。该操作按需抓取公开 Binance USDⓈ-M 行情、Alternative.me 情绪读数，以及八个受治理英文 RSS 来源的标题和摘要；另按专题能力采集资金费率和 BTC/ETH 的 Farside ETF 数据。报告提供带冻结证据的中文短期（数天至两周）与长期（数周至数月）观点。单一来源失败会显示覆盖不足，不会回退到旧数据；模型不可用或输出无效时会保存降级报告。该操作不创建交易指令、不访问真实账户，币种同步也不会自动触发研究报告。

## 安全升级、停止与排障

进行安全的前向升级时，仍执行 `docker compose up -d --build`。API 启动只会向前应用 Alembic migration；若迁移失败，API 会保持停止状态，不会回退或修改迁移历史。

停止本地服务请执行：

```powershell
docker compose down
```

该操作保留命名的数据库 volume，便于后续继续使用本地数据。遇到启动或健康检查失败时，先执行 `docker compose ps`，再按需使用安全日志命令（例如 `docker compose logs api` 或 `docker compose logs frontend`）诊断；不要删除卷、编辑迁移记录或提供交易所凭据。

Compose 启动 PostgreSQL、API 和前端。币种同步是 API 进程内消费已排队任务的 worker，不是独立的 Compose market-worker 服务；当前没有定时自动研究或自动交易。真实下单不支持。

## 安全调试研究任务

仅在本地排查一次任务时，临时将未跟踪根目录 `.env` 中的 `LOG_LEVEL` 改为 `DEBUG`，然后重建 API：

```powershell
docker compose up -d --build --force-recreate api
```

在页面手动发起一次研究后，查看生命周期日志：

```powershell
docker compose logs --tail=200 api
```

应只关注 JSON 日志中的 `agent_research_started`、`agent_research_completed` 或 `agent_research_failed`，以及 `analysis_id`、`symbol`、`report_id`、`status`、`phase`、`duration_ms` 和安全的 `error_type` 字段。日志不会包含密钥、完整 Prompt、模型原始响应、新闻全文或证据载荷；不要尝试打印环境变量值。排查结束后将同一未跟踪 `.env` 恢复为 `LOG_LEVEL=INFO`，再重建 API：

```powershell
docker compose up -d --build --force-recreate api
```

模型校验问题还可通过报告/API 的 `validationFailure` 查看安全的字段路径、错误类别和尝试次数，再结合格式重试和正文压缩事件排查；详见 [AI 维护指南](ai-maintenance.md)。安全摘要不能替换为完整模型响应。

## 本地进程与测试配置

不使用 Compose 时，可按[前端说明](../frontend/README.md)分别启动服务；PostgreSQL 仍是持久化功能的前提。后端配置优先读取 `backend/.env`，不存在时回退到根目录 `.env`；环境变量也可提供配置。不要为排障打印配置值，或未经明确要求自动创建、修改这些文件。

`TEST_DATABASE_URL` 只用于专用测试数据库，不是普通启动的必填项。迁移与仓储测试的前提见[后端开发约定](../backend/AGENTS.md)。执行质量检查不能替代部署后的迁移、公开源连通与页面流程验收。

技术计划书 v2 升级需同时部署前后端和迁移 `0018_technical_report_runs`。它新增持久化队列，不删除或改写历史报告；升级前按既有流程备份，升级后检查版本、健康、任务进度及 v1/v2 历史读取。额度与租约说明见 [交易计划书](technical-trading-plan.md)。
