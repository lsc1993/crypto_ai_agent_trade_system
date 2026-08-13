from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.model import AgentAnalysisProposal, ModelOutputError, ResearchModelRequest
from app.agent.service import (
    AgentResearchDependencies,
    AgentResearchService,
    CapturedAgentMarket,
    PersistedAgentMarketCapture,
)
from app.market.capture import MarketCaptureService
from app.market.contracts import (
    Candle,
    CandleSeries,
    ContractSymbol,
    DataFreshness,
    FreshnessStatus,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.research import PersistedMarketReader, PersistedMarketSnapshot
from app.news.contracts import (
    NewsEventCategory,
    NewsItemDraft,
    NewsSourceTier,
    parse_http_url,
)
from app.news.service import NewsCollection
from app.reports.contracts import (
    AgentReportCreation,
    AnalysisReportStatus,
    Catalyst,
    MarketOutlook,
    PersistedAnalysisEvidence,
    PersistedAnalysisReport,
    RiskAndInvalidation,
)

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000701")


class FakeMarketCapture:
    def __init__(self, market: CapturedAgentMarket) -> None:
        self.market = market
        self.requests: list[tuple[ContractSymbol, datetime]] = []

    async def capture(
        self,
        symbol: ContractSymbol,
        *,
        captured_at: datetime,
    ) -> CapturedAgentMarket:
        self.requests.append((symbol, captured_at))
        return self.market


class FakeNewsIngestion:
    def __init__(self, collection: NewsCollection) -> None:
        self.collection = collection
        self.requests: list[tuple[ContractSymbol, datetime, datetime]] = []

    async def collect(
        self,
        symbol: ContractSymbol,
        *,
        since: datetime,
        until: datetime,
    ) -> NewsCollection:
        self.requests.append((symbol, since, until))
        return self.collection


class RecordingModel:
    def __init__(
        self,
        outcomes: list[AgentAnalysisProposal | ModelOutputError] | None = None,
    ) -> None:
        self.outcomes = outcomes or []
        self.requests: list[ResearchModelRequest] = []

    async def generate(self, request: ResearchModelRequest) -> AgentAnalysisProposal:
        self.requests.append(request)
        if not self.outcomes:
            return _proposal(request.evidences[0].id)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, ModelOutputError):
            raise outcome
        return outcome


class RecordingRepository:
    def __init__(self) -> None:
        self.creations: list[AgentReportCreation] = []

    async def persist_agent(self, creation: AgentReportCreation) -> PersistedAnalysisReport:
        self.creations.append(creation)
        return PersistedAnalysisReport(
            **creation.report.model_dump(),
            created_at=creation.completed_at,
            evidence=tuple(
                PersistedAnalysisEvidence(
                    id=evidence.id,
                    **evidence.model_dump(),
                    created_at=creation.completed_at,
                )
                for evidence in creation.evidences
            ),
            agent_analysis=creation.agent_analysis,
        )


class RawCapture:
    async def capture_symbol(
        self,
        symbol: ContractSymbol,
        *,
        captured_at: datetime,
    ) -> UUID:
        assert symbol is ContractSymbol.BTCUSDT
        assert captured_at is NOW
        return SNAPSHOT_ID


class StaticMarketReader:
    def __init__(self, market: CapturedAgentMarket) -> None:
        self.market = market

    async def load_snapshot(self, snapshot_id: UUID) -> PersistedMarketSnapshot | None:
        return self.market.snapshot if snapshot_id == SNAPSHOT_ID else None

    async def load_latest_snapshot(
        self,
        symbol: ContractSymbol,
    ) -> PersistedMarketSnapshot | None:
        del symbol
        return self.market.snapshot

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        del symbol, limit
        series = next(
            item for item in self.market.detail.series if item.timeframe is timeframe
        )
        return series.candles


@pytest.mark.asyncio
async def test_persisted_market_capture_excludes_candles_after_run_start() -> None:
    market = _market()
    h1 = next(
        series for series in market.detail.series if series.timeframe is MarketTimeframe.H1
    )
    future = h1.candles[-1].model_copy(
        update={
            "open_at": NOW + timedelta(hours=1),
            "close_at": NOW + timedelta(hours=2),
            "observed_at": NOW + timedelta(hours=2),
        }
    )
    market = CapturedAgentMarket(
        snapshot_id=market.snapshot_id,
        snapshot=market.snapshot,
        detail=market.detail.model_copy(
            update={
                "series": tuple(
                    CandleSeries(
                        timeframe=series.timeframe,
                        candles=(
                            (*series.candles, future)
                            if series.timeframe is MarketTimeframe.H1
                            else series.candles
                        ),
                    )
                    for series in market.detail.series
                )
            }
        ),
    )
    capture = PersistedAgentMarketCapture(
        capture_service=cast(MarketCaptureService, RawCapture()),
        reader=cast(PersistedMarketReader, StaticMarketReader(market)),
    )

    frozen = await capture.capture(ContractSymbol.BTCUSDT, captured_at=NOW)

    assert all(
        candle.close_at <= NOW
        for series in frozen.detail.series
        for candle in series.candles
    )


@pytest.mark.asyncio
async def test_graph_persists_degraded_without_model_when_market_is_stale() -> None:
    model = RecordingModel()
    repository = RecordingRepository()
    service = _service(
        market=_market(captured_at=NOW - timedelta(minutes=3)),
        news=_collection(),
        model=model,
        repository=repository,
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.DEGRADED
    assert model.requests == []
    assert "市场数据已过期" in report.risks[0]
    assert repository.creations[0].error_code == "market_stale"


@pytest.mark.asyncio
async def test_graph_persists_degraded_when_the_model_is_not_configured() -> None:
    repository = RecordingRepository()
    service = _service(
        market=_market(),
        news=_collection(),
        model=None,
        repository=repository,
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.DEGRADED
    assert repository.creations[0].error_code == "model_not_configured"


@pytest.mark.asyncio
async def test_graph_freezes_deduplicated_evidence_and_calls_model_once() -> None:
    duplicate = _news_item("same", "Raw governed news body")
    repository = RecordingRepository()
    model = RecordingModel()
    service = _service(
        market=_market(),
        news=_collection(items=(duplicate, duplicate)),
        model=model,
        repository=repository,
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.COMPLETED
    assert len(model.requests) == 1
    assert len(model.requests[0].evidences) == 2
    assert len(report.evidence) == 2
    assert {evidence.id for evidence in model.requests[0].evidences} <= {
        evidence.id for evidence in report.evidence
    }
    assert repository.creations[0].report.analysis_id == report.analysis_id


@pytest.mark.asyncio
async def test_graph_continues_after_one_news_source_fails() -> None:
    service = _service(
        market=_market(),
        news=_collection(items=(_news_item("one", "One governed article"),), failures=1),
        model=RecordingModel(),
        repository=RecordingRepository(),
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.COMPLETED
    assert report.agent_analysis is not None
    assert report.agent_analysis.data_quality.source_coverage == "partial"


@pytest.mark.asyncio
async def test_graph_persists_market_only_completed_report_when_all_news_fail() -> None:
    service = _service(
        market=_market(),
        news=_collection(failures=2),
        model=RecordingModel(),
        repository=RecordingRepository(),
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.COMPLETED
    assert len(report.evidence) == 1
    assert report.agent_analysis is not None
    assert report.agent_analysis.data_quality.source_coverage == "none"
    assert any("英文新闻" in item for item in report.limitations)


@pytest.mark.asyncio
async def test_graph_retries_empty_model_output_once_then_persists_degraded() -> None:
    model = RecordingModel(
        [
            ModelOutputError("model_empty_response", "empty"),
            ModelOutputError("model_empty_response", "empty"),
        ]
    )
    service = _service(
        market=_market(),
        news=_collection(),
        model=model,
        repository=RecordingRepository(),
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.DEGRADED
    assert len(model.requests) == 2


@pytest.mark.asyncio
async def test_graph_degrades_when_model_references_unknown_evidence() -> None:
    service = _service(
        market=_market(),
        news=_collection(),
        model=RecordingModel([_proposal(uuid4())]),
        repository=RecordingRepository(),
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.DEGRADED
    assert report.agent_analysis is not None
    assert "model_invalid_evidence" in report.limitations[0]


@pytest.mark.asyncio
async def test_checkpoint_state_and_metadata_do_not_include_research_payloads() -> None:
    checkpointer = InMemorySaver()
    service = _service(
        market=_market(),
        news=_collection(items=(_news_item("safe", "LEAKED_NEWS_BODY"),)),
        model=RecordingModel(),
        repository=RecordingRepository(),
        checkpointer=checkpointer,
    )

    report = await service.generate(ContractSymbol.BTCUSDT)
    checkpoints = tuple(
        checkpointer.list({"configurable": {"thread_id": str(report.analysis_id)}})
    )
    serialized = repr(checkpoints).casefold()

    assert checkpoints
    assert "leaked_news_body" not in serialized
    assert "raw_market_json" not in serialized
    assert "api_key" not in serialized
    assert "system prompt" not in serialized
    assert "title" not in serialized
    assert "summary" not in serialized


def _service(
    *,
    market: CapturedAgentMarket,
    news: NewsCollection,
    model: RecordingModel | None,
    repository: RecordingRepository,
    checkpointer: InMemorySaver | None = None,
) -> AgentResearchService:
    return AgentResearchService(
        dependencies=AgentResearchDependencies(
            market=FakeMarketCapture(market),
            news=FakeNewsIngestion(news),
            model=model,
            repository=repository,
            clock=lambda: NOW,
        ),
        checkpointer=checkpointer,
    )


def _market(*, captured_at: datetime = NOW) -> CapturedAgentMarket:
    summary = MarketSummary(
        symbol=ContractSymbol.BTCUSDT,
        price=Decimal("68000"),
        change_24h=Decimal("1.5"),
        volume_24h=Decimal("1000000"),
        funding_rate=Decimal("0.0001"),
        open_interest=Decimal("500000"),
        freshness=DataFreshness(
            status=FreshnessStatus.FRESH,
            source="binance_usdm_public_rest",
            observed_at=captured_at,
            fetched_at=captured_at,
        ),
    )
    return CapturedAgentMarket(
        snapshot_id=SNAPSHOT_ID,
        snapshot=PersistedMarketSnapshot(summary=summary, captured_at=captured_at),
        detail=MarketDetail(
            summary=summary,
            series=tuple(_series(timeframe, captured_at) for timeframe in MarketTimeframe),
        ),
    )


def _series(timeframe: MarketTimeframe, captured_at: datetime) -> CandleSeries:
    duration = {
        MarketTimeframe.M15: timedelta(minutes=15),
        MarketTimeframe.H1: timedelta(hours=1),
        MarketTimeframe.H4: timedelta(hours=4),
        MarketTimeframe.D1: timedelta(days=1),
    }[timeframe]
    candles = tuple(
        Candle(
            symbol=ContractSymbol.BTCUSDT,
            timeframe=timeframe,
            open_at=captured_at - duration * (51 - index),
            close_at=captured_at - duration * (50 - index),
            open_price=Decimal("68000"),
            high_price=Decimal("68100"),
            low_price=Decimal("67900"),
            close_price=Decimal("68000") + Decimal(index),
            volume=Decimal("10"),
            observed_at=captured_at - duration * (50 - index),
            fetched_at=captured_at,
        )
        for index in range(50)
    )
    return CandleSeries(timeframe=timeframe, candles=candles)


def _collection(
    *,
    items: tuple[NewsItemDraft, ...] = (),
    failures: int = 0,
) -> NewsCollection:
    return NewsCollection(
        items=items,
        source_count=2,
        successful_source_count=2 - failures,
        failed_source_count=failures,
        error_codes=("news_source_failed",) * failures,
    )


def _news_item(key: str, content: str) -> NewsItemDraft:
    return NewsItemDraft(
        source_id="coindesk",
        source_tier=NewsSourceTier.PROFESSIONAL_MEDIA,
        source_item_id=key,
        canonical_url=parse_http_url(f"https://www.coindesk.com/markets/{key}"),
        published_at=NOW - timedelta(hours=1),
        fetched_at=NOW,
        language="en",
        title=f"Governed {key}",
        summary=content,
        related_symbols=(ContractSymbol.BTCUSDT,),
        event_category=NewsEventCategory.MARKET,
        content_hash="a" * 64,
        deduplication_key=key,
    )


def _proposal(evidence_id: UUID) -> AgentAnalysisProposal:
    return AgentAnalysisProposal(
        outlook=MarketOutlook.NEUTRAL,
        confidence="low",
        catalysts=(
            Catalyst(
                category="market",
                direction=MarketOutlook.NEUTRAL,
                claim="Frozen public evidence remains balanced.",
                evidence_ids=(evidence_id,),
                timing="Within one to three days.",
            ),
        ),
        risks_and_invalidation=(
            RiskAndInvalidation(
                condition="The cited public context changes materially.",
                impact="The research outlook requires reassessment.",
                evidence_ids=(evidence_id,),
            ),
        ),
    )
