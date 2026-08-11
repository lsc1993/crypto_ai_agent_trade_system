import tomllib
from pathlib import Path


def test_agent_dependencies_include_required_packages_and_exclude_forbidden_packages() -> None:
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    dependencies = tuple(pyproject["project"]["dependencies"])

    assert all(
        any(dependency.startswith(package) for dependency in dependencies)
        for package in ("langgraph", "langgraph-checkpoint-postgres", "defusedxml")
    )
    assert not {
        dependency
        for dependency in dependencies
        if dependency.startswith("langchain-openai")
        or dependency.startswith("ccxt")
        or dependency.startswith(("binance", "coinbase", "kraken", "okx", "bybit"))
    }
