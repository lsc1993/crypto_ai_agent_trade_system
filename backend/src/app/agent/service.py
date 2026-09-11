"""Agent 市场研究应用服务。

数据流：采集并冻结行情/新闻/公开上下文 → 计算技术结构 → 构造最小证据请求 →
验证模型引用 → 持久化完成或降级报告。所有异常都归一化为可审计的错误码。
"""

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
from app.agent.evidence import FrozenResearchEvidence as _FrozenEvidence
from app.agent.factor_collection import (
    EtfFlowReader,
    FundingHistoryReader,
    collect_etf,
    collect_funding,
)
from app.agent.factors import POLICY_SOURCES, apply_interpretations, policy_topic, select_news
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
    FrozenMarketMetrics,
    MarketOutlook,
    ModelValidationFailure,
    PersistedAnalysisReport,
    ReportGeneratorKind,
    report_payload_sha256,
)
from app.reports.factors import FactorAnalysis

SourceCoverage = Literal["none", "partial", "complete"]

_TIMEFRAMES = (
    MarketTimeframe.M15,
    MarketTimeframe.H1,
    MarketTimeframe.H4,
    MarketTimeframe.D1,
)
_CANDLE_LIMIT = 200
_FRESHNESS_THRESHOLD = timedelta(minutes=2)
_NEWS_WINDOW = timedelta(days=7)
_MAX_NEWS_EVIDENCE = 26
_MARKET_SOURCE_URL = "https://www.binance.com/en/futures/"
_MARKET_CONTEXT_SOURCE_URL = "https://fapi.binance.com/"
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CapturedAgentMarket:
    """一次 Agent 运行使用的冻结行情摘要、已收盘 K 线和可选公开上下文。"""

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
    """组合采集和读取端口，不让 Agent 服务直接访问市场网关。"""

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
        """采集一个标的并从刚持久化的快照重建完整研究输入。

        不直接把网关响应交给后续节点，确保市场结构、模型证据和最终报告都引用同一
        快照 ID 与输入哈希。
        """
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
        # 研究结构需要完整的冻结序列；仅从刚持久化的输入读取，避免随后行情变化影响本次运行。
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
        """从冻结输入筛选一个周期的已收盘 K 线，并按开盘时间排序。"""
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
    funding: FundingHistoryReader | None = None
    etf: EtfFlowReader | None = None


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

    async def generate(
        self,
        symbol: ContractSymbol,
        *,
        analysis_id: UUID | None = None,
    ) -> PersistedAnalysisReport:
        """为手动请求运行完整研究图，并返回已持久化的最终或降级报告。

        analysis_id 既是图 checkpoint 的 thread_id，也是整个审计链的关联键；取消会
        原样传播，其他异常保留为日志和调用方可见的失败。
        """
        started_at = _require_utc(self._dependencies.clock())
        # 每次手动请求都是隔离的运行实例，图状态只保存可检查的轻量元数据。
        run = _AgentResearchRun(
            dependencies=self._dependencies,
            analysis_id=uuid4() if analysis_id is None else analysis_id,
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


@dataclass
class _AgentResearchRun:
    """LangGraph 各节点共享的请求内工作区，不作为持久化领域模型使用。"""

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
    factor_analysis: FactorAnalysis | None = None
    factor_evidence: tuple[_FrozenEvidence, ...] = ()
    validation_failure: ModelValidationFailure | None = None

    async def collect_market(self, state: AgentRunState) -> dict[str, object]:
        """图节点：采集并校验冻结行情，将可用证据 ID 写入轻量状态。"""
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
        # 节点失败被归一化为受控错误码，由后续分支生成可审计的降级报告。
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
        """图节点：收集固定时间窗内新闻；失败时保留空集合并进入可审计降级路径。"""
        collection_failed = False
        try:
            self.news = await self.dependencies.news.collect(
                state.symbol,
                since=self.started_at - _NEWS_WINDOW,
                until=self.started_at,
            )
        except Exception:
            collection_failed = True
            self.news = NewsCollection(
                items=(),
                source_count=0,
                successful_source_count=0,
                failed_source_count=0,
                error_codes=(),
            )
        selected = select_news(
            self.news.items, symbol=self.symbol, as_of=self.started_at, limit=_MAX_NEWS_EVIDENCE
        )
        self.news_evidence = _news_evidences(selected)
        funding, etf = await asyncio.gather(
            collect_funding(self.dependencies.funding, symbol=self.symbol, as_of=self.started_at),
            collect_etf(self.dependencies.etf, symbol=self.symbol, as_of=self.started_at),
        )
        self.factor_evidence = tuple(item for item in (funding[1], etf[1]) if item is not None)
        self.factor_analysis = FactorAnalysis(
            policy=policy_topic(
                tuple(
                    (item, evidence.id)
                    for item, evidence in zip(selected, self.news_evidence, strict=True)
                ),
                as_of=self.started_at,
                source_coverage=_policy_source_coverage(self.news),
            ),
            funding=funding[0],
            etf=etf[0],
        )
        error_code = (
            AgentErrorCode.NEWS_SOURCE_FAILED
            if collection_failed or self.news.failed_source_count
            else None
        )
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
        """图节点：确认行情新鲜、K 线完整且模型已配置后计算确定性结构。"""
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
        """图条件边：只有此前节点没有设置降级错误码时才允许进入模型节点。"""
        del state
        return "degraded" if self.degraded_error is not None else "model"

    async def generate_model_report(self, state: AgentRunState) -> dict[str, object]:
        """图节点：以冻结证据请求模型，并拒绝引用未知证据的候选结论。"""
        model = self.dependencies.model
        if model is None or self.structure is None:
            self.degraded_error = AgentErrorCode.MODEL_NOT_CONFIGURED
            return self._update(
                state,
                node_name="generate_model_report",
                error_code=self.degraded_error,
            )
        # 传给模型的是本次运行冻结的最小证据集；模型不能自行扩展数据来源。
        request = ResearchModelRequest(
            symbol=self.symbol,
            structure=self.structure,
            factor_analysis=self.factor_analysis,
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
            # 模型结论必须显式引用已冻结的证据 ID，防止凭空生成不可追溯的观点。
            if not _proposal_uses_known_evidence(proposal, self._evidence_ids()):
                self.degraded_error = AgentErrorCode.MODEL_INVALID_EVIDENCE
            else:
                if self.factor_analysis is not None:
                    try:
                        self.factor_analysis = apply_interpretations(
                            self.factor_analysis,
                            proposal.factor_interpretations,
                        )
                    except ValueError as error:
                        raise ModelOutputError(
                            "model_invalid_evidence",
                            "模型引用了错误专题证据",
                        ) from error
                self.proposal = proposal
        except ModelOutputError as error:
            self.degraded_error = _safe_error_code(error.code)
            if (
                error.code == AgentErrorCode.MODEL_INVALID_RESPONSE.value
                and error.format_attempt_count > 0
            ):
                self.validation_failure = ModelValidationFailure(
                    attempt_count=error.format_attempt_count,
                    issue_count=error.validation_issue_count,
                    field_paths=error.validation_field_paths,
                    error_categories=error.validation_error_categories,
                )
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
        """图节点：将已有证据和受控错误码保存为不含市场结论的降级报告。"""
        await self._persist(completed=False)
        return self._update(state, node_name="persist_degraded_report")

    async def validate_and_persist_report(self, state: AgentRunState) -> dict[str, object]:
        """图节点：根据模型提案与运行状态选择完成或降级报告并持久化。"""
        await self._persist(completed=self.proposal is not None and self.degraded_error is None)
        return self._update(state, node_name="validate_and_persist_report")

    async def _generate_with_one_empty_retry(
        self,
        model: ResearchLanguageModel,
        request: ResearchModelRequest,
    ) -> AgentAnalysisProposal:
        """只在模型返回空结果时额外重试一次，避免泛化重试掩盖上游故障。"""
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
        """把冻结证据、报告草稿与结构化 Agent 分析作为一个关联结果交给仓储。"""
        completed_at = _require_utc(self.dependencies.clock())
        report_id = uuid4()
        evidence = tuple(
            _to_report_evidence(item, report_id=report_id, symbol=self.symbol)
            for item in self._evidences()
        )
        # 无论成功还是降级都落库：失败本身也是需要关联证据和错误码的审计结果。
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
        agent_analysis = AgentAnalysis.model_validate(
            {
                **agent_analysis.model_dump(),
                "factor_analysis": self.factor_analysis,
            }
        )
        self.persisted_report = await self.dependencies.repository.persist_agent(
            AgentReportCreation(
                report=report,
                evidences=evidence,
                started_at=self.started_at,
                completed_at=completed_at,
                generator_kind=ReportGeneratorKind.LANGGRAPH_DEEPSEEK,
                error_code=None if completed else _error_code_value(self.degraded_error),
                validation_failure=None if completed else self.validation_failure,
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
                market.research_context is not None and market.research_context.symbol is not symbol
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
        return market_evidence + context_evidence + self.news_evidence + self.factor_evidence

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
    if not completed or proposal is None or structure is None or market is None:
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
        market_metrics=_frozen_market_metrics(market),
    )


def _frozen_market_metrics(market: CapturedAgentMarket) -> FrozenMarketMetrics:
    summary = market.snapshot.summary
    context = market.research_context
    return FrozenMarketMetrics(
        price=summary.price,
        change_24h=summary.change_24h,
        volume_24h=summary.volume_24h,
        funding_rate=summary.funding_rate,
        open_interest=summary.open_interest,
        fear_greed_value=None if context is None else context.fear_greed_value,
        fear_greed_classification=(None if context is None else context.fear_greed_classification),
        fear_greed_change_7d=(None if context is None else context.fear_greed_change_7d),
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
            *proposal.factor_interpretations,
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


def _policy_source_coverage(news: NewsCollection) -> SourceCoverage:
    if not news.successful_source_ids and not news.failed_source_ids:
        return _source_coverage(news)
    covered = set(news.successful_source_ids) & POLICY_SOURCES
    return "none" if not covered else "complete" if covered == set(POLICY_SOURCES) else "partial"


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
    # 最终置信度只能低于或等于确定性技术结构给出的上限，模型不能自行抬高。
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
