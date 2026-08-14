from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import JsonValue

from app.agent.contracts import AgentErrorCode, AgentRunState
from app.agent.graph import build_agent_graph
from app.agent.market_structure import MarketStructure, calculate_market_structure
from app.agent.model import (
    AgentAnalysisProposal,
    ModelEvidence,
    ModelEvidenceKind,
    ModelOutputError,
    ResearchLanguageModel,
    ResearchModelRequest,
)
from app.market.capture import MarketCaptureService
from app.market.contracts import (
    CandleSeries,
    ContractSymbol,
    FreshnessStatus,
    MarketDataUnavailableError,
    MarketDetail,
    MarketTimeframe,
)
from app.market.research import (
    PersistedMarketSnapshot,
    PersistedMarketSnapshotInput,
)
from app.market.research_context import PublicResearchContext
from app.news.contracts import ALLOWED_NEWS_SOURCES, NewsItemDraft
from app.news.service import NewsCollection
from app.reports.contracts import (
    AgentAnalysis,
    AgentDataQuality,
    AgentReportCreation,
    AnalysisEvidenceDraft,
    AnalysisReportDraft,
    AnalysisReportStatus,
    MarketOutlook,
    PersistedAnalysisReport,
    ReportGeneratorKind,
    report_payload_sha256,
)

SourceCoverage = Literal["none", "partial", "complete"]

_TIMEFRAMES = (
    MarketTimeframe.M15,
    MarketTimeframe.H1,
    MarketTimeframe.H4,
    MarketTimeframe.D1,
)
_CANDLE_LIMIT = 200
_FRESHNESS_THRESHOLD = timedelta(minutes=2)
_NEWS_WINDOW = timedelta(days=3)
_MAX_NEWS_EVIDENCE = 28
_MARKET_SOURCE_URL = "https://www.binance.com/en/futures/"
_MARKET_CONTEXT_SOURCE_URL = "https://fapi.binance.com/"
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CapturedAgentMarket:
    """Frozen Task 4 market snapshot plus closed series, kept out of graph state."""

    snapshot_id: UUID
    snapshot: PersistedMarketSnapshot
    detail: MarketDetail
    snapshot_input_sha256: str | None = None
    research_context: PublicResearchContext | None = None
    research_context_error: AgentErrorCode | None = None


class AgentMarketCapture(Protocol):
    async def capture(
        self,
        symbol: ContractSymbol,
        *,
        captured_at: datetime,
    ) -> CapturedAgentMarket: ...


class AgentSnapshotInputReader(Protocol):
    async def load_snapshot(self, snapshot_id: UUID) -> PersistedMarketSnapshot | None: ...

    async def load_snapshot_input(
        self,
        snapshot_id: UUID,
    ) -> PersistedMarketSnapshotInput | None: ...


class AgentNewsCollector(Protocol):
    async def collect(
        self,
        symbol: ContractSymbol,
        *,
        since: datetime,
        until: datetime,
    ) -> NewsCollection: ...


class AgentResearchContextCollector(Protocol):
    async def collect(
        self,
        symbol: ContractSymbol,
        *,
        captured_at: datetime,
    ) -> PublicResearchContext: ...


class AgentReportPersister(Protocol):
    async def persist_agent(
        self,
        creation: AgentReportCreation,
    ) -> PersistedAnalysisReport: ...


class PersistedAgentMarketCapture:
    """Composes Task 4 capture/read ports without accessing a market gateway directly."""

    def __init__(
        self,
        *,
        capture_service: MarketCaptureService,
        reader: AgentSnapshotInputReader,
        research_context: AgentResearchContextCollector | None = None,
    ) -> None:
        self._capture_service = capture_service
        self._reader = reader
        self._research_context = research_context

    async def capture(
        self,
        symbol: ContractSymbol,
        *,
        captured_at: datetime,
    ) -> CapturedAgentMarket:
        _require_utc(captured_at)
        snapshot_id = await self._capture_service.capture_symbol(
            symbol,
            captured_at=captured_at,
        )
        snapshot = await self._reader.load_snapshot(snapshot_id)
        if snapshot is None or snapshot.summary.symbol is not symbol:
            raise MarketDataUnavailableError(
                AgentErrorCode.MARKET_RESEARCH_UNAVAILABLE.value,
                "冻结市场快照不可用",
            )
        snapshot_input = await self._reader.load_snapshot_input(snapshot_id)
        if snapshot_input is None:
            raise MarketDataUnavailableError(
                AgentErrorCode.MARKET_RESEARCH_UNAVAILABLE.value,
                "冻结市场 K 线输入不可用",
            )
        series = tuple(
            [
                self._closed_series(
                    snapshot_input,
                    symbol,
                    timeframe,
                    captured_at=captured_at,
                )
                for timeframe in _TIMEFRAMES
            ]
        )
        context: PublicResearchContext | None = None
        context_error: AgentErrorCode | None = None
        if self._research_context is not None:
            try:
                context = await self._research_context.collect(
                    symbol,
                    captured_at=captured_at,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                context_error = AgentErrorCode.MARKET_CONTEXT_UNAVAILABLE
        return CapturedAgentMarket(
            snapshot_id=snapshot_id,
            snapshot=snapshot,
            detail=MarketDetail(summary=snapshot.summary, series=series),
            snapshot_input_sha256=snapshot_input.payload_sha256,
            research_context=context,
            research_context_error=context_error,
        )

    def _closed_series(
        self,
        snapshot_input: PersistedMarketSnapshotInput,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        *,
        captured_at: datetime,
    ) -> CandleSeries:
        candles = tuple(
            candle
            for candle in snapshot_input.candles
            if candle.symbol is symbol and candle.timeframe is timeframe
        )
        if any(
            candle.symbol is not symbol or candle.timeframe is not timeframe for candle in candles
        ):
            raise MarketDataUnavailableError(
                AgentErrorCode.MARKET_DATA_INVALID.value,
                "冻结市场 K 线标的或周期无效",
            )
        closed = tuple(
            candle
            for candle in candles
            if candle.close_at <= captured_at
            and candle.symbol is symbol
            and candle.timeframe is timeframe
        )
        if not closed:
            raise MarketDataUnavailableError(
                AgentErrorCode.MARKET_CLOSED_CANDLE_MISSING.value,
                "冻结市场缺少已收盘 K 线",
            )
        # Later rows are never eligible for this manual analysis run.
        return CandleSeries(
            timeframe=timeframe,
            candles=tuple(sorted(closed, key=lambda candle: candle.open_at)),
        )


@dataclass(frozen=True)
class AgentResearchDependencies:
    market: AgentMarketCapture
    news: AgentNewsCollector
    model: ResearchLanguageModel | None
    repository: AgentReportPersister
    clock: Callable[[], datetime]


class AgentResearchService:
    """Runs one manually requested, evidence-bound 1–3 day market study."""

    def __init__(
        self,
        *,
        dependencies: AgentResearchDependencies,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
    ) -> None:
        self._dependencies = dependencies
        self._checkpointer = checkpointer

    async def generate(self, symbol: ContractSymbol) -> PersistedAnalysisReport:
        started_at = _require_utc(self._dependencies.clock())
        run = _AgentResearchRun(
            dependencies=self._dependencies,
            analysis_id=uuid4(),
            symbol=symbol,
            started_at=started_at,
        )
        graph = build_agent_graph(run, checkpointer=self._checkpointer)
        run_started_at = perf_counter()
        logger.info(
            "agent_research_started",
            analysis_id=str(run.analysis_id),
            symbol=symbol.value,
        )
        try:
            await graph.ainvoke(
                AgentRunState(
                    analysis_id=run.analysis_id,
                    symbol=symbol,
                    started_at=started_at,
                ),
                config={"configurable": {"thread_id": str(run.analysis_id)}},
            )
            if run.persisted_report is None:
                raise RuntimeError("Agent 图未持久化终态报告")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.info(
                "agent_research_failed",
                analysis_id=str(run.analysis_id),
                symbol=symbol.value,
            )
            logger.debug(
                "agent_research_run_details",
                analysis_id=str(run.analysis_id),
                phase="failed",
                error_type=type(error).__name__,
                duration_ms=_duration_ms(run_started_at),
            )
            raise
        logger.info(
            "agent_research_completed",
            analysis_id=str(run.analysis_id),
            symbol=symbol.value,
            report_id=str(run.persisted_report.id),
            status=run.persisted_report.status.value,
        )
        logger.debug(
            "agent_research_run_details",
            analysis_id=str(run.analysis_id),
            phase="completed",
            duration_ms=_duration_ms(run_started_at),
        )
        return run.persisted_report


@dataclass(frozen=True)
class _FrozenEvidence:
    id: UUID
    kind: ModelEvidenceKind
    source: str
    source_url: str
    observed_at: datetime
    fetched_at: datetime
    summary: str
    content: str
    payload: dict[str, JsonValue]


@dataclass
class _AgentResearchRun:
    dependencies: AgentResearchDependencies
    analysis_id: UUID
    symbol: ContractSymbol
    started_at: datetime
    market: CapturedAgentMarket | None = None
    news: NewsCollection | None = None
    structure: MarketStructure | None = None
    proposal: AgentAnalysisProposal | None = None
    degraded_error: AgentErrorCode | None = None
    market_evidence: _FrozenEvidence | None = None
    market_context_evidence: _FrozenEvidence | None = None
    news_evidence: tuple[_FrozenEvidence, ...] = ()
    persisted_report: PersistedAnalysisReport | None = None

    async def collect_market(self, state: AgentRunState) -> dict[str, object]:
        try:
            market = await self.dependencies.market.capture(
                state.symbol,
                captured_at=self.started_at,
            )
            self._validate_market(market, state.symbol)
            self.market = market
            self.market_evidence = _market_evidence(market)
            self.market_context_evidence = (
                None
                if market.research_context is None
                else _market_context_evidence(market.research_context)
            )
            return self._update(
                state,
                node_name="collect_market",
                snapshot_id=market.snapshot_id,
                evidence_ids=self._evidence_ids(),
                error_code=market.research_context_error,
            )
        except MarketDataUnavailableError as error:
            code = _safe_error_code(error.code)
        except (TypeError, ValueError):
            code = AgentErrorCode.MARKET_DATA_INVALID
        except asyncio.CancelledError:
            raise
        except Exception:
            code = AgentErrorCode.MARKET_RESEARCH_UNAVAILABLE
        self.degraded_error = code
        return self._update(state, node_name="collect_market", error_code=code)

    async def collect_news(self, state: AgentRunState) -> dict[str, object]:
        try:
            self.news = await self.dependencies.news.collect(
                state.symbol,
                since=self.started_at - _NEWS_WINDOW,
                until=self.started_at,
            )
        except Exception:
            self.news = NewsCollection(
                items=(),
                source_count=0,
                successful_source_count=0,
                failed_source_count=0,
                error_codes=(),
            )
            return self._update(
                state,
                node_name="collect_news",
                error_code=AgentErrorCode.NEWS_SOURCE_FAILED,
            )

        self.news_evidence = _news_evidences(self.news.items)
        error_code = AgentErrorCode.NEWS_SOURCE_FAILED if self.news.failed_source_count else None
        return self._update(
            state,
            node_name="collect_news",
            evidence_ids=self._evidence_ids(),
            news_source_count=self.news.source_count,
            news_success_count=self.news.successful_source_count,
            news_failure_count=self.news.failed_source_count,
            error_code=error_code,
        )

    async def compute_structure(self, state: AgentRunState) -> dict[str, object]:
        if self.market is None:
            return self._update(state, node_name="compute_structure")
        if _is_stale(self.market, self.started_at):
            self.degraded_error = AgentErrorCode.MARKET_STALE
            return self._update(
                state,
                node_name="compute_structure",
                error_code=self.degraded_error,
            )
        if not _has_required_closed_series(self.market.detail, self.started_at):
            self.degraded_error = AgentErrorCode.MARKET_CLOSED_CANDLE_MISSING
            return self._update(
                state,
                node_name="compute_structure",
                error_code=self.degraded_error,
            )
        try:
            self.structure = calculate_market_structure(
                self.market.detail,
                captured_at=self.started_at,
            )
        except (TypeError, ValueError):
            self.degraded_error = AgentErrorCode.MARKET_DATA_INVALID
            return self._update(
                state,
                node_name="compute_structure",
                error_code=self.degraded_error,
            )
        if self.dependencies.model is None:
            self.degraded_error = AgentErrorCode.MODEL_NOT_CONFIGURED
            return self._update(
                state,
                node_name="compute_structure",
                error_code=self.degraded_error,
            )
        return self._update(
            state,
            node_name="compute_structure",
            evidence_ids=self._evidence_ids(),
        )

    def evidence_gate(
        self,
        state: AgentRunState,
    ) -> Literal["model", "degraded"]:
        del state
        return "degraded" if self.degraded_error is not None else "model"

    async def generate_model_report(self, state: AgentRunState) -> dict[str, object]:
        model = self.dependencies.model
        if model is None or self.structure is None:
            self.degraded_error = AgentErrorCode.MODEL_NOT_CONFIGURED
            return self._update(
                state,
                node_name="generate_model_report",
                error_code=self.degraded_error,
            )
        request = ResearchModelRequest(
            symbol=self.symbol,
            structure=self.structure,
            evidences=tuple(
                ModelEvidence(
                    id=evidence.id,
                    kind=evidence.kind,
                    source=evidence.source,
                    observed_at=evidence.observed_at,
                    content=evidence.content,
                )
                for evidence in self._evidences()
            ),
        )
        try:
            proposal = await self._generate_with_one_empty_retry(model, request)
            if not _proposal_uses_known_evidence(proposal, self._evidence_ids()):
                self.degraded_error = AgentErrorCode.MODEL_INVALID_EVIDENCE
            else:
                self.proposal = proposal
        except ModelOutputError as error:
            self.degraded_error = _safe_error_code(error.code)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.degraded_error = AgentErrorCode.MODEL_UPSTREAM_ERROR
        if self.degraded_error is not None:
            return self._update(
                state,
                node_name="generate_model_report",
                error_code=self.degraded_error,
            )
        return self._update(state, node_name="generate_model_report")

    async def persist_degraded_report(self, state: AgentRunState) -> dict[str, object]:
        await self._persist(completed=False)
        return self._update(state, node_name="persist_degraded_report")

    async def validate_and_persist_report(self, state: AgentRunState) -> dict[str, object]:
        await self._persist(completed=self.proposal is not None and self.degraded_error is None)
        return self._update(state, node_name="validate_and_persist_report")

    async def _generate_with_one_empty_retry(
        self,
        model: ResearchLanguageModel,
        request: ResearchModelRequest,
    ) -> AgentAnalysisProposal:
        try:
            return await model.generate(request)
        except ModelOutputError as error:
            if error.code != AgentErrorCode.MODEL_EMPTY_RESPONSE.value:
                raise
        logger.info(
            "agent_model_empty_response_retry",
            analysis_id=str(self.analysis_id),
            symbol=self.symbol.value,
            attempt=2,
            error_code=AgentErrorCode.MODEL_EMPTY_RESPONSE.value,
        )
        return await model.generate(request)

    async def _persist(self, *, completed: bool) -> None:
        completed_at = _require_utc(self.dependencies.clock())
        report_id = uuid4()
        evidence = tuple(
            _to_report_evidence(item, report_id=report_id, symbol=self.symbol)
            for item in self._evidences()
        )
        report = (
            _completed_report(
                report_id=report_id,
                analysis_id=self.analysis_id,
                symbol=self.symbol,
                generated_at=completed_at,
                data_cutoff_at=_data_cutoff(evidence),
                proposal=self.proposal,
                structure=self.structure,
                news=self.news,
                market=self.market,
            )
            if completed
            else _degraded_report(
                report_id=report_id,
                analysis_id=self.analysis_id,
                symbol=self.symbol,
                generated_at=completed_at,
                data_cutoff_at=_data_cutoff(evidence),
                error=self.degraded_error,
            )
        )
        agent_analysis = _agent_analysis(
            completed=completed,
            proposal=self.proposal,
            structure=self.structure,
            news=self.news,
            market=self.market,
            error=self.degraded_error,
        )
        self.persisted_report = await self.dependencies.repository.persist_agent(
            AgentReportCreation(
                report=report,
                evidences=evidence,
                started_at=self.started_at,
                completed_at=completed_at,
                generator_kind=ReportGeneratorKind.LANGGRAPH_DEEPSEEK,
                error_code=None if completed else _error_code_value(self.degraded_error),
                agent_analysis=agent_analysis,
            )
        )

    def _validate_market(
        self,
        market: CapturedAgentMarket,
        symbol: ContractSymbol,
    ) -> None:
        if (
            market.snapshot.summary.symbol is not symbol
            or market.detail.summary.symbol is not symbol
            or (
                market.research_context is not None
                and market.research_context.symbol is not symbol
            )
        ):
            raise ValueError("market symbol mismatch")
        if market.research_context is not None and market.research_context_error is not None:
            raise ValueError("market context state mismatch")

    def _evidences(self) -> tuple[_FrozenEvidence, ...]:
        market_evidence = () if self.market_evidence is None else (self.market_evidence,)
        context_evidence = (
            () if self.market_context_evidence is None else (self.market_context_evidence,)
        )
        return market_evidence + context_evidence + self.news_evidence

    def _evidence_ids(self) -> tuple[UUID, ...]:
        return tuple(evidence.id for evidence in self._evidences())

    def _update(
        self,
        state: AgentRunState,
        *,
        node_name: str,
        snapshot_id: UUID | None = None,
        evidence_ids: tuple[UUID, ...] | None = None,
        news_source_count: int | None = None,
        news_success_count: int | None = None,
        news_failure_count: int | None = None,
        error_code: AgentErrorCode | None = None,
    ) -> dict[str, object]:
        errors = state.error_codes
        if error_code is not None and error_code not in errors:
            errors = (*errors, error_code)
        resolved_snapshot_id = state.snapshot_id if snapshot_id is None else snapshot_id
        resolved_evidence_ids = state.evidence_ids if evidence_ids is None else evidence_ids
        resolved_news_source_count = (
            state.news_source_count if news_source_count is None else news_source_count
        )
        resolved_news_success_count = (
            state.news_success_count if news_success_count is None else news_success_count
        )
        resolved_news_failure_count = (
            state.news_failure_count if news_failure_count is None else news_failure_count
        )
        return {
            "snapshot_id": resolved_snapshot_id,
            "evidence_ids": resolved_evidence_ids,
            "news_source_count": resolved_news_source_count,
            "news_success_count": resolved_news_success_count,
            "news_failure_count": resolved_news_failure_count,
            "node_name": node_name,
            "error_codes": errors,
        }


def _duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1_000))


def _market_evidence(market: CapturedAgentMarket) -> _FrozenEvidence:
    summary = market.snapshot.summary
    payload: dict[str, JsonValue] = {
        "summary": summary.model_dump(mode="json"),
        "capturedAt": market.snapshot.captured_at.isoformat(),
    }
    if market.snapshot_input_sha256 is not None:
        payload["snapshotInputSha256"] = market.snapshot_input_sha256
    return _FrozenEvidence(
        id=uuid4(),
        kind=ModelEvidenceKind.MARKET,
        source=summary.freshness.source,
        source_url=f"{_MARKET_SOURCE_URL}{summary.symbol.value}",
        observed_at=summary.freshness.observed_at,
        fetched_at=summary.freshness.fetched_at,
        summary="冻结的公开市场快照。",
        content=(
            f"Frozen market snapshot for {summary.symbol.value}: price={summary.price}, "
            f"change_24h={summary.change_24h}, volume_24h={summary.volume_24h}, "
            f"funding_rate={summary.funding_rate}, open_interest={summary.open_interest}."
        ),
        payload=payload,
    )


def _news_evidences(items: tuple[NewsItemDraft, ...]) -> tuple[_FrozenEvidence, ...]:
    unique: dict[str, NewsItemDraft] = {}
    for item in items:
        unique.setdefault(item.deduplication_key, item)
    return tuple(_news_evidence(item) for item in tuple(unique.values())[:_MAX_NEWS_EVIDENCE])


def _market_context_evidence(context: PublicResearchContext) -> _FrozenEvidence:
    payload: dict[str, JsonValue] = {
        "context": context.model_dump(mode="json"),
    }
    return _FrozenEvidence(
        id=uuid4(),
        kind=ModelEvidenceKind.MARKET,
        source="binance_usdm_public_context",
        source_url=_MARKET_CONTEXT_SOURCE_URL,
        observed_at=context.observed_at,
        fetched_at=context.fetched_at,
        summary="冻结的公开衍生品指标与市场情绪上下文。",
        content=(
            "Frozen public market context: "
            f"basis_rate={context.basis_rate}, "
            f"long_short_account_ratio={context.long_short_account_ratio}, "
            f"taker_buy_sell_ratio={context.taker_buy_sell_ratio}, "
            f"fear_greed_value={context.fear_greed_value}, "
            f"fear_greed_classification={context.fear_greed_classification}, "
            f"fear_greed_change_7d={context.fear_greed_change_7d}, "
            f"fear_greed_7d_start_at={context.fear_greed_7d_start_at.isoformat()}."
        ),
        payload=payload,
    )


def _news_evidence(item: NewsItemDraft) -> _FrozenEvidence:
    source = ALLOWED_NEWS_SOURCES[item.source_id]
    source_url = str(item.canonical_url) if item.canonical_url is not None else str(source.feed_url)
    payload: dict[str, JsonValue] = {
        "news": {
            "sourceId": item.source_id,
            "sourceTier": item.source_tier.value,
            "eventCategory": item.event_category.value,
            "title": item.title,
            "summary": item.summary,
        },
    }
    return _FrozenEvidence(
        id=uuid4(),
        kind=ModelEvidenceKind.NEWS,
        source=item.source_id,
        source_url=source_url,
        observed_at=item.published_at,
        fetched_at=item.fetched_at,
        summary=f"{item.source_id} 的英文新闻快照。",
        content=(
            "UNTRUSTED_NEWS_CONTENT\n"
            f"source={item.source_id}\n"
            f"title={item.title}\n"
            f"summary={item.summary}"
        ),
        payload=payload,
    )


def _to_report_evidence(
    evidence: _FrozenEvidence,
    *,
    report_id: UUID,
    symbol: ContractSymbol,
) -> AnalysisEvidenceDraft:
    return AnalysisEvidenceDraft(
        id=evidence.id,
        report_id=report_id,
        symbol=symbol,
        source=evidence.source,
        source_url=evidence.source_url,
        observed_at=evidence.observed_at,
        fetched_at=evidence.fetched_at,
        summary=evidence.summary,
        payload=evidence.payload,
        payload_sha256=report_payload_sha256(evidence.payload),
    )


def _completed_report(
    *,
    report_id: UUID,
    analysis_id: UUID,
    symbol: ContractSymbol,
    generated_at: datetime,
    data_cutoff_at: datetime | None,
    proposal: AgentAnalysisProposal | None,
    structure: MarketStructure | None,
    news: NewsCollection | None,
    market: CapturedAgentMarket | None,
) -> AnalysisReportDraft:
    if proposal is None or structure is None or market is None:
        raise RuntimeError("completed agent report requires frozen market and model proposal")
    narrative = proposal.narrative
    limitations = _limitations(news, proposal.limitations, market=market)
    return AnalysisReportDraft(
        id=report_id,
        analysis_id=analysis_id,
        symbol=symbol,
        status=AnalysisReportStatus.COMPLETED,
        title=f"{symbol.value} {narrative.market_overview.headline}",
        summary=narrative.market_overview.summary,
        facts=(f"冻结市场快照价格：{market.snapshot.summary.price}。",),
        inferences=(narrative.short_term.heading, narrative.long_term.heading),
        risks=("公开市场环境可能快速变化，需重新抓取后复核。",),
        limitations=limitations,
        generated_at=generated_at,
        data_cutoff_at=data_cutoff_at,
    )


def _degraded_report(
    *,
    report_id: UUID,
    analysis_id: UUID,
    symbol: ContractSymbol,
    generated_at: datetime,
    data_cutoff_at: datetime | None,
    error: AgentErrorCode | None,
) -> AnalysisReportDraft:
    return AnalysisReportDraft(
        id=report_id,
        analysis_id=analysis_id,
        symbol=symbol,
        status=AnalysisReportStatus.DEGRADED,
        title=f"{symbol.value} 市场研究已降级",
        summary="当前证据不足，无法形成市场研究结论。",
        facts=(),
        inferences=(),
        risks=(_degraded_risk(error),),
        limitations=(
            f"限制原因：{_error_code_value(error)}。",
            "仅保留可审计的冻结证据，未形成市场结论。",
        ),
        generated_at=generated_at,
        data_cutoff_at=data_cutoff_at,
    )


def _agent_analysis(
    *,
    completed: bool,
    proposal: AgentAnalysisProposal | None,
    structure: MarketStructure | None,
    news: NewsCollection | None,
    market: CapturedAgentMarket | None,
    error: AgentErrorCode | None,
) -> AgentAnalysis:
    freshness = (
        FreshnessStatus.MISSING if market is None else market.snapshot.summary.freshness.status
    )
    if not completed or proposal is None or structure is None:
        return AgentAnalysis(
            horizon="1_to_3_days",
            outlook=MarketOutlook.NEUTRAL,
            confidence="low",
            support_zones=(),
            resistance_zones=(),
            catalysts=(),
            risks_and_invalidation=(),
            data_quality=AgentDataQuality(
                freshness=freshness,
                missing_inputs=(_error_code_value(error),),
                source_coverage=_source_coverage(news),
            ),
            limitations=(f"{_error_code_value(error)}：未形成市场结论。",),
        )
    return AgentAnalysis(
        horizon=proposal.horizon,
        outlook=proposal.outlook,
        confidence=_bounded_confidence(proposal.confidence, structure.confidence),
        trend_alignment=structure.trend_alignment,
        support_zones=structure.support_zones,
        resistance_zones=structure.resistance_zones,
        catalysts=proposal.catalysts,
        risks_and_invalidation=proposal.risks_and_invalidation,
        data_quality=AgentDataQuality(
            freshness=freshness,
            missing_inputs=_missing_inputs(news, market),
            source_coverage=_source_coverage(news),
        ),
        limitations=_limitations(news, proposal.limitations, market=market),
        narrative=proposal.narrative,
    )


def _is_stale(market: CapturedAgentMarket, started_at: datetime) -> bool:
    return (
        market.snapshot.summary.freshness.status is not FreshnessStatus.FRESH
        or started_at - market.snapshot.captured_at > _FRESHNESS_THRESHOLD
    )


def _has_required_closed_series(detail: MarketDetail, captured_at: datetime) -> bool:
    by_timeframe = {series.timeframe: series for series in detail.series}
    return all(
        timeframe in by_timeframe
        and any(candle.close_at <= captured_at for candle in by_timeframe[timeframe].candles)
        for timeframe in _TIMEFRAMES
    )


def _proposal_uses_known_evidence(
    proposal: AgentAnalysisProposal,
    evidence_ids: tuple[UUID, ...],
) -> bool:
    known = set(evidence_ids)
    referenced = {
        evidence_id
        for item in (
            *proposal.catalysts,
            *proposal.risks_and_invalidation,
            proposal.market_overview,
            *proposal.short_term.drivers,
            *proposal.short_term.invalidation,
            *proposal.long_term.drivers,
            *proposal.long_term.invalidation,
        )
        for evidence_id in item.evidence_ids
    }
    return bool(referenced) and referenced <= known


def _source_coverage(news: NewsCollection | None) -> SourceCoverage:
    if news is None or news.successful_source_count == 0:
        return "none"
    return "partial" if news.failed_source_count else "complete"


def _limitations(
    news: NewsCollection | None,
    proposal_limitations: tuple[str, ...],
    *,
    market: CapturedAgentMarket | None,
) -> tuple[str, ...]:
    limitations = list(dict.fromkeys(proposal_limitations))
    input_limits: list[str] = []
    if _source_coverage(news) == "none":
        input_limits.append("英文新闻来源暂不可用，报告仅基于冻结公开行情。")
    elif _source_coverage(news) == "partial":
        input_limits.append("部分英文新闻来源不可用，来源覆盖不完整。")
    if (
        market is not None
        and market.research_context_error is AgentErrorCode.MARKET_CONTEXT_UNAVAILABLE
    ):
        input_limits.append("公开市场上下文暂不可用，未纳入衍生品与情绪指标。")
    return tuple((*limitations[: 12 - len(input_limits)], *input_limits))


def _missing_inputs(
    news: NewsCollection | None,
    market: CapturedAgentMarket | None,
) -> tuple[str, ...]:
    missing = [] if _source_coverage(news) != "none" else ["english_news"]
    if (
        market is not None
        and market.research_context_error is AgentErrorCode.MARKET_CONTEXT_UNAVAILABLE
    ):
        missing.append(AgentErrorCode.MARKET_CONTEXT_UNAVAILABLE.value)
    return tuple(missing)


def _bounded_confidence(
    proposed: Literal["low", "medium", "high"],
    deterministic: Literal["low", "medium", "high"],
) -> Literal["low", "medium", "high"]:
    return (
        proposed if _CONFIDENCE_RANK[proposed] <= _CONFIDENCE_RANK[deterministic] else deterministic
    )


def _data_cutoff(evidence: tuple[AnalysisEvidenceDraft, ...]) -> datetime | None:
    return None if not evidence else min(item.observed_at for item in evidence)


def _safe_error_code(value: str) -> AgentErrorCode:
    try:
        return AgentErrorCode(value)
    except ValueError:
        return AgentErrorCode.MARKET_RESEARCH_UNAVAILABLE


def _error_code_value(error: AgentErrorCode | None) -> str:
    return AgentErrorCode.MARKET_RESEARCH_UNAVAILABLE.value if error is None else error.value


def _degraded_risk(error: AgentErrorCode | None) -> str:
    if error is AgentErrorCode.MARKET_STALE:
        return "市场数据已过期，当前无法形成市场研究结论。"
    if error is AgentErrorCode.MODEL_NOT_CONFIGURED:
        return "研究模型当前不可用，未形成市场结论。"
    if error in {
        AgentErrorCode.MODEL_TIMEOUT,
        AgentErrorCode.MODEL_UPSTREAM_ERROR,
        AgentErrorCode.MODEL_TRANSPORT_ERROR,
        AgentErrorCode.MODEL_INVALID_RESPONSE,
        AgentErrorCode.MODEL_EMPTY_RESPONSE,
        AgentErrorCode.MODEL_INVALID_EVIDENCE,
    }:
        return "研究模型未返回可验证结论，未形成市场结论。"
    return "冻结市场证据不可用，当前无法形成市场研究结论。"


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("Agent 运行时间必须是 UTC 且带时区")
    return value.astimezone(UTC)
