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

from app.harness.audit import (
    HarnessAuditEvent,
    HarnessAuditEventKind,
    HarnessAuditRun,
    HarnessEvaluation,
    HarnessEvaluationDecision,
    HarnessEvaluationDetails,
    HarnessEventDetails,
    HarnessInitiatorKind,
)
from app.harness.contracts import HarnessRunKind
from app.infrastructure.persistence.harness_audit_repository import (
    SqlAlchemyHarnessAuditRepository,
)
from app.infrastructure.persistence.models.agent_research import (
    AgentAnalysisRunRecord,
    AgentReportDetailRecord,
)
from app.infrastructure.persistence.models.harness import HarnessAuditEventRecord
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
    ModelValidationFailure,
    PriceZone,
    ReportGeneratorKind,
    RiskAndInvalidation,
    TrendDirection,
    report_payload_sha256,
)
from app.reports.factors import FactorAnalysis, FactorFact, FactorTopic

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)
REPORT_ID = UUID("00000000-0000-0000-0000-000000000301")
EVIDENCE_ID = UUID("00000000-0000-0000-0000-000000000302")


class MigratedDatabase(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


@pytest.mark.asyncio
async def test_repository_round_trips_frozen_report_factors(
    migrated_database: MigratedDatabase,
) -> None:
    creation = _agent_creation()
    funding = FactorTopic(
        status="available",
        window_end=NOW,
        evidence_ids=(EVIDENCE_ID,),
        facts=(FactorFact(label="最新结算费率", value="-0.000125", unit="rate"),),
    )
    missing = FactorTopic(status="missing", window_end=NOW)
    factors = FactorAnalysis(policy=missing, funding=funding, etf=missing)
    updated = creation.model_copy(
        update={
            "agent_analysis": creation.agent_analysis.model_copy(
                update={"factor_analysis": factors},
            )
        }
    )
    repository = SqlAlchemyAnalysisReportRepository(migrated_database.session_factory)
    saved = await repository.persist_agent(updated)
    assert saved.agent_analysis is not None
    assert saved.agent_analysis.factor_analysis == factors
    fetched = await repository.get_by_id(saved.id)
    assert fetched is not None and fetched.agent_analysis is not None
    assert fetched.agent_analysis.factor_analysis == factors


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
async def test_agent_repository_persists_sanitized_model_validation_failure(
    migrated_database: MigratedDatabase,
) -> None:
    validation_failure = ModelValidationFailure(
        attempt_count=3,
        issue_count=2,
        field_paths=("short_term.thesis", "factor_interpretations.0.summary"),
        error_categories=("schema", "trading_instruction"),
    )
    creation = _agent_creation_for(
        report_id=UUID("00000000-0000-0000-0000-000000000308"),
        evidence_id=UUID("00000000-0000-0000-0000-000000000309"),
        status=AnalysisReportStatus.DEGRADED,
        error_code="model_invalid_response",
        validation_failure=validation_failure,
    )
    repository = SqlAlchemyAnalysisReportRepository(migrated_database.session_factory)

    persisted = await repository.persist_agent(creation)

    assert persisted.validation_failure == validation_failure
    async with migrated_database.session_factory() as session:
        run = (
            await session.execute(
                select(AgentAnalysisRunRecord).where(
                    AgentAnalysisRunRecord.analysis_id == persisted.analysis_id
                )
            )
        ).scalar_one()
    assert run.model_validation_attempt_count == 3
    assert run.model_validation_issue_count == 2
    assert run.model_validation_field_paths == [
        "short_term.thesis",
        "factor_interpretations.0.summary",
    ]
    assert run.model_validation_error_categories == ["schema", "trading_instruction"]

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


@pytest.mark.asyncio
async def test_agent_report_persistence_appends_harness_terminal_event_atomically(
    migrated_database: MigratedDatabase,
) -> None:
    report_repository = SqlAlchemyAnalysisReportRepository(migrated_database.session_factory)
    audit_repository = SqlAlchemyHarnessAuditRepository(migrated_database.session_factory)
    completed = _agent_creation()
    await _record_admitted_run(audit_repository, completed.report.analysis_id)

    prior_events = await _audit_event_snapshots(
        migrated_database.session_factory,
        completed.report.analysis_id,
    )
    await report_repository.persist_agent(completed)
    completed_events = await _audit_event_snapshots(
        migrated_database.session_factory,
        completed.report.analysis_id,
    )

    assert completed_events[:3] == prior_events
    assert completed_events[3] == (
        3,
        "workflow_completed",
        completed.completed_at,
        0,
        None,
        {},
    )

    degraded = _agent_creation_for(
        report_id=UUID("00000000-0000-0000-0000-000000000304"),
        evidence_id=UUID("00000000-0000-0000-0000-000000000305"),
        status=AnalysisReportStatus.DEGRADED,
        error_code="partial_data",
    )
    await _record_admitted_run(audit_repository, degraded.report.analysis_id)
    await report_repository.persist_agent(degraded)

    degraded_events = await _audit_event_snapshots(
        migrated_database.session_factory,
        degraded.report.analysis_id,
    )
    assert [event[1] for event in degraded_events] == [
        "requested",
        "policy_authorized",
        "workflow_started",
        "workflow_degraded",
    ]
    assert degraded_events[3] == (
        3,
        "workflow_degraded",
        degraded.completed_at,
        0,
        "partial_data",
        {},
    )

    no_envelope = _agent_creation_for(
        report_id=UUID("00000000-0000-0000-0000-000000000306"),
        evidence_id=UUID("00000000-0000-0000-0000-000000000307"),
        status=AnalysisReportStatus.COMPLETED,
        error_code=None,
    )
    await report_repository.persist_agent(no_envelope)

    assert (
        await _audit_event_snapshots(
            migrated_database.session_factory,
            no_envelope.report.analysis_id,
        )
        == ()
    )


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


def _agent_creation_for(
    *,
    report_id: UUID,
    evidence_id: UUID,
    status: AnalysisReportStatus,
    error_code: str | None,
    validation_failure: ModelValidationFailure | None = None,
) -> AgentReportCreation:
    creation = _agent_creation()
    report_updates: dict[str, object] = {
        "id": report_id,
        "analysis_id": report_id,
        "status": status,
    }
    if status is AnalysisReportStatus.DEGRADED:
        report_updates.update(facts=(), inferences=())
    report = AnalysisReportDraft.model_validate(
        {**creation.report.model_dump(mode="python"), **report_updates}
    )
    evidence = AnalysisEvidenceDraft.model_validate(
        {
            **creation.evidences[0].model_dump(mode="python"),
            "id": evidence_id,
            "report_id": report_id,
        }
    )
    analysis = AgentAnalysis.model_validate(
        {
            **creation.agent_analysis.model_dump(mode="python"),
            "catalysts": tuple(
                catalyst.model_copy(update={"evidence_ids": (evidence_id,)})
                for catalyst in creation.agent_analysis.catalysts
            ),
            "risks_and_invalidation": tuple(
                risk.model_copy(update={"evidence_ids": (evidence_id,)})
                for risk in creation.agent_analysis.risks_and_invalidation
            ),
        }
    )
    return AgentReportCreation(
        report=report,
        evidences=(evidence,),
        started_at=creation.started_at,
        completed_at=creation.completed_at,
        generator_kind=creation.generator_kind,
        error_code=error_code,
        validation_failure=validation_failure,
        agent_analysis=analysis,
    )


async def _record_admitted_run(
    repository: SqlAlchemyHarnessAuditRepository,
    run_id: UUID,
) -> None:
    run = HarnessAuditRun(
        run_id=run_id,
        run_kind=HarnessRunKind.MARKET_RESEARCH,
        policy_version="market_research_v1",
        policy_sha256="a" * 64,
        symbol=ContractSymbol.BTCUSDT,
        requested_at=NOW,
        initiator_kind=HarnessInitiatorKind.MANUAL_API,
        request_sha256="b" * 64,
    )
    await repository.create_requested_run(
        run,
        HarnessAuditEvent(
            run_id=run_id,
            sequence=0,
            kind=HarnessAuditEventKind.REQUESTED,
            occurred_at=NOW,
            duration_ms=0,
            error_code=None,
            details=HarnessEventDetails(declared_capability_count=4),
        ),
    )
    await repository.append_policy_evaluation(
        HarnessEvaluation(
            run_id=run_id,
            sequence=0,
            evaluator_name="policy_allowlist",
            evaluator_version="1",
            decision=HarnessEvaluationDecision.PASSED,
            reason_code=None,
            evaluated_at=NOW,
            details=HarnessEvaluationDetails(
                declared_capability_count=4,
                allowed_capability_count=4,
            ),
        ),
        HarnessAuditEvent(
            run_id=run_id,
            sequence=1,
            kind=HarnessAuditEventKind.POLICY_AUTHORIZED,
            occurred_at=NOW,
            duration_ms=0,
            error_code=None,
            details=HarnessEventDetails(allowed_capability_count=4),
        ),
    )
    await repository.append_event(
        HarnessAuditEvent(
            run_id=run_id,
            sequence=2,
            kind=HarnessAuditEventKind.WORKFLOW_STARTED,
            occurred_at=NOW,
            duration_ms=0,
            error_code=None,
            details=HarnessEventDetails(workflow_kind=HarnessRunKind.MARKET_RESEARCH),
        )
    )


async def _audit_event_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
) -> tuple[tuple[int, str, datetime, int, str | None, dict[str, object]], ...]:
    async with session_factory() as session:
        records = tuple(
            (
                await session.execute(
                    select(HarnessAuditEventRecord)
                    .where(HarnessAuditEventRecord.run_id == run_id)
                    .order_by(HarnessAuditEventRecord.sequence.asc())
                )
            ).scalars()
        )
    return tuple(
        (
            record.sequence,
            record.event_kind,
            record.occurred_at,
            record.duration_ms,
            record.error_code,
            record.details,
        )
        for record in records
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
