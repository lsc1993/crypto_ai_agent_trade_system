from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI

from app.main import create_app
from app.trades.contracts import (
    AnalyticsFilters,
    AnalyticsSnapshot,
    EquityPoint,
    TradeCalendarPoint,
    TradeStorageUnavailableError,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_analytics_route_preserves_decimal_strings_null_profit_factor_and_filters() -> None:
    service = FakeAnalyticsService()
    app = create_app()
    app.state.performance_analytics_service = service

    response = await _get(
        app,
        "/api/v1/analytics?symbol=BTCUSDT&direction=long&from=2026-07-31T00:00:00Z",
    )

    assert response.status_code == 200
    assert response.json()["netPnl"] == "1.25"
    assert response.json()["profitFactor"] is None
    assert response.json()["equityCurve"][0]["equity"] == "1.25"
    assert service.filters is not None
    assert service.filters.symbol is not None
    assert service.filters.symbol.value == "BTCUSDT"


@pytest.mark.asyncio
async def test_analytics_route_returns_stable_storage_unavailable_error() -> None:
    app = create_app()
    app.state.performance_analytics_service = UnavailableAnalyticsService()

    response = await _get(app, "/api/v1/analytics")

    assert response.status_code == 503
    assert response.json() == {
        "code": "trade_storage_unavailable",
        "message": "交易日志存储不可用",
        "details": {},
    }


class FakeAnalyticsService:
    def __init__(self) -> None:
        self.filters: AnalyticsFilters | None = None

    async def get_snapshot(self, filters: AnalyticsFilters) -> AnalyticsSnapshot:
        self.filters = filters
        return _snapshot()


class UnavailableAnalyticsService:
    async def get_snapshot(self, filters: AnalyticsFilters) -> AnalyticsSnapshot:
        del filters
        raise TradeStorageUnavailableError("unexpected database message")


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


def _snapshot() -> AnalyticsSnapshot:
    return AnalyticsSnapshot(
        net_pnl=Decimal("1.25"),
        win_rate=Decimal("0.5"),
        profit_factor=None,
        expectancy=Decimal("0.625"),
        max_drawdown=Decimal("-2"),
        equity_curve=(
            EquityPoint(at=NOW, equity=Decimal("1.25"), net_pnl=Decimal("1.25")),
        ),
        trade_calendar=(
            TradeCalendarPoint(at=NOW, net_pnl=Decimal("1.25"), trade_count=1),
        ),
        generated_at=NOW,
    )
