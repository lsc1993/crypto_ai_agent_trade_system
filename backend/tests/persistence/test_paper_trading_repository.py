from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.execution.contracts import ExecutionQuote
from app.infrastructure.persistence.models.paper_trading import PaperFillRecord
from app.infrastructure.persistence.paper_trading_repository import (
    SqlAlchemyPaperTradingRepository,
)
from app.market.contracts import ContractSymbol
from app.paper_trading.contracts import (
    PaperAccount,
    PaperAccountCreate,
    PaperAccountStateError,
    PaperPosition,
    PaperTransition,
)
from app.paper_trading.engine import PaperTradingEngine
from app.strategy.contracts import IntentAction, IntentSource, TradeIntent
from tests.conftest import MigratedDatabase

NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)
REQUEST_ID = UUID("00000000-0000-0000-0000-000000000902")


@pytest.mark.asyncio
async def test_repository_persists_transition_and_reuses_idempotent_outcome(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyPaperTradingRepository(migrated_database.session_factory)
    created = await repository.create_account(
        PaperAccountCreate(initial_cash=Decimal("10000")),
        occurred_at=NOW,
    )
    transition = _open_transition(created.account.id, created.account, created.position)

    first = await repository.apply_transition(
        created.account.id,
        "paper:manual:open",
        transition,
        occurred_at=NOW,
    )
    replay = await repository.apply_transition(
        created.account.id,
        "paper:manual:open",
        transition,
        occurred_at=NOW,
    )

    assert replay == first
    assert first.action_outcome is not None
    assert first.action_outcome.source is IntentSource.MANUAL
    async with migrated_database.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(PaperFillRecord))
    assert count == 1


@pytest.mark.asyncio
async def test_repository_rejects_archive_while_position_is_open(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyPaperTradingRepository(migrated_database.session_factory)
    created = await repository.create_account(
        PaperAccountCreate(initial_cash=Decimal("10000")),
        occurred_at=NOW,
    )
    transition = _open_transition(created.account.id, created.account, created.position)
    await repository.apply_transition(
        created.account.id,
        "paper:manual:open",
        transition,
        occurred_at=NOW,
    )

    with pytest.raises(PaperAccountStateError, match="持仓"):
        await repository.archive(created.account.id, occurred_at=NOW)


def _open_transition(
    account_id: UUID,
    account: PaperAccount,
    position: PaperPosition,
) -> PaperTransition:
    return PaperTradingEngine().apply(
        account=account,
        position=position,
        intent=TradeIntent(
            run_id=account_id,
            symbol=ContractSymbol.BTCUSDT,
            action=IntentAction.OPEN_LONG,
            decision_at=NOW,
            source=IntentSource.MANUAL,
            idempotency_key="paper:manual:open",
        ),
        quote=ExecutionQuote(
            symbol=ContractSymbol.BTCUSDT,
            price=Decimal("100"),
            observed_at=NOW,
            fetched_at=NOW,
            source="binance_usdm_public",
        ),
        latest_closed_candle_at=NOW,
    )
