# Integration, Local Deployment and Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已完成的前端、API、市场 Worker、PostgreSQL 与 Agent 组合为可在本机安全运行的 Docker Compose 工作台，并建立覆盖安全边界、数据持久化、失败降级与用户关键路径的质量门槛。

**Architecture:** 使用同一个后端镜像运行 `api` 和 `market-worker`，PostgreSQL 作为唯一状态存储，React 由 Nginx 提供静态文件。Compose 仅面向单用户本地部署和单 API 副本；配置来自本地未提交环境文件；应用运行时不需要也不允许交易所凭据。

**Tech Stack:** Docker Compose、PostgreSQL、FastAPI/Uvicorn、React/Nginx、Alembic、pytest、Vitest、Playwright、Ruff、Pyright、OpenTelemetry/structlog。

## Global Constraints

- 任何 Dockerfile、Compose 文件、示例环境文件、日志和测试夹具都不能包含真实凭据、私钥、交易账户或交易所认证字段。
- 数据卷、附件卷和用户数据库不得因开发、测试或关闭服务而被删除；`docker compose down -v` 不属于本计划的验证命令。
- Docker 仅在本地运行。不得将端口公开到远程网络、部署云服务或自动推送镜像。
- 生产样式 Compose 默认禁用模型生成，除非用户在本地显式设置运行时模型密钥；即使设置，也不改变无交易边界。
- 备份导出只读且版本化；导入/覆盖用户数据需要独立的冲突策略和用户确认，因此不在本计划实现。

---

## Target file layout

```text
.
├── compose.yaml
├── .env.example
├── docs/
│   ├── local-deployment.md
│   ├── backup-and-restore.md
│   └── operational-boundaries.md
├── backend/
│   ├── Dockerfile
│   ├── docker-entrypoint.sh
│   ├── src/app/api/routes/{health.py,maintenance.py}
│   ├── src/app/application/maintenance/export.py
│   └── tests/{integration/api/test_maintenance_export_api.py,security/}
└── frontend/
    ├── Dockerfile
    ├── nginx.conf
    └── e2e/{local-stack.spec.ts,security-boundaries.spec.ts}
```

## Task 1: Build deterministic local containers without secrets

**Files:**
- Create: `backend/Dockerfile`, `backend/docker-entrypoint.sh`, `frontend/Dockerfile`, `frontend/nginx.conf`
- Modify: `compose.yaml`, `.env.example`
- Create: `backend/tests/integration/test_container_configuration.py`

- [ ] Write a configuration test first that parses Compose/Docker-related settings and asserts four named services (`postgres`, `api`, `market-worker`, `frontend`), named persistent volumes for PostgreSQL and attachments, health checks, no exchange credential environment variables and no privileged host mounts.
- [ ] Build the backend image from `backend/pyproject.toml`/`uv.lock` using `uv sync --frozen --all-groups` for local validation. Run as an unprivileged user where image support allows it. Do not copy `.env`, `.git`, local virtual environments or attachment data into the image context.
- [ ] Use `docker-entrypoint.sh` to run Alembic migrations in the single local API deployment before launching Uvicorn. It must fail closed if migrations fail and must not issue schema drop/reset commands. The Worker waits for API/database health before starting.
- [ ] Build the frontend in a Node builder stage and serve only static artifacts via a minimal Nginx stage. Nginx must proxy neither Binance nor LLM requests; browser traffic goes only to local API paths.
- [ ] Compose service requirements:

| Service | Required behavior |
|---|---|
| `postgres` | named `postgres_data` volume, health check, local-only published port optional via profile, UTC configuration. |
| `api` | exposes local port 8000, runs health check, depends on healthy PostgreSQL, has attachment volume mount. |
| `market-worker` | same backend image, no published port, depends on PostgreSQL/API readiness, no credentials. |
| `frontend` | exposes local port 8080, configured only with public API base URL. |

- [ ] Keep sample variables non-sensitive: `POSTGRES_DB`, `POSTGRES_USER`, an example-only `POSTGRES_PASSWORD`, `DATABASE_URL`, `APP_ENV`, `LOG_LEVEL`, `CORS_ALLOWED_ORIGINS`, `VITE_API_BASE_URL`, `VITE_DATA_MODE`, `OPENAI_API_KEY`. Clearly document that blank/example values must be replaced only in untracked local `.env`.
- [ ] Add `.dockerignore` files that exclude `.env`, `.venv`, `node_modules`, test screenshots, local attachments and Git metadata from build context.

**Verification:**

```powershell
docker compose config
docker compose build
docker compose up -d
docker compose ps
```

Expected result: all four services report healthy/running states; Compose configuration contains no secret value and no service has exchange/account capability.

## Task 2: Establish API/UI integration and failure-mode smoke tests

**Files:**
- Create: `frontend/e2e/local-stack.spec.ts`, `frontend/e2e/security-boundaries.spec.ts`
- Create: `backend/tests/integration/api/test_cross_feature_workflow.py`
- Modify: `frontend/src/shared/api/http-workbench-api.ts`, `frontend/src/app/providers.tsx`

- [ ] Write cross-feature API tests first for: market data query with a stale result; manual multi-leg journal creation; completed-trade analytics; analysis run returning a deterministic degraded report; report-to-trade association; archive filtering.
- [ ] Write Playwright tests against Compose, not Mock mode, for dashboard freshness state, market page source display, manual journal persistence after browser reload, analytics calendar drill-down, report evidence rendering and the absence of trade/action buttons.
- [ ] Add a network-request test asserting the browser only requests the local frontend/API origins. It must fail on Binance/OpenAI/external exchange requests initiated from browser code.
- [ ] Ensure frontend error mapping renders the backend error `code`/safe `message` without displaying raw stack traces. Ensure API does not let an invalid market source or missing model key become an HTTP 500 with sensitive details.
- [ ] Add a manual smoke checklist in `docs/local-deployment.md`: first start, health URLs, Mock vs HTTP mode, data freshness meaning, journal persistence, model-unavailable behavior and how to stop the stack without data deletion.

**Verification:**

```powershell
docker compose up -d --build
Set-Location backend
uv run pytest tests/integration/api/test_cross_feature_workflow.py
Set-Location ../frontend
npm run test:e2e -- --project=chromium
```

Expected result: the full user path works with local services; unavailable market/model inputs are shown as bounded degraded states; no browser-to-third-party call is made.

## Task 3: Add read-only versioned backup export and operating documentation

**Files:**
- Create: `backend/src/app/application/maintenance/export.py`, `backend/src/app/api/routes/maintenance.py`
- Create: `backend/tests/integration/api/test_maintenance_export_api.py`
- Create: `docs/{backup-and-restore.md,operational-boundaries.md}`
- Modify: `backend/src/app/api/router.py`, `frontend/src/features/settings/SettingsPage.tsx`

- [ ] Write tests first for empty export, populated journal/report export, schema version manifest, attachment metadata reference, streamed response headers and redaction of checkpoints/keys/database configuration.
- [ ] Implement `GET /api/v1/maintenance/export` as a read-only streamed ZIP. It contains `manifest.json`, normalized JSON data for manually entered trades/tags/cashflows/attachments metadata and immutable reports/evidences. Do not include LangGraph checkpoints, raw external payloads, model prompts, database configuration or secrets.
- [ ] Manifest contains `format_version`, `created_at` in UTC, application schema migration revision, included dataset list and SHA-256 hash for each entry. Use a generated download filename; do not accept a path/name from the client.
- [ ] Attachments are not bundled in the first export to keep archive size and file safety bounded. The manifest records attachment IDs/checksums and `docs/backup-and-restore.md` explains how to copy the local attachments volume alongside the export.
- [ ] Add a Settings page action labeled `导出本地研究数据（只读备份）`, with a clear warning that it is not an import/restore tool and can contain private journal notes. It must not export automatically on page load.
- [ ] Document safe backup procedure using `docker compose stop`, copy named volumes through Docker-supported tooling or database dump tooling, and restart. Do not document destructive restore commands; restoration requires an explicit future recovery plan and user confirmation.
- [ ] Document runtime safety boundaries: no automated execution, no user-data sync, public market data only, failure/degradation behavior, and required review before adding a real news source, strategy, exchange or external MCP.

**Verification:**

```powershell
Set-Location backend
uv run pytest tests/integration/api/test_maintenance_export_api.py
uv run ruff check .
uv run pyright
```

Expected result: a local user can obtain a verifiable, read-only export without exposing credentials or overwriting any data.

## Task 4: Enforce quality gates, audit boundaries and final regression

**Files:**
- Create: `backend/tests/security/{test_no_exchange_private_capabilities.py,test_no_secret_material.py,test_no_trade_execution_surface.py}`
- Create: `frontend/src/test/security-boundaries.test.tsx`
- Modify: `backend/README.md`, `frontend/README.md`, root `README.md`

- [ ] Write source-level security tests that scan application source (not documentation/history) and fail on order submission/cancellation, account/balance/position calls, exchange credential configuration, private WebSocket streams or API routes that perform an execution action.
- [ ] Write secret-material tests that detect committed `.env` files, common private-key headers and non-example key patterns in source/fixtures. Allow only variable names and documented empty examples in `.env.example`.
- [ ] Write frontend tests ensuring there are no labels/routes/actions for live execution, and no environment variable beginning with a server-only secret is referenced by `import.meta.env`.
- [ ] Run all back-end and front-end quality commands from clean dependency environments. Investigate each failure at its source; do not mute type/lint/tests or blanket-exclude paths to obtain a passing run.
- [ ] Run an audit of current schema migrations and verify `alembic upgrade head` from an empty local database. Ensure all times remain UTC and all numeric monetary columns remain `NUMERIC` rather than float types.
- [ ] Update root documentation with exact local start/stop commands, quality commands, system limitations, Mock/HTTP data modes and a concise explanation that AI reports assist research rather than predict or execute trades.

**Verification:**

```powershell
Set-Location backend
uv run ruff check .
uv run pyright
uv run pytest
uv run alembic upgrade head
Set-Location ../frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
npm run test:e2e -- --project=chromium
Set-Location ..
docker compose ps
```

Expected result: every command exits `0`; Compose services stay healthy; migration is repeatable; static audits prove no keys, private exchange APIs or execution surfaces exist.

## Task 5: Prepare an evidence-based delivery review

**Files:**
- Create: `docs/acceptance-record.md`

- [ ] Record exact command outputs/versions, migration revision, Compose service status and test counts after the final successful run. Do not record secrets, full journal data, external payloads or model prompt text.
- [ ] Map each acceptance item from the confirmed design specification to a concrete route, page, test or documented exclusion.
- [ ] Record known intentional limits: only BTCUSDT/ETHUSDT, four timeframes, one local user/API replica, manual journal input, fake news until source approval, no strategy engine, no exchange account and no execution.
- [ ] Obtain a user decision before enabling a real news source, configuring a model key or expanding scope. A successful local build is not authorization to change those boundaries.

**Verification:**

```powershell
git diff --check
git status --short
```

Expected result: the delivery record is evidence-backed, whitespace-clean and explicit about all intentionally excluded high-risk functionality.
