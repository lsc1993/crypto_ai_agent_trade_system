from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.main import create_app
from app.market.contracts import (
    Candle,
    ContractSymbol,
    DataFreshness,
    FreshnessStatus,
    MarketDataUnavailableError,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.gateway import PublicMarketGateway
from app.market.research import PersistedMarketReader, PersistedMarketSnapshot
from app.reports.contracts import (
    AnalysisReportCreation,
    AnalysisReportStatus,
    AnalysisReportSummary,
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
async def test_create_list_and_read_a_persisted_completed_report() -> None:
    app = _analysis_app(FreshPersistedMarketReader())

    created = await post(app, "/api/v1/analysis-runs", {"symbol": "BTCUSDT"})
    listed = await get(app, "/api/v1/analysis-runs?page=1&page_size=20&symbol=BTCUSDT")
    detail = await get(app, f"/api/v1/analysis-runs/{created.json()['reportId']}")

    assert created.status_code == 201
    assert UUID(created.json()["analysisId"])
    assert listed.status_code == 200
    assert listed.json()["page_size"] == 20
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["status"] == "completed"
    assert detail.status_code == 200
    assert detail.json()["analysisId"] == created.json()["analysisId"]
    assert detail.json()["dataCutoffAt"] == "2026-07-30T11:59:00Z"
    assert len(detail.json()["evidence"]) == 5


@pytest.mark.asyncio
async def test_retry_creates_a_distinct_report_and_analysis_id() -> None:
    app = _analysis_app(FreshPersistedMarketReader())
    original = await post(app, "/api/v1/analysis-runs", {"symbol": "BTCUSDT"})

    retry = await post(app, f"/api/v1/analysis-runs/{original.json()['reportId']}/retry")

    assert retry.status_code == 201
    assert retry.json()["reportId"] != original.json()["reportId"]
    assert retry.json()["analysisId"] != original.json()["analysisId"]


@pytest.mark.asyncio
async def test_sse_replays_one_persisted_degraded_terminal_event() -> None:
    app = _analysis_app(UnavailablePersistedMarketReader())
    created = await post(app, "/api/v1/analysis-runs", {"symbol": "BTCUSDT"})

    event_response = await get(
        app,
        f"/api/v1/analysis-runs/{created.json()['analysisId']}/events",
    )

    assert event_response.status_code == 200
    assert event_response.headers["content-type"].startswith("text/event-stream")
    assert _event_payload(event_response.text) == {
        "analysisId": created.json()["analysisId"],
        "symbol": "BTCUSDT",
        "status": "degraded",
        "occurredAt": "2026-07-30T12:00:00Z",
        "message": "持久化市场研究报告已降级完成。",
    }


@pytest.mark.asyncio
async def test_report_generation_never_falls_back_to_the_live_market_gateway() -> None:
    app = _analysis_app(
        UnavailablePersistedMarketReader(),
        market_gateway=ForbiddenLiveMarketGateway(),
    )

    created = await post(app, "/api/v1/analysis-runs", {"symbol": "BTCUSDT"})
    detail = await get(app, f"/api/v1/analysis-runs/{created.json()['reportId']}")

    assert created.status_code == 201
    assert detail.status_code == 200
    assert detail.json()["status"] == "degraded"
    assert detail.json()["dataCutoffAt"] is None


@pytest.mark.asyncio
async def test_unknown_report_or_analysis_id_returns_not_found() -> None:
    app = _analysis_app(FreshPersistedMarketReader())
    unknown_id = "00000000-0000-0000-0000-000000000099"

    report_response = await get(app, f"/api/v1/analysis-runs/{unknown_id}")
    event_response = await get(app, f"/api/v1/analysis-runs/{unknown_id}/events")

    assert report_response.status_code == 404
    assert event_response.status_code == 404
    assert report_response.json()["code"] == "not_found"


async def get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


async def post(
    app: FastAPI,
    path: str,
    payload: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(path, json=payload)


def _analysis_app(
    reader: PersistedMarketReader,
    *,
    market_gateway: PublicMarketGateway | None = None,
) -> FastAPI:
    repository = InMemoryAnalysisReportRepository()
    app = create_app(
        market_gateway=market_gateway,
        market_research_reader=reader,
        analysis_report_repository=repository,
    )
    app.state.analysis_report_service = DeterministicResearchReportService(
        reader,
        repository,
        clock=lambda: NOW,
    )
    return app


def _event_payload(body: str) -> dict[str, object]:
    lines = [line for line in body.splitlines() if line.startswith("data: ")]
    assert lines
    return json.loads(lines[0].removeprefix("data: "))


class InMemoryAnalysisReportRepository:
    def __init__(self) -> None:
        self._reports: dict[UUID, PersistedAnalysisReport] = {}

    async def persist(
        self,
        creation: AnalysisReportCreation,
    ) -> PersistedAnalysisReport:
        report = PersistedAnalysisReport(
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
        self._reports[report.id] = report
        return report

    async def get_by_id(self, report_id: UUID) -> PersistedAnalysisReport | None:
        return self._reports.get(report_id)

    async def get_by_analysis_id(
        self,
        analysis_id: UUID,
    ) -> PersistedAnalysisReport | None:
        return next(
            (report for report in self._reports.values() if report.analysis_id == analysis_id),
            None,
        )

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        symbol: ContractSymbol | None,
        status: AnalysisReportStatus | None,
    ) -> ReportPage:
        reports = tuple(
            report
            for report in self._reports.values()
            if (symbol is None or report.symbol is symbol)
            and (status is None or report.status is status)
        )
        return ReportPage(
            items=tuple(
                AnalysisReportSummary(
                    **report.model_dump(exclude={"evidence", "agent_analysis"}),
                )
                for report in reports[(page - 1) * page_size : page * page_size]
            ),
            page=page,
            page_size=page_size,
            total=len(reports),
        )


class FreshPersistedMarketReader(PersistedMarketReader):
    async def load_latest_snapshot(
        self,
        symbol: ContractSymbol,
    ) -> PersistedMarketSnapshot | None:
        return PersistedMarketSnapshot(
            summary=_summary(symbol),
            captured_at=NOW - timedelta(minutes=1),
        )

    async def load_recent_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        assert limit == 200
        return (_candle(symbol, timeframe),)


class UnavailablePersistedMarketReader(PersistedMarketReader):
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


class ForbiddenLiveMarketGateway:
    async def get_summaries(
        self,
        symbols: tuple[ContractSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        del symbols
        raise AssertionError("报告不得调用实时市场网关")

    async def get_market(
        self,
        symbol: ContractSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        del symbol, timeframes
        raise AssertionError("报告不得调用实时市场网关")


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
