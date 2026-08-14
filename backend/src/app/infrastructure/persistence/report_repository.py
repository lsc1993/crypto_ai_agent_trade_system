from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.agent_research import (
    AgentAnalysisRunRecord,
    AgentReportDetailRecord,
)
from app.infrastructure.persistence.models.reports import (
    AnalysisEvidenceRecord,
    AnalysisReportRecord,
)
from app.market.contracts import ContractSymbol
from app.reports.contracts import (
    AgentAnalysis,
    AgentReportCreation,
    AnalysisReportCreation,
    AnalysisReportStatus,
    AnalysisReportSummary,
    PersistedAnalysisEvidence,
    PersistedAnalysisReport,
    ReportGeneratorKind,
    ReportPage,
    ReportStorageUnavailableError,
)
from app.reports.repository import AgentAnalysisReportRepository


class SqlAlchemyAnalysisReportRepository(AgentAnalysisReportRepository):
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
                    await _add_report_records(session, creation)
        except SQLAlchemyError as error:
            raise ReportStorageUnavailableError("研究报告持久化不可用") from error

        persisted = await self.get_by_id(report.id)
        if persisted is None:
            raise ReportStorageUnavailableError("研究报告持久化不可用")
        return persisted

    async def persist_agent(
        self,
        creation: AgentReportCreation,
    ) -> PersistedAnalysisReport:
        report = creation.report
        analysis_payload = creation.agent_analysis.model_dump(mode="json")
        narrative_payload = (
            None
            if creation.agent_analysis.narrative is None
            else cast(dict[str, object], analysis_payload["narrative"])
        )
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await _add_report_records(session, creation)
                    session.add(
                        AgentAnalysisRunRecord(
                            id=uuid4(),
                            analysis_id=report.analysis_id,
                            symbol=report.symbol.value,
                            status=report.status.value,
                            started_at=creation.started_at,
                            completed_at=creation.completed_at,
                            generator_kind=creation.generator_kind.value,
                            error_code=creation.error_code,
                        )
                    )
                    session.add(
                        AgentReportDetailRecord(
                            analysis_report_id=report.id,
                            horizon=creation.agent_analysis.horizon,
                            outlook=creation.agent_analysis.outlook.value,
                            confidence=creation.agent_analysis.confidence,
                            trend_alignment=cast(
                                dict[str, object], analysis_payload["trend_alignment"]
                            ),
                            support_zones=cast(
                                list[dict[str, object]], analysis_payload["support_zones"]
                            ),
                            resistance_zones=cast(
                                list[dict[str, object]],
                                analysis_payload["resistance_zones"],
                            ),
                            catalysts=cast(
                                list[dict[str, object]], analysis_payload["catalysts"]
                            ),
                            risks_and_invalidation=cast(
                                list[dict[str, object]],
                                analysis_payload["risks_and_invalidation"],
                            ),
                            data_quality=cast(
                                dict[str, object], analysis_payload["data_quality"]
                            ),
                            limitations=cast(list[str], analysis_payload["limitations"]),
                            market_overview=(
                                None
                                if narrative_payload is None
                                else cast(
                                    dict[str, object],
                                    narrative_payload["market_overview"],
                                )
                            ),
                            short_term_view=(
                                None
                                if narrative_payload is None
                                else cast(
                                    dict[str, object],
                                    narrative_payload["short_term"],
                                )
                            ),
                            long_term_view=(
                                None
                                if narrative_payload is None
                                else cast(
                                    dict[str, object],
                                    narrative_payload["long_term"],
                                )
                            ),
                        )
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
            select(AnalysisReportRecord, AgentAnalysisRunRecord)
            .outerjoin(
                AgentAnalysisRunRecord,
                AgentAnalysisRunRecord.analysis_id == AnalysisReportRecord.analysis_id,
            )
            .where(*filters)
            .order_by(AnalysisReportRecord.created_at.desc(), AnalysisReportRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        count_statement = select(func.count()).select_from(AnalysisReportRecord).where(*filters)
        try:
            async with self._session_factory() as session:
                records = tuple((await session.execute(statement)).tuples())
                total = (await session.execute(count_statement)).scalar_one()
        except SQLAlchemyError as error:
            raise ReportStorageUnavailableError("研究报告读取不可用") from error
        return ReportPage(
            items=tuple(_to_summary(record, run) for record, run in records),
            page=page,
            page_size=page_size,
            total=total,
        )


async def _add_report_records(
    session: AsyncSession,
    creation: AnalysisReportCreation,
) -> None:
    report = creation.report
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
    # Both evidence and Agent-run rows reference this report. Flush the parent
    # before adding either child collection so database FK enforcement does not
    # depend on SQLAlchemy's unordered pending-object traversal.
    await session.flush()
    session.add_all(
        AnalysisEvidenceRecord(
            id=evidence.id,
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


async def _get_report_record(
    session: AsyncSession,
    condition: ColumnElement[bool],
) -> tuple[
    AnalysisReportRecord,
    AgentAnalysisRunRecord | None,
    AgentReportDetailRecord | None,
] | None:
    statement = (
        select(
            AnalysisReportRecord,
            AgentAnalysisRunRecord,
            AgentReportDetailRecord,
        )
        .outerjoin(
            AgentAnalysisRunRecord,
            AgentAnalysisRunRecord.analysis_id == AnalysisReportRecord.analysis_id,
        )
        .outerjoin(
            AgentReportDetailRecord,
            AgentReportDetailRecord.analysis_report_id == AnalysisReportRecord.id,
        )
        .where(condition)
    )
    result = await session.execute(statement)
    return result.tuples().one_or_none()


async def _to_persisted_report(
    session: AsyncSession,
    loaded: tuple[
        AnalysisReportRecord,
        AgentAnalysisRunRecord | None,
        AgentReportDetailRecord | None,
    ],
) -> PersistedAnalysisReport:
    record, run, detail = loaded
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
        **_to_summary(record, run).model_dump(),
        evidence=tuple(_to_evidence(evidence) for evidence in evidence_records),
        agent_analysis=None if detail is None else _to_agent_analysis(detail),
    )


def _to_summary(
    record: AnalysisReportRecord,
    run: AgentAnalysisRunRecord | None,
) -> AnalysisReportSummary:
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
        generator_kind=(
            ReportGeneratorKind.DETERMINISTIC
            if run is None
            else ReportGeneratorKind(run.generator_kind)
        ),
    )


def _to_agent_analysis(record: AgentReportDetailRecord) -> AgentAnalysis:
    narrative = (
        None
        if (
            record.market_overview is None
            or record.short_term_view is None
            or record.long_term_view is None
        )
        else {
            "market_overview": record.market_overview,
            "short_term": record.short_term_view,
            "long_term": record.long_term_view,
        }
    )
    return AgentAnalysis.model_validate(
        {
            "horizon": record.horizon,
            "outlook": record.outlook,
            "confidence": record.confidence,
            "trend_alignment": record.trend_alignment,
            "support_zones": record.support_zones,
            "resistance_zones": record.resistance_zones,
            "catalysts": record.catalysts,
            "risks_and_invalidation": record.risks_and_invalidation,
            "data_quality": record.data_quality,
            "limitations": record.limitations,
            "narrative": narrative,
        }
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
