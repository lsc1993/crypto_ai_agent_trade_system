from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.reports import (
    AnalysisEvidenceRecord,
    AnalysisReportRecord,
)
from app.market.contracts import ContractSymbol
from app.reports.contracts import (
    AnalysisReportCreation,
    AnalysisReportStatus,
    AnalysisReportSummary,
    PersistedAnalysisEvidence,
    PersistedAnalysisReport,
    ReportPage,
    ReportStorageUnavailableError,
)
from app.reports.repository import AnalysisReportRepository


class SqlAlchemyAnalysisReportRepository(AnalysisReportRepository):
    """保存并只读查询不可变的研究报告。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def persist(
        self,
        creation: AnalysisReportCreation,
    ) -> PersistedAnalysisReport:
        report = creation.report
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add(
                        AnalysisReportRecord(
                            id=report.id,
                            analysis_id=report.analysis_id,
                            symbol=report.symbol.value,
                            status=report.status.value,
                            title=report.title,
                            summary=report.summary,
                            facts=list(report.facts),
                            inferences=list(report.inferences),
                            risks=list(report.risks),
                            limitations=list(report.limitations),
                            generated_at=report.generated_at,
                            data_cutoff_at=report.data_cutoff_at,
                        )
                    )
                    await session.flush()
                    session.add_all(
                        AnalysisEvidenceRecord(
                            id=uuid4(),
                            analysis_report_id=evidence.report_id,
                            symbol=evidence.symbol.value,
                            source=evidence.source,
                            source_url=evidence.source_url,
                            observed_at=evidence.observed_at,
                            fetched_at=evidence.fetched_at,
                            summary=evidence.summary,
                            payload=cast(dict[str, object], evidence.payload),
                            payload_sha256=evidence.payload_sha256,
                        )
                        for evidence in creation.evidences
                    )
        except SQLAlchemyError as error:
            raise ReportStorageUnavailableError("研究报告持久化不可用") from error

        persisted = await self.get_by_id(report.id)
        if persisted is None:
            raise ReportStorageUnavailableError("研究报告持久化不可用")
        return persisted

    async def get_by_id(self, report_id: UUID) -> PersistedAnalysisReport | None:
        try:
            async with self._session_factory() as session:
                record = await _get_report_record(session, AnalysisReportRecord.id == report_id)
                return None if record is None else await _to_persisted_report(session, record)
        except SQLAlchemyError as error:
            raise ReportStorageUnavailableError("研究报告读取不可用") from error

    async def get_by_analysis_id(
        self,
        analysis_id: UUID,
    ) -> PersistedAnalysisReport | None:
        try:
            async with self._session_factory() as session:
                record = await _get_report_record(
                    session,
                    AnalysisReportRecord.analysis_id == analysis_id,
                )
                return None if record is None else await _to_persisted_report(session, record)
        except SQLAlchemyError as error:
            raise ReportStorageUnavailableError("研究报告读取不可用") from error

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        symbol: ContractSymbol | None,
        status: AnalysisReportStatus | None,
    ) -> ReportPage:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("报告分页参数无效")
        filters = _filters(symbol=symbol, status=status)
        statement = (
            select(AnalysisReportRecord)
            .where(*filters)
            .order_by(AnalysisReportRecord.created_at.desc(), AnalysisReportRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        count_statement = select(func.count()).select_from(AnalysisReportRecord).where(*filters)
        try:
            async with self._session_factory() as session:
                records = tuple((await session.execute(statement)).scalars())
                total = (await session.execute(count_statement)).scalar_one()
        except SQLAlchemyError as error:
            raise ReportStorageUnavailableError("研究报告读取不可用") from error
        return ReportPage(
            items=tuple(_to_summary(record) for record in records),
            page=page,
            page_size=page_size,
            total=total,
        )


async def _get_report_record(
    session: AsyncSession,
    condition: ColumnElement[bool],
) -> AnalysisReportRecord | None:
    result = await session.execute(select(AnalysisReportRecord).where(condition))
    return result.scalar_one_or_none()


async def _to_persisted_report(
    session: AsyncSession,
    record: AnalysisReportRecord,
) -> PersistedAnalysisReport:
    evidence_records = tuple(
        (
            await session.execute(
                select(AnalysisEvidenceRecord)
                .where(AnalysisEvidenceRecord.analysis_report_id == record.id)
                .order_by(AnalysisEvidenceRecord.created_at.asc(), AnalysisEvidenceRecord.id.asc())
            )
        ).scalars()
    )
    return PersistedAnalysisReport(
        **_to_summary(record).model_dump(),
        evidence=tuple(_to_evidence(evidence) for evidence in evidence_records),
    )


def _to_summary(record: AnalysisReportRecord) -> AnalysisReportSummary:
    return AnalysisReportSummary(
        id=record.id,
        analysis_id=record.analysis_id,
        symbol=ContractSymbol(record.symbol),
        status=AnalysisReportStatus(record.status),
        title=record.title,
        summary=record.summary,
        facts=tuple(record.facts),
        inferences=tuple(record.inferences),
        risks=tuple(record.risks),
        limitations=tuple(record.limitations),
        generated_at=record.generated_at,
        data_cutoff_at=record.data_cutoff_at,
        created_at=record.created_at,
    )


def _to_evidence(record: AnalysisEvidenceRecord) -> PersistedAnalysisEvidence:
    return PersistedAnalysisEvidence(
        id=record.id,
        report_id=record.analysis_report_id,
        symbol=ContractSymbol(record.symbol),
        source=record.source,
        source_url=record.source_url,
        observed_at=record.observed_at,
        fetched_at=record.fetched_at,
        summary=record.summary,
        payload=cast(dict[str, JsonValue], record.payload),
        payload_sha256=record.payload_sha256,
        created_at=record.created_at,
    )


def _filters(
    *,
    symbol: ContractSymbol | None,
    status: AnalysisReportStatus | None,
) -> tuple[ColumnElement[bool], ...]:
    filters: list[ColumnElement[bool]] = []
    if symbol is not None:
        filters.append(AnalysisReportRecord.symbol == symbol.value)
    if status is not None:
        filters.append(AnalysisReportRecord.status == status.value)
    return tuple(filters)
