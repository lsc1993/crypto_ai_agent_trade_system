from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import cast
from urllib.parse import quote, urlsplit

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
CHILD_ENVIRONMENT_NAMES = (
    "APPDATA",
    "DOCKER_CERT_PATH",
    "DOCKER_CONFIG",
    "DOCKER_CONTEXT",
    "DOCKER_HOST",
    "DOCKER_TLS_VERIFY",
    "HOME",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
)


def compose_child_environment() -> dict[str, str]:
    environment = {
        name: os.environ[name]
        for name in CHILD_ENVIRONMENT_NAMES
        if name in os.environ
    }
    environment["COMPOSE_PROJECT_NAME"] = "crypto_compose_test"
    return environment


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
                "DEEPSEEK_API_KEY=",
                "DEEPSEEK_MODEL=deepseek-v4-pro",
            ),
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [docker, "compose", "--env-file", str(env_file), "config", "--format", "json"],
        cwd=ROOT,
        env=compose_child_environment(),
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
    postgres_ports = cast(list[dict[str, object]], postgres["ports"])
    assert postgres_ports == [
        {
            "host_ip": "127.0.0.1",
            "target": 5432,
            "published": "5433",
            "protocol": "tcp",
            "mode": "ingress",
        }
    ]
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


def test_compose_reserves_loopback_postgres_port_for_test_database() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert 'ports: ["127.0.0.1:5433:5432"]' in compose


def test_entrypoint_and_nginx_forbid_destructive_or_external_routes() -> None:
    entrypoint = (ROOT / "backend" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    nginx = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")

    assert "uv run alembic upgrade head" in entrypoint
    assert "exec uv run python -m app" in entrypoint
    assert all(
        token not in entrypoint.lower()
        for token in ("alembic downgrade", "drop", "truncate", "reset")
    )
    assert all(token not in entrypoint.lower() for token in BACKGROUND_PROCESS_TOKENS)
    proxy_targets = re.findall(r"(?m)^\s*proxy_pass\s+([^;]+);", nginx)
    assert proxy_targets == ["http://api:8000", "http://api:8000"]
    assert "location /api/ {" in nginx
    assert "location = /healthz {" in nginx
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
    assert len(api_ports) == 1
    assert len(frontend_ports) == 1
    api_port = api_ports[0]
    frontend_port = frontend_ports[0]
    assert api_port["host_ip"] == "127.0.0.1"
    assert api_port["target"] == 8000
    assert str(api_port["published"]) == "8000"
    assert frontend_port["host_ip"] == "127.0.0.1"
    assert frontend_port["target"] == 8080
    assert str(frontend_port["published"]) == "8080"
    api_environment = cast(dict[str, str], api["environment"])
    assert api_environment["APP_ENV"] == "production"
    assert api_environment["CORS_ALLOWED_ORIGINS"] == '["http://localhost:8080"]'


def test_compose_configuration_ignores_host_project_and_application_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    poisoned_values = {
        "POSTGRES_DB": "host_database",
        "POSTGRES_USER": "host_user",
        "POSTGRES_PASSWORD": "host_password",
        "DATABASE_URL": "postgresql+asyncpg://host:host@outside:5432/host",
        "APP_ENV": "host-environment",
        "LOG_LEVEL": "DEBUG",
        "CORS_ALLOWED_ORIGINS": '["https://outside.invalid"]',
        "COMPOSE_FILE": str(tmp_path / "untrusted-compose.yaml"),
        "COMPOSE_PROJECT_NAME": "host_project",
        "COMPOSE_PROFILES": "host_profile",
    }
    for name, value in poisoned_values.items():
        monkeypatch.setenv(name, value)

    configuration = load_compose_configuration(tmp_path)
    services = cast(dict[str, dict[str, object]], configuration["services"])
    postgres_environment = cast(dict[str, str], services["postgres"]["environment"])
    api_environment = cast(dict[str, str], services["api"]["environment"])

    assert configuration["name"] == "crypto_compose_test"
    assert postgres_environment["POSTGRES_DB"] == "crypto_research"
    assert postgres_environment["POSTGRES_USER"] == "crypto_research"
    assert postgres_environment["POSTGRES_PASSWORD"] == "compose-test-password"
    assert api_environment["DATABASE_URL"] == (
        "postgresql+asyncpg://crypto_research:compose-test-password"
        "@postgres:5432/crypto_research"
    )
    assert api_environment["APP_ENV"] == "production"
    assert api_environment["LOG_LEVEL"] == "INFO"
    assert api_environment["CORS_ALLOWED_ORIGINS"] == '["http://localhost:8080"]'
    assert api_environment["DEEPSEEK_API_KEY"] == ""
    assert api_environment["DEEPSEEK_MODEL"] == "deepseek-v4-pro"


def test_environment_template_has_unique_synchronized_compose_values() -> None:
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    assignments: list[tuple[str, str]] = []
    for line in template.splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", maxsplit=1)
            assignments.append((name, value))
    names = [name for name, _ in assignments]
    values = dict(assignments)

    assert len(names) == len(set(names))
    assert "# Non-Compose development options" in template
    assert "# Compose local deployment" in template

    database_url = urlsplit(values["DATABASE_URL"])
    test_database_url = urlsplit(values["TEST_DATABASE_URL"])
    password = values["POSTGRES_PASSWORD"]
    assert quote(password, safe="") == password
    assert database_url.username == values["POSTGRES_USER"]
    assert database_url.password == password
    assert database_url.hostname == "postgres"
    assert database_url.path == f"/{values['POSTGRES_DB']}"
    assert test_database_url.hostname == "127.0.0.1"
    assert test_database_url.port == 5433
    assert test_database_url.path == "/crypto_research_test"


def test_dockerignore_excludes_local_configuration_and_generated_state() -> None:
    for path in (ROOT / "backend" / ".dockerignore", ROOT / "frontend" / ".dockerignore"):
        patterns = set(path.read_text(encoding="utf-8").splitlines())
        assert {".env", ".venv", "node_modules", ".git", "dist", "test-results"} <= patterns


def test_local_deployment_documentation_preserves_safe_operations() -> None:
    documents = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "README.md",
            "docs/local-deployment.md",
            "docs/operational-boundaries.md",
        )
    )

    assert "docker compose up -d --build" in documents
    assert "docker compose down" in documents
    assert "真实下单" in documents
    assert "不支持" in documents
    assert "docker compose down -v" not in documents
