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
    allowed_capabilities=(
        HarnessCapability.READ_PUBLIC_MARKET,
        HarnessCapability.READ_APPROVED_NEWS,
        HarnessCapability.CALL_RESEARCH_MODEL,
        HarnessCapability.PERSIST_IMMUTABLE_REPORT,
    ),
)
