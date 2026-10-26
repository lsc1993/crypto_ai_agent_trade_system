# 综合市场研究的固定策略配置：公开市场、批准新闻、受限模型与不可变报告保存。
# 预置标的保留静态兼容入口，额外研究标的必须通过目录准入；能力不随标的扩展。
from app.harness.contracts import (
    HarnessCapability,
    HarnessPolicy,
    HarnessRunKind,
)
from app.market.contracts import ContractSymbol

MARKET_RESEARCH_POLICY = HarnessPolicy(
    version="market_research_v1",
    run_kind=HarnessRunKind.MARKET_RESEARCH,
    allowed_symbols=(ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT),
    symbol_admission="research_directory",
    allowed_capabilities=(
        HarnessCapability.READ_PUBLIC_MARKET,
        HarnessCapability.READ_APPROVED_NEWS,
        HarnessCapability.CALL_RESEARCH_MODEL,
        HarnessCapability.PERSIST_IMMUTABLE_REPORT,
    ),
)
