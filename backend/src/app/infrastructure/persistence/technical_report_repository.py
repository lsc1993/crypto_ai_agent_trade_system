# 保存版本化技术报告及冻结证据，并分页读取历史。
# 保存前按公开 JSON 精度解析文档；有租约时在事务中锁定并校验任务所有权。
# 报告只追加，终态审计由数据库触发器关联；读取解析既有版本，不重新计算历史计划。
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.technical_reports import TechnicalReportRecord
from app.infrastructure.persistence.models.technical_runs import TechnicalRunRecord
from app.market.symbols import ResearchSymbol
from app.reports.contracts import ReportStorageUnavailableError, report_payload_sha256
from app.reports.technical_plan import TechnicalReportDocument, parse_technical_report
from app.reports.technical_repository import TechnicalReportPage
from app.reports.technical_runs import TechnicalRunLease


# SqlAlchemyTechnicalReportRepository 将已校验领域契约连接到异步会话；数据库操作范围由各方法决定。
class SqlAlchemyTechnicalReportRepository:
    # 仅保存注入的会话工厂供后续操作使用；构造实例时不连接数据库或开启事务。
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    # 按公开精度重新解析报告；可选租约在数据库时间下验证并锁定，事务追加报告和证据哈希。
    async def persist(
        self,
        report: TechnicalReportDocument,
        evidence: dict[str, JsonValue],
        *,
        lease: TechnicalRunLease | None = None,
    ) -> TechnicalReportDocument:
        # Return exactly the public precision stored for immutable history.
        report = parse_technical_report(report.model_dump(mode="json"))
        try:
            async with self._factory() as session, session.begin():
                if lease is not None:
                    run = await session.scalar(
                        select(TechnicalRunRecord)
                        .where(
                            TechnicalRunRecord.id == lease.run_id,
                            TechnicalRunRecord.owner == lease.owner,
                            TechnicalRunRecord.status == "running",
                            # 提交时采用数据库当前时间核验租约，避免 worker
                            # 本地时钟误判所有权仍有效。
                            TechnicalRunRecord.lease_expires_at > func.clock_timestamp(),
                        )
                        .with_for_update()
                    )
                    if run is None or run.analysis_id != report.analysis_id:
                        raise ReportStorageUnavailableError("技术研究任务租约已失效")
                # 租约锁与报告插入处于同一事务；数据库触发器终态审计依赖对应迁移已应用。
                session.add(
                    TechnicalReportRecord(
                        id=report.id,
                        analysis_id=report.analysis_id,
                        symbol=report.symbol,
                        status=report.status,
                        created_at=report.created_at,
                        report=report.model_dump(mode="json"),
                        frozen_evidence=cast(dict[str, object], evidence),
                        evidence_sha256=report_payload_sha256(evidence),
                    )
                )
                # The DB trigger appends the Harness terminal event in this transaction.
        except SQLAlchemyError:
            raise ReportStorageUnavailableError("技术报告保存不可用") from None
        return report

    # 按传入标识/币种读取持久记录并映射领域契约；缺失返回 None，不隐式创建新数据。
    async def get(self, report_id: UUID) -> TechnicalReportDocument | None:
        try:
            async with self._factory() as session:
                record = await session.get(TechnicalReportRecord, report_id)
                return None if record is None else parse_technical_report(record.report)
        except SQLAlchemyError:
            raise ReportStorageUnavailableError("技术报告读取不可用") from None

    # 按传入标识/币种读取持久记录并映射领域契约；缺失返回 None，不隐式创建新数据。
    async def get_by_analysis_id(self, analysis_id: UUID) -> TechnicalReportDocument | None:
        try:
            async with self._factory() as session:
                record = await session.scalar(
                    select(TechnicalReportRecord).where(
                        TechnicalReportRecord.analysis_id == analysis_id
                    )
                )
                return None if record is None else parse_technical_report(record.report)
        except SQLAlchemyError:
            raise ReportStorageUnavailableError("技术报告读取不可用") from None

    # 按明确筛选和排序读取已保存记录；分页项和总数分别查询，不额外声明跨查询快照隔离。
    async def list(
        self,
        *,
        symbol: ResearchSymbol | None,
        page: int,
        page_size: int,
    ) -> TechnicalReportPage:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("技术报告分页无效")
        filters = () if symbol is None else (TechnicalReportRecord.symbol == symbol,)
        try:
            async with self._factory() as session:
                rows = (
                    await session.scalars(
                        select(TechnicalReportRecord)
                        .where(*filters)
                        .order_by(
                            TechnicalReportRecord.created_at.desc(), TechnicalReportRecord.id.desc()
                        )
                        .offset((page - 1) * page_size)
                        .limit(page_size)
                    )
                ).all()
                total = await session.scalar(
                    select(func.count()).select_from(TechnicalReportRecord).where(*filters)
                )
        except SQLAlchemyError:
            raise ReportStorageUnavailableError("技术报告读取不可用") from None
        return TechnicalReportPage(
            items=tuple(parse_technical_report(row.report) for row in rows),
            page=page,
            page_size=page_size,
            total=total or 0,
        )
