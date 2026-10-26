# 维护技术研究的持久队列、请求去重、阶段进度及限时所有权。
# 入队和领取通过队列单例行锁协调；更新要求 owner 和未过期租约匹配。
# 过期任务按已提交报告恢复终态，否则标记失败；可变运行状态与不可变报告分开。
"""Atomic durable queue with bounded global concurrency and expiring ownership."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.harness import HarnessAuditEventRecord
from app.infrastructure.persistence.models.technical_reports import TechnicalReportRecord
from app.infrastructure.persistence.models.technical_runs import (
    TechnicalQueueRecord,
    TechnicalRequestRecord,
    TechnicalRunRecord,
)
from app.market.symbols import ResearchSymbol
from app.reports.technical import require_utc
from app.reports.technical_runs import (
    PHASES,
    TechnicalRun,
    TechnicalRunError,
    TechnicalRunPhase,
    TechnicalRunStatus,
)


# 按 TechnicalRun 字段名单取 ORM 属性并重新校验，避免把内部映射对象直接交给调用方。
def public_run(record: TechnicalRunRecord) -> TechnicalRun:
    return TechnicalRun.model_validate(
        {key: getattr(record, key) for key in TechnicalRun.model_fields}
    )


# SqlAlchemyTechnicalRunRepository 将已校验领域契约连接到异步会话；数据库操作范围由各方法决定。
class SqlAlchemyTechnicalRunRepository:
    # 仅保存注入的会话工厂供后续操作使用；构造实例时不连接数据库或开启事务。
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    # 锁定 ID 为 1 的队列协调记录；该记录由 schema 准备，不在这里临时创建。
    async def _lock(self, session: AsyncSession) -> None:
        await session.scalar(
            select(TechnicalQueueRecord).where(TechnicalQueueRecord.id == 1).with_for_update()
        )

    # 锁定全局队列后按 requestId 去重或合并同币种活跃任务；容量达到二十时拒绝新任务。
    async def enqueue(
        self, symbol: ResearchSymbol, *, request_id: UUID, now: datetime
    ) -> TechnicalRun:
        now = require_utc(now)
        try:
            async with self._factory() as session, session.begin():
                await self._lock(session)
                old = await session.get(TechnicalRequestRecord, request_id)
                if old:
                    record = await session.get(TechnicalRunRecord, old.run_id)
                    assert record is not None
                    if record.symbol != symbol:
                        raise TechnicalRunError("request_conflict")
                    return public_run(record)
                record = await session.scalar(
                    select(TechnicalRunRecord).where(
                        TechnicalRunRecord.symbol == symbol,
                        TechnicalRunRecord.status.in_(("queued", "running")),
                    )
                )
                if record is None:
                    count = await session.scalar(
                        select(func.count())
                        .select_from(TechnicalRunRecord)
                        .where(TechnicalRunRecord.status.in_(("queued", "running")))
                    )
                    if count is not None and count >= 20:
                        raise TechnicalRunError("queue_full")
                    record = TechnicalRunRecord(
                        id=uuid4(),
                        analysis_id=uuid4(),
                        symbol=symbol,
                        status="queued",
                        phase="queued",
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(record)
                    await session.flush()
                session.add(TechnicalRequestRecord(request_id=request_id, run_id=record.id))
                return public_run(record)
        except SQLAlchemyError:
            raise TechnicalRunError("storage_unavailable") from None

    # 按传入标识/币种读取持久记录并映射领域契约；缺失返回 None，不隐式创建新数据。
    async def get(self, run_id: UUID) -> TechnicalRun | None:
        try:
            async with self._factory() as session:
                record = await session.get(TechnicalRunRecord, run_id)
                return public_run(record) if record else None
        except SQLAlchemyError:
            raise TechnicalRunError("storage_unavailable") from None

    # 队列锁内确认没有 running 任务，再按创建顺序领取 queued 记录并授予三十秒 owner 租约。
    async def claim(self, *, owner: UUID, now: datetime) -> TechnicalRun | None:
        now = require_utc(now)
        try:
            async with self._factory() as session, session.begin():
                await self._lock(session)
                running = await session.scalar(
                    select(TechnicalRunRecord.id)
                    .where(TechnicalRunRecord.status == "running")
                    .limit(1)
                )
                if running:
                    return None
                record = await session.scalar(
                    select(TechnicalRunRecord)
                    .where(TechnicalRunRecord.status == "queued")
                    .order_by(TechnicalRunRecord.created_at, TechnicalRunRecord.id)
                    .limit(1)
                    .with_for_update()
                )
                if record is None:
                    return None
                record.status, record.phase = "running", "collecting"
                record.owner, record.lease_expires_at = owner, now + timedelta(seconds=30)
                record.started_at, record.updated_at = now, now
                return public_run(record)
        except SQLAlchemyError:
            raise TechnicalRunError("storage_unavailable") from None

    # 锁定符合 run_id、owner、running 和未过期租约的记录；缺失意味着不能继续写入。
    async def _owned(
        self, session: AsyncSession, run_id: UUID, owner: UUID, now: datetime
    ) -> TechnicalRunRecord | None:
        return await session.scalar(
            select(TechnicalRunRecord)
            .where(
                TechnicalRunRecord.id == run_id,
                TechnicalRunRecord.owner == owner,
                TechnicalRunRecord.status == "running",
                TechnicalRunRecord.lease_expires_at > now,
            )
            .with_for_update()
        )

    # 通过统一所有权更新入口延长三十秒租约；失去所有权时返回 False。
    async def heartbeat(self, run_id: UUID, *, owner: UUID, now: datetime) -> bool:
        return await self._change(run_id, owner=owner, now=now)

    # 在有效租约下推进阶段；统一更新入口拒绝 queued/finished 和阶段回退。
    async def advance(
        self, run_id: UUID, *, owner: UUID, phase: TechnicalRunPhase, now: datetime
    ) -> bool:
        return await self._change(run_id, owner=owner, now=now, phase=phase)

    # 通过统一租约更新结束任务；若报告已经提交，失败请求会修正为报告对应终态。
    async def finish(
        self,
        run_id: UUID,
        *,
        owner: UUID,
        status: TechnicalRunStatus,
        report_id: UUID | None,
        error_code: str | None,
        now: datetime,
    ) -> bool:
        return await self._change(
            run_id, owner=owner, now=now, status=status, report_id=report_id, error_code=error_code
        )

    # 持有效租约才能续租、推进或结束；阶段不能回退，终态与关联报告必须一致。
    async def _change(
        self,
        run_id: UUID,
        *,
        owner: UUID,
        now: datetime,
        phase: TechnicalRunPhase | None = None,
        status: TechnicalRunStatus | None = None,
        report_id: UUID | None = None,
        error_code: str | None = None,
    ) -> bool:
        now = require_utc(now)
        try:
            async with self._factory() as session, session.begin():
                record = await self._owned(session, run_id, owner, now)
                if record is None:
                    return False
                if phase:
                    if phase in {"queued", "finished"} or PHASES.index(phase) < PHASES.index(
                        record.phase
                    ):
                        raise ValueError("phase_regression")
                    record.phase = phase
                elif status:
                    if status not in {"completed", "degraded", "failed"}:
                        raise ValueError("terminal_status")
                    # 模型/worker 报错可能发生在报告已经提交之后；优先查询落库报告，
                    # 防止失败状态掩盖成功历史。
                    if status == "failed":
                        committed = await session.scalar(
                            select(TechnicalReportRecord).where(
                                TechnicalReportRecord.analysis_id == record.analysis_id
                            )
                        )
                        if committed:
                            status = "completed" if committed.status == "completed" else "degraded"
                            report_id, error_code = committed.id, None
                    if report_id:
                        report = await session.get(TechnicalReportRecord, report_id)
                        if (
                            not report
                            or report.analysis_id != record.analysis_id
                            or report.status != status
                        ):
                            raise ValueError("report_association")
                    record.status, record.phase = status, "finished"
                    record.report_id, record.error_code, record.finished_at = (
                        report_id,
                        error_code,
                        now,
                    )
                    record.owner, record.lease_expires_at = None, None
                    # 仅最终状态仍为失败时补齐审计；已经关联到报告的完成/降级状态不追加失败终态。
                    if status == "failed":
                        await self._close_failed_audit(
                            session, record.analysis_id, now, error_code or "research_failed"
                        )
                else:
                    record.lease_expires_at = now + timedelta(seconds=30)
                record.updated_at = now
                public_run(record)
                return True
        except SQLAlchemyError:
            raise TechnicalRunError("storage_unavailable") from None

    # 锁定队列与过期运行；存在已保存报告时关联该终态，否则标记 interrupted 并补失败审计。
    async def recover_expired(self, *, now: datetime) -> int:
        now = require_utc(now)
        try:
            async with self._factory() as session, session.begin():
                await self._lock(session)
                records = (
                    await session.scalars(
                        select(TechnicalRunRecord)
                        .where(
                            TechnicalRunRecord.status == "running",
                            # 只恢复过期 running 任务，不自动将失败任务重新入队，
                            # 避免无用户请求的研究重跑。
                            TechnicalRunRecord.lease_expires_at <= now,
                        )
                        .with_for_update()
                    )
                ).all()
                for record in records:
                    report = await session.scalar(
                        select(TechnicalReportRecord).where(
                            TechnicalReportRecord.analysis_id == record.analysis_id
                        )
                    )
                    record.status = report.status if report else "failed"
                    record.report_id = report.id if report else None
                    record.error_code = None if report else "interrupted"
                    record.phase, record.finished_at, record.updated_at = "finished", now, now
                    record.owner, record.lease_expires_at = None, None
                    if report is None:
                        await self._close_failed_audit(
                            session, record.analysis_id, now, "interrupted"
                        )
                return len(records)
        except SQLAlchemyError:
            raise TechnicalRunError("storage_unavailable") from None

    # 仅当已有开始事件且没有终态时追加序号 3 的失败事件，冲突忽略避免重复终态。
    async def _close_failed_audit(
        self,
        session: AsyncSession,
        analysis_id: UUID,
        now: datetime,
        code: str,
    ) -> None:
        started = await session.get(HarnessAuditEventRecord, (analysis_id, 2))
        terminal = await session.get(HarnessAuditEventRecord, (analysis_id, 3))
        if started is not None and terminal is None:
            await session.execute(
                insert(HarnessAuditEventRecord)
                .values(
                    run_id=analysis_id,
                    sequence=3,
                    event_kind="workflow_failed",
                    occurred_at=now,
                    duration_ms=max(0, int((now - started.occurred_at).total_seconds() * 1000)),
                    error_code=code,
                    details={"error_type": "InterruptedRun"},
                )
                .on_conflict_do_nothing(index_elements=["run_id", "sequence"])
            )
