# 集中定义环境配置、模型白名单、请求超时与 CORS 来源。
# 优先读取后端本地配置，缺失时寻找根目录配置，再由 Pydantic 校验并冻结实例。
# 连接串和模型密钥使用 SecretStr 包装；配置模型不授权真实交易，也不负责记录配置值。
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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


# 不可变应用配置契约；读取环境时校验类型和范围，敏感字段保留 SecretStr 包装。
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
    agent_request_timeout_seconds: int = Field(default=60, ge=5, le=60)
    technical_analysis_max_tokens: int = Field(default=32768, ge=4096, le=65536)
    technical_composition_max_tokens: int = Field(default=8192, ge=2048, le=16384)
    technical_analysis_timeout_seconds: int = Field(default=180, ge=30, le=180)
    technical_composition_timeout_seconds: int = Field(default=90, ge=15, le=90)
    technical_run_timeout_seconds: int = Field(default=600, ge=120, le=600)

    # 校验各模型阶段超时不超过任务截止；返回同一配置实例而不改写用户值。
    @model_validator(mode="after")
    def technical_timeouts(self) -> "AppSettings":
        if (
            max(self.technical_analysis_timeout_seconds, self.technical_composition_timeout_seconds)
            > self.technical_run_timeout_seconds
        ):
            raise ValueError("技术模型阶段超时不能超过任务截止")
        return self

    # 输入必须是允许模型名称的字符串；只去除首尾空白，不对未知模型自动回退。
    @field_validator("deepseek_model", mode="before")
    @classmethod
    def validate_deepseek_model(cls, value: Any) -> str:
        if not isinstance(value, str) or value.strip() not in {
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        }:
            raise ValueError("DeepSeek 模型不在允许列表")
        return value.strip()

    # 拒绝 CORS 通配符并返回原始来源列表，避免扩大浏览器跨域访问范围。
    @field_validator("cors_allowed_origins")
    @classmethod
    def reject_wildcard_origin(
        cls,
        origins: tuple[str, ...],
    ) -> tuple[str, ...]:
        if "*" in origins:
            raise ValueError("CORS 来源不允许使用通配符")
        return origins
