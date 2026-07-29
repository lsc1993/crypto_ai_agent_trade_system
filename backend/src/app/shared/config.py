from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
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

    @field_validator("cors_allowed_origins")
    @classmethod
    def reject_wildcard_origin(
        cls,
        origins: tuple[str, ...],
    ) -> tuple[str, ...]:
        if "*" in origins:
            raise ValueError("CORS 来源不允许使用通配符")
        return origins
