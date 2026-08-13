from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from app.main import create_app
from app.market.contracts import (
    ContractSymbol,
    DataFreshness,
    FreshnessStatus,
    MarketDataUnavailableError,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.reports.contracts import (
    AnalysisReportCreation,
    AnalysisReportStatus,
    AnalysisReportSummary,
    PersistedAnalysisReport,
    ReportPage,
    ReportStorageUnavailableError,
)

NOW = datetime(2026, 8, 9, 10, 30, tzinfo=UTC)
REPORT_ID = UUID("00000000-0000-0000-0000-000000000101")
ANALYSIS_ID = UUID("00000000-0000-0000-0000-000000000201")


@pytest.mark.asyncio
async def test_dashboard_returns_public_markets_recent_reports_and_utc_time() -> None:
    response = await _get(
        create_app(
            market_gateway=FakeMarketGateway(),
            analysis_report_repository=InMemoryReportRepository(),
            dashboard_clock=lambda: NOW,
        ),
        "/api/v1/dashboard",
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"markets", "news", "recentReports", "generatedAt"}
    assert [market["symbol"] for market in payload["markets"]] == [
        "BTCUSDT",
        "ETHUSDT",
    ]
    assert payload["news"] == []
    assert payload["recentReports"][0]["id"] == str(REPORT_ID)
    assert payload["recentReports"][0]["generatorKind"] == "deterministic"
    assert payload["generatedAt"] == "2026-08-09T10:30:00Z"


@pytest.mark.asyncio
async def test_dashboard_preserves_market_unavailable_error_envelope() -> None:
    response = await _get(
        create_app(
            market_gateway=UnavailableMarketGateway(),
            analysis_report_repository=InMemoryReportRepository(),
        ),
        "/api/v1/dashboard",
    )

    assert response.status_code == 503
    assert response.json()["code"] == "market_data_rate_limited"


@pytest.mark.asyncio
async def test_dashboard_hides_report_storage_exception_text() -> None:
    response = await _get(
        create_app(
            market_gateway=FakeMarketGateway(),
            analysis_report_repository=UnavailableReportRepository(),
        ),
        "/api/v1/dashboard",
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "report_storage_unavailable",
        "message": "研究报告存储暂不可用",
        "details": {},
    }
    assert "database password leaked" not in response.text


@pytest.mark.asyncio
async def test_dashboard_rejects_a_naive_generated_time() -> None:
    response = await _get(
        create_app(
            market_gateway=FakeMarketGateway(),
            analysis_report_repository=InMemoryReportRepository(),
            dashboard_clock=lambda: datetime(2026, 8, 9, 10, 30),
        ),
        "/api/v1/dashboard",
    )

    assert response.status_code == 500
    assert response.json()["code"] == "internal_server_error"


@pytest.mark.asyncio
async def test_dashboard_loads_markets_and_reports_concurrently() -> None:
    market_started = asyncio.Event()
    reports_started = asyncio.Event()
    response = await _get(
        create_app(
            market_gateway=CoordinatedMarketGateway(market_started, reports_started),
            analysis_report_repository=CoordinatedReportRepository(
                market_started,
                reports_started,
            ),
        ),
        "/api/v1/dashboard",
    )

    assert response.status_code == 200


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


class FakeMarketGateway:
    async def get_summaries(
        self,
        symbols: tuple[ContractSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        assert symbols == (ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT)
        return tuple(_market_summary(symbol) for symbol in symbols)

    async def get_market(
        self,
        symbol: ContractSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        raise AssertionError(f"dashboard must not load market detail: {symbol}, {timeframes}")


class UnavailableMarketGateway(FakeMarketGateway):
    async def get_summaries(
        self,
        symbols: tuple[ContractSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        del symbols
        raise MarketDataUnavailableError(
            "market_data_rate_limited",
            "公开行情请求受到限流",
        )


class CoordinatedMarketGateway(FakeMarketGateway):
    def __init__(
        self,
        market_started: asyncio.Event,
        reports_started: asyncio.Event,
    ) -> None:
        self._market_started = market_started
        self._reports_started = reports_started

    async def get_summaries(
        self,
        symbols: tuple[ContractSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        self._market_started.set()
        await asyncio.wait_for(self._reports_started.wait(), timeout=0.5)
        return await super().get_summaries(symbols)


class InMemoryReportRepository:
    async def persist(
        self,
        creation: AnalysisReportCreation,
    ) -> PersistedAnalysisReport:
        raise AssertionError(f"dashboard must not persist reports: {creation}")

    async def get_by_id(self, report_id: UUID) -> PersistedAnalysisReport | None:
        raise AssertionError(f"dashboard must not load report detail: {report_id}")

    async def get_by_analysis_id(
        self,
        analysis_id: UUID,
    ) -> PersistedAnalysisReport | None:
        raise AssertionError(f"dashboard must not load analysis detail: {analysis_id}")

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        symbol: ContractSymbol | None,
        status: AnalysisReportStatus | None,
    ) -> ReportPage:
        assert (page, page_size, symbol, status) == (1, 5, None, None)
        return ReportPage(items=(_report_summary(),), page=1, page_size=5, total=1)


class UnavailableReportRepository(InMemoryReportRepository):
    async def list(
        self,
        *,
        page: int,
        page_size: int,
        symbol: ContractSymbol | None,
        status: AnalysisReportStatus | None,
    ) -> ReportPage:
        del page, page_size, symbol, status
        raise ReportStorageUnavailableError("database password leaked")


class CoordinatedReportRepository(InMemoryReportRepository):
    def __init__(
        self,
        market_started: asyncio.Event,
        reports_started: asyncio.Event,
    ) -> None:
        self._market_started = market_started
        self._reports_started = reports_started

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        symbol: ContractSymbol | None,
        status: AnalysisReportStatus | None,
    ) -> ReportPage:
        self._reports_started.set()
        await asyncio.wait_for(self._market_started.wait(), timeout=0.5)
        return await super().list(
            page=page,
            page_size=page_size,
            symbol=symbol,
            status=status,
        )


def _market_summary(symbol: ContractSymbol) -> MarketSummary:
    return MarketSummary(
        symbol=symbol,
        price=Decimal("68000.30"),
        change_24h=Decimal("1.25"),
        volume_24h=Decimal("123456.789"),
        funding_rate=Decimal("0.00010000"),
        open_interest=Decimal("1234.5678"),
        freshness=DataFreshness(
            status=FreshnessStatus.FRESH,
            source="public-test-gateway",
            observed_at=NOW,
            fetched_at=NOW,
        ),
    )


def _report_summary() -> AnalysisReportSummary:
    return AnalysisReportSummary(
        id=REPORT_ID,
        analysis_id=ANALYSIS_ID,
        symbol=ContractSymbol.BTCUSDT,
        status=AnalysisReportStatus.COMPLETED,
        title="BTC 市场研究",
        summary="公开市场数据研究摘要",
        facts=("价格维持区间波动",),
        inferences=("波动率处于近期中位区间",),
        risks=("公开行情可能延迟",),
        limitations=("仅使用公开数据",),
        generated_at=NOW,
        data_cutoff_at=NOW,
        created_at=NOW,
    )
