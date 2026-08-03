from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.market.contracts import MarketDataUnavailableError
from app.market.gateway import HistoricalCandleGateway
from app.research.backtests.contracts import (
    BacktestFilters,
    BacktestNotFoundError,
    BacktestPage,
    BacktestRequest,
    ExpectedBacktestFailure,
    PersistedBacktestRun,
)
from app.research.backtests.engine import DeterministicBacktestEngine
from app.research.backtests.repository import BacktestRepository


class BacktestService:
    """协调受限历史行情、纯回放引擎和可审计回测仓储。"""

    def __init__(
        self,
        *,
        history: HistoricalCandleGateway,
        repository: BacktestRepository,
        engine: DeterministicBacktestEngine,
        clock: Callable[[], datetime],
    ) -> None:
        self._history = history
        self._repository = repository
        self._engine = engine
        self._clock = clock

    async def start(self, request: BacktestRequest) -> PersistedBacktestRun:
        pending = await self._repository.create_pending(
            request,
            occurred_at=self._now(),
        )
        try:
            candles = await self._history.load_closed_candles(
                request.symbol,
                request.timeframe,
                start_at=request.warmup_start_at,
                end_at=request.end_at,
            )
            result = self._engine.run(pending.id, request, candles)
            return await self._repository.complete(
                pending.id,
                result,
                candles,
                occurred_at=self._now(),
            )
        except MarketDataUnavailableError as error:
            await self._repository.fail(
                pending.id,
                code=error.code,
                message=str(error),
                occurred_at=self._now(),
            )
            raise
        except ExpectedBacktestFailure as error:
            return await self._repository.fail(
                pending.id,
                code=error.code,
                message=error.safe_message,
                occurred_at=self._now(),
            )

    async def list(self, filters: BacktestFilters) -> BacktestPage:
        return await self._repository.list(filters)

    async def get(self, run_id: UUID) -> PersistedBacktestRun:
        run = await self._repository.get_by_id(run_id)
        if run is None:
            raise BacktestNotFoundError("回测运行不存在")
        return run

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("回测服务时钟必须返回 UTC 带时区时间")
        return value.astimezone(UTC)
