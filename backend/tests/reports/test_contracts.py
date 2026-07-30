from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue, ValidationError

from app.market.contracts import ContractSymbol
from app.reports.contracts import (
    AnalysisEvidenceDraft,
    AnalysisReportCreation,
    AnalysisReportDraft,
    AnalysisReportStatus,
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
