# 静态核对研究依赖、装配路径及跨领域访问边界。
# 读取包配置和源码，不调用模型或交易服务。
# 检查包括源码文本，新增注释也不能被误写为受禁止的依赖或能力声明。
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


# 扫描范围含注释，维护说明也不能错误地宣称协调层拥有外部实现依赖。
def test_harness_source_has_no_risk_execution_or_persistence_implementation_dependency() -> None:
    harness_files = sorted((BACKEND_ROOT / "src" / "app" / "harness").rglob("*.py"))
    assert harness_files
    assert "audit.py" in {path.name for path in harness_files}

    forbidden = (
        "sqlalchemy",
        "alembic",
        "app.risk",
        "app.execution",
        "app.paper_trading",
        "app.infrastructure.persistence",
        "httpx",
        "subprocess",
        "os.system",
        "playwright",
        "selenium",
        "browser",
        "tools=",
        "tool_choice",
        "mcp",
        "api_key",
        "secret_key",
        "private_key",
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
    assert "SqlAlchemyHarnessAuditRepository(session_factory)" in source
    assert "return HarnessedMarketResearchService(" in source
    assert "app.state.harness_runtime" not in source
    assert "app.state.harness_audit_repository" not in source
    assert "app.state.audit_repository" not in source


def test_technical_plan_modules_cannot_access_execution_or_accounts() -> None:
    files = tuple((BACKEND_ROOT / "src" / "app" / "agent" / "technical").glob("*.py"))
    forbidden = (
        "app.execution",
        "app.risk",
        "app.strategy",
        "app.paper_trading",
        "subprocess",
        "ccxt",
    )
    assert files
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden)
