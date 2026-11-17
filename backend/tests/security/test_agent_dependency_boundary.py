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

    assert {
        "langgraph",
        "langgraph-checkpoint-postgres",
        "defusedxml",
        "mcp",
        "httpx2",
    } <= dependency_names
    assert not {
        dependency
        for dependency in dependencies
        if dependency.startswith("langchain-openai")
        or dependency.startswith("ccxt")
        or dependency.startswith(("binance", "coinbase", "kraken", "okx", "bybit"))
        or dependency.startswith("mcp[")
    }


# 扫描范围含注释，维护说明也不能错误地宣称治理内核拥有外部实现依赖。
def test_governance_source_has_no_risk_execution_or_persistence_implementation_dependency() -> None:
    governance_files = sorted((BACKEND_ROOT / "src" / "app" / "governance").rglob("*.py"))
    assert governance_files
    assert "audit.py" in {path.name for path in governance_files}

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
        for path in governance_files
    }
    assert not {path: tokens for path, tokens in violations.items() if tokens}


def test_live_agent_factory_routes_market_research_through_the_governance_kernel() -> None:
    source = (BACKEND_ROOT / "src" / "app" / "main.py").read_text(encoding="utf-8")

    assert "GovernanceRuntime[PersistedAnalysisReport]" in source
    assert "MarketResearchWorkflow(agent_service)" in source
    assert "SqlAlchemyHarnessAuditRepository(session_factory)" in source
    assert "return GovernedMarketResearchService(" in source
    assert "app.state.harness_runtime" not in source
    assert "app.state.harness_audit_repository" not in source
    assert "app.state.governance_runtime" not in source
    assert "app.state.audit_repository" not in source


def test_interactive_tool_modules_cannot_import_trade_execution_or_model_clients() -> None:
    # 工具处理器只依赖研究端口/领域服务；模型循环、真实发送和交易实现不能下沉到工具层。
    files = tuple((BACKEND_ROOT / "src" / "app" / "agent" / "interactive" / "tools").glob("*.py"))
    assert files
    forbidden = (
        "app.execution",
        "app.risk",
        "app.strategy",
        "app.paper_trading",
        "openai",
        "anthropic",
        "langchain",
        "langgraph",
        "litellm",
    )
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path


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


# MCP 基础设施只能承载本地只读策略定义；不得下沉交易、任意网络/进程或模型客户端能力。
def test_mcp_infrastructure_is_read_only_and_has_no_trade_or_generic_network_surface() -> None:
    files = sorted((BACKEND_ROOT / "src" / "app" / "infrastructure" / "mcp").glob("*.py"))
    assert files
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)
    forbidden = (
        "app.execution",
        "app.risk",
        "app.strategy",
        "app.paper_trading",
        "app.agent.interactive.model_port",
        "openai",
        "anthropic",
        "langchain",
        "langgraph",
        "litellm",
        "ccxt",
        "subprocess",
        "os.system",
        "stdio_client",
        "SamplingFnT",
        "ListRootsFnT",
        "ElicitationFnT",
        "sampling_callback",
        "list_roots_callback",
        "elicitation_callback",
        "create_order",
        "cancel_order",
        "fetch_balance",
        "fetch_positions",
        "private_key",
        "api_key",
        "secret_key",
        "build_manual_trade_plan",
    )
    assert not {token for token in forbidden if token in source}
    # 只登记一个只读工具，且不注册模型可调用的批准/订单工具。
    assert source.count("@server.tool(") == 1
    assert 'STRATEGY_DEFINITION_TOOL = "read_strategy_definition"' in source
    assert "app.infrastructure.mcp" in source
    assert "httpx2" in source
    assert "httpx." not in source
