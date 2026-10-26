# 保存综合报告、证据及可选 Agent 分析，并提供历史读取。
# 报告父记录先 flush，再在同一事务追加证据、运行诊断和分析详情。
# 提供追加保存和只读查询；历史缺失的 Agent 字段按现有兼容映射还原，不重跑模型。
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
from app.market.symbols import ResearchSymbol
from app.reports.contracts import (
    AgentAnalysis,
    AgentReportCreation,
    AnalysisReportCreation,
    AnalysisReportStatus,
    AnalysisReportSummary,
    ModelValidationFailure,
    PersistedAnalysisEvidence,
    PersistedAnalysisReport,
    ReportGeneratorKind,
    ReportPage,
    ReportStorageUnavailableError,
)
from app.reports.repository import AgentAnalysisReportRepository


# SqlAlchemyAnalysisReportRepository 将已校验领域契约连接到异步会话；数据库操作范围由各方法决定。
class SqlAlchemyAnalysisReportRepository(AgentAnalysisReportRepository):
    """保存并只读查询不可变的研究报告。"""

    # 仅保存注入的会话工厂供后续操作使用；构造实例时不连接数据库或开启事务。
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # 同事务追加报告和证据；提交后重新查询并返回持久化契约，缺失时视为存储不可用。
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

    # 在报告/证据事务内同时保存 Agent 运行诊断与详情，提交后重新读取最终领域报告。
    async def persist_agent(
        self,
        creation: AgentReportCreation,
    ) -> PersistedAnalysisReport:
        report = creation.report
        analysis_payload = creation.agent_analysis.model_dump(mode="json")
        # 叙事与指标分别允许缺失，保留旧报告兼容性；这里不使用新模型输出补写历史。
        narrative_payload = (
            None
            if creation.agent_analysis.narrative is None
            else cast(dict[str, object], analysis_payload["narrative"])
        )
        metrics_payload = (
            None
            if creation.agent_analysis.market_metrics is None
            else cast(dict[str, object], analysis_payload["market_metrics"])
        )
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await _add_report_records(session, creation)
                    session.add(
                        AgentAnalysisRunRecord(
                            id=uuid4(),
                            analysis_id=report.analysis_id,
                            symbol=report.symbol,
                            status=report.status.value,
                            started_at=creation.started_at,
                            completed_at=creation.completed_at,
                            generator_kind=creation.generator_kind.value,
                            error_code=creation.error_code,
                            model_validation_attempt_count=(
                                None
                                if creation.validation_failure is None
                                else creation.validation_failure.attempt_count
                            ),
                            model_validation_issue_count=(
                                None
                                if creation.validation_failure is None
                                else creation.validation_failure.issue_count
                            ),
                            model_validation_field_paths=(
                                None
                                if creation.validation_failure is None
                                else list(creation.validation_failure.field_paths)
                            ),
                            model_validation_error_categories=(
                                None
                                if creation.validation_failure is None
                                else list(creation.validation_failure.error_categories)
                            ),
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
                            catalysts=cast(list[dict[str, object]], analysis_payload["catalysts"]),
                            risks_and_invalidation=cast(
                                list[dict[str, object]],
                                analysis_payload["risks_and_invalidation"],
                            ),
                            data_quality=cast(dict[str, object], analysis_payload["data_quality"]),
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
                            market_metrics=metrics_payload,
                            factor_analysis=(
                                None
                                if creation.agent_analysis.factor_analysis is None
                                else cast(dict[str, object], analysis_payload["factor_analysis"])
                            ),
                        )
                    )
        except SQLAlchemyError as error:
            raise ReportStorageUnavailableError("研究报告持久化不可用") from error

        persisted = await self.get_by_id(report.id)
        if persisted is None:
            raise ReportStorageUnavailableError("研究报告持久化不可用")
        return persisted

    # 按传入标识/币种读取持久记录并映射领域契约；缺失返回 None，不隐式创建新数据。
    async def get_by_id(self, report_id: UUID) -> PersistedAnalysisReport | None:
        try:
            async with self._session_factory() as session:
                record = await _get_report_record(session, AnalysisReportRecord.id == report_id)
                return None if record is None else await _to_persisted_report(session, record)
        except SQLAlchemyError as error:
            raise ReportStorageUnavailableError("研究报告读取不可用") from error

    # 按传入标识/币种读取持久记录并映射领域契约；缺失返回 None，不隐式创建新数据。
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

    # 按明确筛选和排序读取已保存记录；分页项和总数分别查询，不额外声明跨查询快照隔离。
    async def list(
        self,
        *,
        page: int,
        page_size: int,
        symbol: ResearchSymbol | None,
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


# 追加报告父记录后 flush，再添加具有报告 ID 与载荷哈希的证据子记录。
async def _add_report_records(
    session: AsyncSession,
    creation: AnalysisReportCreation,
) -> None:
    report = creation.report
    session.add(
        AnalysisReportRecord(
            id=report.id,
            analysis_id=report.analysis_id,
            symbol=report.symbol,
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
            symbol=evidence.symbol,
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
) -> (
    tuple[
        AnalysisReportRecord,
        AgentAnalysisRunRecord | None,
        AgentReportDetailRecord | None,
    ]
    | None
):
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


# 按下面的显式字段映射还原 PersistedAnalysisReport，保留可选值与已有顺序；不重新执行业务计算。
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
        validation_failure=_validation_failure(run),
    )


# 按下面的显式字段映射还原 AnalysisReportSummary，保留可选值与已有顺序；不重新执行业务计算。
def _to_summary(
    record: AnalysisReportRecord,
    run: AgentAnalysisRunRecord | None,
) -> AnalysisReportSummary:
    return AnalysisReportSummary(
        id=record.id,
        analysis_id=record.analysis_id,
        symbol=record.symbol,
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


# 仅在 model_invalid_response 且诊断字段齐全时返回有限诊断；历史缺项返回 None。
def _validation_failure(run: AgentAnalysisRunRecord | None) -> ModelValidationFailure | None:
    if (
        run is None
        or run.error_code != "model_invalid_response"
        or run.model_validation_attempt_count is None
        or run.model_validation_issue_count is None
        or run.model_validation_field_paths is None
        or run.model_validation_error_categories is None
    ):
        return None
    return ModelValidationFailure(
        attempt_count=run.model_validation_attempt_count,
        issue_count=run.model_validation_issue_count,
        field_paths=tuple(run.model_validation_field_paths),
        error_categories=tuple(run.model_validation_error_categories),
    )


# 只有双周期叙事字段完整时组装 narrative，再通过 AgentAnalysis 验证历史 JSON。
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
            "market_metrics": record.market_metrics,
            "factor_analysis": record.factor_analysis,
        }
    )


# 按下面的显式字段映射还原 PersistedAnalysisEvidence，保留可选值与已有顺序；不重新执行业务计算。
def _to_evidence(record: AnalysisEvidenceRecord) -> PersistedAnalysisEvidence:
    return PersistedAnalysisEvidence(
        id=record.id,
        report_id=record.analysis_report_id,
        symbol=record.symbol,
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
    symbol: ResearchSymbol | None,
    status: AnalysisReportStatus | None,
) -> tuple[ColumnElement[bool], ...]:
    filters: list[ColumnElement[bool]] = []
    if symbol is not None:
        filters.append(AnalysisReportRecord.symbol == symbol)
    if status is not None:
        filters.append(AnalysisReportRecord.status == status.value)
    return tuple(filters)
