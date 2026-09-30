"""Fixed public-data -> facts -> bounded narrative -> immutable report workflow."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

import structlog
from pydantic import JsonValue

from app.agent.technical.engine import calculate_technical_analysis
from app.agent.technical.methods import method_instructions
from app.agent.technical.model import (
    TechnicalLanguageModel,
    TechnicalModelError,
    parse_technical_narrative,
)
from app.market.contracts import MarketDataUnavailableError, MarketTimeframe
from app.market.gateway import PublicMarketGateway
from app.market.symbols import ResearchSymbol
from app.reports.technical import TechnicalAnalysis, TechnicalQuality, TechnicalReport
from app.reports.technical_repository import TechnicalReportRepository

TIMEFRAMES = (MarketTimeframe.H1, MarketTimeframe.H4, MarketTimeframe.D1)


class TechnicalResearchService:
    def __init__(
        self,
        *,
        market: PublicMarketGateway,
        repository: TechnicalReportRepository,
        model: TechnicalLanguageModel,
        clock: Callable[[], datetime],
    ) -> None:
        self._market, self._repository, self._model, self._clock = market, repository, model, clock

    async def generate(self, symbol: ResearchSymbol, *, analysis_id: UUID) -> TechnicalReport:
        evidence: dict[str, JsonValue] = {
            "market": None,
            "methodInstructions": method_instructions(),
        }
        narrative = None
        error_code = None
        captured_at = self._clock()
        try:
            detail = await self._market.get_market(symbol, TIMEFRAMES)
            captured_at = self._clock()
            if detail.summary.symbol != symbol:
                raise MarketDataUnavailableError("market_data_invalid", "币种不一致")
            analysis = calculate_technical_analysis(detail, captured_at=captured_at)
            evidence["methodInstructions"] = method_instructions(analysis.methods)
            # Preserve all closed rows consulted by quality checks, including older defects.
            evidence["market"] = cast(
                dict[str, JsonValue],
                {
                    "source": detail.summary.freshness.source,
                    "summary": detail.summary.model_dump(mode="json"),
                    "capturedAt": captured_at.isoformat(),
                    "series": [
                        {
                            "timeframe": series.timeframe.value,
                            "candles": [
                                candle.model_dump(mode="json")
                                for candle in series.candles
                                if candle.close_at <= captured_at
                            ],
                        }
                        for series in detail.series
                        if series.timeframe in TIMEFRAMES
                    ],
                },
            )
        except MarketDataUnavailableError:
            error_code = "market_unavailable"
            analysis = TechnicalAnalysis(
                quality=TechnicalQuality(
                    status="invalid",
                    reasons=("公开行情不可用",),
                    candle_counts={},
                    latest_closed_at={},
                ),
                facts=None,
                plans=(),
                no_plan_reasons=("缺少本次公开行情，不能生成计划。",),
                methods=(),
                evidence_id=uuid4(),
            )
        if analysis.quality.status != "valid":
            error_code = error_code or "data_quality_insufficient"
        else:
            try:
                proposed = await self._model.generate(analysis)
                narrative = parse_technical_narrative(
                    proposed.model_dump_json(), analysis.evidence_id
                )
            except TechnicalModelError as error:
                allowed = {
                    "model_not_configured",
                    "model_timeout",
                    "model_upstream_error",
                    "model_invalid_response",
                }
                error_code = error.code if error.code in allowed else "model_invalid_response"
        evidence["analysis"] = analysis.model_dump(mode="json")
        report = TechnicalReport(
            id=uuid4(),
            analysis_id=analysis_id,
            symbol=symbol,
            status="completed" if narrative is not None else "degraded",
            created_at=self._clock(),
            data_cutoff_at=captured_at,
            analysis=analysis,
            narrative=narrative,
            error_code=error_code,
        )
        saved = await self._repository.persist(report, evidence)
        structlog.get_logger(__name__).info(
            "technical_research_completed",
            analysis_id=str(analysis_id),
            report_id=str(report.id),
            symbol=symbol,
            status=report.status,
            error_code=report.error_code,
        )
        return saved
