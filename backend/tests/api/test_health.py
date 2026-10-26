# 验证基础健康检查、API 根文档、跨域配置与全局错误处理。
# 内存 HTTP 请求覆盖默认开发来源和结构化错误归一化。
# 配置保持不可变，连接信息需脱敏，通配跨域来源不被接受。
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError

from app.main import create_app
from app.shared.config import AppSettings


async def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    raise_app_exceptions: bool = True,
    **kwargs: Any,
) -> Any:
    transport = ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_healthz_returns_ok() -> None:
    response = await request(create_app(), "GET", "/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_api_root_returns_version_document() -> None:
    app = create_app()

    response = await request(app, "GET", "/api/v1")

    assert app.title == "AI 加密合约研究工作台"
    assert response.status_code == 200
    assert response.json() == {
        "name": "AI 加密合约研究工作台",
        "version": "v1",
    }


@pytest.mark.asyncio
async def test_cors_preflight_allows_configured_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = "http://localhost:5173"
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["http://localhost:5173"]')

    response = await request(
        create_app(),
        "OPTIONS",
        "/api/v1",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.asyncio
async def test_default_cors_allows_the_documented_vite_development_origin() -> None:
    origin = "http://127.0.0.1:4173"

    response = await request(
        create_app(),
        "OPTIONS",
        "/api/v1/markets",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.asyncio
async def test_http_errors_use_global_error_envelope() -> None:
    response = await request(create_app(), "GET", "/missing")

    assert response.status_code == 404
    assert response.json() == {
        "code": "not_found",
        "message": "Not Found",
        "details": {},
    }


@pytest.mark.asyncio
async def test_structured_http_error_detail_is_normalized() -> None:
    app = create_app()

    async def raise_structured_error() -> None:
        raise HTTPException(
            status_code=409,
            detail={"reason": "conflict"},
        )

    app.add_api_route(
        "/structured-error",
        raise_structured_error,
        methods=["GET"],
    )
    response = await request(app, "GET", "/structured-error")

    assert response.status_code == 409
    assert response.json() == {
        "code": "http_error",
        "message": "请求无法处理",
        "details": {"detail": {"reason": "conflict"}},
    }


def test_settings_are_immutable_and_database_urls_are_redacted() -> None:
    database_url = "postgresql+asyncpg://user:password@localhost/research"
    test_database_url = "postgresql+asyncpg://test:password@localhost/research_test"
    settings = AppSettings(
        database_url=SecretStr(database_url),
        test_database_url=SecretStr(test_database_url),
    )

    assert database_url not in repr(settings)
    assert test_database_url not in repr(settings)
    assert settings.test_database_url is not None
    assert settings.test_database_url.get_secret_value() == test_database_url
    with pytest.raises(ValidationError):
        setattr(settings, "log_level", "DEBUG")


def test_settings_reject_wildcard_cors_origin() -> None:
    with pytest.raises(ValidationError):
        AppSettings(cors_allowed_origins=("*",))
