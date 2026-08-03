from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from app.market.contracts import ContractSymbol
from app.trades.calculator import TradePnl
from app.trades.contracts import (
    PersistedTrade,
    TradeDirection,
    TradeDraft,
    TradeFilters,
    TradeHorizon,
    TradeLegAction,
    TradeLegDraft,
    TradePage,
    TradeStatus,
)
from app.trades.service import TradeNotFoundError, TradeService

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000777")


@pytest.mark.asyncio
async def test_create_trade_calculates_pnl_and_uses_one_clock_and_correlation_id() -> None:
    repository = FakeTradeRepository()
    draft = _closed_draft()
    service = TradeService(
        repository=repository,
        clock=lambda: NOW,
        correlation_id_factory=lambda: CORRELATION_ID,
    )

    created = await service.create_trade(draft)

    assert created == repository.created_trade
    assert repository.create_calls[0].draft == draft
    assert repository.create_calls[0].pnl.net_pnl == Decimal("19.7")
    assert repository.create_calls[0].occurred_at == NOW
    assert repository.create_calls[0].correlation_id == CORRELATION_ID


@pytest.mark.asyncio
async def test_update_unknown_trade_returns_typed_not_found_without_a_write() -> None:
    repository = FakeTradeRepository(has_existing_trade=False)
    service = TradeService(
        repository=repository,
        clock=lambda: NOW,
        correlation_id_factory=lambda: CORRELATION_ID,
    )

    with pytest.raises(TradeNotFoundError):
        await service.update_trade(uuid4(), _closed_draft())

    assert repository.replace_calls == []


@pytest.mark.asyncio
async def test_calculator_rejection_does_not_record_a_write() -> None:
    repository = FakeTradeRepository()
    invalid_draft = _closed_draft().model_copy(
        update={"legs": (_leg("open", "open", "100", "1"), _leg("close", "close", "90", "2"))}
    )
    service = TradeService(
        repository=repository,
        clock=lambda: NOW,
        correlation_id_factory=lambda: CORRELATION_ID,
    )

    with pytest.raises(ValueError, match="减仓或平仓数量不能超过剩余开仓数量"):
        await service.create_trade(invalid_draft)

    assert repository.create_calls == []
    assert repository.replace_calls == []


class FakeTradeRepository:
    def __init__(self, *, has_existing_trade: bool = True) -> None:
        self.created_trade = _persisted_trade(_closed_draft())
        self.existing_trade = self.created_trade if has_existing_trade else None
        self.create_calls: list[CreateCall] = []
        self.replace_calls: list[ReplaceCall] = []

    async def create(
        self,
        *,
        draft: TradeDraft,
        pnl: TradePnl,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> PersistedTrade:
        self.create_calls.append(
            CreateCall(
                draft=draft,
                pnl=pnl,
                occurred_at=occurred_at,
                correlation_id=correlation_id,
            )
        )
        return self.created_trade

    async def get_by_id(self, trade_id: UUID) -> PersistedTrade | None:
        del trade_id
        return self.existing_trade

    async def replace(
        self,
        *,
        trade_id: UUID,
        draft: TradeDraft,
        pnl: TradePnl,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> PersistedTrade | None:
        self.replace_calls.append(
            ReplaceCall(
                trade_id=trade_id,
                draft=draft,
                pnl=pnl,
                occurred_at=occurred_at,
                correlation_id=correlation_id,
            )
        )
        return self.created_trade

    async def archive(
        self,
        trade_id: UUID,
        *,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> bool:
        del trade_id, occurred_at, correlation_id
        return True

    async def list(self, filters: TradeFilters) -> TradePage:
        return TradePage(
            items=(),
            page=filters.page,
            page_size=filters.page_size,
            total=0,
        )

    async def list_closed(self, filters: TradeFilters) -> tuple[PersistedTrade, ...]:
        del filters
        return ()


@dataclass(frozen=True)
class CreateCall:
    draft: TradeDraft
    pnl: TradePnl
    occurred_at: datetime
    correlation_id: UUID


@dataclass(frozen=True)
class ReplaceCall:
    trade_id: UUID
    draft: TradeDraft
    pnl: TradePnl
    occurred_at: datetime
    correlation_id: UUID


def _closed_draft() -> TradeDraft:
    return TradeDraft(
        symbol=ContractSymbol.BTCUSDT,
        direction=TradeDirection.LONG,
        horizon=TradeHorizon.SHORT_TERM,
        labels=("manual",),
        linked_report_id=None,
        leverage=Decimal("2"),
        legs=(
            _leg("open", "open", "100", "1"),
            _leg("close", "close", "120", "1"),
        ),
        cashflows=(),
        thesis="thesis",
        review="review",
    )


def _leg(name: str, action: str, price: str, quantity: str) -> TradeLegDraft:
    return TradeLegDraft(
        id=uuid5(NAMESPACE_URL, f"https://example.invalid/trades/{name}"),
        action=TradeLegAction(action),
        executed_at=NOW,
        sequence=0 if action == "open" else 1,
        price=Decimal(price),
        quantity=Decimal(quantity),
        fee=Decimal("0.1") if action == "open" else Decimal("0.2"),
    )


def _persisted_trade(draft: TradeDraft) -> PersistedTrade:
    return PersistedTrade(
        **draft.model_dump(),
        id=UUID("00000000-0000-0000-0000-000000000088"),
        status=TradeStatus.CLOSED,
        gross_realized_pnl=Decimal("20"),
        total_fees=Decimal("0.3"),
        total_funding_cashflow=Decimal("0"),
        net_pnl=Decimal("19.7"),
        opened_at=NOW,
        closed_at=NOW,
        archived_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
