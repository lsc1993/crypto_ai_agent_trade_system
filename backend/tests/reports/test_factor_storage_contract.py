from datetime import UTC, datetime

from app.api.routes.analysis_reports import (
    _to_agent_analysis_response,  # pyright: ignore[reportPrivateUsage]
)
from app.infrastructure.persistence.models.agent_research import AgentReportDetailRecord
from app.market.contracts import FreshnessStatus
from app.reports.contracts import AgentAnalysis, AgentDataQuality, MarketOutlook
from app.reports.factors import FactorAnalysis, FactorFact, FactorTopic


def test_api_exposes_camel_case_topic_values_and_nullable_legacy_field() -> None:
    analysis = AgentAnalysis(
        horizon="1_to_3_days",
        outlook=MarketOutlook.NEUTRAL,
        confidence="low",
        support_zones=(),
        resistance_zones=(),
        catalysts=(),
        risks_and_invalidation=(),
        data_quality=AgentDataQuality(
            freshness=FreshnessStatus.MISSING,
            missing_inputs=(),
            source_coverage="none",
        ),
    )
    assert _to_agent_analysis_response(analysis).model_dump(by_alias=True)["factorAnalysis"] is None
    topic = FactorTopic(
        status="partial",
        window_end=datetime(2026, 9, 6, tzinfo=UTC),
        facts=(
            FactorFact(label="ETF 净流量", value="-12500000", unit="usd"),
            FactorFact(label="尚未披露", value=None, unit="usd"),
        ),
    )
    enriched = analysis.model_copy(
        update={
            "factor_analysis": FactorAnalysis(
                policy=topic,
                funding=topic,
                etf=topic,
            )
        }
    )
    payload = _to_agent_analysis_response(enriched).model_dump(mode="json", by_alias=True)
    assert payload["factorAnalysis"]["etf"]["facts"][0]["value"] == "-12500000"
    assert payload["factorAnalysis"]["etf"]["facts"][1]["value"] is None
    assert payload["factorAnalysis"]["etf"]["windowEnd"] == "2026-09-06T00:00:00Z"


def test_storage_column_is_nullable_to_preserve_existing_reports() -> None:
    column = AgentReportDetailRecord.__table__.columns["factor_analysis"]
    assert column.nullable is True
