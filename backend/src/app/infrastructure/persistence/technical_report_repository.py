from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.technical_reports import TechnicalReportRecord
from app.market.symbols import ResearchSymbol
from app.reports.contracts import ReportStorageUnavailableError, report_payload_sha256
from app.reports.technical import TechnicalReport
from app.reports.technical_repository import TechnicalReportPage


class SqlAlchemyTechnicalReportRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def persist(
        self, report: TechnicalReport, evidence: dict[str, JsonValue]
    ) -> TechnicalReport:
        # Return exactly the public precision stored for immutable history.
        report = TechnicalReport.model_validate_json(report.model_dump_json())
        try:
            async with self._factory() as session, session.begin():
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

    async def get(self, report_id: UUID) -> TechnicalReport | None:
        try:
            async with self._factory() as session:
                record = await session.get(TechnicalReportRecord, report_id)
                return None if record is None else TechnicalReport.model_validate(record.report)
        except SQLAlchemyError:
            raise ReportStorageUnavailableError("技术报告读取不可用") from None

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
            items=tuple(TechnicalReport.model_validate(row.report) for row in rows),
            page=page,
            page_size=page_size,
            total=total or 0,
        )
