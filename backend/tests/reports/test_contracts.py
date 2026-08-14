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


def test_dual_horizon_narrative_requires_chinese_evidence_backed_sections() -> None:
    evidence_id = uuid4()

    analysis = AgentAnalysis.model_validate(
        {
            **_dual_horizon_analysis_payload(evidence_id),
            "market_metrics": _market_metrics_payload(),
        }
    )

    assert analysis.narrative is not None
    assert analysis.narrative.short_term.horizon == "short_term"
    assert analysis.narrative.long_term.horizon == "long_term"
    assert analysis.market_metrics is not None
    assert str(analysis.market_metrics.price) == "68000.12"


def test_dual_horizon_analysis_requires_frozen_market_metrics() -> None:
    with pytest.raises(ValidationError, match="冻结市场指标"):
        AgentAnalysis.model_validate(_dual_horizon_analysis_payload(uuid4()))


def test_frozen_market_metrics_require_a_complete_sentiment_group() -> None:
    with pytest.raises(ValidationError, match="情绪"):
        AgentAnalysis.model_validate(
            {
                **_dual_horizon_analysis_payload(uuid4()),
                "market_metrics": {
                    **_market_metrics_payload(),
                    "fear_greed_classification": None,
                },
            }
        )


def test_frozen_market_metrics_reject_non_finite_decimal_values() -> None:
    with pytest.raises(ValidationError, match="有限"):
        AgentAnalysis.model_validate(
            {
                **_dual_horizon_analysis_payload(uuid4()),
                "market_metrics": {
                    **_market_metrics_payload(),
                    "funding_rate": "NaN",
                },
            }
        )


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
        ("catalyst_category", "做多 BTC"),
        ("catalyst_claim", "建仓 ETH"),
        ("risk_condition", "Invest in BTC now."),
        ("limitation", "Purchase ETH today."),
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


def _dual_horizon_analysis_payload(evidence_id: UUID) -> dict[str, object]:
    return {
        "horizon": "dual_horizon",
        "outlook": MarketOutlook.NEUTRAL,
        "confidence": "medium",
        "support_zones": (),
        "resistance_zones": (),
        "catalysts": (
            {
                "category": "macro",
                "direction": MarketOutlook.NEUTRAL,
                "claim": "冻结证据显示宏观流动性信号仍需持续观察。",
                "evidence_ids": (evidence_id,),
                "timing": "本次研究周期内",
            },
        ),
        "risks_and_invalidation": (
            {
                "condition": "冻结证据对应的市场结构出现显著变化。",
                "impact": "当前研究观点需要重新评估。",
                "evidence_ids": (evidence_id,),
            },
        ),
        "data_quality": {
            "freshness": FreshnessStatus.FRESH,
            "missing_inputs": (),
            "source_coverage": "complete",
        },
        "limitations": ("本报告只解释冻结的公开证据，不构成交易建议。",),
        "narrative": {
            "market_overview": {
                "headline": "流动性回暖但趋势尚未确认",
                "summary": _research_text("市场概况", 330),
                "evidence_ids": (evidence_id,),
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
                        "evidence_ids": (evidence_id,),
                    },
                ),
                "invalidation": (
                    {
                        "condition": "短期冻结数据的关键区间被新的已验证证据否定。",
                        "impact": "短期观点需要重新评估。",
                        "evidence_ids": (evidence_id,),
                    },
                ),
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
                        "evidence_ids": (evidence_id,),
                    },
                ),
                "invalidation": (
                    {
                        "condition": "长期冻结证据的基本假设出现明显变化。",
                        "impact": "长期观点需要重新评估。",
                        "evidence_ids": (evidence_id,),
                    },
                ),
            },
        },
    }


def _market_metrics_payload() -> dict[str, object]:
    return {
        "price": "68000.12",
        "change_24h": "-2.50",
        "volume_24h": "123456789.01",
        "funding_rate": "0.0001",
        "open_interest": "456789012.34",
        "fear_greed_value": 23,
        "fear_greed_classification": "Extreme Fear",
        "fear_greed_change_7d": -11,
    }


def _research_text(prefix: str, length: int) -> str:
    return (prefix * ((length // len(prefix)) + 1))[:length]
