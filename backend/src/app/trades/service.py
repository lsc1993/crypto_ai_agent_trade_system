from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.trades.calculator import TradeCalculator, TradePnl
from app.trades.contracts import PersistedTrade, TradeDraft, TradeValidationError
from app.trades.repository import TradeRepository


class TradeNotFoundError(LookupError):
    """请求的活动交易不存在，或已经归档。"""


class TradeService:
    """在写入前重算手工交易的确定性派生盈亏。"""

    def __init__(
        self,
        *,
        repository: TradeRepository,
        calculator: TradeCalculator | None = None,
        clock: Callable[[], datetime] | None = None,
        correlation_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repository = repository
        self._calculator = calculator or TradeCalculator()
        self._clock = clock or _utc_now
        self._correlation_id_factory = correlation_id_factory

    async def create_trade(self, draft: TradeDraft) -> PersistedTrade:
        pnl = self._calculate(draft)
        occurred_at = self._event_time()
        return await self._repository.create(
            draft=draft,
            pnl=pnl,
            occurred_at=occurred_at,
            correlation_id=self._correlation_id_factory(),
        )

    async def update_trade(self, trade_id: UUID, draft: TradeDraft) -> PersistedTrade:
        current = await self._repository.get_by_id(trade_id)
        if current is None or current.archived_at is not None:
            raise TradeNotFoundError("交易不存在或已归档")
        pnl = self._calculate(draft)
        occurred_at = self._event_time()
        updated = await self._repository.replace(
            trade_id=trade_id,
            draft=draft,
            pnl=pnl,
            occurred_at=occurred_at,
            correlation_id=self._correlation_id_factory(),
        )
        if updated is None:
            raise TradeNotFoundError("交易不存在或已归档")
        return updated

    async def archive_trade(self, trade_id: UUID) -> None:
        archived = await self._repository.archive(
            trade_id,
            occurred_at=self._event_time(),
            correlation_id=self._correlation_id_factory(),
        )
        if not archived:
            raise TradeNotFoundError("交易不存在或已归档")

    def _calculate(self, draft: TradeDraft) -> TradePnl:
        return self._calculator.calculate(
            direction=draft.direction,
            legs=draft.legs,
            cashflows=draft.cashflows,
        )

    def _event_time(self) -> datetime:
        occurred_at = self._clock()
        if occurred_at.tzinfo is None or occurred_at.utcoffset() != timedelta(0):
            raise TradeValidationError("服务时钟必须返回 UTC 且带时区的时间")
        return occurred_at.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)
