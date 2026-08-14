from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIRECTORY = Path(__file__).resolve().parents[3]
_REPOSITORY_ROOT = _BACKEND_DIRECTORY.parent


def _find_local_env_file() -> Path | None:
    # 后端专用配置优先；不存在时才回退到仓库根目录配置。
    for candidate in (
        _BACKEND_DIRECTORY / ".env",
        _REPOSITORY_ROOT / ".env",
    ):
        if candidate.is_file():
            return candidate
    return None


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_find_local_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    cors_allowed_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    )
    database_url: SecretStr | None = None
    test_database_url: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None
    deepseek_model: Literal["deepseek-v4-flash", "deepseek-v4-pro"] = "deepseek-v4-pro"
    news_http_timeout_seconds: int = Field(default=8, ge=1, le=20)
    agent_request_timeout_seconds: int = Field(default=30, ge=5, le=60)

    @field_validator("deepseek_model", mode="before")
    @classmethod
    def validate_deepseek_model(cls, value: Any) -> str:
        if not isinstance(value, str) or value.strip() not in {
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        }:
            raise ValueError("DeepSeek 模型不在允许列表")
        return value.strip()

    @field_validator("cors_allowed_origins")
    @classmethod
    def reject_wildcard_origin(
        cls,
        origins: tuple[str, ...],
    ) -> tuple[str, ...]:
        if "*" in origins:
            raise ValueError("CORS 来源不允许使用通配符")
        return origins
