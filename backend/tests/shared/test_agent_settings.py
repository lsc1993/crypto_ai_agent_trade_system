import pytest
from pydantic import ValidationError

from app.shared.config import AppSettings


def test_agent_settings_default_to_disabled_key_and_allowed_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    settings = AppSettings()

    assert settings.deepseek_api_key is None
    assert settings.deepseek_model == "deepseek-v4-pro"


def test_agent_settings_reject_legacy_or_unknown_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")

    with pytest.raises(ValidationError, match="DeepSeek 模型不在允许列表"):
        AppSettings()
