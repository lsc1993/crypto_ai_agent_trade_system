from typing import Protocol

from app.market.contracts import (
    ContractSymbol,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)


class PublicMarketGateway(Protocol):
    async def get_summaries(
        self,
        symbols: tuple[ContractSymbol, ...],
    ) -> tuple[MarketSummary, ...]: ...

    async def get_market(
        self,
        symbol: ContractSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail: ...
