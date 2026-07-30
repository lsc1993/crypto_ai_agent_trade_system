from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import NoReturn, cast
from uuid import UUID

from pydantic import JsonValue

from app.market.contracts import Candle, ContractSymbol, MarketDataUnavailableError, MarketTimeframe
from app.market.research import PersistedMarketReader, PersistedMarketSnapshot
from app.reports.contracts import (
    AnalysisEvidenceDraft,
    AnalysisReportCreation,
    AnalysisReportDraft,
    AnalysisReportStatus,
    PersistedAnalysisReport,
    report_payload_sha256,
)
from app.reports.repository import AnalysisReportRepository

_TIMEFRAMES = (
    MarketTimeframe.M15,
    MarketTimeframe.H1,
    MarketTimeframe.H4,
    MarketTimeframe.D1,
)
_CANDLE_LIMIT = 200
_FRESHNESS_THRESHOLD = timedelta(minutes=2)
_SOURCE_BASE_URL = "https://www.binance.com/en/futures/"


class DeterministicResearchReportService:
    """仅以持久化公开市场证据生成非交易性研究报告。"""

    def __init__(
        self,
        reader: PersistedMarketReader,
        repository: AnalysisReportRepository,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._reader = reader
        self._repository = repository
        self._clock = clock

    async def generate(self, symbol: ContractSymbol) -> PersistedAnalysisReport:
        generated_at = _require_utc(self._clock())
        snapshot: PersistedMarketSnapshot | None = None
        candles: dict[MarketTimeframe, Candle] = {}
        try:
            snapshot = await self._require_snapshot(symbol)
            for timeframe in _TIMEFRAMES:
                candles[timeframe] = await self._latest_closed_candle(
                    symbol,
                    timeframe,
                    generated_at,
                )
        except MarketDataUnavailableError as error:
            return await self._persist_degraded(
                symbol,
                generated_at,
                str(error),
                snapshot,
                candles,
            )

        data_cutoff_at = _data_cutoff(snapshot, candles)
        if generated_at - snapshot.captured_at > _FRESHNESS_THRESHOLD:
            report = _degraded_draft(
                symbol,
                generated_at,
                "持久化市场数据已过期。",
                data_cutoff_at,
            )
            return await self._repository.persist(
                AnalysisReportCreation(
                    report=report,
                    evidences=_evidence_from(report.id, symbol, snapshot, candles),
                )
            )
        report = _completed_draft(
            symbol,
            snapshot,
            candles,
            generated_at,
            data_cutoff_at,
        )
        return await self._repository.persist(
            AnalysisReportCreation(
                report=report,
                evidences=_evidence_from(report.id, symbol, snapshot, candles),
            )
        )

    async def _persist_degraded(
        self,
        symbol: ContractSymbol,
        generated_at: datetime,
        reason: str,
        snapshot: PersistedMarketSnapshot | None,
        candles: dict[MarketTimeframe, Candle],
    ) -> PersistedAnalysisReport:
        data_cutoff_at = None if snapshot is None else _data_cutoff(snapshot, candles)
        report = _degraded_draft(symbol, generated_at, reason, data_cutoff_at)
        evidence = (
            ()
            if snapshot is None
            else _evidence_from(report.id, symbol, snapshot, candles)
        )
        return await self._repository.persist(
            AnalysisReportCreation(
                report=report,
                evidences=evidence,
            )
        )

    async def _require_snapshot(
        self,
        symbol: ContractSymbol,
    ) -> PersistedMarketSnapshot:
        snapshot = await self._reader.load_latest_snapshot(symbol)
        if snapshot is None:
            _raise_unavailable("持久化市场快照缺失。")
        if snapshot.summary.symbol is not symbol:
            _raise_unavailable("持久化市场快照缺失。")
        return snapshot

    async def _latest_closed_candle(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        generated_at: datetime,
    ) -> Candle:
        candles = await self._reader.load_recent_candles(symbol, timeframe, _CANDLE_LIMIT)
        if not candles:
            _raise_unavailable(f"持久化 {timeframe.value} K 线缺失。")
        if any(
            candle.symbol is not symbol
            or candle.timeframe is not timeframe
            or candle.close_at > generated_at
            for candle in candles
        ):
            _raise_unavailable(f"持久化 {timeframe.value} K 线无效。")
        return max(candles, key=lambda candle: candle.close_at)


def _completed_draft(
    symbol: ContractSymbol,
    snapshot: PersistedMarketSnapshot,
    candles: dict[MarketTimeframe, Candle],
    generated_at: datetime,
    data_cutoff_at: datetime,
) -> AnalysisReportDraft:
    summary = snapshot.summary
    facts = (
        f"冻结快照价格：{summary.price}。",
        f"24 小时变动：{summary.change_24h}；24 小时成交量：{summary.volume_24h}。",
        f"资金费率：{summary.funding_rate}；未平仓量：{summary.open_interest}。",
        *(
            f"{timeframe.value} 最新已收盘 K 线收盘价：{candles[timeframe].close_price}。"
            for timeframe in _TIMEFRAMES
        ),
    )
    return AnalysisReportDraft(
        symbol=symbol,
        status=AnalysisReportStatus.COMPLETED,
        title=f"{symbol.value} 持久化市场研究",
        summary="本报告只陈述已冻结的公开市场观察。",
        facts=facts,
        inferences=("这些观察不构成方向或交易结论。",),
        risks=("市场数据可能随时间过期。",),
        limitations=("报告未访问账户、模型或实时市场。",),
        generated_at=generated_at,
        data_cutoff_at=data_cutoff_at,
    )


def _degraded_draft(
    symbol: ContractSymbol,
    generated_at: datetime,
    reason: str,
    data_cutoff_at: datetime | None,
) -> AnalysisReportDraft:
    return AnalysisReportDraft(
        symbol=symbol,
        status=AnalysisReportStatus.DEGRADED,
        title=f"{symbol.value} 持久化市场研究已降级",
        summary="当前证据不足，无法形成市场研究结论。",
        facts=(),
        inferences=(),
        risks=(reason,),
        limitations=("报告未形成市场结论，需等待新的持久化市场数据。",),
        generated_at=generated_at,
        data_cutoff_at=data_cutoff_at,
    )


def _evidence_from(
    report_id: UUID,
    symbol: ContractSymbol,
    snapshot: PersistedMarketSnapshot,
    candles: dict[MarketTimeframe, Candle],
) -> tuple[AnalysisEvidenceDraft, ...]:
    snapshot_payload = cast(
        dict[str, JsonValue],
        {"summary": snapshot.summary.model_dump(mode="json")},
    )
    evidence: list[AnalysisEvidenceDraft] = [
        _evidence(
            report_id=report_id,
            symbol=symbol,
            summary="持久化公开市场快照。",
            observed_at=snapshot.summary.freshness.observed_at,
            fetched_at=snapshot.summary.freshness.fetched_at,
            payload=snapshot_payload,
        )
    ]
    evidence.extend(
        _evidence(
            report_id=report_id,
            symbol=symbol,
            summary=f"{timeframe.value} 最新已收盘 K 线。",
            observed_at=candle.observed_at,
            fetched_at=candle.fetched_at,
            payload=cast(
                dict[str, JsonValue],
                {"latestClosedCandle": candle.model_dump(mode="json")},
            ),
        )
        for timeframe, candle in candles.items()
    )
    return tuple(evidence)


def _evidence(
    *,
    report_id: UUID,
    symbol: ContractSymbol,
    summary: str,
    observed_at: datetime,
    fetched_at: datetime,
    payload: dict[str, JsonValue],
) -> AnalysisEvidenceDraft:
    return AnalysisEvidenceDraft(
        report_id=report_id,
        symbol=symbol,
        source="binance_usdm_public_rest",
        source_url=f"{_SOURCE_BASE_URL}{symbol.value}",
        observed_at=observed_at,
        fetched_at=fetched_at,
        summary=summary,
        payload=payload,
        payload_sha256=report_payload_sha256(payload),
    )


def _data_cutoff(
    snapshot: PersistedMarketSnapshot,
    candles: dict[MarketTimeframe, Candle],
) -> datetime:
    return min(
        snapshot.summary.freshness.observed_at,
        *(candle.observed_at for candle in candles.values()),
    )


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是 UTC 且带时区")
    return value.astimezone(UTC)


def _raise_unavailable(message: str) -> NoReturn:
    raise MarketDataUnavailableError("market_research_unavailable", message)
