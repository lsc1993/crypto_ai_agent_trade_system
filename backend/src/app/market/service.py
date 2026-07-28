from app.market.contracts import (
    ContractSymbol,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.gateway import PublicMarketGateway


class MarketQueryService:
    """为 API 提供已标准化的只读公开市场数据。"""

    def __init__(self, gateway: PublicMarketGateway) -> None:
        self._gateway = gateway

    async def get_summaries(
        self,
        symbols: tuple[ContractSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        return await self._gateway.get_summaries(symbols)

    async def get_market(
        self,
        symbol: ContractSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        return await self._gateway.get_market(symbol, timeframes)
