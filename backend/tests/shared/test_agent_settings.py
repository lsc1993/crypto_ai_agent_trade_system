# 验证模型配置默认无密钥且模型名来自允许集合。
# 直接构造配置隔离运行环境，历史或未知模型名需拒绝。
# 未配置模型凭证不应隐式开启模型能力。
import pytest
from pydantic import ValidationError

from app.shared.config import AppSettings


def test_agent_settings_default_to_disabled_key_and_allowed_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setitem(AppSettings.model_config, "env_file", None)
    settings = AppSettings()

    assert settings.deepseek_api_key is None
    assert settings.deepseek_model == "deepseek-v4-pro"
    assert settings.agent_request_timeout_seconds == 60


def test_agent_settings_reject_legacy_or_unknown_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")

    with pytest.raises(ValidationError, match="DeepSeek 模型不在允许列表"):
        AppSettings()
