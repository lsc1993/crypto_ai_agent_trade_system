from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.trades.calculator import TradePnl
from app.trades.contracts import PersistedTrade, TradeDraft, TradeFilters, TradePage


class TradeRepository(Protocol):
    async def create(
        self,
        *,
        draft: TradeDraft,
        pnl: TradePnl,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> PersistedTrade: ...

    async def replace(
        self,
        *,
        trade_id: UUID,
        draft: TradeDraft,
        pnl: TradePnl,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> PersistedTrade | None: ...

    async def archive(
        self,
        trade_id: UUID,
        *,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> bool: ...

    async def get_by_id(self, trade_id: UUID) -> PersistedTrade | None: ...

    async def list(self, filters: TradeFilters) -> TradePage: ...

    async def list_closed(self, filters: TradeFilters) -> tuple[PersistedTrade, ...]: ...
