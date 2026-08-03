from datetime import datetime
from typing import Protocol

from app.market.contracts import (
    Candle,
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


class HistoricalCandleGateway(Protocol):
    async def load_closed_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[Candle, ...]: ...
