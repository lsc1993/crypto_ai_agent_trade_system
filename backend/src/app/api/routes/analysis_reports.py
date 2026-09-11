from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.market.contracts import ContractSymbol, UtcDateTime
from app.reports.contracts import (
    AgentAnalysis,
    AgentResearchNarrative,
    AnalysisReportStatus,
    AnalysisReportSummary,
    Catalyst,
    EvidenceBackedClaim,
    FrozenMarketMetrics,
    MarketOutlook,
    MarketOverview,
    PersistedAnalysisEvidence,
    PersistedAnalysisReport,
    PriceZone,
    ReportGeneratorKind,
    ReportPage,
    ResearchPerspective,
    RiskAndInvalidation,
    TrendDirection,
)
from app.reports.factors import FactorAnalysis
from app.reports.repository import AnalysisReportRepository
from app.reports.service import AnalysisReportService

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
    generator_kind: ReportGeneratorKind


class AnalysisEvidenceResponse(_ApiModel):
    id: UUID
    symbol: ContractSymbol
    source: str
    source_url: str
    observed_at: UtcDateTime
    summary: str


class PriceZoneResponse(_ApiModel):
    lower: str
    upper: str
    timeframe: str
    rationale: str


class CatalystResponse(_ApiModel):
    category: str
    direction: MarketOutlook
    claim: str
    evidence_ids: tuple[UUID, ...]
    timing: str


class RiskAndInvalidationResponse(_ApiModel):
    condition: str
    impact: str
    evidence_ids: tuple[UUID, ...]


class AgentDataQualityResponse(_ApiModel):
    freshness: str
    missing_inputs: tuple[str, ...]
    source_coverage: str


class ModelValidationFailureResponse(_ApiModel):
    attempt_count: int
    issue_count: int
    field_paths: tuple[str, ...]
    error_categories: tuple[str, ...]


class EvidenceBackedClaimResponse(_ApiModel):
    label: str
    detail: str
    evidence_ids: tuple[UUID, ...]


class MarketOverviewResponse(_ApiModel):
    headline: str
    summary: str
    evidence_ids: tuple[UUID, ...]


class ResearchPerspectiveResponse(_ApiModel):
    horizon: str
    outlook: MarketOutlook
    heading: str
    thesis: str
    drivers: tuple[EvidenceBackedClaimResponse, ...]
    invalidation: tuple[RiskAndInvalidationResponse, ...]


class AgentResearchNarrativeResponse(_ApiModel):
    market_overview: MarketOverviewResponse
    short_term: ResearchPerspectiveResponse
    long_term: ResearchPerspectiveResponse


class FrozenMarketMetricsResponse(_ApiModel):
    price: str
    change_24h: str
    volume_24h: str
    funding_rate: str
    open_interest: str
    fear_greed_value: int | None
    fear_greed_classification: str | None
    fear_greed_change_7d: int | None


class AgentAnalysisResponse(_ApiModel):
    horizon: str
    outlook: MarketOutlook
    confidence: str
    trend_alignment: dict[str, TrendDirection]
    support_zones: tuple[PriceZoneResponse, ...]
    resistance_zones: tuple[PriceZoneResponse, ...]
    catalysts: tuple[CatalystResponse, ...]
    risks_and_invalidation: tuple[RiskAndInvalidationResponse, ...]
    data_quality: AgentDataQualityResponse
    limitations: tuple[str, ...]
    narrative: AgentResearchNarrativeResponse | None
    market_metrics: FrozenMarketMetricsResponse | None
    factor_analysis: FactorAnalysis | None = None


class AnalysisReportDetailResponse(AnalysisReportSummaryResponse):
    facts: tuple[str, ...]
    inferences: tuple[str, ...]
    risks: tuple[str, ...]
    limitations: tuple[str, ...]
    generated_at: UtcDateTime
    evidence: tuple[AnalysisEvidenceResponse, ...]
    agent_analysis: AgentAnalysisResponse | None
    validation_failure: ModelValidationFailureResponse | None


class AnalysisReportPageResponse(_ApiModel):
    items: tuple[AnalysisReportSummaryResponse, ...]
    page: int
    page_size: int = Field(serialization_alias="page_size")
    total: int


class AnalysisRunEvent(_ApiModel):
    analysis_id: UUID
    symbol: ContractSymbol
    status: AnalysisReportStatus
    occurred_at: UtcDateTime
    message: str


def get_analysis_report_service(request: Request) -> AnalysisReportService:
    return cast(AnalysisReportService, request.app.state.analysis_report_service)


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
        AnalysisReportService,
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
        AnalysisReportService,
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
        generator_kind=report.generator_kind,
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
        agent_analysis=(
            None
            if report.agent_analysis is None
            else _to_agent_analysis_response(report.agent_analysis)
        ),
        validation_failure=(
            None
            if report.validation_failure is None
            else ModelValidationFailureResponse(
                attempt_count=report.validation_failure.attempt_count,
                issue_count=report.validation_failure.issue_count,
                field_paths=report.validation_failure.field_paths,
                error_categories=report.validation_failure.error_categories,
            )
        ),
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


def _to_agent_analysis_response(analysis: AgentAnalysis) -> AgentAnalysisResponse:
    return AgentAnalysisResponse(
        factor_analysis=analysis.factor_analysis,
        horizon=analysis.horizon,
        outlook=analysis.outlook,
        confidence=analysis.confidence,
        trend_alignment={
            timeframe.value: trend for timeframe, trend in analysis.trend_alignment.items()
        },
        support_zones=tuple(_to_price_zone_response(zone) for zone in analysis.support_zones),
        resistance_zones=tuple(_to_price_zone_response(zone) for zone in analysis.resistance_zones),
        catalysts=tuple(_to_catalyst_response(item) for item in analysis.catalysts),
        risks_and_invalidation=tuple(
            _to_risk_response(item) for item in analysis.risks_and_invalidation
        ),
        data_quality=AgentDataQualityResponse(
            freshness=analysis.data_quality.freshness.value,
            missing_inputs=analysis.data_quality.missing_inputs,
            source_coverage=analysis.data_quality.source_coverage,
        ),
        limitations=analysis.limitations,
        narrative=(
            None if analysis.narrative is None else _to_narrative_response(analysis.narrative)
        ),
        market_metrics=(
            None
            if analysis.market_metrics is None
            else _to_market_metrics_response(analysis.market_metrics)
        ),
    )


def _to_narrative_response(
    narrative: AgentResearchNarrative,
) -> AgentResearchNarrativeResponse:
    return AgentResearchNarrativeResponse(
        market_overview=_to_market_overview_response(narrative.market_overview),
        short_term=_to_perspective_response(narrative.short_term),
        long_term=_to_perspective_response(narrative.long_term),
    )


def _to_market_metrics_response(
    metrics: FrozenMarketMetrics,
) -> FrozenMarketMetricsResponse:
    return FrozenMarketMetricsResponse(
        price=str(metrics.price),
        change_24h=str(metrics.change_24h),
        volume_24h=str(metrics.volume_24h),
        funding_rate=str(metrics.funding_rate),
        open_interest=str(metrics.open_interest),
        fear_greed_value=metrics.fear_greed_value,
        fear_greed_classification=metrics.fear_greed_classification,
        fear_greed_change_7d=metrics.fear_greed_change_7d,
    )


def _to_market_overview_response(overview: MarketOverview) -> MarketOverviewResponse:
    return MarketOverviewResponse(
        headline=overview.headline,
        summary=overview.summary,
        evidence_ids=overview.evidence_ids,
    )


def _to_perspective_response(
    perspective: ResearchPerspective,
) -> ResearchPerspectiveResponse:
    return ResearchPerspectiveResponse(
        horizon=perspective.horizon,
        outlook=perspective.outlook,
        heading=perspective.heading,
        thesis=perspective.thesis,
        drivers=tuple(_to_claim_response(driver) for driver in perspective.drivers),
        invalidation=tuple(_to_risk_response(item) for item in perspective.invalidation),
    )


def _to_claim_response(claim: EvidenceBackedClaim) -> EvidenceBackedClaimResponse:
    return EvidenceBackedClaimResponse(
        label=claim.label,
        detail=claim.detail,
        evidence_ids=claim.evidence_ids,
    )


def _to_price_zone_response(zone: PriceZone) -> PriceZoneResponse:
    return PriceZoneResponse(
        lower=str(zone.lower),
        upper=str(zone.upper),
        timeframe=zone.timeframe.value,
        rationale=zone.rationale,
    )


def _to_catalyst_response(catalyst: Catalyst) -> CatalystResponse:
    return CatalystResponse(
        category=catalyst.category,
        direction=catalyst.direction,
        claim=catalyst.claim,
        evidence_ids=catalyst.evidence_ids,
        timing=catalyst.timing,
    )


def _to_risk_response(risk: RiskAndInvalidation) -> RiskAndInvalidationResponse:
    return RiskAndInvalidationResponse(
        condition=risk.condition,
        impact=risk.impact,
        evidence_ids=risk.evidence_ids,
    )
