"""Fixed research path with bounded model stages and honest fallback."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from time import monotonic
from typing import Literal
from uuid import UUID, uuid4

from pydantic import JsonValue

from app.agent.technical.engine import calculate_technical_analysis
from app.agent.technical.methods import method_instructions
from app.agent.technical.plan_fallback import build_decision_plan_book, build_rules_plan_book
from app.agent.technical.plan_model import (
    TechnicalPlanLanguageModel,
    TechnicalPlanModelError,
    model_deadline,
)
from app.agent.technical.references import (
    build_reference_catalog,
    render_plan_book,
    validate_decision,
)
from app.agent.technical.service import TIMEFRAMES
from app.market.contracts import MarketDataUnavailableError
from app.market.gateway import PublicMarketGateway
from app.market.symbols import ResearchSymbol
from app.reports.technical import TechnicalAnalysis, TechnicalQuality
from app.reports.technical_plan import (
    TechnicalContext,
    TechnicalGeneration,
    TechnicalPlanReport,
    TechnicalStageDiagnostic,
)
from app.reports.technical_repository import TechnicalReportRepository
from app.reports.technical_runs import TechnicalRunLease, TechnicalRunPhase


class TechnicalPlanResearchService:
    def __init__(
        self,
        *,
        market: PublicMarketGateway,
        repository: TechnicalReportRepository,
        model: TechnicalPlanLanguageModel,
        clock: Callable[[], datetime],
        timeout_seconds: int = 600,
    ) -> None:
        self._market, self._repository, self._model, self._clock, self._timeout = (
            market,
            repository,
            model,
            clock,
            timeout_seconds,
        )

    async def generate(
        self,
        symbol: ResearchSymbol,
        *,
        analysis_id: UUID,
        progress: Callable[[TechnicalRunPhase], Awaitable[None]],
        before_save: Callable[[], Awaitable[TechnicalRunLease | None]],
    ) -> TechnicalPlanReport:
        captured_at = self._clock()
        evidence: dict[str, JsonValue] = {"market": None}
        context = TechnicalContext(
            analysis=TechnicalAnalysis(
                quality=TechnicalQuality(
                    status="invalid",
                    reasons=("market_unavailable",),
                    candle_counts={},
                    latest_closed_at={},
                ),
                facts=None,
                plans=(),
                no_plan_reasons=("market_unavailable",),
                methods=(),
                evidence_id=uuid4(),
            ),
            summary_price=None,
            latest_closed_prices={},
            data_cutoff_at=captured_at,
        )
        decision = None
        book = None
        diagnostics: list[TechnicalStageDiagnostic] = []
        error_code: (
            Literal[
                "market_unavailable",
                "data_quality_insufficient",
                "model_not_configured",
                "model_timeout",
                "model_upstream_error",
                "model_invalid_response",
                "model_output_limit",
                "model_empty_response",
                "run_timeout",
            ]
            | None
        ) = None
        quality: Literal[
            "complete", "composition_fallback", "analysis_unavailable", "data_insufficient"
        ] = "data_insufficient"
        deadline_token = model_deadline.set(monotonic() + max(1, self._timeout - 15))
        try:
            # Leave a bounded window for ownership verification and storage.
            async with asyncio.timeout(max(1, self._timeout - 15)):
                await progress("collecting")
                try:
                    detail = await self._market.get_market(symbol, TIMEFRAMES)
                    captured_at = self._clock()
                    if detail.summary.symbol != symbol:
                        raise MarketDataUnavailableError("market_data_invalid", "币种不一致")
                    analysis = calculate_technical_analysis(detail, captured_at=captured_at)
                    context = TechnicalContext(
                        analysis=analysis,
                        summary_price=detail.summary.price,
                        latest_closed_prices={
                            series.timeframe.value: closed[-1].close_price
                            for series in detail.series
                            if series.timeframe in TIMEFRAMES
                            and (closed := [c for c in series.candles if c.close_at <= captured_at])
                        },
                        data_cutoff_at=captured_at,
                    )
                    evidence["market"] = {
                        "summary": detail.summary.model_dump(mode="json"),
                        "capturedAt": captured_at.isoformat(),
                        "series": [
                            {
                                "timeframe": series.timeframe.value,
                                "candles": [
                                    c.model_dump(mode="json")
                                    for c in series.candles
                                    if c.close_at <= captured_at
                                ],
                            }
                            for series in detail.series
                            if series.timeframe in TIMEFRAMES
                        ],
                    }
                except MarketDataUnavailableError:
                    error_code = "market_unavailable"
                if context.analysis.quality.status != "valid":
                    error_code = error_code or "data_quality_insufficient"
                else:
                    quality = "analysis_unavailable"
                    await progress("analyzing")
                    try:
                        result = await self._model.analyze(context)
                        diagnostics.extend(result.diagnostics)
                        await progress("validating")
                        decision = validate_decision(
                            result.summary, build_reference_catalog(context)
                        )
                        quality = "composition_fallback"
                        await progress("composing")
                        composed = await self._model.compose(context, decision)
                        diagnostics.extend(composed.diagnostics)
                        if (composed.summary.stance, composed.summary.selected_plan_ref) != (
                            decision.stance,
                            decision.selected_plan_ref,
                        ):
                            raise ValueError("decision_changed")
                        book = render_plan_book(composed.summary, build_reference_catalog(context))
                        quality = "complete"
                    except TechnicalPlanModelError as error:
                        diagnostics.extend(error.diagnostics)
                        error_code = error.code
                    except ValueError:
                        error_code = "model_invalid_response"
        except TimeoutError:
            error_code = "run_timeout"
        finally:
            model_deadline.reset(deadline_token)
        if book is None:
            book = (
                build_decision_plan_book(context, decision)
                if decision is not None
                else build_rules_plan_book(context)
            )
        evidence["context"] = context.model_dump(mode="json")
        evidence["methodInstructions"] = (
            method_instructions(context.analysis.methods) if context.analysis.methods else ""
        )
        evidence["decision"] = None if decision is None else decision.model_dump(mode="json")
        report = TechnicalPlanReport(
            id=uuid4(),
            analysis_id=analysis_id,
            symbol=symbol,
            status="completed" if quality == "complete" else "degraded",
            created_at=self._clock(),
            data_cutoff_at=context.data_cutoff_at,
            analysis=context.analysis,
            context=context,
            decision=decision,
            plan_book=book,
            generation=TechnicalGeneration(
                source="model" if quality == "complete" else "rules",
                quality=quality,
                diagnostics=tuple(diagnostics),
            ),
            error_code=error_code,
        )
        async with asyncio.timeout(15):
            await progress("saving")
            lease = await before_save()
            saved = await self._repository.persist(report, evidence, lease=lease)
        if not isinstance(saved, TechnicalPlanReport):
            raise ValueError("report_version")
        return saved
