# 维护研究目录、操作审计和具有租约的初始同步队列。
# 登记/归档与队列事件在事务中保存，领取使用行锁，续租和完成核对 lease_token。
# 可研究状态依赖目录启用及成功/部分成功同步记录；动态目录不扩展交易枚举。
"""PostgreSQL implementation of the research-symbol directory.

The directory is intentionally separate from the trading ``ContractSymbol`` enum.
It only admits public USDⓈ-M perpetual contracts and owns the durable, leased
initial-sync queue used before research endpoints can read a new symbol.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import case, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.symbols import (
    ResearchSymbolEventRecord,
    ResearchSymbolRecord,
    ResearchSymbolSyncRunRecord,
)
from app.symbols.contracts import (
    Capability,
    CheckResult,
    ResearchSymbolEntry,
    SymbolError,
    SyncRun,
    SyncSource,
    SyncStatus,
)

_LEASE_DURATION = timedelta(seconds=30)
_ACTIVE_STATUSES = ("queued", "running")
_ADMITTED_STATUSES = ("ready", "partial")


# SqlAlchemySymbolRepository 将已校验领域契约连接到异步会话；数据库操作范围由各方法决定。
class SqlAlchemySymbolRepository:
    """Atomically manage admission rows, audit events, and leased sync jobs."""

    # 仅保存注入的会话工厂供后续操作使用；构造实例时不连接数据库或开启事务。
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # 按明确筛选和排序读取已保存记录；分页项和总数分别查询，不额外声明跨查询快照隔离。
    async def list(self, *, include_archived: bool = False) -> tuple[ResearchSymbolEntry, ...]:
        statement = select(ResearchSymbolRecord).order_by(ResearchSymbolRecord.symbol.asc())
        if not include_archived:
            statement = statement.where(ResearchSymbolRecord.enabled.is_(True))
        try:
            async with self._session_factory() as session:
                records = tuple((await session.scalars(statement)).all())
                entries: list[ResearchSymbolEntry] = []
                for record in records:
                    entries.append(await _to_entry(session, record))
                return tuple(entries)
        except SQLAlchemyError as exception:
            raise _storage_error(exception) from exception

    # 按传入标识/币种读取持久记录并映射领域契约；缺失返回 None，不隐式创建新数据。
    async def get(self, symbol: str) -> ResearchSymbolEntry | None:
        try:
            async with self._session_factory() as session:
                record = await session.get(ResearchSymbolRecord, symbol)
                return None if record is None else await _to_entry(session, record)
        except SQLAlchemyError as error:
            raise _storage_error(error) from error

    # 用通过检查的元数据 upsert 目录，同事务复用活跃任务或新建初始同步并追加操作事件。
    async def add(
        self,
        check: CheckResult,
        *,
        keywords: tuple[str, ...],
        now: datetime,
    ) -> ResearchSymbolEntry:
        if not check.supported or check.metadata is None:
            raise SymbolError("research_symbol_unsupported", "该币对暂不满足研究数据要求。", 422)
        metadata = check.metadata
        values: dict[str, object] = {
            "symbol": check.symbol,
            "base_asset": metadata.base_asset,
            "quote_asset": metadata.quote_asset,
            "margin_asset": metadata.margin_asset,
            "contract_type": metadata.contract_type,
            "enabled": True,
            "keywords": list(keywords),
            "capabilities": [item.model_dump(mode="json") for item in check.checks],
            "version": 1,
            "created_at": now,
            "archived_at": None,
        }
        statement = insert(ResearchSymbolRecord).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[ResearchSymbolRecord.symbol],
            set_={
                "base_asset": statement.excluded.base_asset,
                "quote_asset": statement.excluded.quote_asset,
                "margin_asset": statement.excluded.margin_asset,
                "contract_type": statement.excluded.contract_type,
                "enabled": True,
                "keywords": statement.excluded.keywords,
                "capabilities": statement.excluded.capabilities,
                "archived_at": None,
                "version": case(
                    (ResearchSymbolRecord.enabled.is_(False), ResearchSymbolRecord.version + 1),
                    else_=ResearchSymbolRecord.version,
                ),
            },
        ).returning(ResearchSymbolRecord)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = (await session.execute(statement)).scalar_one()
                    run = await _active_run(session, record.symbol, lock=True)
                    if run is None:
                        run = _new_queued_run(record, now)
                        session.add(run)
                        await session.flush()
                        _add_event(session, record.symbol, "added", now, run_id=run.id)
                        _add_event(session, record.symbol, "queued", now, run_id=run.id)
                    elif record.created_at == now:
                        _add_event(session, record.symbol, "added", now, run_id=run.id)
                    entry = await _to_entry(session, record)
                return entry
        except SQLAlchemyError as error:
            raise _storage_error(error) from error

    # 锁定目录行，禁用币种并增加版本，同时取消活跃同步任务并释放租约；历史记录保留。
    async def archive(self, symbol: str, *, now: datetime) -> ResearchSymbolEntry:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = await _locked_symbol(session, symbol)
                    if record is None:
                        raise SymbolError("research_symbol_not_found", "研究币对不存在。", 404)
                    if record.enabled:
                        record.enabled = False
                        record.archived_at = now
                        record.version += 1
                        active_runs = tuple(
                            (
                                await session.scalars(
                                    select(ResearchSymbolSyncRunRecord)
                                    .where(
                                        ResearchSymbolSyncRunRecord.symbol == symbol,
                                        ResearchSymbolSyncRunRecord.status.in_(_ACTIVE_STATUSES),
                                    )
                                    .with_for_update()
                                )
                            ).all()
                        )
                        for run in active_runs:
                            run.status = "cancelled"
                            run.stage = "cancelled"
                            run.completed_at = now
                            run.lease_token = None
                            run.lease_until = None
                            run.error = "research_symbol_archived"
                            _add_event(session, symbol, "cancelled", now, run_id=run.id)
                        _add_event(session, symbol, "archived", now)
                    entry = await _to_entry(session, record)
                return entry
        except SymbolError:
            raise
        except SQLAlchemyError as error:
            raise _storage_error(error) from error

    async def enqueue(self, symbol: str, *, now: datetime) -> SyncRun:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = await _locked_symbol(session, symbol)
                    if record is None:
                        raise SymbolError("research_symbol_not_found", "研究币对不存在。", 404)
                    if not record.enabled:
                        raise SymbolError("research_symbol_archived", "研究币对已删除。", 409)
                    run = await _active_run(session, symbol, lock=True)
                    if run is None:
                        run = _new_queued_run(record, now)
                        session.add(run)
                        await session.flush()
                        _add_event(session, symbol, "queued", now, run_id=run.id)
                    return _to_run(run)
        except SymbolError:
            raise
        except SQLAlchemyError as error:
            raise _storage_error(error) from error

    # 按传入标识/币种读取持久记录并映射领域契约；缺失返回 None，不隐式创建新数据。
    async def get_run(self, run_id: UUID) -> SyncRun | None:
        try:
            async with self._session_factory() as session:
                record = await session.get(ResearchSymbolSyncRunRecord, run_id)
                return None if record is None else _to_run(record)
        except SQLAlchemyError as error:
            raise _storage_error(error) from error

    # 用 skip_locked 领取启用币种的最早 queued 任务，分配随机租约令牌和三十秒有效期。
    async def claim(self, *, now: datetime) -> SyncRun | None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    statement = (
                        select(ResearchSymbolSyncRunRecord)
                        .join(
                            ResearchSymbolRecord,
                            ResearchSymbolRecord.symbol == ResearchSymbolSyncRunRecord.symbol,
                        )
                        .where(
                            ResearchSymbolSyncRunRecord.status == "queued",
                            ResearchSymbolRecord.enabled.is_(True),
                        )
                        .order_by(ResearchSymbolSyncRunRecord.created_at.asc())
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                    run = (await session.execute(statement)).scalar_one_or_none()
                    if run is None:
                        return None
                    run.status = "running"
                    run.stage = "capturing"
                    run.started_at = now
                    run.lease_token = uuid4()
                    run.lease_until = now + _LEASE_DURATION
                    _add_event(session, run.symbol, "claimed", now, run_id=run.id)
                    await session.flush()
                    return _to_run(run)
        except SQLAlchemyError as error:
            raise _storage_error(error) from error

    # 锁定同步任务并核对令牌；过期则标记失败，否则续租并追加审计。
    async def renew(self, run: SyncRun, *, now: datetime) -> bool:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = await session.get(
                        ResearchSymbolSyncRunRecord,
                        run.id,
                        with_for_update=True,
                    )
                    if not _owns_lease(record, run):
                        return False
                    assert record is not None
                    if record.lease_until is None or record.lease_until < now:
                        _expire_run(session, record, now)
                        return False
                    record.lease_until = now + _LEASE_DURATION
                    _add_event(session, record.symbol, "lease_renewed", now, run_id=record.id)
                    return True
        except SQLAlchemyError as error:
            raise _storage_error(error) from error

    # 仅允许 ready/partial/failed，所有权和有效期检查通过后保存来源、快照及同步终态。
    async def finish(
        self,
        run: SyncRun,
        *,
        status: str,
        sources: tuple[SyncSource, ...],
        snapshot_id: UUID | None,
        error: str | None,
        now: datetime,
    ) -> bool:
        if status not in {"ready", "partial", "failed"}:
            raise ValueError("同步完成状态无效")
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = await session.get(
                        ResearchSymbolSyncRunRecord,
                        run.id,
                        with_for_update=True,
                    )
                    if not _owns_lease(record, run):
                        return False
                    assert record is not None
                    if record.lease_until is None or record.lease_until < now:
                        _expire_run(session, record, now)
                        return False
                    record.status = status
                    record.stage = status
                    record.completed_at = now
                    record.lease_token = None
                    record.lease_until = None
                    record.snapshot_id = snapshot_id
                    record.sources = [item.model_dump(mode="json") for item in sources]
                    record.error = error
                    _add_event(session, record.symbol, status, now, run_id=record.id)
                    return True
        except SQLAlchemyError as exception:
            raise _storage_error(exception) from exception

    async def record_check(self, check: CheckResult, *, now: datetime) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    _add_event(
                        session,
                        check.symbol,
                        "checked",
                        now,
                        payload=check.model_dump(mode="json"),
                    )
        except SQLAlchemyError as error:
            raise _storage_error(error) from error


async def _locked_symbol(session: AsyncSession, symbol: str) -> ResearchSymbolRecord | None:
    return (
        await session.execute(
            select(ResearchSymbolRecord)
            .where(ResearchSymbolRecord.symbol == symbol)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def _active_run(
    session: AsyncSession,
    symbol: str,
    *,
    lock: bool,
) -> ResearchSymbolSyncRunRecord | None:
    statement = (
        select(ResearchSymbolSyncRunRecord)
        .where(
            ResearchSymbolSyncRunRecord.symbol == symbol,
            ResearchSymbolSyncRunRecord.status.in_(_ACTIVE_STATUSES),
        )
        .order_by(ResearchSymbolSyncRunRecord.created_at.desc())
    )
    if lock:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


def _new_queued_run(record: ResearchSymbolRecord, now: datetime) -> ResearchSymbolSyncRunRecord:
    return ResearchSymbolSyncRunRecord(
        id=uuid4(),
        symbol=record.symbol,
        version=record.version,
        status="queued",
        stage="queued",
        created_at=now,
        sources=[],
    )


def _add_event(
    session: AsyncSession,
    symbol: str,
    kind: str,
    now: datetime,
    *,
    run_id: UUID | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    session.add(
        ResearchSymbolEventRecord(
            id=uuid4(),
            operation_id=uuid4(),
            symbol=symbol,
            run_id=run_id,
            kind=kind,
            occurred_at=now,
            payload={} if payload is None else payload,
        )
    )


# 只检查运行状态与令牌身份；时间有效性由 renew/finish 随后单独校验。
def _owns_lease(record: ResearchSymbolSyncRunRecord | None, run: SyncRun) -> bool:
    return bool(
        record is not None
        and record.status == "running"
        and record.lease_token is not None
        and record.lease_token == run.lease_token
    )


# 把到期任务终结为失败并释放令牌，追加 lease_expired 事件；不会自动重排任务。
def _expire_run(
    session: AsyncSession,
    record: ResearchSymbolSyncRunRecord,
    now: datetime,
) -> None:
    record.status = "failed"
    record.stage = "failed"
    record.completed_at = now
    record.lease_token = None
    record.lease_until = None
    record.error = "sync_lease_expired"
    _add_event(session, record.symbol, "lease_expired", now, run_id=record.id)


# 按下面的显式字段映射还原 ResearchSymbolEntry，保留可选值与已有顺序；不重新执行业务计算。
# 读取最新同步展示信息，并独立检查任意 ready/partial 历史；can_research 还要求目录启用。
async def _to_entry(
    session: AsyncSession,
    record: ResearchSymbolRecord,
) -> ResearchSymbolEntry:
    last_run = (
        await session.execute(
            select(ResearchSymbolSyncRunRecord)
            .where(ResearchSymbolSyncRunRecord.symbol == record.symbol)
            .order_by(
                ResearchSymbolSyncRunRecord.version.desc(),
                ResearchSymbolSyncRunRecord.created_at.desc(),
                ResearchSymbolSyncRunRecord.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    admitted = (
        await session.execute(
            select(
                exists().where(
                    ResearchSymbolSyncRunRecord.symbol == record.symbol,
                    ResearchSymbolSyncRunRecord.status.in_(_ADMITTED_STATUSES),
                )
            )
        )
    ).scalar_one()
    return ResearchSymbolEntry(
        symbol=record.symbol,
        base_asset=record.base_asset,
        quote_asset=record.quote_asset,
        margin_asset=record.margin_asset,
        contract_type=record.contract_type,
        enabled=record.enabled,
        keywords=tuple(record.keywords),
        capabilities=tuple(Capability.model_validate(item) for item in record.capabilities),
        version=record.version,
        created_at=record.created_at,
        archived_at=record.archived_at,
        can_research=record.enabled and admitted,
        last_sync=None if last_run is None else _to_run(last_run),
    )


# 按下面的显式字段映射还原 SyncRun，保留可选值与已有顺序；不重新执行业务计算。
def _to_run(record: ResearchSymbolSyncRunRecord) -> SyncRun:
    return SyncRun(
        id=record.id,
        symbol=record.symbol,
        version=record.version,
        status=cast(SyncStatus, record.status),
        stage=record.stage,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        lease_token=record.lease_token,
        lease_until=record.lease_until,
        snapshot_id=record.snapshot_id,
        sources=tuple(SyncSource.model_validate(item) for item in record.sources),
        error=record.error,
    )


# 丢弃底层数据库异常正文，构造固定安全错误码和 503 消息供 API 映射。
def _storage_error(error: SQLAlchemyError) -> SymbolError:
    del error
    return SymbolError("research_symbol_storage_unavailable", "研究币对存储暂时不可用。", 503)
