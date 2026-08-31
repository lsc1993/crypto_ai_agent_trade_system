import tomllib
from pathlib import Path

from packaging.requirements import Requirement

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_agent_dependencies_include_required_packages_and_exclude_forbidden_packages() -> None:
    pyproject_path = BACKEND_ROOT / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    dependencies = tuple(pyproject["project"]["dependencies"])
    dependency_names = {Requirement(dependency).name for dependency in dependencies}

    assert {"langgraph", "langgraph-checkpoint-postgres", "defusedxml"} <= dependency_names
    assert not {
        dependency
        for dependency in dependencies
        if dependency.startswith("langchain-openai")
        or dependency.startswith("ccxt")
        or dependency.startswith(("binance", "coinbase", "kraken", "okx", "bybit"))
    }


def test_harness_source_has_no_risk_execution_or_persistence_implementation_dependency() -> None:
    harness_files = sorted((BACKEND_ROOT / "src" / "app" / "harness").rglob("*.py"))
    assert harness_files

    forbidden = (
        "app.risk",
        "app.execution",
        "app.paper_trading",
        "app.infrastructure.persistence",
        "ccxt",
    )
    violations = {
        str(path.relative_to(BACKEND_ROOT)): tuple(
            token for token in forbidden if token in path.read_text(encoding="utf-8").lower()
        )
        for path in harness_files
    }
    assert not {path: tokens for path, tokens in violations.items() if tokens}


def test_live_agent_factory_routes_market_research_through_the_harness() -> None:
    source = (BACKEND_ROOT / "src" / "app" / "main.py").read_text(encoding="utf-8")

    assert "HarnessRuntime[PersistedAnalysisReport]" in source
    assert "MarketResearchWorkflow(agent_service)" in source
    assert "return HarnessedMarketResearchService(" in source
    assert "app.state.harness_runtime" not in source
