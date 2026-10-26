# 保存本地模拟账户当前状态及追加式估值、订单、成交、账本和审计。
# 状态转换先核对账户和幂等审计，在账户/仓位行锁内更新状态并追加关联事实。
# 这是模拟持久层，不做最终风控计算；行锁保护此处写入流程，不声明上游计算无竞争。
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.execution.contracts import ExecutionConfig, OrderStatus, SimulatedFill, SimulatedOrder
from app.infrastructure.persistence.models.paper_trading import (
    PaperAccountRecord,
    PaperAccountValuationRecord,
    PaperAuditEventRecord,
    PaperFillRecord,
    PaperLedgerEntryRecord,
    PaperMarketSnapshotRecord,
    PaperOrderRecord,
    PaperPositionRecord,
)
from app.market.contracts import ContractSymbol
from app.paper_trading.contracts import (
    PaperAccount,
    PaperAccountCreate,
    PaperAccountDetail,
    PaperAccountFilters,
    PaperAccountNotFoundError,
    PaperAccountPage,
    PaperAccountStateError,
    PaperAccountStatus,
    PaperAccountSummary,
    PaperAccountValuation,
    PaperActionOutcome,
    PaperAuditEvent,
    PaperEventKind,
    PaperLedgerEntry,
    PaperMarketSnapshot,
    PaperPerformanceData,
    PaperPosition,
    PaperStorageUnavailableError,
    PaperTransition,
    PaperValuationKind,
)
from app.paper_trading.repository import PaperTradingRepository
from app.risk.contracts import DEFAULT_RISK_CONFIG, RiskConfig
from app.strategy.contracts import IntentAction


# SqlAlchemyPaperTradingRepository 将已校验领域契约连接到异步会话；数据库操作范围由各方法决定。
class SqlAlchemyPaperTradingRepository(PaperTradingRepository):
    """以事务、行锁和追加式审计保存模拟盘状态。"""

    # 仅保存注入的会话工厂供后续操作使用；构造实例时不连接数据库或开启事务。
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # 按固定 BTC 合约与默认模拟配置创建账户、空仓位和初始估值，活动账户冲突映射为状态错误。
    async def create_account(
        self,
        request: PaperAccountCreate,
        *,
        occurred_at: datetime,
    ) -> PaperAccountDetail:
        account_id = uuid4()
        account = PaperAccountRecord(
            id=account_id,
            status=PaperAccountStatus.ACTIVE.value,
            symbol=ContractSymbol.BTCUSDT.value,
            initial_cash=request.initial_cash,
            cash=request.initial_cash,
            equity=request.initial_cash,
            peak_equity=request.initial_cash,
            daily_start_equity=request.initial_cash,
            daily_realized_loss=Decimal("0"),
            daily_day=occurred_at.date(),
            cooldown_remaining=0,
            last_closed_candle_at=None,
            risk_config=_json_object(DEFAULT_RISK_CONFIG.model_dump(mode="json")),
            execution_config=_json_object(ExecutionConfig.model_validate({
                "fee_rate": "0.001",
                "slippage_rate": "0.0005",
                "fill_ratio": "1",
            }).model_dump(mode="json")),
            created_at=occurred_at,
            archived_at=None,
        )
        position = PaperPositionRecord(
            account_id=account_id,
            quantity=Decimal("0"),
            average_entry_price=None,
            remaining_entry_cost=Decimal("0"),
            opened_at=None,
            updated_at=occurred_at,
        )
        try:
            async with self._session_factory.begin() as session:
                session.add_all((account, position))
                await session.flush()
                session.add(
                    PaperAccountValuationRecord(
                        account_id=account_id,
                        sequence=0,
                        kind=PaperValuationKind.INITIAL.value,
                        snapshot_id=None,
                        valued_at=occurred_at,
                        cash=request.initial_cash,
                        position_quantity=Decimal("0"),
                        equity=request.initial_cash,
                        peak_equity=request.initial_cash,
                    )
                )
                await session.flush()
                return await _detail_from_session(session, account, position)
        except IntegrityError as error:
            if "uq_paper_accounts_one_active" in str(error):
                raise PaperAccountStateError("已有活动模拟账户") from error
            raise PaperStorageUnavailableError("模拟账户创建不可用") from error
        except SQLAlchemyError as error:
            raise PaperStorageUnavailableError("模拟账户创建不可用") from error

    # 按明确筛选和排序读取已保存记录；分页项和总数分别查询，不额外声明跨查询快照隔离。
    async def list(self, filters: PaperAccountFilters) -> PaperAccountPage:
        statement = (
            select(PaperAccountRecord)
            .order_by(PaperAccountRecord.created_at.desc(), PaperAccountRecord.id.desc())
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        )
        count_statement = select(func.count()).select_from(PaperAccountRecord)
        try:
            async with self._session_factory() as session:
                records = tuple((await session.execute(statement)).scalars())
                total = (await session.execute(count_statement)).scalar_one()
                items: list[PaperAccountSummary] = []
                for record in records:
                    position = await _position_for_account(session, record.id)
                    items.append(_to_summary(record, position))
                return PaperAccountPage(
                    items=tuple(items),
                    page=filters.page,
                    page_size=filters.page_size,
                    total=total,
                )
        except SQLAlchemyError as error:
            raise PaperStorageUnavailableError("模拟账户读取不可用") from error

    # 按传入标识/币种读取持久记录并映射领域契约；缺失返回 None，不隐式创建新数据。
    async def get_by_id(self, account_id: UUID) -> PaperAccountDetail | None:
        try:
            async with self._session_factory() as session:
                account = await _account_by_id(session, account_id)
                if account is None:
                    return None
                position = await _position_for_account(session, account_id)
                return await _detail_from_session(session, account, position)
        except SQLAlchemyError as error:
            raise PaperStorageUnavailableError("模拟账户读取不可用") from error

    # 按传入标识/币种读取持久记录并映射领域契约；缺失返回 None，不隐式创建新数据。
    async def get_performance_data(
        self,
        account_id: UUID,
    ) -> PaperPerformanceData | None:
        try:
            async with self._session_factory() as session:
                account = await _account_by_id(session, account_id)
                if account is None:
                    return None
                position = await _position_for_account(session, account_id)
                return await _performance_data_from_session(session, account, position)
        except SQLAlchemyError as error:
            raise PaperStorageUnavailableError("模拟账户绩效读取不可用") from error

    # 按账户和幂等键读取意图/无信号审计内的结果；未找到返回 None。
    async def find_outcome(
        self,
        account_id: UUID,
        idempotency_key: str,
    ) -> PaperActionOutcome | None:
        try:
            async with self._session_factory() as session:
                event = await _idempotent_event(session, account_id, idempotency_key)
                return None if event is None else _outcome_from_event(event)
        except SQLAlchemyError as error:
            raise PaperStorageUnavailableError("模拟账户幂等结果读取不可用") from error

    # 核对转换及幂等键，在事务和账户行锁内保存状态与关联事实；已处理键返回当前详情。
    async def apply_transition(
        self,
        account_id: UUID,
        idempotency_key: str,
        transition: PaperTransition,
        *,
        occurred_at: datetime,
    ) -> PaperAccountDetail:
        _validate_transition(account_id, idempotency_key, transition)
        try:
            async with self._session_factory.begin() as session:
                account, position = await _locked_account_and_position(session, account_id)
                # 账户锁内再次检查幂等审计，防止并发重放请求重复追加成交和现金流。
                existing = await _idempotent_event(session, account_id, idempotency_key)
                if existing is not None:
                    return await _detail_from_session(session, account, position)

                _apply_account(account, transition.account)
                _apply_position(position, transition.position)
                snapshot_id = uuid4()
                session.add(_snapshot_record(snapshot_id, account_id, transition.snapshot))
                valuation_sequence = await _next_valuation_sequence(session, account_id)
                session.add(
                    _valuation_record(
                        account_id,
                        valuation_sequence,
                        kind=PaperValuationKind.MARKET_VALUATION,
                        snapshot_id=snapshot_id,
                        valued_at=transition.snapshot.observed_at,
                        account=transition.account,
                        position=transition.position,
                    )
                )
                # 先添加订单并 flush，再写带父订单外键的成交，避免父子记录提交顺序不确定。
                order_ids = _order_records(
                    account_id,
                    snapshot_id,
                    transition,
                )
                session.add_all(order_ids.values())
                await session.flush()
                session.add_all(_fill_records(account_id, transition, order_ids))
                # 序号分配建立在同账户写入持锁的前提上；max+1 自身不是独立并发保护。
                ledger_start = await _next_ledger_sequence(session, account_id)
                session.add_all(
                    _ledger_records(account_id, transition.ledger_entries, ledger_start)
                )
                event_start = await _next_event_sequence(session, account_id)
                session.add_all(
                    _event_records(
                        account_id,
                        transition.events,
                        event_start,
                        idempotency_key=idempotency_key,
                        outcome=transition.outcome,
                    )
                )
                await session.flush()
                return await _detail_from_session(session, account, position)
        except (PaperAccountNotFoundError, PaperAccountStateError):
            raise
        except SQLAlchemyError as error:
            raise PaperStorageUnavailableError("模拟账户状态保存不可用") from error

    # 只追加带错误码的行情失败审计并返回账户详情；不制造模拟订单或成交。
    async def record_market_failure(
        self,
        account_id: UUID,
        idempotency_key: str,
        *,
        code: str,
        occurred_at: datetime,
    ) -> PaperAccountDetail:
        try:
            async with self._session_factory.begin() as session:
                account, position = await _locked_account_and_position(session, account_id)
                sequence = await _next_event_sequence(session, account_id)
                session.add(
                    PaperAuditEventRecord(
                        account_id=account_id,
                        sequence=sequence,
                        kind=PaperEventKind.MARKET_UNAVAILABLE.value,
                        occurred_at=occurred_at,
                        idempotency_key=idempotency_key,
                        payload={"code": code},
                    )
                )
                await session.flush()
                return await _detail_from_session(session, account, position)
        except (PaperAccountNotFoundError, PaperAccountStateError):
            raise
        except SQLAlchemyError as error:
            raise PaperStorageUnavailableError("模拟盘行情失败审计不可用") from error

    # 账户与仓位加锁后确认数量为零，再修改归档状态并追加事件；不会强制平仓。
    async def archive(
        self,
        account_id: UUID,
        *,
        occurred_at: datetime,
    ) -> PaperAccountDetail:
        try:
            async with self._session_factory.begin() as session:
                account, position = await _locked_account_and_position(session, account_id)
                if position.quantity != Decimal("0"):
                    raise PaperAccountStateError("存在持仓时不能归档模拟账户")
                account.status = PaperAccountStatus.ARCHIVED.value
                account.archived_at = occurred_at
                sequence = await _next_event_sequence(session, account_id)
                session.add(
                    PaperAuditEventRecord(
                        account_id=account_id,
                        sequence=sequence,
                        kind=PaperEventKind.ARCHIVED.value,
                        occurred_at=occurred_at,
                        idempotency_key=None,
                        payload={"status": PaperAccountStatus.ARCHIVED.value},
                    )
                )
                await session.flush()
                return await _detail_from_session(session, account, position)
        except (PaperAccountNotFoundError, PaperAccountStateError):
            raise
        except SQLAlchemyError as error:
            raise PaperStorageUnavailableError("模拟账户归档不可用") from error


async def _account_by_id(
    session: AsyncSession,
    account_id: UUID,
) -> PaperAccountRecord | None:
    result = await session.execute(
        select(PaperAccountRecord).where(PaperAccountRecord.id == account_id)
    )
    return result.scalar_one_or_none()


# 依次锁定账户与仓位，拒绝不存在、非活动或缺少仓位状态的账户。
async def _locked_account_and_position(
    session: AsyncSession,
    account_id: UUID,
) -> tuple[PaperAccountRecord, PaperPositionRecord]:
    result = await session.execute(
        select(PaperAccountRecord)
        .where(PaperAccountRecord.id == account_id)
        .with_for_update()
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise PaperAccountNotFoundError("未找到模拟账户")
    if account.status != PaperAccountStatus.ACTIVE.value:
        raise PaperAccountStateError("归档模拟账户不可操作")
    position_result = await session.execute(
        select(PaperPositionRecord)
        .where(PaperPositionRecord.account_id == account_id)
        .with_for_update()
    )
    position = position_result.scalar_one_or_none()
    if position is None:
        raise PaperStorageUnavailableError("模拟账户仓位状态缺失")
    return account, position


async def _position_for_account(
    session: AsyncSession,
    account_id: UUID,
) -> PaperPositionRecord:
    result = await session.execute(
        select(PaperPositionRecord).where(PaperPositionRecord.account_id == account_id)
    )
    position = result.scalar_one_or_none()
    if position is None:
        raise PaperStorageUnavailableError("模拟账户仓位状态缺失")
    return position


async def _idempotent_event(
    session: AsyncSession,
    account_id: UUID,
    idempotency_key: str,
) -> PaperAuditEventRecord | None:
    result = await session.execute(
        select(PaperAuditEventRecord)
        .where(PaperAuditEventRecord.account_id == account_id)
        .where(
            PaperAuditEventRecord.kind.in_(
                (PaperEventKind.INTENT.value, PaperEventKind.NO_SIGNAL.value)
            )
        )
        .where(PaperAuditEventRecord.idempotency_key == idempotency_key)
    )
    return result.scalar_one_or_none()


# 读取当前账户最大序号并加一；写入调用方必须已持有账户行锁，空历史从零开始。
async def _next_ledger_sequence(
    session: AsyncSession,
    account_id: UUID,
) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(PaperLedgerEntryRecord.sequence), -1)).where(
            PaperLedgerEntryRecord.account_id == account_id
        )
    )
    return int(result.scalar_one()) + 1


# 读取当前账户最大序号并加一；写入调用方必须已持有账户行锁，空历史从零开始。
async def _next_valuation_sequence(
    session: AsyncSession,
    account_id: UUID,
) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(PaperAccountValuationRecord.sequence), -1)).where(
            PaperAccountValuationRecord.account_id == account_id
        )
    )
    return int(result.scalar_one()) + 1


# 读取当前账户最大序号并加一；写入调用方必须已持有账户行锁，空历史从零开始。
async def _next_event_sequence(session: AsyncSession, account_id: UUID) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(PaperAuditEventRecord.sequence), -1)).where(
            PaperAuditEventRecord.account_id == account_id
        )
    )
    return int(result.scalar_one()) + 1


async def _detail_from_session(
    session: AsyncSession,
    account: PaperAccountRecord,
    position: PaperPositionRecord,
) -> PaperAccountDetail:
    snapshot_result = await session.execute(
        select(PaperMarketSnapshotRecord)
        .where(PaperMarketSnapshotRecord.account_id == account.id)
        .order_by(
            PaperMarketSnapshotRecord.observed_at.desc(),
            PaperMarketSnapshotRecord.id.desc(),
        )
        .limit(1)
    )
    latest_snapshot = snapshot_result.scalar_one_or_none()
    order_records = tuple(
        (
            await session.execute(
                select(PaperOrderRecord)
                .where(PaperOrderRecord.account_id == account.id)
                .order_by(PaperOrderRecord.submitted_at.asc(), PaperOrderRecord.id.asc())
            )
        ).scalars()
    )
    fill_rows = tuple(
        (
            await session.execute(
                select(PaperFillRecord, PaperOrderRecord)
                .join(PaperOrderRecord, PaperFillRecord.order_id == PaperOrderRecord.id)
                .where(PaperFillRecord.account_id == account.id)
                .order_by(PaperFillRecord.filled_at.asc(), PaperFillRecord.id.asc())
            )
        ).tuples()
    )
    ledger_records = tuple(
        (
            await session.execute(
                select(PaperLedgerEntryRecord)
                .where(PaperLedgerEntryRecord.account_id == account.id)
                .order_by(PaperLedgerEntryRecord.sequence.asc())
            )
        ).scalars()
    )
    event_records = tuple(
        (
            await session.execute(
                select(PaperAuditEventRecord)
                .where(PaperAuditEventRecord.account_id == account.id)
                .order_by(PaperAuditEventRecord.sequence.asc())
            )
        ).scalars()
    )
    return PaperAccountDetail(
        account=_to_account(account),
        position=_to_position(position),
        latest_snapshot=(
            None if latest_snapshot is None else _to_snapshot(latest_snapshot)
        ),
        orders=tuple(_to_order(order) for order in order_records),
        fills=tuple(_to_fill(fill, order) for fill, order in fill_rows),
        ledger_entries=tuple(_to_ledger_entry(entry) for entry in ledger_records),
        events=tuple(_to_event(event) for event in event_records),
        action_outcome=_latest_action_outcome(event_records),
    )


async def _performance_data_from_session(
    session: AsyncSession,
    account: PaperAccountRecord,
    position: PaperPositionRecord,
) -> PaperPerformanceData:
    valuation_records = tuple(
        (
            await session.execute(
                select(PaperAccountValuationRecord)
                .where(PaperAccountValuationRecord.account_id == account.id)
                .order_by(PaperAccountValuationRecord.sequence.asc())
            )
        ).scalars()
    )
    fill_rows = tuple(
        (
            await session.execute(
                select(PaperFillRecord, PaperOrderRecord)
                .join(PaperOrderRecord, PaperFillRecord.order_id == PaperOrderRecord.id)
                .where(PaperFillRecord.account_id == account.id)
                .order_by(PaperFillRecord.filled_at.asc(), PaperFillRecord.id.asc())
            )
        ).tuples()
    )
    ledger_records = tuple(
        (
            await session.execute(
                select(PaperLedgerEntryRecord)
                .where(PaperLedgerEntryRecord.account_id == account.id)
                .order_by(PaperLedgerEntryRecord.sequence.asc())
            )
        ).scalars()
    )
    event_records = tuple(
        (
            await session.execute(
                select(PaperAuditEventRecord)
                .where(PaperAuditEventRecord.account_id == account.id)
                .order_by(PaperAuditEventRecord.sequence.asc())
            )
        ).scalars()
    )
    return PaperPerformanceData(
        account=_to_account(account),
        position=_to_position(position),
        valuations=tuple(_to_valuation(record) for record in valuation_records),
        fills=tuple(_to_fill(fill, order) for fill, order in fill_rows),
        ledger_entries=tuple(_to_ledger_entry(entry) for entry in ledger_records),
        events=tuple(_to_event(event) for event in event_records),
    )



# 验证转换中的账户归属、非空幂等键及对应意图事件，防止写入不可关联状态。
def _validate_transition(
    account_id: UUID,
    idempotency_key: str,
    transition: PaperTransition,
) -> None:
    if transition.account.id != account_id or transition.position.account_id != account_id:
        raise ValueError("模拟盘状态转换必须属于当前账户")
    if not idempotency_key.strip():
        raise ValueError("模拟盘状态转换幂等键不能为空")
    if not any(
        event.kind in {PaperEventKind.INTENT, PaperEventKind.NO_SIGNAL}
        and event.idempotency_key == idempotency_key
        for event in transition.events
    ):
        raise ValueError("模拟盘状态转换必须包含匹配的意图审计事件")


def _apply_account(record: PaperAccountRecord, account: PaperAccount) -> None:
    record.status = account.status.value
    record.cash = account.cash
    record.equity = account.equity
    record.peak_equity = account.peak_equity
    record.daily_start_equity = account.daily_start_equity
    record.daily_realized_loss = account.daily_realized_loss
    record.daily_day = account.daily_day
    record.cooldown_remaining = account.cooldown_remaining
    record.last_closed_candle_at = account.last_closed_candle_at
    record.risk_config = _json_object(account.risk_config.model_dump(mode="json"))
    record.execution_config = _json_object(account.execution_config.model_dump(mode="json"))
    record.archived_at = account.archived_at


def _apply_position(record: PaperPositionRecord, position: PaperPosition) -> None:
    record.quantity = position.quantity
    record.average_entry_price = position.average_entry_price
    record.remaining_entry_cost = position.remaining_entry_cost
    record.opened_at = position.opened_at
    record.updated_at = position.updated_at


def _snapshot_record(
    snapshot_id: UUID,
    account_id: UUID,
    snapshot: PaperMarketSnapshot,
) -> PaperMarketSnapshotRecord:
    return PaperMarketSnapshotRecord(
        id=snapshot_id,
        account_id=account_id,
        price=snapshot.price,
        source=snapshot.source,
        observed_at=snapshot.observed_at,
        fetched_at=snapshot.fetched_at,
        payload_hash=snapshot.payload_hash,
    )


def _valuation_record(
    account_id: UUID,
    sequence: int,
    *,
    kind: PaperValuationKind,
    snapshot_id: UUID | None,
    valued_at: datetime,
    account: PaperAccount,
    position: PaperPosition,
) -> PaperAccountValuationRecord:
    return PaperAccountValuationRecord(
        account_id=account_id,
        sequence=sequence,
        kind=kind.value,
        snapshot_id=snapshot_id,
        valued_at=valued_at,
        cash=account.cash,
        position_quantity=position.quantity,
        equity=account.equity,
        peak_equity=account.peak_equity,
    )


# 为转换内的模拟订单分配 UUID，按幂等键建立映射；重复键或缺少来源直接拒绝。
def _order_records(
    account_id: UUID,
    snapshot_id: UUID,
    transition: PaperTransition,
) -> dict[str, PaperOrderRecord]:
    records: dict[str, PaperOrderRecord] = {}
    for order in transition.orders:
        if order.idempotency_key in records:
            raise ValueError("模拟盘状态转换包含重复订单幂等键")
        if transition.outcome.source is None:
            raise ValueError("模拟盘订单缺少意图来源")
        records[order.idempotency_key] = PaperOrderRecord(
            id=uuid4(),
            account_id=account_id,
            snapshot_id=snapshot_id,
            action=order.action.value,
            source=transition.outcome.source.value,
            idempotency_key=order.idempotency_key,
            submitted_at=order.submitted_at,
            requested_quantity=order.requested_quantity,
            status=order.status.value,
        )
    return records


# 按订单幂等键找到模拟成交的父订单 UUID；没有匹配订单即拒绝孤立成交。
def _fill_records(
    account_id: UUID,
    transition: PaperTransition,
    order_records: dict[str, PaperOrderRecord],
) -> tuple[PaperFillRecord, ...]:
    records: list[PaperFillRecord] = []
    for fill in transition.fills:
        order = order_records.get(fill.order_idempotency_key)
        if order is None:
            raise ValueError("模拟盘成交缺少对应订单")
        records.append(
            PaperFillRecord(
                id=uuid4(),
                order_id=order.id,
                account_id=account_id,
                quantity=fill.quantity,
                price=fill.price,
                fee=fill.fee,
                filled_at=fill.filled_at,
                status=fill.status.value,
            )
        )
    return tuple(records)


def _ledger_records(
    account_id: UUID,
    entries: tuple[PaperLedgerEntry, ...],
    start: int,
) -> tuple[PaperLedgerEntryRecord, ...]:
    return tuple(
        PaperLedgerEntryRecord(
            account_id=account_id,
            sequence=start + offset,
            occurred_at=entry.occurred_at,
            kind=entry.kind.value,
            cash_delta=entry.cash_delta,
            position_delta=entry.position_delta,
            realized_pnl=entry.realized_pnl,
            fee=entry.fee,
            cash_after=entry.cash_after,
            quantity_after=entry.quantity_after,
        )
        for offset, entry in enumerate(entries)
    )


def _event_records(
    account_id: UUID,
    events: tuple[PaperAuditEvent, ...],
    start: int,
    *,
    idempotency_key: str,
    outcome: PaperActionOutcome,
) -> tuple[PaperAuditEventRecord, ...]:
    records: list[PaperAuditEventRecord] = []
    for offset, event in enumerate(events):
        payload = _json_object(event.payload)
        if (
            event.kind in {PaperEventKind.INTENT, PaperEventKind.NO_SIGNAL}
            and event.idempotency_key == idempotency_key
        ):
            payload["outcome"] = outcome.model_dump(mode="json")
        records.append(
            PaperAuditEventRecord(
                account_id=account_id,
                sequence=start + offset,
                kind=event.kind.value,
                occurred_at=event.occurred_at,
                idempotency_key=event.idempotency_key,
                payload=payload,
            )
        )
    return tuple(records)


# 按下面的显式字段映射还原 PaperAccount，保留可选值与已有顺序；不重新执行业务计算。
def _to_account(record: PaperAccountRecord) -> PaperAccount:
    return PaperAccount(
        id=record.id,
        status=PaperAccountStatus(record.status),
        symbol=ContractSymbol(record.symbol),
        initial_cash=record.initial_cash,
        cash=record.cash,
        equity=record.equity,
        peak_equity=record.peak_equity,
        daily_start_equity=record.daily_start_equity,
        daily_realized_loss=record.daily_realized_loss,
        daily_day=record.daily_day,
        cooldown_remaining=record.cooldown_remaining,
        last_closed_candle_at=record.last_closed_candle_at,
        risk_config=RiskConfig.model_validate(record.risk_config),
        execution_config=ExecutionConfig.model_validate(record.execution_config),
        created_at=record.created_at,
        archived_at=record.archived_at,
    )


# 按下面的显式字段映射还原 PaperPosition，保留可选值与已有顺序；不重新执行业务计算。
def _to_position(record: PaperPositionRecord) -> PaperPosition:
    return PaperPosition(
        account_id=record.account_id,
        quantity=record.quantity,
        average_entry_price=record.average_entry_price,
        remaining_entry_cost=record.remaining_entry_cost,
        opened_at=record.opened_at,
        updated_at=record.updated_at,
    )


# 按下面的显式字段映射还原 PaperAccountSummary，保留可选值与已有顺序；不重新执行业务计算。
def _to_summary(
    account: PaperAccountRecord,
    position: PaperPositionRecord,
) -> PaperAccountSummary:
    return PaperAccountSummary(
        id=account.id,
        status=PaperAccountStatus(account.status),
        symbol=ContractSymbol(account.symbol),
        cash=account.cash,
        equity=account.equity,
        position_quantity=position.quantity,
        created_at=account.created_at,
        archived_at=account.archived_at,
    )


# 按下面的显式字段映射还原 PaperMarketSnapshot，保留可选值与已有顺序；不重新执行业务计算。
def _to_snapshot(record: PaperMarketSnapshotRecord) -> PaperMarketSnapshot:
    return PaperMarketSnapshot(
        symbol=ContractSymbol.BTCUSDT,
        price=record.price,
        source=record.source,
        observed_at=record.observed_at,
        fetched_at=record.fetched_at,
        payload_hash=record.payload_hash,
    )


# 按下面的显式字段映射还原 PaperAccountValuation，保留可选值与已有顺序；不重新执行业务计算。
def _to_valuation(record: PaperAccountValuationRecord) -> PaperAccountValuation:
    return PaperAccountValuation(
        account_id=record.account_id,
        sequence=record.sequence,
        kind=PaperValuationKind(record.kind),
        snapshot_id=record.snapshot_id,
        valued_at=record.valued_at,
        cash=record.cash,
        position_quantity=record.position_quantity,
        equity=record.equity,
        peak_equity=record.peak_equity,
    )


# 按下面的显式字段映射还原 SimulatedOrder，保留可选值与已有顺序；不重新执行业务计算。
def _to_order(record: PaperOrderRecord) -> SimulatedOrder:
    return SimulatedOrder(
        run_id=record.account_id,
        symbol=ContractSymbol.BTCUSDT,
        action=IntentAction(record.action),
        idempotency_key=record.idempotency_key,
        submitted_at=record.submitted_at,
        requested_quantity=record.requested_quantity,
        status=OrderStatus(record.status),
    )


# 按下面的显式字段映射还原 SimulatedFill，保留可选值与已有顺序；不重新执行业务计算。
def _to_fill(record: PaperFillRecord, order: PaperOrderRecord) -> SimulatedFill:
    return SimulatedFill(
        run_id=record.account_id,
        symbol=ContractSymbol.BTCUSDT,
        action=IntentAction(order.action),
        order_idempotency_key=order.idempotency_key,
        submitted_at=order.submitted_at,
        filled_at=record.filled_at,
        requested_quantity=order.requested_quantity,
        quantity=record.quantity,
        price=record.price,
        fee=record.fee,
        status=OrderStatus(record.status),
    )


# 按下面的显式字段映射还原 PaperLedgerEntry，保留可选值与已有顺序；不重新执行业务计算。
def _to_ledger_entry(record: PaperLedgerEntryRecord) -> PaperLedgerEntry:
    return PaperLedgerEntry(
        occurred_at=record.occurred_at,
        kind=IntentAction(record.kind),
        cash_delta=record.cash_delta,
        position_delta=record.position_delta,
        realized_pnl=record.realized_pnl,
        fee=record.fee,
        cash_after=record.cash_after,
        quantity_after=record.quantity_after,
    )


# 按下面的显式字段映射还原 PaperAuditEvent，保留可选值与已有顺序；不重新执行业务计算。
def _to_event(record: PaperAuditEventRecord) -> PaperAuditEvent:
    return PaperAuditEvent(
        sequence=record.sequence,
        kind=PaperEventKind(record.kind),
        occurred_at=record.occurred_at,
        idempotency_key=record.idempotency_key,
        payload=cast(dict[str, JsonValue], record.payload),
    )


def _latest_action_outcome(
    events: tuple[PaperAuditEventRecord, ...],
) -> PaperActionOutcome | None:
    for event in reversed(events):
        if event.kind not in {
            PaperEventKind.INTENT.value,
            PaperEventKind.NO_SIGNAL.value,
        }:
            continue
        outcome = event.payload.get("outcome")
        if isinstance(outcome, dict):
            return PaperActionOutcome.model_validate(outcome)
    return None


def _outcome_from_event(event: PaperAuditEventRecord) -> PaperActionOutcome | None:
    outcome = event.payload.get("outcome")
    if not isinstance(outcome, dict):
        return None
    return PaperActionOutcome.model_validate(outcome)


def _json_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("模拟盘审计载荷必须是对象")
    return cast(dict[str, object], value)
