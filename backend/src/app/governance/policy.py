# 固定研究/规划策略配置：公开市场、受限模型、知识/策略读取及已登记的规划工具。
# 预置标的保留静态兼容入口，额外研究标的必须通过目录准入；能力不随标的扩展。
# 授予 planning 能力不等于当前已注册规划工具；工具可用性仍由 T09/T14 的目录与守卫决定。
from app.governance.contracts import (
    GovernanceCapability,
    GovernancePolicy,
    GovernanceRunKind,
)
from app.market.contracts import ContractSymbol

MARKET_RESEARCH_POLICY = GovernancePolicy(
    version="market_research_v1",
    run_kind=GovernanceRunKind.MARKET_RESEARCH,
    allowed_symbols=(ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT),
    symbol_admission="research_directory",
    allowed_capabilities=(
        GovernanceCapability.READ_PUBLIC_MARKET,
        GovernanceCapability.READ_APPROVED_NEWS,
        GovernanceCapability.CALL_RESEARCH_MODEL,
        GovernanceCapability.PERSIST_IMMUTABLE_REPORT,
    ),
)

# 交互式分析/规划片段使用独立策略版本；研究能力与规划请求能力分开登记。
# 策略只覆盖公开证据、已发布策略/知识、确定性规划请求和已登记工具，
# 不包含私有账户、订单执行、预算追加或计划采纳（这些仍走 AP-01/AP-05 审核）。
INTERACTIVE_PLANNING_POLICY = GovernancePolicy(
    version="interactive_planning_v1",
    run_kind=GovernanceRunKind.INTERACTIVE_PLANNING,
    allowed_symbols=(ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT),
    symbol_admission="research_directory",
    allowed_capabilities=(
        GovernanceCapability.READ_PUBLIC_MARKET,
        GovernanceCapability.READ_APPROVED_NEWS,
        GovernanceCapability.CALL_RESEARCH_MODEL,
        GovernanceCapability.PERSIST_IMMUTABLE_REPORT,
        GovernanceCapability.READ_RESEARCH_KNOWLEDGE,
        GovernanceCapability.READ_STRATEGY_CATALOG,
        GovernanceCapability.EVALUATE_SELECTED_STRATEGY,
        GovernanceCapability.REQUEST_MANUAL_PLANNING,
        GovernanceCapability.USE_REGISTERED_RESEARCH_TOOL,
    ),
)
