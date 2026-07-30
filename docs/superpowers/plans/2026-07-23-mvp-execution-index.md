# AI 加密合约研究工作台 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不接入账户、不下单且不实现技术策略的前提下，交付可本地部署的 BTCUSDT/ETHUSDT 永续合约研究、手工交易记录、统计复盘与 AI 研究工作台。

**Architecture:** 采用前后端分离的单用户本地部署架构。React SPA 先通过类型化 Mock 开发；FastAPI 提供版本化 API 与 SSE；PostgreSQL 是唯一事实存储；market-worker 只访问公开行情接口；单一 LangGraph 图只生成带证据的研究报告。

**Tech Stack:** React + TypeScript + Vite、Tailwind CSS、shadcn/ui、TanStack Query、FastAPI、Pydantic v2、SQLAlchemy 2.x、PostgreSQL、Alembic、CCXT、币安公开 REST/WebSocket、LangGraph、pytest、Vitest、Playwright、Docker Compose。

## Global Constraints

- 任何阶段都不得实现下单、撤单、账户查询、资金划转、提现或交易所私有 API。
- 不提交或记录 API Key、Secret、私钥、账户信息；币安公开行情不配置认证字段。
- 金额、数量、价格、手续费和盈亏在 Python 与数据库中使用 `Decimal` / `NUMERIC(38,18)`；前端 API 契约使用十进制字符串。
- 所有持久化时间使用 UTC 带时区时间；前端仅在显示层转换为 `Asia/Shanghai`。
- Agent、前端和 Worker 不得直接绕过 application/domain 层访问数据库或交易所。
- 每一个实现任务先写失败测试，再写最小实现；每个可独立验证的任务单独提交。
- 所有面向用户的说明、领域规则与复杂计算使用中文注释；不要用注释隐藏不确定的设计。

---

## 交付顺序与依赖

```text
计划 01：工程基础与前端 Mock 工作台
        │
        ├───────────────┐
        ▼               ▼
计划 02：交易日志与统计    计划 03：市场数据与资讯
        │               │
        └───────┬───────┘
                ▼
计划 04：LangGraph 研究 Agent
                ▼
计划 05：集成、Docker 与质量验收
```

| 顺序 | 计划文件 | 完成定义 |
|---|---|---|
| 01 | `2026-07-23-foundation-and-frontend-workbench.md` | 前后端基础工程、类型化 Mock、六个可导航页面和统一 API 契约可验证。 |
| 02 | `2026-07-23-trading-journal-and-analytics.md` | 手工交易可持久化、可审计、可按既定统计口径复盘。 |
| 03 | `2026-07-23-market-data-and-news.md` | BTC/ETH 的公开 K 线、衍生品数据与可追溯资讯能够安全落库并展示。 |
| 04 | `2026-07-23-langgraph-research-agent.md` | 用户可手动触发、流式观察并阅读带不可变证据的降级安全研究报告。 |
| 05 | `2026-07-23-integration-deployment-and-quality.md` | Docker Compose 本地部署、备份说明、端到端测试、可观测性与安全回归完成。 |

## 执行前环境门槛

- [ ] 在仓库根目录执行 `uv python install 3.12`，确认 `backend/.venv` 可以由 `uv sync` 创建。当前系统 `python` 不在 PATH，开发时应以 `uv run` 为准，不能假定全局 Python 可用。
- [ ] 安装并启动 Docker Desktop，确认 `docker version` 与 `docker compose version` 可用。当前环境未检测到 Docker，因此只能先完成不依赖容器的前端 Mock 和纯领域测试。
- [ ] 在首次安装依赖前审阅计划 01 中的依赖清单及影响：新增依赖只覆盖 HTTP/API、数据库、图表、Agent 和测试；不新增交易执行或账户访问能力。
- [ ] 在根目录创建仅含变量名和非敏感示例值的 `.env.example`；不创建或修改真实 `.env`。

## 全局验证命令

后端命令在 `backend/` 目录执行：

```powershell
uv run ruff check .
uv run pyright
uv run pytest
```

前端命令在 `frontend/` 目录执行：

```powershell
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

端到端与 Compose 验收在仓库根目录执行：

```powershell
docker compose up --build -d
docker compose ps
docker compose exec api uv run pytest tests/integration
npm --prefix frontend run test:e2e
docker compose down
```

期望结果：质量命令全部返回退出码 `0`；`docker compose ps` 中 `postgres`、`api`、`market-worker`、`frontend` 均为运行状态；任何网络、模型或数据源故障都在 UI/API 中显示为可追溯的降级状态，而非伪造成功结果。

## 计划间契约冻结

- HTTP 根路径固定为 `/api/v1`，健康检查固定为 `GET /healthz`。
- 成功列表响应固定为 `{ "items": [...], "page": 1, "page_size": 20, "total": 0 }`；错误响应固定为 `{ "code": "...", "message": "...", "details": {} }`。
- `Symbol` 仅为 `BTCUSDT | ETHUSDT`；`Timeframe` 仅为 `15m | 1h | 4h | 1d`；未来扩容必须通过显式枚举迁移和测试完成。
- 前端只能依赖 `WorkbenchApi` 接口；从 Mock 切换到 HTTP 时不改业务页面组件。
- `Trade` 通过可选 `analysis_report_id` 引用报告，不复制报告正文或证据；该外键只在计划 04 的报告表创建后启用。
- 研究报告不是交易指令。UI、API Schema、Prompt 和测试均不得出现“自动执行”“保证盈利”“全仓”或等价承诺。
