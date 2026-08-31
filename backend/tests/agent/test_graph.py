from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

import app.agent.graph as agent_graph
import app.agent.service as agent_service
from app.agent.contracts import AgentErrorCode
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
    MarketDataUnavailableError,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.research import (
    PersistedMarketSnapshot,
    PersistedMarketSnapshotInput,
)
from app.market.research_context import PublicResearchContext
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
    EvidenceBackedClaim,
    MarketOutlook,
    MarketOverview,
    PersistedAnalysisEvidence,
    PersistedAnalysisReport,
    ResearchPerspective,
    RiskAndInvalidation,
)

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000701")
ANALYSIS_ID = UUID("00000000-0000-0000-0000-000000000702")


class RecordingLogger:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def info(self, event: str, **fields: object) -> None:
        self.entries.append({"event": event, "log_level": "info", **fields})

    def debug(self, event: str, **fields: object) -> None:
        self.entries.append({"event": event, "log_level": "debug", **fields})


def _record_agent_logs(monkeypatch: pytest.MonkeyPatch) -> RecordingLogger:
    logger = RecordingLogger()
    monkeypatch.setattr(agent_graph, "logger", logger)
    monkeypatch.setattr(agent_service, "logger", logger)
    return logger


class FakeMarketCapture:
    def __init__(
        self,
        market: CapturedAgentMarket,
        error: BaseException | None = None,
    ) -> None:
        self.market = market
        self.error = error
        self.requests: list[tuple[ContractSymbol, datetime]] = []

    async def capture(
        self,
        symbol: ContractSymbol,
        *,
        captured_at: datetime,
    ) -> CapturedAgentMarket:
        self.requests.append((symbol, captured_at))
        if self.error is not None:
            raise self.error
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
        outcomes: list[AgentAnalysisProposal | BaseException] | None = None,
    ) -> None:
        self.outcomes = outcomes or []
        self.requests: list[ResearchModelRequest] = []

    async def generate(self, request: ResearchModelRequest) -> AgentAnalysisProposal:
        self.requests.append(request)
        if not self.outcomes:
            return _proposal(request.evidences[0].id)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class HighConfidenceModel(RecordingModel):
    async def generate(self, request: ResearchModelRequest) -> AgentAnalysisProposal:
        self.requests.append(request)
        return _proposal(request.evidences[0].id, confidence="high")


class LimitedProposalModel(RecordingModel):
    def __init__(self, limitations: tuple[str, ...]) -> None:
        super().__init__()
        self._limitations = limitations

    async def generate(self, request: ResearchModelRequest) -> AgentAnalysisProposal:
        self.requests.append(request)
        return _proposal(request.evidences[0].id, limitations=self._limitations)


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


class FailingRepository:
    async def persist_agent(self, creation: AgentReportCreation) -> PersistedAnalysisReport:
        del creation
        raise RuntimeError("LEAKED_DATABASE_URL")


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


class UnavailableResearchContextCollector:
    async def collect(
        self,
        symbol: ContractSymbol,
        *,
        captured_at: datetime,
    ) -> PublicResearchContext:
        del symbol, captured_at
        raise MarketDataUnavailableError(
            "market_context_unavailable",
            "upstream response must not be retained",
        )


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

    async def load_snapshot_input(
        self,
        snapshot_id: UUID,
    ) -> PersistedMarketSnapshotInput | None:
        if snapshot_id != SNAPSHOT_ID:
            return None
        return PersistedMarketSnapshotInput(
            candles=tuple(
                candle for series in self.market.detail.series for candle in series.candles
            ),
            payload_sha256="a" * 64,
        )

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        del symbol, limit
        series = next(item for item in self.market.detail.series if item.timeframe is timeframe)
        return series.candles


class ImmutableInputMarketReader(StaticMarketReader):
    def __init__(self, market: CapturedAgentMarket) -> None:
        super().__init__(market)
        self.recent_candle_calls = 0

    async def load_snapshot_input(
        self,
        snapshot_id: UUID,
    ) -> PersistedMarketSnapshotInput | None:
        if snapshot_id != SNAPSHOT_ID:
            return None
        return PersistedMarketSnapshotInput(
            candles=tuple(
                candle for series in self.market.detail.series for candle in series.candles
            ),
            payload_sha256="b" * 64,
        )

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        del symbol, timeframe, limit
        self.recent_candle_calls += 1
        return ()


@pytest.mark.asyncio
async def test_persisted_market_capture_excludes_candles_after_run_start() -> None:
    market = _market()
    h1 = next(series for series in market.detail.series if series.timeframe is MarketTimeframe.H1)
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
        reader=StaticMarketReader(market),
    )

    frozen = await capture.capture(ContractSymbol.BTCUSDT, captured_at=NOW)

    assert all(
        candle.close_at <= NOW for series in frozen.detail.series for candle in series.candles
    )


@pytest.mark.asyncio
async def test_persisted_market_capture_uses_immutable_snapshot_input_not_mutable_candles() -> None:
    market = _market()
    reader = ImmutableInputMarketReader(market)
    capture = PersistedAgentMarketCapture(
        capture_service=cast(MarketCaptureService, RawCapture()),
        reader=reader,
    )

    frozen = await capture.capture(ContractSymbol.BTCUSDT, captured_at=NOW)

    assert reader.recent_candle_calls == 0
    assert frozen.snapshot_input_sha256 == "b" * 64
    assert all(series.candles for series in frozen.detail.series)


@pytest.mark.asyncio
async def test_persisted_market_capture_keeps_snapshot_when_context_is_unavailable() -> None:
    capture = PersistedAgentMarketCapture(
        capture_service=cast(MarketCaptureService, RawCapture()),
        reader=StaticMarketReader(_market()),
        research_context=UnavailableResearchContextCollector(),
    )

    frozen = await capture.capture(ContractSymbol.BTCUSDT, captured_at=NOW)

    assert frozen.research_context is None
    assert frozen.research_context_error is AgentErrorCode.MARKET_CONTEXT_UNAVAILABLE


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
async def test_graph_persists_degraded_for_an_unexpected_market_failure() -> None:
    repository = RecordingRepository()
    market = FakeMarketCapture(_market(), error=RuntimeError("private upstream detail"))
    model = RecordingModel()
    service = AgentResearchService(
        dependencies=AgentResearchDependencies(
            market=market,
            news=FakeNewsIngestion(_collection()),
            model=model,
            repository=repository,
            clock=lambda: NOW,
        )
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.DEGRADED
    assert model.requests == []
    assert repository.creations[0].error_code == "market_research_unavailable"
    assert "private upstream detail" not in repr(repository.creations[0])


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
async def test_graph_persists_degraded_for_an_unexpected_model_failure() -> None:
    repository = RecordingRepository()
    service = _service(
        market=_market(),
        news=_collection(),
        model=RecordingModel([RuntimeError("secret model failure")]),
        repository=repository,
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.DEGRADED
    assert repository.creations[0].error_code == "model_upstream_error"
    assert "secret model failure" not in repr(repository.creations[0])


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
async def test_graph_records_the_frozen_snapshot_input_hash_with_market_evidence() -> None:
    input_sha256 = "c" * 64
    service = _service(
        market=_market(snapshot_input_sha256=input_sha256),
        news=_collection(),
        model=RecordingModel(),
        repository=RecordingRepository(),
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    market_evidence = next(
        evidence for evidence in report.evidence if evidence.source == "binance_usdm_public_rest"
    )
    assert market_evidence.payload["snapshotInputSha256"] == input_sha256


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
async def test_graph_persists_public_context_as_separate_frozen_evidence() -> None:
    repository = RecordingRepository()
    model = RecordingModel()
    report = await _service(
        market=_market(research_context=_research_context()),
        news=_collection(),
        model=model,
        repository=repository,
    ).generate(ContractSymbol.BTCUSDT)

    context_evidence = next(
        evidence
        for evidence in repository.creations[0].evidences
        if evidence.source == "binance_usdm_public_context"
    )

    assert report.status is AnalysisReportStatus.COMPLETED
    context_payload = cast(dict[str, object], context_evidence.payload["context"])
    assert context_payload["fear_greed_value"] == 31
    assert report.agent_analysis is not None
    assert report.agent_analysis.market_metrics is not None
    assert report.agent_analysis.market_metrics.price == Decimal("68000")
    assert report.agent_analysis.market_metrics.fear_greed_value == 31
    assert report.agent_analysis.market_metrics.fear_greed_classification == "Fear"
    assert report.agent_analysis.market_metrics.fear_greed_change_7d == -8
    assert {evidence.source for evidence in model.requests[0].evidences} == {
        "binance_usdm_public_context",
        "binance_usdm_public_rest",
    }


@pytest.mark.asyncio
async def test_graph_completes_with_a_visible_public_context_input_gap() -> None:
    market = _market(
        research_context_error=AgentErrorCode.MARKET_CONTEXT_UNAVAILABLE,
    )
    report = await _service(
        market=market,
        news=_collection(),
        model=RecordingModel(),
        repository=RecordingRepository(),
    ).generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.COMPLETED
    assert report.agent_analysis is not None
    assert "market_context_unavailable" in report.agent_analysis.data_quality.missing_inputs
    assert any("市场上下文" in item for item in report.limitations)
    assert report.agent_analysis.market_metrics is not None
    assert report.agent_analysis.market_metrics.price == Decimal("68000")
    assert report.agent_analysis.market_metrics.fear_greed_value is None
    assert report.agent_analysis.market_metrics.fear_greed_classification is None
    assert report.agent_analysis.market_metrics.fear_greed_change_7d is None


@pytest.mark.asyncio
async def test_graph_caps_model_confidence_at_the_frozen_structure_confidence() -> None:
    market = _market_with_sparse_timeframes()
    repository = RecordingRepository()
    service = _service(
        market=market,
        news=_collection(),
        model=HighConfidenceModel(),
        repository=repository,
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.COMPLETED
    assert report.agent_analysis is not None
    assert report.agent_analysis.confidence == "low"


@pytest.mark.asyncio
async def test_graph_bounds_model_limitations_before_adding_source_coverage_limit() -> None:
    market = _market()
    repository = RecordingRepository()
    service = _service(
        market=market,
        news=_collection(failures=2),
        model=LimitedProposalModel(tuple(f"Model limitation {index}." for index in range(12))),
        repository=repository,
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    assert report.status is AnalysisReportStatus.COMPLETED
    assert report.agent_analysis is not None
    assert len(report.limitations) == 12
    assert any("英文新闻" in limitation for limitation in report.limitations)
    assert repository.creations[0].error_code is None


@pytest.mark.asyncio
async def test_graph_retries_empty_model_output_once_then_persists_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = _record_agent_logs(monkeypatch)
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

    logs = logger.entries
    assert report.status is AnalysisReportStatus.DEGRADED
    assert len(model.requests) == 2
    retry = next(entry for entry in logs if entry["event"] == "agent_model_empty_response_retry")
    assert retry["log_level"] == "info"
    assert retry["attempt"] == 2
    assert retry["error_code"] == "model_empty_response"


@pytest.mark.asyncio
async def test_agent_run_logs_safe_lifecycle_and_node_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = _record_agent_logs(monkeypatch)
    service = _service(
        market=_market(),
        news=_collection(items=(_news_item("safe", "LEAKED_NEWS_BODY"),)),
        model=RecordingModel(),
        repository=RecordingRepository(),
    )

    report = await service.generate(ContractSymbol.BTCUSDT)

    logs = logger.entries
    events = [entry["event"] for entry in logs]
    assert events[0] == "agent_research_started"
    assert "agent_research_completed" in events
    assert events.count("agent_research_node_started") == 5
    assert events.count("agent_research_node_completed") == 5
    assert events.count("agent_research_node_details") == 5
    completed = next(entry for entry in logs if entry["event"] == "agent_research_completed")
    assert completed["analysis_id"] == str(report.analysis_id)
    assert completed["symbol"] == "BTCUSDT"
    assert completed["report_id"] == str(report.id)
    assert completed["status"] == "completed"
    run_details = next(
        entry
        for entry in logs
        if entry["event"] == "agent_research_run_details" and entry["phase"] == "completed"
    )
    assert isinstance(run_details["duration_ms"], int)
    assert run_details["duration_ms"] >= 0
    node_details = [
        entry
        for entry in logs
        if entry["event"] == "agent_research_node_details" and entry["phase"] == "completed"
    ]
    assert all(isinstance(entry["duration_ms"], int) for entry in node_details)
    serialized = repr(logs)
    assert "LEAKED_NEWS_BODY" not in serialized
    assert "api_key" not in serialized.lower()


@pytest.mark.asyncio
async def test_agent_run_logs_safe_node_and_run_failure_when_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = _record_agent_logs(monkeypatch)
    service = AgentResearchService(
        dependencies=AgentResearchDependencies(
            market=FakeMarketCapture(_market()),
            news=FakeNewsIngestion(_collection()),
            model=RecordingModel(),
            repository=FailingRepository(),
            clock=lambda: NOW,
        )
    )

    with pytest.raises(RuntimeError):
        await service.generate(ContractSymbol.BTCUSDT)

    logs = logger.entries
    node_failure = next(entry for entry in logs if entry["event"] == "agent_research_node_failed")
    assert node_failure["log_level"] == "info"
    assert node_failure["node_name"] == "validate_and_persist_report"
    run_failure = next(entry for entry in logs if entry["event"] == "agent_research_failed")
    assert run_failure["log_level"] == "info"
    node_failure_details = next(
        entry
        for entry in logs
        if entry["event"] == "agent_research_node_details" and entry["phase"] == "failed"
    )
    assert node_failure_details["error_type"] == "RuntimeError"
    assert isinstance(node_failure_details["duration_ms"], int)
    run_failure_details = next(
        entry
        for entry in logs
        if entry["event"] == "agent_research_run_details" and entry["phase"] == "failed"
    )
    assert run_failure_details["error_type"] == "RuntimeError"
    serialized = repr(logs)
    assert "LEAKED_DATABASE_URL" not in serialized


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
async def test_graph_uses_supplied_analysis_id_as_checkpoint_thread_without_research_payloads(
) -> None:
    checkpointer = InMemorySaver()
    service = _service(
        market=_market(),
        news=_collection(items=(_news_item("safe", "LEAKED_NEWS_BODY"),)),
        model=RecordingModel(),
        repository=RecordingRepository(),
        checkpointer=checkpointer,
    )

    report = await service.generate(ContractSymbol.BTCUSDT, analysis_id=ANALYSIS_ID)
    checkpoints = tuple(checkpointer.list({"configurable": {"thread_id": str(ANALYSIS_ID)}}))
    serialized = repr(checkpoints).casefold()

    assert report.analysis_id == ANALYSIS_ID
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


def _market(
    *,
    captured_at: datetime = NOW,
    snapshot_input_sha256: str | None = None,
    research_context: PublicResearchContext | None = None,
    research_context_error: AgentErrorCode | None = None,
) -> CapturedAgentMarket:
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
        snapshot_input_sha256=snapshot_input_sha256,
        research_context=research_context,
        research_context_error=research_context_error,
    )


def _research_context() -> PublicResearchContext:
    return PublicResearchContext(
        symbol=ContractSymbol.BTCUSDT,
        basis_rate=Decimal("0.0004"),
        long_short_account_ratio=Decimal("1.2345"),
        taker_buy_sell_ratio=Decimal("0.8765"),
        fear_greed_value=31,
        fear_greed_classification="Fear",
        fear_greed_change_7d=-8,
        fear_greed_7d_start_at=NOW - timedelta(days=7),
        freshness=FreshnessStatus.FRESH,
        observed_at=NOW,
        fetched_at=NOW,
    )


def _market_with_sparse_timeframes() -> CapturedAgentMarket:
    market = _market()
    detail = market.detail.model_copy(
        update={
            "series": tuple(
                CandleSeries(
                    timeframe=series.timeframe,
                    candles=(
                        series.candles
                        if series.timeframe is MarketTimeframe.H1
                        else series.candles[-49:]
                    ),
                )
                for series in market.detail.series
            )
        }
    )
    return market.__class__(
        snapshot_id=market.snapshot_id,
        snapshot=market.snapshot,
        detail=detail,
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


def _proposal(
    evidence_id: UUID,
    *,
    confidence: str = "low",
    limitations: tuple[str, ...] = (),
) -> AgentAnalysisProposal:
    research_text = _research_text
    return AgentAnalysisProposal(
        outlook=MarketOutlook.NEUTRAL,
        confidence=cast(Literal["low", "medium", "high"], confidence),
        market_overview=MarketOverview(
            headline="流动性与情绪分歧下的市场概况",
            summary=research_text("市场概况", 330),
            evidence_ids=(evidence_id,),
        ),
        short_term=ResearchPerspective(
            horizon="short_term",
            outlook=MarketOutlook.NEUTRAL,
            heading="短期结构等待成交与情绪共同确认",
            thesis=research_text("短期观点", 460),
            drivers=(
                EvidenceBackedClaim(
                    label="冻结证据驱动",
                    detail=research_text("短期驱动", 300),
                    evidence_ids=(evidence_id,),
                ),
            ),
            invalidation=(
                RiskAndInvalidation(
                    condition="关键公开指标方向改变。",
                    impact="需要重新评估观点。",
                    evidence_ids=(evidence_id,),
                ),
            ),
        ),
        long_term=ResearchPerspective(
            horizon="long_term",
            outlook=MarketOutlook.NEUTRAL,
            heading="长期方向仍需宏观与流动性证据复核",
            thesis=research_text("长期观点", 460),
            drivers=(
                EvidenceBackedClaim(
                    label="冻结证据驱动",
                    detail=research_text("长期驱动", 300),
                    evidence_ids=(evidence_id,),
                ),
            ),
            invalidation=(
                RiskAndInvalidation(
                    condition="关键公开指标方向改变。",
                    impact="需要重新评估观点。",
                    evidence_ids=(evidence_id,),
                ),
            ),
        ),
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
        limitations=limitations,
    )


def _research_text(label: str, length: int) -> str:
    unit = f"{label}围绕冻结价格结构、公开衍生品指标、情绪读数与英文新闻交叉复核，"
    return (unit * ((length // len(unit)) + 1))[:length]
