from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.market.contracts import ContractSymbol, UtcDateTime
from app.reports.contracts import (
    AnalysisReportStatus,
    AnalysisReportSummary,
    PersistedAnalysisEvidence,
    PersistedAnalysisReport,
    ReportPage,
)
from app.reports.repository import AnalysisReportRepository
from app.reports.service import DeterministicResearchReportService

router = APIRouter(prefix="/analysis-runs", tags=["analysis-reports"])


class _ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda value: "".join(
            [
                value.split("_")[0],
                *(part.capitalize() for part in value.split("_")[1:]),
            ]
        ),
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class StartAnalysisRequest(_ApiModel):
    symbol: ContractSymbol


class AnalysisRunCreatedResponse(_ApiModel):
    analysis_id: UUID
    report_id: UUID


class AnalysisReportSummaryResponse(_ApiModel):
    id: UUID
    analysis_id: UUID
    symbol: ContractSymbol
    status: AnalysisReportStatus
    title: str
    summary: str
    created_at: UtcDateTime
    data_cutoff_at: UtcDateTime | None


class AnalysisEvidenceResponse(_ApiModel):
    id: UUID
    symbol: ContractSymbol
    source: str
    source_url: str
    observed_at: UtcDateTime
    summary: str


class AnalysisReportDetailResponse(AnalysisReportSummaryResponse):
    facts: tuple[str, ...]
    inferences: tuple[str, ...]
    risks: tuple[str, ...]
    limitations: tuple[str, ...]
    generated_at: UtcDateTime
    evidence: tuple[AnalysisEvidenceResponse, ...]


class AnalysisReportPageResponse(_ApiModel):
    items: tuple[AnalysisReportSummaryResponse, ...]
    page: int
    page_size: int
    total: int


class AnalysisRunEvent(_ApiModel):
    analysis_id: UUID
    symbol: ContractSymbol
    status: AnalysisReportStatus
    occurred_at: UtcDateTime
    message: str


def get_analysis_report_service(request: Request) -> DeterministicResearchReportService:
    return cast(DeterministicResearchReportService, request.app.state.analysis_report_service)


def get_analysis_report_repository(request: Request) -> AnalysisReportRepository:
    return cast(AnalysisReportRepository, request.app.state.analysis_report_repository)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=AnalysisRunCreatedResponse,
)
async def create_analysis_run(
    request: StartAnalysisRequest,
    service: Annotated[
        DeterministicResearchReportService,
        Depends(get_analysis_report_service),
    ],
) -> AnalysisRunCreatedResponse:
    report = await service.generate(request.symbol)
    return AnalysisRunCreatedResponse(
        analysis_id=report.analysis_id,
        report_id=report.id,
    )


@router.get("", response_model=AnalysisReportPageResponse)
async def list_analysis_runs(
    repository: Annotated[
        AnalysisReportRepository,
        Depends(get_analysis_report_repository),
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    symbol: ContractSymbol | None = None,
    status_filter: Annotated[AnalysisReportStatus | None, Query(alias="status")] = None,
) -> AnalysisReportPageResponse:
    reports = await repository.list(
        page=page,
        page_size=page_size,
        symbol=symbol,
        status=status_filter,
    )
    return _to_page_response(reports)


@router.get("/{report_id}", response_model=AnalysisReportDetailResponse)
async def get_analysis_run(
    report_id: UUID,
    repository: Annotated[
        AnalysisReportRepository,
        Depends(get_analysis_report_repository),
    ],
) -> AnalysisReportDetailResponse:
    report = await _require_report(repository.get_by_id(report_id))
    return _to_detail_response(report)


@router.post(
    "/{report_id}/retry",
    status_code=status.HTTP_201_CREATED,
    response_model=AnalysisRunCreatedResponse,
)
async def retry_analysis_run(
    report_id: UUID,
    repository: Annotated[
        AnalysisReportRepository,
        Depends(get_analysis_report_repository),
    ],
    service: Annotated[
        DeterministicResearchReportService,
        Depends(get_analysis_report_service),
    ],
) -> AnalysisRunCreatedResponse:
    original = await _require_report(repository.get_by_id(report_id))
    report = await service.generate(original.symbol)
    return AnalysisRunCreatedResponse(
        analysis_id=report.analysis_id,
        report_id=report.id,
    )


@router.get("/{analysis_id}/events")
async def replay_analysis_run_event(
    analysis_id: UUID,
    repository: Annotated[
        AnalysisReportRepository,
        Depends(get_analysis_report_repository),
    ],
) -> StreamingResponse:
    report = await _require_report(repository.get_by_analysis_id(analysis_id))
    event = AnalysisRunEvent(
        analysis_id=report.analysis_id,
        symbol=report.symbol,
        status=report.status,
        occurred_at=report.generated_at,
        message=_terminal_message(report.status),
    )
    return StreamingResponse(
        _terminal_event(event),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


async def _require_report(
    pending_report: Awaitable[PersistedAnalysisReport | None],
) -> PersistedAnalysisReport:
    report = await pending_report
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="研究报告不存在")
    return report


async def _terminal_event(event: AnalysisRunEvent) -> AsyncIterator[str]:
    yield f"data: {event.model_dump_json(by_alias=True)}\n\n"


def _terminal_message(status_value: AnalysisReportStatus) -> str:
    if status_value is AnalysisReportStatus.COMPLETED:
        return "持久化市场研究报告已完成。"
    return "持久化市场研究报告已降级完成。"


def _to_page_response(reports: ReportPage) -> AnalysisReportPageResponse:
    return AnalysisReportPageResponse(
        items=tuple(_to_summary_response(report) for report in reports.items),
        page=reports.page,
        page_size=reports.page_size,
        total=reports.total,
    )


def _to_summary_response(
    report: AnalysisReportSummary,
) -> AnalysisReportSummaryResponse:
    return AnalysisReportSummaryResponse(
        id=report.id,
        analysis_id=report.analysis_id,
        symbol=report.symbol,
        status=report.status,
        title=report.title,
        summary=report.summary,
        created_at=report.created_at,
        data_cutoff_at=report.data_cutoff_at,
    )


def _to_detail_response(
    report: PersistedAnalysisReport,
) -> AnalysisReportDetailResponse:
    return AnalysisReportDetailResponse(
        **_to_summary_response(report).model_dump(),
        facts=report.facts,
        inferences=report.inferences,
        risks=report.risks,
        limitations=report.limitations,
        generated_at=report.generated_at,
        evidence=tuple(_to_evidence_response(evidence) for evidence in report.evidence),
    )


def _to_evidence_response(
    evidence: PersistedAnalysisEvidence,
) -> AnalysisEvidenceResponse:
    return AnalysisEvidenceResponse(
        id=evidence.id,
        symbol=evidence.symbol,
        source=evidence.source,
        source_url=evidence.source_url,
        observed_at=evidence.observed_at,
        summary=evidence.summary,
    )
