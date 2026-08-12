from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest

from app.market.contracts import (
    Candle,
    ContractSymbol,
    DataFreshness,
    FreshnessStatus,
    MarketDataUnavailableError,
    MarketSummary,
    MarketTimeframe,
)
from app.market.research import PersistedMarketReader, PersistedMarketSnapshot
from app.reports.contracts import (
    AnalysisReportCreation,
    AnalysisReportStatus,
    PersistedAnalysisEvidence,
    PersistedAnalysisReport,
    ReportPage,
)
from app.reports.service import DeterministicResearchReportService

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
TIMEFRAMES = (
    MarketTimeframe.M15,
    MarketTimeframe.H1,
    MarketTimeframe.H4,
    MarketTimeframe.D1,
)


@pytest.mark.asyncio
async def test_service_freezes_latest_snapshot_and_four_closed_candles() -> None:
    reader = FakePersistedMarketReader(captured_at=NOW - timedelta(minutes=1))
    repository = RecordingReportRepository()
    service = DeterministicResearchReportService(reader, repository, clock=lambda: NOW)

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.COMPLETED
    assert report.data_cutoff_at == NOW - timedelta(minutes=1)
    assert len(report.evidence) == 5
    assert reader.candle_requests == [(timeframe, 200) for timeframe in TIMEFRAMES]
    snapshot_payload = cast(dict[str, object], report.evidence[0].payload["summary"])
    candle_payload = cast(
        dict[str, object],
        report.evidence[1].payload["latestClosedCandle"],
    )
    assert snapshot_payload["symbol"] == "BTCUSDT"
    assert candle_payload["timeframe"] == "15m"
    report_text = " ".join(
        (
            report.title,
            report.summary,
            *report.facts,
            *report.inferences,
            *report.risks,
            *report.limitations,
        )
    )
    assert "买入" not in report_text
    assert "卖出" not in report_text


@pytest.mark.asyncio
async def test_service_generates_no_market_conclusion_for_stale_data() -> None:
    reader = FakePersistedMarketReader(captured_at=NOW - timedelta(minutes=2, microseconds=1))
    repository = RecordingReportRepository()
    service = DeterministicResearchReportService(reader, repository, clock=lambda: NOW)

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.DEGRADED
    assert report.facts == ()
    assert report.inferences == ()
    assert len(report.evidence) == 5
    assert "过期" in report.risks[0]


@pytest.mark.asyncio
async def test_service_generates_degraded_report_without_evidence_when_reader_is_unavailable(
) -> None:
    repository = RecordingReportRepository()
    service = DeterministicResearchReportService(
        UnavailablePersistedMarketReader(),
        repository,
        clock=lambda: NOW,
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.DEGRADED
    assert report.data_cutoff_at is None
    assert report.evidence == ()
    assert report.facts == ()
    assert report.inferences == ()


@pytest.mark.asyncio
async def test_service_degrades_when_a_required_timeframe_is_missing() -> None:
    reader = FakePersistedMarketReader(
        captured_at=NOW - timedelta(minutes=1),
        missing_timeframe=MarketTimeframe.H4,
    )
    repository = RecordingReportRepository()
    service = DeterministicResearchReportService(reader, repository, clock=lambda: NOW)

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.DEGRADED
    assert report.facts == ()
    assert report.inferences == ()
    assert "缺失" in report.risks[0]


class FakePersistedMarketReader(PersistedMarketReader):
    def __init__(
        self,
        *,
        captured_at: datetime,
        missing_timeframe: MarketTimeframe | None = None,
    ) -> None:
        self._captured_at = captured_at
        self._missing_timeframe = missing_timeframe
        self.candle_requests: list[tuple[MarketTimeframe, int]] = []

    async def load_snapshot(self, snapshot_id: UUID) -> PersistedMarketSnapshot | None:
        del snapshot_id
        return None

    async def load_latest_snapshot(
        self,
        symbol: ContractSymbol,
    ) -> PersistedMarketSnapshot | None:
        return PersistedMarketSnapshot(
            summary=_summary(symbol),
            captured_at=self._captured_at,
        )

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        self.candle_requests.append((timeframe, limit))
        if timeframe is self._missing_timeframe:
            return ()
        return (_candle(symbol, timeframe),)


class UnavailablePersistedMarketReader(PersistedMarketReader):
    async def load_snapshot(self, snapshot_id: UUID) -> PersistedMarketSnapshot | None:
        del snapshot_id
        raise MarketDataUnavailableError(
            "market_research_unavailable",
            "持久化市场研究数据不可用",
        )

    async def load_latest_snapshot(
        self,
        symbol: ContractSymbol,
    ) -> PersistedMarketSnapshot | None:
        del symbol
        raise MarketDataUnavailableError(
            "market_research_unavailable",
            "持久化市场研究数据不可用",
        )

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        del symbol, timeframe, limit
        raise MarketDataUnavailableError(
            "market_research_unavailable",
            "持久化市场研究数据不可用",
        )


class RecordingReportRepository:
    def __init__(self) -> None:
        self.creation: AnalysisReportCreation | None = None

    async def persist(
        self,
        creation: AnalysisReportCreation,
    ) -> PersistedAnalysisReport:
        self.creation = creation
        return PersistedAnalysisReport(
            **creation.report.model_dump(),
            created_at=NOW,
            evidence=tuple(
                PersistedAnalysisEvidence(
                    id=uuid4(),
                    **evidence.model_dump(),
                    created_at=NOW,
                )
                for evidence in creation.evidences
            ),
        )

    async def get_by_id(self, report_id: UUID) -> PersistedAnalysisReport | None:
        del report_id
        return None

    async def get_by_analysis_id(
        self,
        analysis_id: UUID,
    ) -> PersistedAnalysisReport | None:
        del analysis_id
        return None

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        symbol: ContractSymbol | None,
        status: AnalysisReportStatus | None,
    ) -> ReportPage:
        del page, page_size, symbol, status
        raise AssertionError("生成服务不应读取报告列表")


def _summary(symbol: ContractSymbol) -> MarketSummary:
    return MarketSummary(
        symbol=symbol,
        price=Decimal("68000.30"),
        change_24h=Decimal("1.25"),
        volume_24h=Decimal("123456.789"),
        funding_rate=Decimal("0.00010000"),
        open_interest=Decimal("1234.5678"),
        freshness=DataFreshness(
            status=FreshnessStatus.FRESH,
            source="binance_usdm_public_rest",
            observed_at=NOW - timedelta(minutes=1),
            fetched_at=NOW,
        ),
    )


def _candle(symbol: ContractSymbol, timeframe: MarketTimeframe) -> Candle:
    close_at = NOW - timedelta(minutes=1)
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_at=close_at - timedelta(minutes=15),
        close_at=close_at,
        open_price=Decimal("68000.10"),
        high_price=Decimal("68001.20"),
        low_price=Decimal("67999.90"),
        close_price=Decimal("68000.30"),
        volume=Decimal("12.34"),
        observed_at=NOW - timedelta(minutes=1),
        fetched_at=NOW,
    )
