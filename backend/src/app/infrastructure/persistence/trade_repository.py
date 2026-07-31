from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, and_, delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.trades import (
    TagRecord,
    TradeAuditEventRecord,
    TradeCashflowRecord,
    TradeLegRecord,
    TradeRecord,
    TradeTagRecord,
)
from app.market.contracts import ContractSymbol
from app.trades.calculator import TradePnl
from app.trades.contracts import (
    PersistedTrade,
    TradeAuditAction,
    TradeCashflowDraft,
    TradeDirection,
    TradeDraft,
    TradeFilters,
    TradeHorizon,
    TradeLegAction,
    TradeLegDraft,
    TradePage,
    TradeStatus,
    TradeStorageUnavailableError,
)
from app.trades.repository import TradeRepository


class SqlAlchemyTradeRepository(TradeRepository):
    """保存交易日志，并为每次替换保留可审计的事实历史。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        *,
        draft: TradeDraft,
        pnl: TradePnl,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> PersistedTrade:
        trade_id = uuid4()
        status = _status_for(pnl)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add(
                        _new_trade_record(
                            trade_id=trade_id,
                            draft=draft,
                            pnl=pnl,
                            status=status,
                            occurred_at=occurred_at,
                        )
                    )
                    await session.flush()
                    await _append_active_facts(
                        session,
                        trade_id=trade_id,
                        draft=draft,
                    )
                    await _replace_tags(session, trade_id=trade_id, labels=draft.labels)
                    session.add(
                        TradeAuditEventRecord(
                            id=uuid4(),
                            trade_id=trade_id,
                            action=TradeAuditAction.CREATED.value,
                            correlation_id=correlation_id,
                            occurred_at=occurred_at,
                            before_snapshot=None,
                            after_snapshot=_snapshot(
                                _persisted_from_values(
                                    trade_id=trade_id,
                                    draft=draft,
                                    pnl=pnl,
                                    status=status,
                                    opened_at=_opened_at(draft),
                                    closed_at=_closed_at(draft, pnl),
                                    archived_at=None,
                                    created_at=occurred_at,
                                    updated_at=occurred_at,
                                )
                            ),
                        )
                    )
        except SQLAlchemyError as error:
            raise TradeStorageUnavailableError("交易日志持久化不可用") from error

        persisted = await self.get_by_id(trade_id)
        if persisted is None:
            raise TradeStorageUnavailableError("交易日志持久化不可用")
        return persisted

    async def replace(
        self,
        *,
        trade_id: UUID,
        draft: TradeDraft,
        pnl: TradePnl,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> PersistedTrade | None:
        status = _status_for(pnl)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = await _get_active_trade_for_update(session, trade_id)
                    if record is None:
                        return None
                    before = await _to_persisted_trade(session, record)
                    _apply_trade_update(
                        record,
                        draft=draft,
                        pnl=pnl,
                        status=status,
                        occurred_at=occurred_at,
                    )
                    await _void_active_facts(session, trade_id=trade_id, occurred_at=occurred_at)
                    await _append_active_facts(session, trade_id=trade_id, draft=draft)
                    await _replace_tags(session, trade_id=trade_id, labels=draft.labels)
                    session.add(
                        TradeAuditEventRecord(
                            id=uuid4(),
                            trade_id=trade_id,
                            action=TradeAuditAction.UPDATED.value,
                            correlation_id=correlation_id,
                            occurred_at=occurred_at,
                            before_snapshot=_snapshot(before),
                            after_snapshot=_snapshot(
                                _persisted_from_record_and_draft(record, draft)
                            ),
                        )
                    )
        except SQLAlchemyError as error:
            raise TradeStorageUnavailableError("交易日志持久化不可用") from error

        return await self.get_by_id(trade_id)

    async def archive(
        self,
        trade_id: UUID,
        *,
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> bool:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = await _get_active_trade_for_update(session, trade_id)
                    if record is None:
                        return False
                    before = await _to_persisted_trade(session, record)
                    record.archived_at = occurred_at
                    record.updated_at = occurred_at
                    session.add(
                        TradeAuditEventRecord(
                            id=uuid4(),
                            trade_id=trade_id,
                            action=TradeAuditAction.ARCHIVED.value,
                            correlation_id=correlation_id,
                            occurred_at=occurred_at,
                            before_snapshot=_snapshot(before),
                            after_snapshot=_snapshot(
                                _persisted_from_record_and_draft(
                                    record,
                                    _draft_from_persisted(before),
                                )
                            ),
                        )
                    )
        except SQLAlchemyError as error:
            raise TradeStorageUnavailableError("交易日志持久化不可用") from error
        return True

    async def get_by_id(self, trade_id: UUID) -> PersistedTrade | None:
        try:
            async with self._session_factory() as session:
                record = await _get_trade(session, TradeRecord.id == trade_id)
                return None if record is None else await _to_persisted_trade(session, record)
        except SQLAlchemyError as error:
            raise TradeStorageUnavailableError("交易日志读取不可用") from error

    async def list(self, filters: TradeFilters) -> TradePage:
        conditions = _active_filters(filters)
        statement = (
            select(TradeRecord)
            .where(*conditions)
            .order_by(TradeRecord.updated_at.desc(), TradeRecord.id.desc())
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        )
        count_statement = select(func.count()).select_from(TradeRecord).where(*conditions)
        try:
            async with self._session_factory() as session:
                records = tuple((await session.execute(statement)).scalars())
                total = (await session.execute(count_statement)).scalar_one()
                items = tuple([await _to_persisted_trade(session, record) for record in records])
        except SQLAlchemyError as error:
            raise TradeStorageUnavailableError("交易日志读取不可用") from error
        return TradePage(
            items=items,
            page=filters.page,
            page_size=filters.page_size,
            total=total,
        )

    async def list_closed(self, filters: TradeFilters) -> tuple[PersistedTrade, ...]:
        conditions = _active_filters(filters, required_status=TradeStatus.CLOSED)
        statement = (
            select(TradeRecord)
            .where(*conditions)
            .order_by(TradeRecord.closed_at.asc(), TradeRecord.id.asc())
        )
        try:
            async with self._session_factory() as session:
                records = tuple((await session.execute(statement)).scalars())
                return tuple([await _to_persisted_trade(session, record) for record in records])
        except SQLAlchemyError as error:
            raise TradeStorageUnavailableError("交易日志读取不可用") from error


def _new_trade_record(
    *,
    trade_id: UUID,
    draft: TradeDraft,
    pnl: TradePnl,
    status: TradeStatus,
    occurred_at: datetime,
) -> TradeRecord:
    return TradeRecord(
        id=trade_id,
        symbol=draft.symbol.value,
        direction=draft.direction.value,
        horizon=draft.horizon.value,
        analysis_report_id=draft.linked_report_id,
        leverage=draft.leverage,
        thesis=draft.thesis,
        review=draft.review,
        status=status.value,
        gross_realized_pnl=pnl.gross_realized_pnl,
        total_fees=pnl.total_fees,
        total_funding_cashflow=pnl.total_funding_cashflow,
        net_pnl=pnl.net_pnl,
        opened_at=_opened_at(draft),
        closed_at=_closed_at(draft, pnl),
        archived_at=None,
        updated_at=occurred_at,
    )


def _apply_trade_update(
    record: TradeRecord,
    *,
    draft: TradeDraft,
    pnl: TradePnl,
    status: TradeStatus,
    occurred_at: datetime,
) -> None:
    record.symbol = draft.symbol.value
    record.direction = draft.direction.value
    record.horizon = draft.horizon.value
    record.analysis_report_id = draft.linked_report_id
    record.leverage = draft.leverage
    record.thesis = draft.thesis
    record.review = draft.review
    record.status = status.value
    record.gross_realized_pnl = pnl.gross_realized_pnl
    record.total_fees = pnl.total_fees
    record.total_funding_cashflow = pnl.total_funding_cashflow
    record.net_pnl = pnl.net_pnl
    record.opened_at = _opened_at(draft)
    record.closed_at = _closed_at(draft, pnl)
    record.updated_at = occurred_at


async def _append_active_facts(
    session: AsyncSession,
    *,
    trade_id: UUID,
    draft: TradeDraft,
) -> None:
    session.add_all(
        TradeLegRecord(
            id=uuid4(),
            trade_id=trade_id,
            action=leg.action.value,
            executed_at=leg.executed_at,
            sequence=leg.sequence,
            price=leg.price,
            quantity=leg.quantity,
            fee=leg.fee,
            voided_at=None,
        )
        for leg in draft.legs
    )
    session.add_all(
        TradeCashflowRecord(
            id=uuid4(),
            trade_id=trade_id,
            occurred_at=cashflow.occurred_at,
            amount=cashflow.amount,
            reason=cashflow.reason,
            voided_at=None,
        )
        for cashflow in draft.cashflows
    )


async def _void_active_facts(
    session: AsyncSession,
    *,
    trade_id: UUID,
    occurred_at: datetime,
) -> None:
    active_facts = and_(
        TradeLegRecord.trade_id == trade_id,
        TradeLegRecord.voided_at.is_(None),
    )
    await session.execute(update(TradeLegRecord).where(active_facts).values(voided_at=occurred_at))
    active_cashflows = and_(
        TradeCashflowRecord.trade_id == trade_id,
        TradeCashflowRecord.voided_at.is_(None),
    )
    await session.execute(
        update(TradeCashflowRecord).where(active_cashflows).values(voided_at=occurred_at)
    )


async def _replace_tags(
    session: AsyncSession,
    *,
    trade_id: UUID,
    labels: tuple[str, ...],
) -> None:
    await session.execute(delete(TradeTagRecord).where(TradeTagRecord.trade_id == trade_id))
    for label in labels:
        result = await session.execute(select(TagRecord).where(TagRecord.value == label))
        tag = result.scalar_one_or_none()
        if tag is None:
            tag = TagRecord(id=uuid4(), value=label)
            session.add(tag)
            await session.flush()
        session.add(TradeTagRecord(trade_id=trade_id, tag_id=tag.id))


async def _get_active_trade_for_update(
    session: AsyncSession,
    trade_id: UUID,
) -> TradeRecord | None:
    result = await session.execute(
        select(TradeRecord)
        .where(TradeRecord.id == trade_id, TradeRecord.archived_at.is_(None))
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _get_trade(
    session: AsyncSession,
    condition: ColumnElement[bool],
) -> TradeRecord | None:
    result = await session.execute(select(TradeRecord).where(condition))
    return result.scalar_one_or_none()


async def _to_persisted_trade(
    session: AsyncSession,
    record: TradeRecord,
) -> PersistedTrade:
    legs = tuple(
        (
            await session.execute(
                select(TradeLegRecord)
                .where(
                    TradeLegRecord.trade_id == record.id,
                    TradeLegRecord.voided_at.is_(None),
                )
                .order_by(
                    TradeLegRecord.executed_at.asc(),
                    TradeLegRecord.sequence.asc(),
                    TradeLegRecord.id.asc(),
                )
            )
        ).scalars()
    )
    cashflows = tuple(
        (
            await session.execute(
                select(TradeCashflowRecord)
                .where(
                    TradeCashflowRecord.trade_id == record.id,
                    TradeCashflowRecord.voided_at.is_(None),
                )
                .order_by(TradeCashflowRecord.occurred_at.asc(), TradeCashflowRecord.id.asc())
            )
        ).scalars()
    )
    labels = tuple(
        (
            await session.execute(
                select(TagRecord.value)
                .join(TradeTagRecord, TradeTagRecord.tag_id == TagRecord.id)
                .where(TradeTagRecord.trade_id == record.id)
                .order_by(TagRecord.value.asc())
            )
        ).scalars()
    )
    draft = TradeDraft(
        symbol=ContractSymbol(record.symbol),
        direction=TradeDirection(record.direction),
        horizon=TradeHorizon(record.horizon),
        labels=labels,
        linked_report_id=record.analysis_report_id,
        leverage=record.leverage,
        legs=tuple(
            TradeLegDraft(
                id=leg.id,
                action=TradeLegAction(leg.action),
                executed_at=leg.executed_at,
                sequence=leg.sequence,
                price=leg.price,
                quantity=leg.quantity,
                fee=leg.fee,
            )
            for leg in legs
        ),
        cashflows=tuple(
            TradeCashflowDraft(
                id=cashflow.id,
                occurred_at=cashflow.occurred_at,
                amount=cashflow.amount,
                reason=cashflow.reason,
            )
            for cashflow in cashflows
        ),
        thesis=record.thesis,
        review=record.review,
    )
    return _persisted_from_values(
        trade_id=record.id,
        draft=draft,
        pnl=TradePnl(
            gross_realized_pnl=record.gross_realized_pnl,
            total_fees=record.total_fees,
            total_funding_cashflow=record.total_funding_cashflow,
            net_pnl=record.net_pnl,
            remaining_quantity=Decimal(0),
            is_fully_closed=record.status == TradeStatus.CLOSED.value,
            matches=(),
        ),
        status=TradeStatus(record.status),
        opened_at=record.opened_at,
        closed_at=record.closed_at,
        archived_at=record.archived_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _persisted_from_record_and_draft(
    record: TradeRecord,
    draft: TradeDraft,
) -> PersistedTrade:
    return _persisted_from_values(
        trade_id=record.id,
        draft=draft,
        pnl=TradePnl(
            gross_realized_pnl=record.gross_realized_pnl,
            total_fees=record.total_fees,
            total_funding_cashflow=record.total_funding_cashflow,
            net_pnl=record.net_pnl,
            remaining_quantity=Decimal(0),
            is_fully_closed=record.status == TradeStatus.CLOSED.value,
            matches=(),
        ),
        status=TradeStatus(record.status),
        opened_at=record.opened_at,
        closed_at=record.closed_at,
        archived_at=record.archived_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _persisted_from_values(
    *,
    trade_id: UUID,
    draft: TradeDraft,
    pnl: TradePnl,
    status: TradeStatus,
    opened_at: datetime,
    closed_at: datetime | None,
    archived_at: datetime | None,
    created_at: datetime,
    updated_at: datetime,
) -> PersistedTrade:
    return PersistedTrade(
        **draft.model_dump(),
        id=trade_id,
        status=status,
        gross_realized_pnl=pnl.gross_realized_pnl,
        total_fees=pnl.total_fees,
        total_funding_cashflow=pnl.total_funding_cashflow,
        net_pnl=pnl.net_pnl,
        opened_at=opened_at,
        closed_at=closed_at,
        archived_at=archived_at,
        created_at=created_at,
        updated_at=updated_at,
    )


def _draft_from_persisted(trade: PersistedTrade) -> TradeDraft:
    persisted_fields = {
        "id",
        "status",
        "gross_realized_pnl",
        "total_fees",
        "total_funding_cashflow",
        "net_pnl",
        "opened_at",
        "closed_at",
        "archived_at",
        "created_at",
        "updated_at",
    }
    return TradeDraft(**trade.model_dump(exclude=persisted_fields))


def _snapshot(trade: PersistedTrade) -> dict[str, object]:
    return cast(dict[str, object], trade.model_dump(mode="json"))


def _status_for(pnl: TradePnl) -> TradeStatus:
    return TradeStatus.CLOSED if pnl.is_fully_closed else TradeStatus.OPEN


def _opened_at(draft: TradeDraft) -> datetime:
    return min(leg.executed_at for leg in draft.legs)


def _closed_at(draft: TradeDraft, pnl: TradePnl) -> datetime | None:
    if not pnl.is_fully_closed:
        return None
    return max(leg.executed_at for leg in draft.legs if leg.action is TradeLegAction.CLOSE)


def _active_filters(
    filters: TradeFilters,
    *,
    required_status: TradeStatus | None = None,
) -> tuple[ColumnElement[bool], ...]:
    conditions: list[ColumnElement[bool]] = [TradeRecord.archived_at.is_(None)]
    status = required_status or filters.status
    if filters.symbol is not None:
        conditions.append(TradeRecord.symbol == filters.symbol.value)
    if filters.direction is not None:
        conditions.append(TradeRecord.direction == filters.direction.value)
    if filters.horizon is not None:
        conditions.append(TradeRecord.horizon == filters.horizon.value)
    if status is not None:
        conditions.append(TradeRecord.status == status.value)
    if filters.label is not None:
        tagged_trade_ids = (
            select(TradeTagRecord.trade_id)
            .join(
                TagRecord,
                TradeTagRecord.tag_id == TagRecord.id,
            )
            .where(TagRecord.value == filters.label)
        )
        conditions.append(TradeRecord.id.in_(tagged_trade_ids))
    if filters.from_at is not None:
        conditions.append(TradeRecord.opened_at >= filters.from_at)
    if filters.to_at is not None:
        conditions.append(TradeRecord.opened_at <= filters.to_at)
    return tuple(conditions)
