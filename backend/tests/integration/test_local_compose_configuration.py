from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKGROUND_PROCESS_TOKENS = (
    "market-worker",
    "celery",
    "beat",
    "scheduler",
    "worker",
    "queue",
)


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
    services = cast(dict[str, dict[str, object]], configuration["services"])
    postgres = services["postgres"]
    api = services["api"]
    frontend = services["frontend"]

    assert set(services) == {"postgres", "api", "frontend"}
    assert "market-worker" not in services
    volumes = cast(dict[str, dict[str, str]], configuration["volumes"])
    assert set(volumes) == {"postgres_data"}
    assert volumes["postgres_data"]["name"] == "crypto_research_postgres_data"
    assert postgres.get("ports") is None
    assert postgres["healthcheck"]
    assert api["healthcheck"]
    api_depends_on = cast(dict[str, dict[str, str]], api["depends_on"])
    assert api_depends_on["postgres"]["condition"] == "service_healthy"
    frontend_depends_on = cast(dict[str, dict[str, str]], frontend["depends_on"])
    assert frontend_depends_on["api"]["condition"] == "service_healthy"

    api_environment = cast(dict[str, str], api["environment"])
    assert all(
        forbidden not in name.upper()
        for name in api_environment
        for forbidden in ("OPENAI", "BINANCE", "SECRET", "PASSPHRASE", "PRIVATE_KEY")
    )
    api_runtime = "\n".join(
        str(api.get(field, "")) for field in ("entrypoint", "command")
    ).lower()
    assert all(
        token not in api_runtime
        for token in BACKGROUND_PROCESS_TOKENS
    )
    frontend_build = cast(dict[str, dict[str, str]], frontend["build"])
    assert frontend_build["args"] == {
        "VITE_DATA_MODE": "api",
        "VITE_API_BASE_URL": "http://localhost:8080",
    }


def test_entrypoint_and_nginx_forbid_destructive_or_external_routes() -> None:
    entrypoint = (ROOT / "backend" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    nginx = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")

    assert "uv run alembic upgrade head" in entrypoint
    assert "exec uv run uvicorn app.main:app" in entrypoint
    assert all(
        token not in entrypoint.lower()
        for token in ("alembic downgrade", "drop", "truncate", "reset")
    )
    assert all(token not in entrypoint.lower() for token in BACKGROUND_PROCESS_TOKENS)
    assert "proxy_pass http://api:8000" in nginx
    assert all(
        host not in nginx.lower()
        for host in ("binance", "openai", "api.binance", "api.openai")
    )


def test_container_images_run_without_root_users() -> None:
    backend_dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    frontend_dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")

    assert "USER app" in backend_dockerfile
    assert "UV_NO_SYNC=1" in backend_dockerfile
    assert "nginxinc/nginx-unprivileged" in frontend_dockerfile


def test_compose_exposes_only_local_web_ports(tmp_path: Path) -> None:
    configuration = load_compose_configuration(tmp_path)
    services = cast(dict[str, dict[str, object]], configuration["services"])
    api = services["api"]
    frontend = services["frontend"]

    api_ports = cast(list[dict[str, object]], api["ports"])
    frontend_ports = cast(list[dict[str, object]], frontend["ports"])
    api_port = api_ports[0]
    frontend_port = frontend_ports[0]
    assert api_port["target"] == 8000
    assert str(api_port["published"]) == "8000"
    assert frontend_port["target"] == 8080
    assert str(frontend_port["published"]) == "8080"
    api_environment = cast(dict[str, str], api["environment"])
    assert api_environment["APP_ENV"] == "production"
    assert api_environment["CORS_ALLOWED_ORIGINS"] == '["http://localhost:8080"]'


def test_dockerignore_excludes_local_configuration_and_generated_state() -> None:
    for path in (ROOT / "backend" / ".dockerignore", ROOT / "frontend" / ".dockerignore"):
        patterns = set(path.read_text(encoding="utf-8").splitlines())
        assert {".env", ".venv", "node_modules", ".git", "dist", "test-results"} <= patterns
