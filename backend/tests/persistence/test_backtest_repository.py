from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.market.contracts import Candle, ContractSymbol, MarketTimeframe
from app.market.repository import snapshot_payload_sha256
from app.research.backtests.contracts import (
    BacktestAuditEvent,
    BacktestEventKind,
    BacktestFilters,
    BacktestRequest,
    BacktestResult,
    BacktestRunStatus,
    BacktestSummary,
    candle_snapshot_payload,
)

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
RUN_ID = UUID("00000000-0000-0000-0000-000000000801")


class MigratedDatabase(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


@pytest.mark.asyncio
async def test_repository_completes_run_with_immutable_snapshot_and_events(
    migrated_database: MigratedDatabase,
) -> None:
    from app.infrastructure.persistence.backtest_repository import SqlAlchemyBacktestRepository

    repository = SqlAlchemyBacktestRepository(migrated_database.session_factory)
    pending = await repository.create_pending(_request(), occurred_at=NOW)
    completed = await repository.complete(
        pending.id,
        _result(),
        _candles(),
        occurred_at=NOW + timedelta(minutes=1),
    )

    assert completed.status is BacktestRunStatus.COMPLETED
    assert completed.result == _result()
    assert completed.finished_at == NOW + timedelta(minutes=1)
    assert (await repository.get_by_id(pending.id)) == completed

    with pytest.raises(DBAPIError):
        async with migrated_database.session_factory.begin() as session:
            await session.execute(
                text("UPDATE backtest_candles SET close_price = 999 WHERE run_id = :run_id"),
                {"run_id": pending.id},
            )
    with pytest.raises(DBAPIError):
        async with migrated_database.session_factory.begin() as session:
            await session.execute(
                text("DELETE FROM backtest_events WHERE run_id = :run_id"),
                {"run_id": pending.id},
            )


@pytest.mark.asyncio
async def test_repository_marks_expected_failures_without_partial_results(
    migrated_database: MigratedDatabase,
) -> None:
    from app.infrastructure.persistence.backtest_repository import SqlAlchemyBacktestRepository

    repository = SqlAlchemyBacktestRepository(migrated_database.session_factory)
    pending = await repository.create_pending(_request(), occurred_at=NOW)
    failed = await repository.fail(
        pending.id,
        code="candles_missing",
        message="回测行情不可用",
        occurred_at=NOW + timedelta(minutes=1),
    )

    assert failed.status is BacktestRunStatus.FAILED
    assert failed.result is None
    assert failed.failure_code == "candles_missing"
    assert failed.failure_message == "回测行情不可用"


@pytest.mark.asyncio
async def test_repository_lists_runs_by_creation_time_descending(
    migrated_database: MigratedDatabase,
) -> None:
    from app.infrastructure.persistence.backtest_repository import SqlAlchemyBacktestRepository

    repository = SqlAlchemyBacktestRepository(migrated_database.session_factory)
    first = await repository.create_pending(_request(), occurred_at=NOW)
    second = await repository.create_pending(_request(), occurred_at=NOW + timedelta(minutes=1))

    page = await repository.list(BacktestFilters(page=1, page_size=20))

    assert page.total == 2
    assert tuple(run.id for run in page.items) == (second.id, first.id)


def _request() -> BacktestRequest:
    return BacktestRequest(
        symbol=ContractSymbol.BTCUSDT,
        timeframe=MarketTimeframe.H1,
        start_at=NOW,
        end_at=NOW + timedelta(hours=1),
        initial_cash=Decimal("10000"),
    )


def _result() -> BacktestResult:
    return BacktestResult(
        summary=BacktestSummary(
            initial_cash=Decimal("10000"),
            final_equity=Decimal("10010"),
            net_pnl=Decimal("10"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("10"),
            return_fraction=Decimal("0.001"),
            max_drawdown_fraction=Decimal("0.002"),
            win_rate=Decimal("0"),
            profit_factor=None,
            closed_trade_count=0,
            fill_count=1,
            rejection_count=0,
            open_position_quantity=Decimal("1"),
            candle_count=1,
            snapshot_hash=snapshot_payload_sha256(candle_snapshot_payload(_candles())),
        ),
        events=(
            BacktestAuditEvent(
                sequence=0,
                kind=BacktestEventKind.FILL,
                occurred_at=NOW,
                candle_sequence=0,
                idempotency_key="backtest:801:fill",
                payload={"price": "100.05", "quantity": "1"},
            ),
        ),
        closed_trades=(),
    )


def _candles() -> tuple[Candle, ...]:
    return (
        Candle(
            symbol=ContractSymbol.BTCUSDT,
            timeframe=MarketTimeframe.H1,
            open_at=NOW,
            close_at=NOW + timedelta(hours=1),
            open_price=Decimal("100"),
            high_price=Decimal("101"),
            low_price=Decimal("99"),
            close_price=Decimal("100"),
            volume=Decimal("10"),
            observed_at=NOW + timedelta(hours=1),
            fetched_at=NOW + timedelta(hours=1),
        ),
    )
