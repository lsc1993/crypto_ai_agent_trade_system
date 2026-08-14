from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID

import pytest
from pydantic import JsonValue
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.agent_research import (
    AgentAnalysisRunRecord,
    AgentReportDetailRecord,
)
from app.infrastructure.persistence.report_repository import (
    SqlAlchemyAnalysisReportRepository,
)
from app.market.contracts import ContractSymbol, FreshnessStatus, MarketTimeframe
from app.reports.contracts import (
    AgentAnalysis,
    AgentDataQuality,
    AgentReportCreation,
    AnalysisEvidenceDraft,
    AnalysisReportCreation,
    AnalysisReportDraft,
    AnalysisReportStatus,
    Catalyst,
    MarketOutlook,
    PriceZone,
    ReportGeneratorKind,
    RiskAndInvalidation,
    TrendDirection,
    report_payload_sha256,
)

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)
REPORT_ID = UUID("00000000-0000-0000-0000-000000000301")
EVIDENCE_ID = UUID("00000000-0000-0000-0000-000000000302")


class MigratedDatabase(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


@pytest.mark.asyncio
async def test_agent_repository_persists_run_frozen_evidence_and_immutable_detail(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyAnalysisReportRepository(migrated_database.session_factory)

    persisted = await repository.persist_agent(_agent_creation())

    assert persisted.generator_kind is ReportGeneratorKind.LANGGRAPH_DEEPSEEK
    assert persisted.agent_analysis is not None
    assert persisted.agent_analysis.outlook is MarketOutlook.NEUTRAL
    assert persisted.agent_analysis.support_zones[0].lower == Decimal("67000.10")
    assert persisted.evidence[0].payload["news"] == {
        "sourceTier": "professional_media",
        "title": "Original governed headline",
    }

    async with migrated_database.session_factory() as session:
        run = (
            await session.execute(
                select(AgentAnalysisRunRecord).where(
                    AgentAnalysisRunRecord.analysis_id == persisted.analysis_id
                )
            )
        ).scalar_one()
        detail = await session.get(AgentReportDetailRecord, persisted.id)
        assert run.error_code is None
        assert detail is not None
        assert detail.support_zones[0]["lower"] == "67000.10"

        with pytest.raises(DBAPIError, match="analysis records are immutable"):
            await session.execute(
                update(AgentReportDetailRecord)
                .where(AgentReportDetailRecord.analysis_report_id == persisted.id)
                .values(outlook="bullish")
            )
            await session.commit()
        await session.rollback()

        with pytest.raises(DBAPIError, match="analysis records are immutable"):
            await session.execute(
                delete(AgentAnalysisRunRecord).where(
                    AgentAnalysisRunRecord.analysis_id == persisted.analysis_id
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_agent_repository_round_trips_dual_horizon_narrative(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyAnalysisReportRepository(migrated_database.session_factory)

    persisted = await repository.persist_agent(_dual_horizon_agent_creation())

    assert persisted.agent_analysis is not None
    assert persisted.agent_analysis.narrative is not None
    assert persisted.agent_analysis.narrative.market_overview.headline == (
        "流动性回暖但趋势尚未确认"
    )
    assert persisted.agent_analysis.market_metrics is not None
    assert persisted.agent_analysis.market_metrics.price == Decimal("68000.12")


@pytest.mark.asyncio
async def test_deterministic_reports_remain_backward_compatible_without_agent_detail(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyAnalysisReportRepository(migrated_database.session_factory)
    creation = _deterministic_creation()

    persisted = await repository.persist(creation)
    page = await repository.list(
        page=1,
        page_size=20,
        symbol=ContractSymbol.ETHUSDT,
        status=AnalysisReportStatus.DEGRADED,
    )

    assert persisted.generator_kind is ReportGeneratorKind.DETERMINISTIC
    assert persisted.agent_analysis is None
    assert page.items[0].generator_kind is ReportGeneratorKind.DETERMINISTIC


def _agent_creation() -> AgentReportCreation:
    report = AnalysisReportDraft(
        id=REPORT_ID,
        analysis_id=REPORT_ID,
        symbol=ContractSymbol.BTCUSDT,
        status=AnalysisReportStatus.COMPLETED,
        title="BTCUSDT Agent 市场研究",
        summary="本报告只陈述已冻结的公开市场与新闻观察。",
        facts=("已冻结一条受治理的英文新闻快照。",),
        inferences=("未来一至三天方向保持中性。",),
        risks=("公开数据可能随时间过期。",),
        limitations=("本报告不访问账户或交易执行。",),
        generated_at=NOW,
        data_cutoff_at=NOW - timedelta(minutes=1),
    )
    payload: dict[str, JsonValue] = {
        "news": {
            "sourceTier": "professional_media",
            "title": "Original governed headline",
        }
    }
    evidence = AnalysisEvidenceDraft(
        id=EVIDENCE_ID,
        report_id=REPORT_ID,
        symbol=ContractSymbol.BTCUSDT,
        source="coindesk",
        source_url="https://www.coindesk.com/markets/item-1",
        observed_at=NOW - timedelta(minutes=2),
        fetched_at=NOW - timedelta(minutes=1),
        summary="单一专业媒体的英文新闻快照。",
        payload=payload,
        payload_sha256=report_payload_sha256(payload),
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
                rationale="由已收盘 K 线局部低点确定。",
            ),
        ),
        resistance_zones=(),
        catalysts=(
            Catalyst(
                category="market",
                direction=MarketOutlook.NEUTRAL,
                claim="单一媒体报道需要更多来源确认。",
                evidence_ids=(EVIDENCE_ID,),
                timing="未来一至三天",
            ),
        ),
        risks_and_invalidation=(
            RiskAndInvalidation(
                condition="价格离开已识别区间。",
                impact="当前中性判断失效。",
                evidence_ids=(EVIDENCE_ID,),
            ),
        ),
        data_quality=AgentDataQuality(
            freshness=FreshnessStatus.FRESH,
            missing_inputs=(),
            source_coverage="partial",
        ),
        limitations=("仅包含一个专业媒体来源。",),
    )
    return AgentReportCreation(
        report=report,
        evidences=(evidence,),
        started_at=NOW - timedelta(minutes=3),
        completed_at=NOW,
        error_code=None,
        agent_analysis=analysis,
    )


def _deterministic_creation() -> AnalysisReportCreation:
    report_id = UUID("00000000-0000-0000-0000-000000000303")
    return AnalysisReportCreation(
        report=AnalysisReportDraft(
            id=report_id,
            analysis_id=report_id,
            symbol=ContractSymbol.ETHUSDT,
            status=AnalysisReportStatus.DEGRADED,
            title="ETHUSDT 持久化市场研究已降级",
            summary="无法形成市场研究结论。",
            facts=(),
            inferences=(),
            risks=("持久化市场数据缺失。",),
            limitations=("本报告未形成市场结论。",),
            generated_at=NOW,
            data_cutoff_at=None,
        ),
        evidences=(),
    )


def _dual_horizon_agent_creation() -> AgentReportCreation:
    creation = _agent_creation()
    analysis = AgentAnalysis.model_validate(
        {
            **creation.agent_analysis.model_dump(mode="python"),
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
                    "invalidation": creation.agent_analysis.risks_and_invalidation,
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
                    "invalidation": creation.agent_analysis.risks_and_invalidation,
                },
            },
        }
    )
    return creation.model_copy(update={"agent_analysis": analysis})


def _research_text(prefix: str, length: int) -> str:
    return (prefix * ((length // len(prefix)) + 1))[:length]
