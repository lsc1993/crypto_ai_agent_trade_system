from app.market.contracts import (
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.gateway import PublicMarketGateway
from app.market.symbols import ResearchSymbol


class MarketQueryService:
    """为 API 提供已标准化的只读公开市场数据。"""

    def __init__(self, gateway: PublicMarketGateway) -> None:
        self._gateway = gateway

    async def get_summaries(
        self,
        symbols: tuple[ResearchSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        return await self._gateway.get_summaries(symbols)

    async def get_market(
        self,
        symbol: ResearchSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        return await self._gateway.get_market(symbol, timeframes)
