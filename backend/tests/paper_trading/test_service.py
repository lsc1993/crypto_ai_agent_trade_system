from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.execution.contracts import DEFAULT_EXECUTION_CONFIG
from app.market.contracts import (
    Candle,
    ContractSymbol,
    DataFreshness,
    FreshnessStatus,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.paper_trading.contracts import (
    ManualPaperIntent,
    PaperAccount,
    PaperAccountCreate,
    PaperAccountDetail,
    PaperAccountFilters,
    PaperAccountPage,
    PaperAccountStatus,
    PaperActionOutcome,
    PaperPosition,
    PaperTransition,
)
from app.paper_trading.service import PaperTradingService
from app.risk.contracts import DEFAULT_RISK_CONFIG
from app.strategy.contracts import IntentAction, IntentSource

ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000903")
REQUEST_ID = UUID("00000000-0000-0000-0000-000000000904")
NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_manual_open_uses_one_public_quote_and_persists_manual_intent() -> None:
    repository = FakePaperRepository(_detail())
    market = FakePublicMarket(_market_detail(price="100"), _closed_candles())
    service = PaperTradingService(
        market=market,
        history=market,
        repository=repository,
        clock=lambda: NOW,
    )

    result = await service.submit_manual_intent(
        ACCOUNT_ID,
        ManualPaperIntent(
            client_request_id=REQUEST_ID,
            action=IntentAction.OPEN_LONG,
        ),
    )

    assert market.get_market_calls == 1
    assert result.action_outcome is not None
    assert result.action_outcome.source is IntentSource.MANUAL
    assert repository.transitions[0].snapshot.price == Decimal("100")


@pytest.mark.asyncio
async def test_strategy_without_cross_persists_no_signal_without_order() -> None:
    repository = FakePaperRepository(_detail())
    market = FakePublicMarket(_market_detail(price="100"), _closed_candles())
    service = PaperTradingService(
        market=market,
        history=market,
        repository=repository,
        clock=lambda: NOW,
    )

    first = await service.evaluate_strategy(ACCOUNT_ID)
    second = await service.evaluate_strategy(ACCOUNT_ID)

    assert first.action_outcome is not None
    assert first.action_outcome.kind.value == "no_signal"
    assert first.action_outcome.source is IntentSource.STRATEGY
    assert first.orders == ()
    assert second == first
    assert market.history_calls == 1


class FakePaperRepository:
    def __init__(self, detail: PaperAccountDetail) -> None:
        self.detail = detail
        self.outcomes: dict[str, PaperActionOutcome] = {}
        self.transitions: list[PaperTransition] = []

    async def create_account(
        self,
        request: PaperAccountCreate,
        *,
        occurred_at: datetime,
    ) -> PaperAccountDetail:
        return self.detail

    async def list(self, filters: PaperAccountFilters) -> PaperAccountPage:
        return PaperAccountPage(items=(), page=filters.page, page_size=filters.page_size, total=0)

    async def get_by_id(self, account_id: UUID) -> PaperAccountDetail | None:
        return self.detail if account_id == ACCOUNT_ID else None

    async def find_outcome(
        self,
        account_id: UUID,
        idempotency_key: str,
    ) -> PaperActionOutcome | None:
        return self.outcomes.get(idempotency_key)

    async def apply_transition(
        self,
        account_id: UUID,
        idempotency_key: str,
        transition: PaperTransition,
        *,
        occurred_at: datetime,
    ) -> PaperAccountDetail:
        self.transitions.append(transition)
        self.outcomes[idempotency_key] = transition.outcome
        self.detail = self.detail.model_copy(
            update={
                "account": transition.account,
                "position": transition.position,
                "latest_snapshot": transition.snapshot,
                "orders": self.detail.orders + transition.orders,
                "fills": self.detail.fills + transition.fills,
                "ledger_entries": self.detail.ledger_entries + transition.ledger_entries,
                "events": self.detail.events + transition.events,
                "action_outcome": transition.outcome,
            }
        )
        return self.detail

    async def record_market_failure(
        self,
        account_id: UUID,
        idempotency_key: str,
        *,
        code: str,
        occurred_at: datetime,
    ) -> PaperAccountDetail:
        return self.detail

    async def archive(self, account_id: UUID, *, occurred_at: datetime) -> PaperAccountDetail:
        return self.detail


class FakePublicMarket:
    def __init__(self, detail: MarketDetail, candles: tuple[Candle, ...]) -> None:
        self._detail = detail
        self._candles = candles
        self.get_market_calls = 0
        self.history_calls = 0

    async def get_summaries(self, symbols: tuple[ContractSymbol, ...]):
        return (self._detail.summary,)

    async def get_market(
        self,
        symbol: ContractSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        self.get_market_calls += 1
        assert symbol is ContractSymbol.BTCUSDT
        assert timeframes == (MarketTimeframe.H1,)
        return self._detail

    async def load_closed_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[Candle, ...]:
        self.history_calls += 1
        assert symbol is ContractSymbol.BTCUSDT
        assert timeframe is MarketTimeframe.H1
        assert start_at == NOW - timedelta(hours=51)
        assert end_at == NOW
        return self._candles


def _detail() -> PaperAccountDetail:
    account = PaperAccount(
        id=ACCOUNT_ID,
        status=PaperAccountStatus.ACTIVE,
        symbol=ContractSymbol.BTCUSDT,
        initial_cash=Decimal("10000"),
        cash=Decimal("10000"),
        equity=Decimal("10000"),
        peak_equity=Decimal("10000"),
        daily_start_equity=Decimal("10000"),
        daily_realized_loss=Decimal("0"),
        daily_day=NOW.date(),
        cooldown_remaining=0,
        last_closed_candle_at=None,
        risk_config=DEFAULT_RISK_CONFIG,
        execution_config=DEFAULT_EXECUTION_CONFIG,
        created_at=NOW,
        archived_at=None,
    )
    return PaperAccountDetail(
        account=account,
        position=PaperPosition(
            account_id=ACCOUNT_ID,
            quantity=Decimal("0"),
            average_entry_price=None,
            remaining_entry_cost=Decimal("0"),
            opened_at=None,
            updated_at=NOW,
        ),
        latest_snapshot=None,
        orders=(),
        fills=(),
        ledger_entries=(),
        events=(),
        action_outcome=None,
    )


def _market_detail(*, price: str) -> MarketDetail:
    return MarketDetail(
        summary=MarketSummary(
            symbol=ContractSymbol.BTCUSDT,
            price=Decimal(price),
            change_24h=Decimal("0"),
            volume_24h=Decimal("1"),
            funding_rate=Decimal("0"),
            open_interest=Decimal("1"),
            freshness=DataFreshness(
                status=FreshnessStatus.FRESH,
                source="binance_usdm_public",
                observed_at=NOW,
                fetched_at=NOW,
            ),
        ),
        series=(),
    )


def _closed_candles() -> tuple[Candle, ...]:
    return tuple(
        Candle(
            symbol=ContractSymbol.BTCUSDT,
            timeframe=MarketTimeframe.H1,
            open_at=NOW - timedelta(hours=51 - offset),
            close_at=NOW - timedelta(hours=50 - offset, milliseconds=1),
            open_price=Decimal("100"),
            high_price=Decimal("100"),
            low_price=Decimal("100"),
            close_price=Decimal("100"),
            volume=Decimal("1"),
            observed_at=NOW,
            fetched_at=NOW,
        )
        for offset in range(51)
    )
