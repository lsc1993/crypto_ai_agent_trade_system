# 本地 Compose 部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为研究、回测和模拟盘工作台提供安全、可重复、按需启动的本地三服务 Compose 部署。

**Architecture:** Compose 只编排内部 PostgreSQL、FastAPI API 与 Nginx 托管的 React 前端。API 仅在数据库健康后进行 `alembic upgrade head` 并运行；前端经 Nginx 同源代理 `/api` 和 `/healthz` 到 API。浏览器只访问 `http://localhost:8080`，不访问容器内部 DNS 或外部服务。

**Tech Stack:** Docker Compose、Python 3.12 slim、uv 0.10.6、FastAPI/Uvicorn、PostgreSQL 17、Node 24、Nginx unprivileged、pytest、Ruff、Pyright、Vitest、TypeScript。

## Global Constraints

- 服务固定为 `postgres`、`api`、`frontend`；不得创建 `market-worker`、定时采集、任务队列或自动执行服务。
- 不修改、读取、打印或提交根目录 `.env`、`backend/.env`、`frontend/.env`、真实凭证或连接串；仅更新 `.env.example`。
- Compose 不发布 PostgreSQL 主机端口，不接触或替换用户现有的独立 PostgreSQL 容器与数据卷。
- `postgres_data` 是唯一 Compose 数据卷；文档只给出 `docker compose down`，禁止 `down -v`、`drop`、`reset`、truncate 或清库命令。
- API 启动脚本只运行 `uv run alembic upgrade head`；迁移失败时不得启动 Uvicorn。
- Nginx 只反向代理 `/api` 与 `/healthz` 到 `api:8000`，不得代理 Binance、OpenAI 或其他外部域名。
- 前端生产构建固定使用 `VITE_DATA_MODE=api` 与 `VITE_API_BASE_URL=http://localhost:8080`。
- 镜像、日志、测试、示例配置和文档不得含交易所 API Key、Secret、Passphrase、私钥、账户数据或真实交易能力。
- 不新增 Python、Node 或容器运行时依赖；复用 `backend/uv.lock` 与 `frontend/package-lock.json`。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `compose.yaml` | 声明三个本地服务、内部网络、命名卷、健康检查、依赖与无凭证环境变量。 |
| `.env.example` | 提供仅用于 Compose 的非敏感变量名与示例值。 |
| `backend/Dockerfile` | 以 Python 3.12 与锁定依赖构建非 root API 镜像。 |
| `backend/docker-entrypoint.sh` | 仅执行前向迁移后以 `exec` 启动 Uvicorn。 |
| `backend/.dockerignore` | 排除本地配置、虚拟环境、缓存、测试产物和 Git 元数据。 |
| `frontend/Dockerfile` | 构建静态 React 产物，并复制到非 root Nginx 镜像。 |
| `frontend/nginx.conf` | 托管 SPA 并只代理本地 API 与健康检查。 |
| `frontend/.dockerignore` | 排除本地配置、依赖目录、构建/测试产物和 Git 元数据。 |
| `backend/tests/integration/test_local_compose_configuration.py` | 以 Compose JSON 配置及文件文本验证服务、安全边界、入口脚本与 Nginx 路由。 |
| `docs/local-deployment.md` | 给出安全的首次启动、健康检查、停止、升级和故障诊断步骤。 |
| `docs/operational-boundaries.md` | 记录本地运行、公开行情、模拟盘与无真实交易的运行边界。 |
| `README.md` | 提供最短启动命令、产品限制与链接到详细运行文档。 |

## Task 1: 容器配置的失败测试与安全契约

**Files:**
- Create: `backend/tests/integration/test_local_compose_configuration.py`

**Interfaces:**
- Consumes: 仓库根目录 `compose.yaml`、后端入口脚本、前端 Nginx 配置。
- Produces: `load_compose_configuration(tmp_path) -> dict[str, object]`，在 Docker CLI 可用时读取 `docker compose config --format json` 的规范化结果；Docker CLI 不可用时只跳过 Compose JSON 解析测试，文本安全断言仍必须执行。

- [ ] **Step 1: 写出失败的 Compose 配置测试**

在 `backend/tests/integration/test_local_compose_configuration.py` 创建下列测试与辅助函数。测试使用临时 env 文件，不读取用户真实 `.env`：

```python
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load_compose_configuration(tmp_path: Path) -> dict[str, object]:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is required to normalize Compose configuration")
    env_file = tmp_path / "compose.env"
    env_file.write_text(
        "\n".join(
            (
                "POSTGRES_DB=crypto_research",
                "POSTGRES_USER=crypto_research",
                "POSTGRES_PASSWORD=compose-test-password",
                "DATABASE_URL=postgresql+asyncpg://crypto_research:compose-test-password@postgres:5432/crypto_research",
                "APP_ENV=production",
                "LOG_LEVEL=INFO",
                'CORS_ALLOWED_ORIGINS=["http://localhost:8080"]',
            ),
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [docker, "compose", "--env-file", str(env_file), "config", "--format", "json"],
        cwd=ROOT,
        env={**os.environ, "COMPOSE_PROJECT_NAME": "crypto_compose_test"},
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_compose_declares_only_safe_local_services(tmp_path: Path) -> None:
    configuration = load_compose_configuration(tmp_path)
    services = configuration["services"]

    assert set(services) == {"postgres", "api", "frontend"}
    assert "market-worker" not in services
    volumes = configuration["volumes"]
    assert set(volumes) == {"postgres_data"}
    assert volumes["postgres_data"]["name"] == "crypto_research_postgres_data"
    assert services["postgres"].get("ports") is None
    assert services["postgres"]["healthcheck"]
    assert services["api"]["healthcheck"]
    assert services["api"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["frontend"]["depends_on"]["api"]["condition"] == "service_healthy"


def test_entrypoint_and_nginx_forbid_destructive_or_external_routes() -> None:
    entrypoint = (ROOT / "backend" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    nginx = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")

    assert "uv run alembic upgrade head" in entrypoint
    assert "exec uv run uvicorn app.main:app" in entrypoint
    assert all(token not in entrypoint.lower() for token in ("alembic downgrade", "drop", "truncate", "reset"))
    assert "proxy_pass http://api:8000" in nginx
    assert all(host not in nginx.lower() for host in ("binance", "openai", "api.binance", "api.openai"))


def test_container_images_run_without_root_users() -> None:
    backend_dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    frontend_dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")

    assert "USER app" in backend_dockerfile
    assert "nginxinc/nginx-unprivileged" in frontend_dockerfile
```

补充断言：API 环境变量集合不包含名称中带有 `OPENAI`、`BINANCE`、`SECRET`、`PASSPHRASE` 或 `PRIVATE_KEY` 的键；前端 build args 仅为 `VITE_DATA_MODE=api` 与 `VITE_API_BASE_URL=http://localhost:8080`。

- [ ] **Step 2: 运行测试，确认基础设施文件尚不存在**

Run: `uv run pytest tests/integration/test_local_compose_configuration.py -v`（工作目录：`backend`）
Expected: FAIL，提示缺少 `compose.yaml`、`backend/docker-entrypoint.sh` 或 `frontend/nginx.conf`；若 Docker CLI 未在 PATH 中，Compose JSON 测试可 skip，但入口/Nginx 文本测试必须失败。

- [ ] **Step 3: 运行后端静态质量门槛，确认测试文件自身合规**

Run: `uv run ruff check tests/integration/test_local_compose_configuration.py; uv run pyright tests/integration/test_local_compose_configuration.py`（工作目录：`backend`）
Expected: 由于生产文件未创建，pytest 失败；Ruff 和 Pyright 对测试文件通过。

## Task 2: 三服务 Compose、非 root 镜像与本地反向代理

**Files:**
- Create: `compose.yaml`
- Create: `backend/Dockerfile`
- Create: `backend/docker-entrypoint.sh`
- Create: `backend/.dockerignore`
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Create: `frontend/.dockerignore`
- Modify: `.env.example`
- Modify: `backend/tests/integration/test_local_compose_configuration.py`

**Interfaces:**
- Consumes: Task 1 的配置断言、`backend/pyproject.toml`、`backend/uv.lock`、`backend/alembic.ini`、`frontend/package-lock.json`、`frontend/package.json`。
- Produces: `docker compose up -d --build` 可启动的 `postgres`、`api`、`frontend`；页面入口 `http://localhost:8080`、API 入口 `http://localhost:8000`、健康检查 `/healthz`。

- [ ] **Step 1: 补全失败测试的精确断言**

在 Task 1 测试追加下列断言，确保实现不会以伪健康或宽松网络权限通过：

```python
def test_compose_exposes_only_local_web_ports(tmp_path: Path) -> None:
    configuration = load_compose_configuration(tmp_path)
    services = configuration["services"]

    api_port = services["api"]["ports"][0]
    frontend_port = services["frontend"]["ports"][0]
    assert api_port["target"] == 8000
    assert str(api_port["published"]) == "8000"
    assert frontend_port["target"] == 8080
    assert str(frontend_port["published"]) == "8080"
    assert services["api"]["environment"]["APP_ENV"] == "production"
    assert services["api"]["environment"]["CORS_ALLOWED_ORIGINS"] == '["http://localhost:8080"]'


def test_dockerignore_excludes_local_configuration_and_generated_state() -> None:
    for path in (ROOT / "backend" / ".dockerignore", ROOT / "frontend" / ".dockerignore"):
        patterns = set(path.read_text(encoding="utf-8").splitlines())
        assert {".env", ".venv", "node_modules", ".git", "dist", "test-results"} <= patterns
```

Run: `uv run pytest tests/integration/test_local_compose_configuration.py -v`（工作目录：`backend`）
Expected: FAIL，新增服务端口、环境或 `.dockerignore` 断言不满足。

- [ ] **Step 2: 编写后端镜像与安全入口脚本**

`backend/Dockerfile` 使用 `python:3.12-slim`，从 `ghcr.io/astral-sh/uv:0.10.6` 复制 `uv` 二进制，先复制 `pyproject.toml` 和 `uv.lock` 并执行：

```dockerfile
RUN uv sync --frozen --no-dev --no-install-project
```

创建无登录 shell 的 `app` 用户，将运行目录与 `.venv` 所有权授予该用户；再复制 `src/`、`alembic/`、`alembic.ini` 和入口脚本。镜像仅以 `app` 用户运行，暴露 `8000`。

`backend/docker-entrypoint.sh` 使用下列精确控制流，不加入降级或清库命令：

```sh
#!/bin/sh
set -eu

uv run alembic upgrade head
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`backend/.dockerignore` 的每行仅包含：

```text
.env
.venv
__pycache__
.pytest_cache
.ruff_cache
*.pyc
node_modules
dist
playwright-report
test-results
.git
```

- [ ] **Step 3: 编写前端镜像与 Nginx 配置**

`frontend/Dockerfile` 使用 `node:24-alpine` 构建阶段，先复制 `package.json`/`package-lock.json` 并执行 `npm ci`；复制源代码后固定设置：

```dockerfile
ARG VITE_DATA_MODE=api
ARG VITE_API_BASE_URL=http://localhost:8080
ENV VITE_DATA_MODE=$VITE_DATA_MODE
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build
```

运行阶段使用 `nginxinc/nginx-unprivileged:1.29-alpine`，监听 `8080`，只复制 `dist/` 和 `nginx.conf`。

`frontend/nginx.conf` 必须包含以下位置块：

```nginx
server {
  listen 8080;
  server_name _;
  root /usr/share/nginx/html;
  index index.html;

  location /api/ {
    proxy_pass http://api:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }

  location = /healthz {
    proxy_pass http://api:8000;
  }

  location / {
    try_files $uri $uri/ /index.html;
  }
}
```

`frontend/.dockerignore` 使用与后端同样的安全条目，并包含 `.cache`。

- [ ] **Step 4: 编写 Compose 与示例环境配置**

`compose.yaml` 固定 `name: crypto-research`，并使用 `postgres:17` 声明：

```yaml
services:
  postgres:
    image: postgres:17
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      TZ: UTC
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 5s
      timeout: 5s
      retries: 20

  api:
    build: ./backend
    environment:
      DATABASE_URL: ${DATABASE_URL}
      APP_ENV: ${APP_ENV}
      LOG_LEVEL: ${LOG_LEVEL}
      CORS_ALLOWED_ORIGINS: ${CORS_ALLOWED_ORIGINS}
      TZ: UTC
    ports: ["8000:8000"]
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
      interval: 10s
      timeout: 5s
      retries: 12

  frontend:
    build:
      context: ./frontend
      args:
        VITE_DATA_MODE: api
        VITE_API_BASE_URL: http://localhost:8080
    ports: ["8080:8080"]
    depends_on:
      api:
        condition: service_healthy

volumes:
  postgres_data:
    name: crypto_research_postgres_data
```

在 `.env.example` 保留现有开发变量，并追加 Compose 注释和下列不含真实凭证的示例：

```dotenv
POSTGRES_DB=crypto_research
POSTGRES_USER=crypto_research
POSTGRES_PASSWORD=replace-before-starting
DATABASE_URL=postgresql+asyncpg://crypto_research:replace-before-starting@postgres:5432/crypto_research
APP_ENV=production
LOG_LEVEL=INFO
CORS_ALLOWED_ORIGINS=["http://localhost:8080"]
```

不要创建根目录 `.env`，不要修改 `backend/.env` 或已删除的 `frontend/.env.example`。

- [ ] **Step 5: 运行配置和入口脚本测试，确认通过**

Run: `uv run pytest tests/integration/test_local_compose_configuration.py -v`（工作目录：`backend`）  
Expected: Docker CLI 可用时全部 PASS；不可用时 Compose JSON 读取测试显示 SKIPPED，而入口脚本、Nginx 与 `.dockerignore` 文本测试全部 PASS。

- [ ] **Step 6: 运行后端质量门槛并提交基础设施**

Run: `uv run ruff check .; uv run pyright; uv run pytest`（工作目录：`backend`）
Expected: PASS；不改变任何开发数据库数据。

```powershell
git add -- compose.yaml .env.example backend/Dockerfile backend/docker-entrypoint.sh backend/.dockerignore frontend/Dockerfile frontend/nginx.conf frontend/.dockerignore backend/tests/integration/test_local_compose_configuration.py
git commit -m "feat: add local compose deployment"
```

## Task 3: 本地运行文档、运维边界与不破坏性冒烟验收

**Files:**
- Create: `docs/local-deployment.md`
- Create: `docs/operational-boundaries.md`
- Create: `README.md`
- Modify: `backend/tests/integration/test_local_compose_configuration.py`

**Interfaces:**
- Consumes: Task 2 的 Compose 服务、端口与安全边界。
- Produces: 用户可复制的安全启动/停止步骤，以及在 Docker CLI 可用时验证前端、API 和 PostgreSQL 状态的冒烟命令。

- [ ] **Step 1: 写失败的文档安全回归测试**

在现有配置测试中加入：

```python
def test_local_deployment_docs_do_not_offer_volume_deletion_or_real_trading() -> None:
    documentation = "\n".join(
        (ROOT / "README.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "local-deployment.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "operational-boundaries.md").read_text(encoding="utf-8"),
    ).lower()

    assert "docker compose up -d --build" in documentation
    assert "docker compose down" in documentation
    assert "docker compose down -v" not in documentation
    assert "真实下单" in documentation
    assert "不支持" in documentation
```

Run: `uv run pytest tests/integration/test_local_compose_configuration.py::test_local_deployment_docs_do_not_offer_volume_deletion_or_real_trading -v`（工作目录：`backend`）
Expected: FAIL，提示运行文档尚不存在。

- [ ] **Step 2: 编写部署与边界文档**

`docs/local-deployment.md` 必须包含：

1. 前置条件：Docker Desktop 已运行，Docker CLI 可用，根目录 `.env` 从 `.env.example` 手工创建且不提交。
2. 首次启动：`docker compose up -d --build`，随后 `docker compose ps`。
3. 健康检查：浏览器/PowerShell 使用 `http://localhost:8000/healthz` 与 `http://localhost:8080/healthz`，页面使用 `http://localhost:8080`。
4. 前向升级：修改后使用同一条 `docker compose up -d --build`；API 只执行前向 Alembic 迁移。
5. 停止：只给出 `docker compose down`，并明确该命令保留 `postgres_data`。
6. 安全故障诊断：服务未就绪时先查看 `docker compose ps` 和安全日志；不建议删除卷、修改迁移历史或填入交易所凭证。

`docs/operational-boundaries.md` 明确：公开行情仅在用户请求时读取；模拟盘是本地、确定性风控后的模拟，不连接真实账户；没有私有接口、下单、撤单、资金划转、提现、后台任务或收益承诺。

`README.md` 提供三行最短路径：创建未提交 `.env`、运行 `docker compose up -d --build`、打开 `http://localhost:8080`；链接到两份详细文档和前后端质量命令。

- [ ] **Step 3: 运行文档测试与完整静态验证**

Run: `uv run pytest tests/integration/test_local_compose_configuration.py -v; uv run ruff check .; uv run pyright`（工作目录：`backend`）
Expected: PASS；文档没有卷删除建议或真实交易表述。

- [ ] **Step 4: 进行 Compose 冒烟验收（需要 Docker CLI）**

先确认 CLI 可用：

```powershell
docker compose version
docker compose config
docker compose build
docker compose up -d
docker compose ps
Invoke-WebRequest http://localhost:8000/healthz | Select-Object -ExpandProperty Content
Invoke-WebRequest http://localhost:8080/healthz | Select-Object -ExpandProperty Content
```

Expected: `postgres`、`api`、`frontend` 均为 healthy/running；两条健康检查均返回 `{"status":"ok"}`。若当前执行环境没有 Docker CLI，不将其标记为代码失败；记录为等待用户在 Docker Desktop PowerShell 中运行的外部验收，并继续执行所有不依赖 Docker 的质量命令。

停止时仅执行：

```powershell
docker compose down
```

- [ ] **Step 5: 运行全量项目验证并提交文档**

Run（后端）：`uv run ruff check .; uv run pyright; uv run pytest`（工作目录：`backend`）
Run（前端）：`npm run lint; npm run typecheck; npm run test -- --run; npm run build`（工作目录：`frontend`）
Expected: 所有命令 PASS；不修改数据库、环境文件或已有独立容器。

```powershell
git add -- README.md docs/local-deployment.md docs/operational-boundaries.md backend/tests/integration/test_local_compose_configuration.py
git commit -m "docs: add local deployment guidance"
```

## Plan Self-Review

### Spec coverage

- 三服务按需 Compose、没有 `market-worker`、没有定时任务：Task 1、Task 2。
- PostgreSQL 内部网络、命名卷、健康依赖、只前向迁移与无清库：Task 1、Task 2。
- 同源 Nginx `/api`、`/healthz` 代理和固定前端生产配置：Task 1、Task 2。
- 不读取/修改真实环境文件、无凭证、无私有交易所能力：全局约束、Task 1、Task 2、Task 3。
- 不破坏性文档、健康检查与 Docker CLI 冒烟验收：Task 3。
- 非 Docker 环境仍可运行代码质量门槛：Task 1、Task 3。

### Placeholder scan

已检查计划，不含未完成标记、未定义的文件名、未指明的命令或需要猜测的服务/端口名称。

### Type consistency

- 服务名在测试、Compose、文档中固定为 `postgres`、`api`、`frontend`。
- 端口固定为 API `8000`、前端 `8080`，PostgreSQL 不发布主机端口。
- 健康路径固定为 `/healthz`，API 代理路径固定为 `/api`。
- Compose 数据卷固定为 `postgres_data`，其底层名称固定为 `crypto_research_postgres_data`。
