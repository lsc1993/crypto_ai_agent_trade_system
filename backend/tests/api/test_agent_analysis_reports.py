from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import JsonValue

from app.harness.audit import (
    HarnessAuditEvent,
    HarnessAuditRun,
    HarnessAuditTrace,
    HarnessEvaluation,
)
from app.harness.market_research import (
    HarnessedMarketResearchService,
    MarketResearchWorkflow,
)
from app.harness.policy import MARKET_RESEARCH_POLICY
from app.harness.runtime import HarnessRuntime
from app.main import create_app
from app.market.contracts import Candle, ContractSymbol, FreshnessStatus, MarketTimeframe
from app.market.research import PersistedMarketReader, PersistedMarketSnapshot
from app.reports.contracts import (
    AgentAnalysis,
    AgentDataQuality,
    AnalysisReportDraft,
    AnalysisReportStatus,
    Catalyst,
    MarketOutlook,
    PersistedAnalysisEvidence,
    PersistedAnalysisReport,
    PriceZone,
    ReportGeneratorKind,
    RiskAndInvalidation,
    TrendDirection,
    report_payload_sha256,
)

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)
REPORT_ID = UUID("00000000-0000-0000-0000-000000000801")
ANALYSIS_ID = UUID("00000000-0000-0000-0000-000000000802")
EVIDENCE_ID = UUID("00000000-0000-0000-0000-000000000803")
RETRY_ANALYSIS_ID = UUID("00000000-0000-0000-0000-000000000804")


def _empty_audit_events() -> list[HarnessAuditEvent]:
    return []


@dataclass
class RecordingAuditRepository:
    events: list[HarnessAuditEvent] = field(default_factory=_empty_audit_events)

    async def create_requested_run(
        self,
        run: HarnessAuditRun,
        event: HarnessAuditEvent,
    ) -> None:
        del run
        self.events.append(event)

    async def append_policy_evaluation(
        self,
        evaluation: HarnessEvaluation,
        event: HarnessAuditEvent,
    ) -> None:
        del evaluation
        self.events.append(event)

    async def append_event(self, event: HarnessAuditEvent) -> None:
        self.events.append(event)

    async def get_trace(self, run_id: UUID) -> HarnessAuditTrace | None:
        del run_id
        return None


class FakeAgentService:
    def __init__(self, report: PersistedAnalysisReport) -> None:
        self.report = report
        self.calls: list[tuple[ContractSymbol, UUID | None]] = []
        self.persisted_reports: list[PersistedAnalysisReport] = []

    async def generate(
        self,
        symbol: ContractSymbol,
        *,
        analysis_id: UUID | None = None,
    ) -> PersistedAnalysisReport:
        self.calls.append((symbol, analysis_id))
        persisted = self.report.model_copy(
            update={
                "analysis_id": self.report.analysis_id if analysis_id is None else analysis_id
            }
        )
        self.persisted_reports.append(persisted)
        return persisted


class ReportReader:
    def __init__(self, report: PersistedAnalysisReport) -> None:
        self.report = report

    async def get_by_id(self, report_id: UUID) -> PersistedAnalysisReport | None:
        return self.report if report_id == self.report.id else None

    async def get_by_analysis_id(
        self,
        analysis_id: UUID,
    ) -> PersistedAnalysisReport | None:
        return self.report if analysis_id == self.report.analysis_id else None

    async def list(self, **_: object) -> object:
        raise AssertionError("not exercised")


class UnusedMarketReader(PersistedMarketReader):
    async def load_snapshot(self, snapshot_id: UUID) -> PersistedMarketSnapshot | None:
        del snapshot_id
        raise AssertionError("agent service is injected")

    async def load_latest_snapshot(
        self,
        symbol: ContractSymbol,
    ) -> PersistedMarketSnapshot | None:
        del symbol
        raise AssertionError("agent service is injected")

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        del symbol, timeframe, limit
        raise AssertionError("agent service is injected")


@pytest.mark.asyncio
async def test_analysis_post_retry_and_detail_preserve_the_http_contract() -> None:
    report = _report()
    delegate = FakeAgentService(report)
    audit = RecordingAuditRepository()
    run_ids = iter((ANALYSIS_ID, RETRY_ANALYSIS_ID))
    service = HarnessedMarketResearchService(
        HarnessRuntime[PersistedAnalysisReport](
            policies=(MARKET_RESEARCH_POLICY,),
            workflows=(MarketResearchWorkflow(delegate),),
            audit_repository=audit,
        ),
        clock=lambda: NOW,
        new_run_id=run_ids.__next__,
    )
    app = create_app(
        market_research_reader=UnusedMarketReader(),
        analysis_report_repository=ReportReader(report),  # type: ignore[arg-type]
        agent_research_service=service,
    )

    created = await _request(app, "POST", "/api/v1/analysis-runs", {"symbol": "BTCUSDT"})
    retried = await _request(
        app,
        "POST",
        f"/api/v1/analysis-runs/{REPORT_ID}/retry",
    )
    detail = await _request(app, "GET", f"/api/v1/analysis-runs/{REPORT_ID}")

    assert created.status_code == 201
    assert created.json() == {"analysisId": str(ANALYSIS_ID), "reportId": str(REPORT_ID)}
    assert retried.status_code == 201
    assert retried.json() == {
        "analysisId": str(RETRY_ANALYSIS_ID),
        "reportId": str(REPORT_ID),
    }
    assert [event.sequence for event in audit.events] == [0, 1, 2, 0, 1, 2]
    assert delegate.calls == [
        (ContractSymbol.BTCUSDT, ANALYSIS_ID),
        (ContractSymbol.BTCUSDT, RETRY_ANALYSIS_ID),
    ]
    assert delegate.persisted_reports[-1].analysis_id == RETRY_ANALYSIS_ID
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["generatorKind"] == "langgraph_deepseek"
    assert payload["agentAnalysis"]["horizon"] == "1_to_3_days"
    assert payload["agentAnalysis"]["narrative"] is None
    assert payload["agentAnalysis"]["supportZones"][0]["lower"] == "67000.10"
    assert payload["agentAnalysis"]["catalysts"][0]["evidenceIds"] == [str(EVIDENCE_ID)]
    assert "api_key" not in detail.text.lower()
    assert "authorization" not in detail.text.lower()


@pytest.mark.asyncio
async def test_manual_report_returns_dual_horizon_chinese_narrative_and_partial_coverage() -> None:
    report = _dual_horizon_report()
    service = FakeAgentService(report)
    app = create_app(
        market_research_reader=UnusedMarketReader(),
        analysis_report_repository=ReportReader(report),  # type: ignore[arg-type]
        agent_research_service=service,
    )

    created = await _request(app, "POST", "/api/v1/analysis-runs", {"symbol": "BTCUSDT"})
    detail = await _request(
        app,
        "GET",
        f"/api/v1/analysis-runs/{created.json()['reportId']}",
    )

    assert created.status_code == 201
    assert service.calls == [(ContractSymbol.BTCUSDT, None)]
    assert detail.status_code == 200
    analysis = detail.json()["agentAnalysis"]
    assert analysis["horizon"] == "dual_horizon"
    assert analysis["dataQuality"]["sourceCoverage"] == "partial"
    assert analysis["marketMetrics"] == {
        "price": "68000.12",
        "change24h": "-2.50",
        "volume24h": "123456789.01",
        "fundingRate": "0.0001",
        "openInterest": "456789012.34",
        "fearGreedValue": 23,
        "fearGreedClassification": "Extreme Fear",
        "fearGreedChange7d": -11,
    }
    assert "payload" not in str(analysis).lower()
    narrative = analysis["narrative"]
    assert narrative["marketOverview"]["headline"] == "流动性回暖但趋势尚未确认"
    assert narrative["shortTerm"]["horizon"] == "short_term"
    assert narrative["longTerm"]["drivers"][0]["evidenceIds"] == [str(EVIDENCE_ID)]


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    payload: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, json=payload)


def _report() -> PersistedAnalysisReport:
    report = AnalysisReportDraft(
        id=REPORT_ID,
        analysis_id=ANALYSIS_ID,
        symbol=ContractSymbol.BTCUSDT,
        status=AnalysisReportStatus.COMPLETED,
        title="BTCUSDT 市场研究",
        summary="冻结的公开证据已形成只读市场研究。",
        facts=("市场证据已冻结。",),
        inferences=("未来一至三天保持中性。",),
        risks=("市场可能快速变化。",),
        limitations=("不构成交易建议。",),
        generated_at=NOW,
        data_cutoff_at=NOW,
    )
    evidence_payload = cast(
        dict[str, JsonValue],
        {"news": {"sourceTier": "professional_media"}},
    )
    evidence = PersistedAnalysisEvidence(
        id=EVIDENCE_ID,
        report_id=REPORT_ID,
        symbol=ContractSymbol.BTCUSDT,
        source="coindesk",
        source_url="https://www.coindesk.com/markets/item-1",
        observed_at=NOW,
        fetched_at=NOW,
        summary="受治理英文新闻快照。",
        payload=evidence_payload,
        payload_sha256=report_payload_sha256(evidence_payload),
        created_at=NOW,
    )
    analysis = AgentAnalysis(
        horizon="1_to_3_days",
        outlook=MarketOutlook.NEUTRAL,
        confidence="medium",
        trend_alignment={MarketTimeframe.H1: TrendDirection.NEUTRAL},
        support_zones=(
            PriceZone(
                lower=Decimal("67000.10"),
                upper=Decimal("67100.20"),
                timeframe=MarketTimeframe.H1,
                rationale="Closed-candle support zone.",
            ),
        ),
        resistance_zones=(),
        catalysts=(
            Catalyst(
                category="market",
                direction=MarketOutlook.NEUTRAL,
                claim="Frozen public evidence remains mixed.",
                evidence_ids=(EVIDENCE_ID,),
                timing="Within one to three days.",
            ),
        ),
        risks_and_invalidation=(
            RiskAndInvalidation(
                condition="The frozen context changes materially.",
                impact="Reassessment is required.",
                evidence_ids=(EVIDENCE_ID,),
            ),
        ),
        data_quality=AgentDataQuality(
            freshness=FreshnessStatus.FRESH,
            missing_inputs=(),
            source_coverage="partial",
        ),
    )
    return PersistedAnalysisReport(
        **report.model_dump(),
        created_at=NOW,
        generator_kind=ReportGeneratorKind.LANGGRAPH_DEEPSEEK,
        evidence=(evidence,),
        agent_analysis=analysis,
    )


def _dual_horizon_report() -> PersistedAnalysisReport:
    report = _report()
    analysis = AgentAnalysis.model_validate(
        {
            **report.agent_analysis.model_dump(mode="python"),  # type: ignore[union-attr]
            "horizon": "dual_horizon",
            "market_metrics": {
                "price": "68000.12",
                "change_24h": "-2.50",
                "volume_24h": "123456789.01",
                "funding_rate": "0.0001",
                "open_interest": "456789012.34",
                "fear_greed_value": 23,
                "fear_greed_classification": "Extreme Fear",
                "fear_greed_change_7d": -11,
            },
            "narrative": {
                "market_overview": {
                    "headline": "流动性回暖但趋势尚未确认",
                    "summary": _research_text("市场概况", 330),
                    "evidence_ids": (EVIDENCE_ID,),
                },
                "short_term": {
                    "horizon": "short_term",
                    "outlook": MarketOutlook.NEUTRAL,
                    "heading": "短期结构仍在关键区间内消化",
                    "thesis": _research_text("短期观点", 460),
                    "drivers": (
                        {
                            "label": "短期流动性",
                            "detail": _research_text("短期驱动", 350),
                            "evidence_ids": (EVIDENCE_ID,),
                        },
                    ),
                    "invalidation": report.agent_analysis.risks_and_invalidation,  # type: ignore[union-attr]
                },
                "long_term": {
                    "horizon": "long_term",
                    "outlook": MarketOutlook.NEUTRAL,
                    "heading": "长期方向等待更多公开证据确认",
                    "thesis": _research_text("长期观点", 460),
                    "drivers": (
                        {
                            "label": "长期结构",
                            "detail": _research_text("长期驱动", 350),
                            "evidence_ids": (EVIDENCE_ID,),
                        },
                    ),
                    "invalidation": report.agent_analysis.risks_and_invalidation,  # type: ignore[union-attr]
                },
            },
        }
    )
    return report.model_copy(update={"agent_analysis": analysis})


def _research_text(prefix: str, length: int) -> str:
    return (prefix * ((length // len(prefix)) + 1))[:length]
