from __future__ import annotations

from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import cast

import pytest
from pydantic import SecretStr

from app.shared.config import AppSettings

_BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]
_PUBLIC_ONLY_MODULES = (
    _BACKEND_DIRECTORY / "src/app/market/capture.py",
    _BACKEND_DIRECTORY / "src/app/infrastructure/persistence/repository.py",
    _BACKEND_DIRECTORY / "scripts/capture_market_snapshot.py",
)
_PROHIBITED_CAPABILITIES = (
    "create_order",
    "cancel_order",
    "fetch_balance",
    "fetch_positions",
    "set_leverage",
    "api_key",
    "secret",
    "passphrase",
)


def test_capture_command_redacts_database_configuration_when_absent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    test_database_url = "postgresql+asyncpg://test:test@localhost/research_test"
    run_capture = _load_capture_command()

    exit_code = run_capture(
        settings=AppSettings(
            database_url=None,
            test_database_url=SecretStr(test_database_url),
        ),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "数据库未配置，无法执行市场快照采集" in captured.err
    assert "DATABASE_URL" not in captured.out + captured.err
    assert "TEST_DATABASE_URL" not in captured.out + captured.err
    assert test_database_url not in captured.out + captured.err


@pytest.mark.parametrize("module_path", _PUBLIC_ONLY_MODULES)
def test_capture_modules_exclude_private_exchange_capabilities(module_path: Path) -> None:
    source = module_path.read_text(encoding="utf-8").lower()

    assert all(capability not in source for capability in _PROHIBITED_CAPABILITIES)


def _load_capture_command() -> Callable[..., int]:
    module_path = _BACKEND_DIRECTORY / "scripts/capture_market_snapshot.py"
    specification = spec_from_file_location("capture_market_snapshot", module_path)
    assert specification is not None
    assert specification.loader is not None
    module = module_from_spec(specification)
    specification.loader.exec_module(module)
    return cast(Callable[..., int], module.run_capture)
