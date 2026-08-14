from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue, ValidationError

from app.market.contracts import ContractSymbol, FreshnessStatus
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
    RiskAndInvalidation,
    report_payload_sha256,
)

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
REPORT_ID = UUID("00000000-0000-0000-0000-000000000001")
ANALYSIS_ID = UUID("00000000-0000-0000-0000-000000000002")


def test_report_creation_requires_evidence_for_a_completed_report() -> None:
    with pytest.raises(ValidationError, match="证据"):
        AnalysisReportCreation(report=_completed_report(), evidences=())


def test_report_draft_rejects_trading_instruction_language_after_normalization() -> None:
    with pytest.raises(ValidationError, match="交易指令"):
        _completed_report(summary="建议 立 即 买 入 BTCUSDT")


def test_report_draft_rejects_english_trading_instruction_language() -> None:
    with pytest.raises(ValidationError, match="交易指令"):
        _completed_report(summary="The model says to buy BTC now.")


@pytest.mark.parametrize(
    "instruction",
    (
        "Bitcoin may be worth buying in the next 1–3 days.",
        "Consider buying BTC now.",
        "We advise buying BTC.",
        "Open a long position.",
    ),
)
def test_report_draft_rejects_common_english_trade_advice(instruction: str) -> None:
    with pytest.raises(ValidationError, match="交易指令"):
        _completed_report(summary=instruction)


def test_degraded_report_rejects_market_facts_or_inferences() -> None:
    with pytest.raises(ValidationError, match="降级报告"):
        AnalysisReportDraft(
            id=REPORT_ID,
            analysis_id=ANALYSIS_ID,
            symbol=ContractSymbol.BTCUSDT,
            status=AnalysisReportStatus.DEGRADED,
            title="BTCUSDT 持久化市场研究已降级",
            summary="无法形成市场研究结论。",
            facts=("价格来自持久化快照。",),
            inferences=(),
            risks=("持久化市场数据缺失。",),
            limitations=("本报告未形成市场结论。",),
            generated_at=NOW,
            data_cutoff_at=None,
        )


def test_evidence_rejects_a_non_matching_payload_hash() -> None:
    with pytest.raises(ValidationError, match="哈希"):
        AnalysisEvidenceDraft(
            report_id=REPORT_ID,
            symbol=ContractSymbol.BTCUSDT,
            source="binance_usdm_public_rest",
            source_url="https://www.binance.com/en/futures/BTCUSDT",
            observed_at=NOW,
            fetched_at=NOW,
            summary="BTCUSDT 持久化市场快照",
            payload={"summary": {"symbol": "BTCUSDT"}},
            payload_sha256="0" * 64,
        )


def test_creation_rejects_evidence_belonging_to_a_different_report() -> None:
    evidence = _valid_evidence(report_id=uuid4())

    with pytest.raises(ValidationError, match="报告 ID"):
        AnalysisReportCreation(report=_completed_report(), evidences=(evidence,))


def test_creation_accepts_a_matching_immutable_completed_report() -> None:
    creation = AnalysisReportCreation(
        report=_completed_report(),
        evidences=(_valid_evidence(report_id=REPORT_ID),),
    )

    assert creation.report.status is AnalysisReportStatus.COMPLETED
    assert creation.evidences[0].payload_sha256 == report_payload_sha256(
        creation.evidences[0].payload,
    )
    with pytest.raises(ValidationError):
        creation.report.title = "不可修改的标题"  # type: ignore[misc]


def test_agent_creation_json_round_trip_preserves_referenced_evidence_ids() -> None:
    evidence = _valid_evidence(report_id=REPORT_ID)
    creation = AgentReportCreation(
        report=_completed_report(),
        evidences=(evidence,),
        started_at=NOW,
        completed_at=NOW,
        agent_analysis=AgentAnalysis(
            horizon="1_to_3_days",
            outlook=MarketOutlook.NEUTRAL,
            confidence="low",
            support_zones=(),
            resistance_zones=(),
            catalysts=(
                Catalyst(
                    category="market",
                    direction=MarketOutlook.NEUTRAL,
                    claim="Frozen evidence describes the current market context.",
                    evidence_ids=(evidence.id,),
                    timing="Within one to three days.",
                ),
            ),
            risks_and_invalidation=(
                RiskAndInvalidation(
                    condition="The cited market context materially changes.",
                    impact="The outlook requires reassessment.",
                    evidence_ids=(evidence.id,),
                ),
            ),
            data_quality=AgentDataQuality(
                freshness=FreshnessStatus.FRESH,
                missing_inputs=(),
                source_coverage="partial",
            ),
        ),
    )

    restored = AgentReportCreation.model_validate_json(creation.model_dump_json())

    assert restored.evidences[0].id == evidence.id
    assert restored.agent_analysis.catalysts[0].evidence_ids == (evidence.id,)


def test_catalyst_rejects_a_category_empty_after_normalization() -> None:
    with pytest.raises(ValidationError, match="类别不能为空"):
        Catalyst(
            category="   ",
            direction=MarketOutlook.NEUTRAL,
            claim="Frozen evidence describes the current market context.",
            evidence_ids=(uuid4(),),
            timing="Within one to three days.",
        )


@pytest.mark.parametrize(
    ("field", "instruction"),
    (
        ("catalyst_category", "Buy BTC now"),
        ("catalyst_claim", "Short BTC immediately."),
        ("risk_condition", "Buy ETH now."),
        ("limitation", "Increase your exposure before the close."),
    ),
)
def test_agent_analysis_rejects_direct_trading_imperatives(
    field: str,
    instruction: str,
) -> None:
    evidence_id = uuid4()
    payload: dict[str, object] = {
        "horizon": "1_to_3_days",
        "outlook": MarketOutlook.NEUTRAL,
        "confidence": "low",
        "support_zones": (),
        "resistance_zones": (),
        "catalysts": (
            {
                "category": instruction if field == "catalyst_category" else "market",
                "direction": MarketOutlook.NEUTRAL,
                "claim": instruction
                if field == "catalyst_claim"
                else "Frozen evidence is mixed.",
                "evidence_ids": (evidence_id,),
                "timing": "Within one to three days.",
            },
        ),
        "risks_and_invalidation": (
            {
                "condition": instruction
                if field == "risk_condition"
                else "Liquidity materially changes.",
                "impact": "The outlook requires reassessment.",
                "evidence_ids": (evidence_id,),
            },
        ),
        "data_quality": AgentDataQuality(
            freshness=FreshnessStatus.FRESH,
            missing_inputs=(),
            source_coverage="partial",
        ),
        "limitations": (
            instruction if field == "limitation" else "Research-only evidence.",
        ),
    }

    with pytest.raises(ValidationError, match="交易指令"):
        AgentAnalysis.model_validate(payload)


def test_agent_analysis_allows_neutral_short_positioning_context() -> None:
    evidence_id = uuid4()

    analysis = AgentAnalysis(
        horizon="1_to_3_days",
        outlook=MarketOutlook.NEUTRAL,
        confidence="low",
        support_zones=(),
        resistance_zones=(),
        catalysts=(
            Catalyst(
                category="market",
                direction=MarketOutlook.NEUTRAL,
                claim="Short positioning has increased in the cited market context.",
                evidence_ids=(evidence_id,),
                timing="Within one to three days.",
            ),
        ),
        risks_and_invalidation=(
            RiskAndInvalidation(
                condition="The cited positioning data materially changes.",
                impact="The outlook requires reassessment.",
                evidence_ids=(evidence_id,),
            ),
        ),
        data_quality=AgentDataQuality(
            freshness=FreshnessStatus.FRESH,
            missing_inputs=(),
            source_coverage="partial",
        ),
        limitations=("Research-only evidence.",),
    )

    assert analysis.catalysts[0].claim.startswith("Short positioning")


def _completed_report(
    *,
    summary: str = "本报告只陈述已冻结的公开市场观察。",
) -> AnalysisReportDraft:
    return AnalysisReportDraft(
        id=REPORT_ID,
        analysis_id=ANALYSIS_ID,
        symbol=ContractSymbol.BTCUSDT,
        status=AnalysisReportStatus.COMPLETED,
        title="BTCUSDT 持久化市场研究",
        summary=summary,
        facts=("价格来自已持久化的公开市场快照。",),
        inferences=("这些观察不构成方向或交易结论。",),
        risks=("市场数据可能随时间过期。",),
        limitations=("报告未访问账户、模型或实时市场。",),
        generated_at=NOW,
        data_cutoff_at=NOW,
    )


def _valid_evidence(*, report_id: UUID) -> AnalysisEvidenceDraft:
    payload: dict[str, JsonValue] = {"summary": {"symbol": "BTCUSDT"}}
    return AnalysisEvidenceDraft(
        report_id=report_id,
        symbol=ContractSymbol.BTCUSDT,
        source="binance_usdm_public_rest",
        source_url="https://www.binance.com/en/futures/BTCUSDT",
        observed_at=NOW,
        fetched_at=NOW,
        summary="BTCUSDT 持久化市场快照",
        payload=payload,
        payload_sha256=report_payload_sha256(payload),
    )
