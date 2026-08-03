from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.market.contracts import Candle
from app.research.backtests.contracts import (
    BacktestFilters,
    BacktestPage,
    BacktestRequest,
    BacktestResult,
    PersistedBacktestRun,
)


class BacktestRepository(Protocol):
    async def create_pending(
        self,
        request: BacktestRequest,
        *,
        occurred_at: datetime,
    ) -> PersistedBacktestRun: ...

    async def complete(
        self,
        run_id: UUID,
        result: BacktestResult,
        candles: tuple[Candle, ...],
        *,
        occurred_at: datetime,
    ) -> PersistedBacktestRun: ...

    async def fail(
        self,
        run_id: UUID,
        *,
        code: str,
        message: str,
        occurred_at: datetime,
    ) -> PersistedBacktestRun: ...

    async def list(self, filters: BacktestFilters) -> BacktestPage: ...

    async def get_by_id(self, run_id: UUID) -> PersistedBacktestRun | None: ...
