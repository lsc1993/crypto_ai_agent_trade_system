# 验证手动日志、腿、现金流与追加审计的数据库事务。
# 更新以作废旧事实并追加新事实表达，归档保留可追溯记录。
# 未知报告关联和重复活动成交需拒绝，审计触发器阻止历史篡改。
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.trades import (
    TradeAuditEventRecord,
    TradeLegRecord,
)
from app.infrastructure.persistence.trade_repository import SqlAlchemyTradeRepository
from app.market.contracts import ContractSymbol
from app.trades.calculator import TradeCalculator
from app.trades.contracts import (
    TradeCashflowDraft,
    TradeDirection,
    TradeDraft,
    TradeFilters,
    TradeHorizon,
    TradeLegAction,
    TradeLegDraft,
    TradeStorageUnavailableError,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


class MigratedDatabase(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


@pytest.mark.asyncio
async def test_repository_persists_lists_and_archives_manual_trade(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyTradeRepository(migrated_database.session_factory)
    draft = _closed_trade_draft("created")
    created = await repository.create(
        draft=draft,
        pnl=_pnl(draft),
        occurred_at=NOW,
        correlation_id=uuid4(),
    )

    listed = await repository.list(TradeFilters(page=1, page_size=20))

    assert listed.items == (created,)
    assert created.net_pnl == Decimal("49.1")
    assert created.status.value == "closed"
    assert created.closed_at == NOW + timedelta(hours=1)

    await repository.archive(
        created.id,
        occurred_at=NOW + timedelta(minutes=1),
        correlation_id=uuid4(),
    )

    assert (await repository.list(TradeFilters(page=1, page_size=20))).items == ()
    assert await repository.list_closed(TradeFilters(page=1, page_size=20)) == ()


@pytest.mark.asyncio
async def test_repository_voids_replaced_facts_and_appends_audit_event(
    migrated_database: MigratedDatabase,
) -> None:
    session_factory = migrated_database.session_factory
    repository = SqlAlchemyTradeRepository(session_factory)
    original_draft = _closed_trade_draft("original")
    created = await repository.create(
        draft=original_draft,
        pnl=_pnl(original_draft),
        occurred_at=NOW,
        correlation_id=uuid4(),
    )
    replacement_draft = _closed_trade_draft("replacement", close_price="130")

    updated = await repository.replace(
        trade_id=created.id,
        draft=replacement_draft,
        pnl=_pnl(replacement_draft),
        occurred_at=NOW + timedelta(minutes=1),
        correlation_id=uuid4(),
    )

    assert updated is not None
    assert updated.id == created.id
    assert updated.net_pnl == Decimal("79.1")
    async with session_factory() as session:
        audit_events = tuple(
            (
                await session.execute(
                    select(TradeAuditEventRecord).order_by(TradeAuditEventRecord.occurred_at)
                )
            ).scalars()
        )
        legs = tuple((await session.execute(select(TradeLegRecord))).scalars())

    assert [event.action for event in audit_events] == ["created", "updated"]
    assert sum(leg.voided_at is not None for leg in legs) == len(original_draft.legs)
    assert sum(leg.voided_at is None for leg in legs) == len(replacement_draft.legs)


@pytest.mark.asyncio
async def test_repository_database_trigger_rejects_audit_mutation(
    migrated_database: MigratedDatabase,
) -> None:
    session_factory = migrated_database.session_factory
    repository = SqlAlchemyTradeRepository(session_factory)
    draft = _closed_trade_draft("immutable")
    await repository.create(
        draft=draft,
        pnl=_pnl(draft),
        occurred_at=NOW,
        correlation_id=uuid4(),
    )

    with pytest.raises(DBAPIError):
        async with session_factory.begin() as session:
            await session.execute(text("UPDATE trade_audit_events SET action = 'updated'"))

    with pytest.raises(DBAPIError):
        async with session_factory.begin() as session:
            await session.execute(text("DELETE FROM trade_audit_events"))


@pytest.mark.asyncio
async def test_repository_rejects_unknown_linked_report(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyTradeRepository(migrated_database.session_factory)
    draft = _closed_trade_draft("unknown-report").model_copy(
        update={"linked_report_id": uuid4()}
    )

    with pytest.raises(TradeStorageUnavailableError):
        await repository.create(
            draft=draft,
            pnl=_pnl(draft),
            occurred_at=NOW,
            correlation_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_database_rejects_duplicate_active_leg_execution(
    migrated_database: MigratedDatabase,
) -> None:
    session_factory = migrated_database.session_factory
    repository = SqlAlchemyTradeRepository(session_factory)
    draft = _closed_trade_draft("unique-active-leg")
    created = await repository.create(
        draft=draft,
        pnl=_pnl(draft),
        occurred_at=NOW,
        correlation_id=uuid4(),
    )

    with pytest.raises(DBAPIError):
        async with session_factory.begin() as session:
            active_leg = (
                await session.execute(
                    select(TradeLegRecord)
                    .where(TradeLegRecord.trade_id == created.id)
                    .order_by(TradeLegRecord.executed_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            assert active_leg is not None
            session.add(
                TradeLegRecord(
                    id=uuid4(),
                    trade_id=created.id,
                    action=active_leg.action,
                    executed_at=active_leg.executed_at,
                    sequence=active_leg.sequence,
                    price=active_leg.price,
                    quantity=active_leg.quantity,
                    fee=active_leg.fee,
                    voided_at=None,
                )
            )


def _closed_trade_draft(name: str, *, close_price: str = "120") -> TradeDraft:
    return TradeDraft(
        symbol=ContractSymbol.BTCUSDT,
        direction=TradeDirection.LONG,
        horizon=TradeHorizon.SHORT_TERM,
        labels=("manual", "journal"),
        linked_report_id=None,
        leverage=Decimal("2"),
        legs=(
            _leg(name, "open-1", "open", NOW, 0, "100", "2", "0.2"),
            _leg(name, "open-2", "open", NOW, 1, "110", "1", "0.1"),
            _leg(name, "close", "close", NOW + timedelta(hours=1), 0, close_price, "3", "0.3"),
        ),
        cashflows=(
            TradeCashflowDraft(
                id=_identifier(name, "funding-paid"),
                occurred_at=NOW + timedelta(minutes=30),
                amount=Decimal("-0.4"),
                reason="funding payment",
            ),
            TradeCashflowDraft(
                id=_identifier(name, "funding-earned"),
                occurred_at=NOW + timedelta(minutes=45),
                amount=Decimal("0.1"),
                reason="funding received",
            ),
        ),
        thesis="manual trade thesis",
        review="manual trade review",
    )


def _leg(
    trade_name: str,
    name: str,
    action: TradeLegAction | str,
    executed_at: datetime,
    sequence: int,
    price: str,
    quantity: str,
    fee: str,
) -> TradeLegDraft:
    return TradeLegDraft(
        id=_identifier(trade_name, name),
        action=TradeLegAction(action),
        executed_at=executed_at,
        sequence=sequence,
        price=Decimal(price),
        quantity=Decimal(quantity),
        fee=Decimal(fee),
    )


def _pnl(draft: TradeDraft):
    return TradeCalculator().calculate(
        direction=draft.direction,
        legs=draft.legs,
        cashflows=draft.cashflows,
    )


def _identifier(*parts: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://example.invalid/trades/{'/'.join(parts)}")
