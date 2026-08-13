from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.main import create_app
from app.market.contracts import Candle, ContractSymbol, MarketTimeframe
from app.research.backtests.contracts import (
    BacktestFilters,
    BacktestPage,
    BacktestRequest,
    BacktestResult,
    BacktestRunStatus,
    PersistedBacktestRun,
)
from app.research.backtests.repository import BacktestRepository
from app.shared.config import AppSettings

NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)
START = datetime(2026, 7, 3, tzinfo=UTC)
END = START + timedelta(hours=3)


@pytest.mark.asyncio
async def test_backtest_routes_create_list_and_detail() -> None:
    repository = FakeBacktestRepository()
    app = _app(repository)

    created = await _request(app, "POST", "/api/v1/backtests", _payload())
    listed = await _request(app, "GET", "/api/v1/backtests?page=1&page_size=20")
    detail = await _request(app, "GET", f"/api/v1/backtests/{created.json()['id']}")

    assert created.status_code == 201
    assert created.json()["status"] == "completed"
    assert created.json()["summary"]["initialCash"] == "10000"
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["page_size"] == 20
    assert detail.status_code == 200
    assert detail.json()["events"][0]["kind"] == "decision"


@pytest.mark.asyncio
async def test_backtest_routes_limit_response_decimal_fraction_to_frontend_contract() -> None:
    repository = FakeBacktestRepository(high_precision_summary=True)
    app = _app(repository)

    created = await _request(app, "POST", "/api/v1/backtests", _payload())
    listed = await _request(app, "GET", "/api/v1/backtests?page=1&page_size=20")
    detail = await _request(app, "GET", f"/api/v1/backtests/{created.json()['id']}")

    assert created.status_code == 201
    assert listed.status_code == 200
    assert detail.status_code == 200
    for payload in (
        created.json(),
        listed.json()["items"][0],
        detail.json(),
    ):
        assert payload["summary"]["maxDrawdownFraction"] == "0.090393119726157725"
        assert payload["summary"]["profitFactor"] == "0.429692729143866704"


@pytest.mark.asyncio
async def test_backtest_routes_reject_invalid_scope_and_return_safe_not_found() -> None:
    app = _app(FakeBacktestRepository())

    invalid = await _request(app, "POST", "/api/v1/backtests", _payload(symbol="ETHUSDT"))
    missing = await _request(
        app,
        "GET",
        "/api/v1/backtests/00000000-0000-0000-0000-000000000999",
    )

    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"
    assert missing.status_code == 404
    assert missing.json() == {"code": "not_found", "message": "回测运行不存在", "details": {}}


@pytest.mark.asyncio
async def test_backtest_routes_use_safe_storage_error_without_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.main.AppSettings", lambda: AppSettings(database_url=None))
    app = create_app(historical_candle_gateway=FakeHistoricalGateway())

    response = await _request(app, "POST", "/api/v1/backtests", _payload())

    assert response.status_code == 503
    assert response.json() == {
        "code": "backtest_storage_unavailable",
        "message": "回测存储不可用",
        "details": {},
    }
    assert "postgres" not in response.text.lower()


class FakeHistoricalGateway:
    async def load_closed_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[Candle, ...]:
        assert symbol is ContractSymbol.BTCUSDT
        assert timeframe is MarketTimeframe.H1
        assert start_at == START - timedelta(hours=49)
        assert end_at == END
        return _candles()


class FakeBacktestRepository:
    def __init__(self, *, high_precision_summary: bool = False) -> None:
        self._runs: dict[UUID, PersistedBacktestRun] = {}
        self._high_precision_summary = high_precision_summary

    async def create_pending(
        self,
        request: BacktestRequest,
        *,
        occurred_at: datetime,
    ) -> PersistedBacktestRun:
        run = PersistedBacktestRun(
            id=uuid4(),
            status=BacktestRunStatus.PENDING,
            request=request,
            created_at=occurred_at,
        )
        self._runs[run.id] = run
        return run

    async def complete(
        self,
        run_id: UUID,
        result: BacktestResult,
        candles: tuple[Candle, ...],
        *,
        occurred_at: datetime,
    ) -> PersistedBacktestRun:
        del candles
        if self._high_precision_summary:
            result = result.model_copy(
                update={
                    "summary": result.summary.model_copy(
                        update={
                            "max_drawdown_fraction": Decimal(
                                "0.09039311972615772470574350276"
                            ),
                            "profit_factor": Decimal(
                                "0.4296927291438667043301680249"
                            ),
                        }
                    )
                }
            )
        pending = self._runs[run_id]
        completed = pending.model_copy(
            update={
                "status": BacktestRunStatus.COMPLETED,
                "finished_at": occurred_at,
                "result": result,
            }
        )
        self._runs[run_id] = completed
        return completed

    async def fail(
        self,
        run_id: UUID,
        *,
        code: str,
        message: str,
        occurred_at: datetime,
    ) -> PersistedBacktestRun:
        pending = self._runs[run_id]
        failed = pending.model_copy(
            update={
                "status": BacktestRunStatus.FAILED,
                "finished_at": occurred_at,
                "failure_code": code,
                "failure_message": message,
            }
        )
        self._runs[run_id] = failed
        return failed

    async def list(self, filters: BacktestFilters) -> BacktestPage:
        items = tuple(reversed(tuple(self._runs.values())))
        start = (filters.page - 1) * filters.page_size
        return BacktestPage(
            items=items[start : start + filters.page_size],
            page=filters.page,
            page_size=filters.page_size,
            total=len(items),
        )

    async def get_by_id(self, run_id: UUID) -> PersistedBacktestRun | None:
        return self._runs.get(run_id)


def _app(repository: BacktestRepository) -> FastAPI:
    app = create_app(
        historical_candle_gateway=FakeHistoricalGateway(),
        backtest_repository=repository,
        backtest_clock=lambda: NOW,
    )
    return app


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, json=payload)


def _payload(*, symbol: str = "BTCUSDT") -> dict[str, object]:
    return {
        "symbol": symbol,
        "timeframe": "1h",
        "startAt": START.isoformat().replace("+00:00", "Z"),
        "endAt": END.isoformat().replace("+00:00", "Z"),
        "initialCash": "10000",
    }


def _candles() -> tuple[Candle, ...]:
    warmup_start = START - timedelta(hours=49)
    return tuple(
        _candle(
            open_at=warmup_start + timedelta(hours=index),
            open_price=Decimal("100") if index < 51 else Decimal("102"),
            close_price=Decimal("100") if index < 50 else Decimal(index + 52),
        )
        for index in range(52)
    )


def _candle(*, open_at: datetime, open_price: Decimal, close_price: Decimal) -> Candle:
    high_price = max(open_price, close_price)
    low_price = min(open_price, close_price)
    return Candle(
        symbol=ContractSymbol.BTCUSDT,
        timeframe=MarketTimeframe.H1,
        open_at=open_at,
        close_at=open_at + timedelta(hours=1),
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=Decimal("1"),
        observed_at=NOW,
        fetched_at=NOW,
    )
