# 验证本地模拟账户的读写操作和只读绩效接口。
# 服务替身提供固定账户与绩效，接口不能接受浮点现金输入。
# 不存在账户和存储失败使用安全信封，绩效响应不授权交易或网络账户访问。
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from app.execution.contracts import DEFAULT_EXECUTION_CONFIG
from app.main import create_app
from app.market.contracts import ContractSymbol
from app.paper_trading.contracts import (
    ManualPaperIntent,
    PaperAccount,
    PaperAccountCreate,
    PaperAccountDetail,
    PaperAccountFilters,
    PaperAccountNotFoundError,
    PaperAccountPage,
    PaperAccountStatus,
    PaperActionOutcome,
    PaperActionOutcomeKind,
    PaperDecisionStats,
    PaperHistoryStatus,
    PaperPerformancePoint,
    PaperPerformanceSnapshot,
    PaperPosition,
)
from app.risk.contracts import DEFAULT_RISK_CONFIG
from app.shared.config import AppSettings
from app.strategy.contracts import IntentAction, IntentSource

ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000905")
REQUEST_ID = UUID("00000000-0000-0000-0000-000000000906")
NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_paper_account_routes_create_list_detail_and_actions() -> None:
    service = FakePaperTradingService(_detail())
    app = create_app()
    app.state.paper_trading_service = service

    created = await _request(app, "POST", "/api/v1/paper-accounts", {"initialCash": "10000"})
    listed = await _request(app, "GET", "/api/v1/paper-accounts?page=1&pageSize=20")
    detail = await _request(app, "GET", f"/api/v1/paper-accounts/{ACCOUNT_ID}")
    action = await _request(
        app,
        "POST",
        f"/api/v1/paper-accounts/{ACCOUNT_ID}/manual-intents",
        {"clientRequestId": str(REQUEST_ID), "action": "open_long"},
    )
    strategy = await _request(
        app,
        "POST",
        f"/api/v1/paper-accounts/{ACCOUNT_ID}/strategy-evaluations",
    )
    archived = await _request(
        app,
        "POST",
        f"/api/v1/paper-accounts/{ACCOUNT_ID}/archive",
    )

    assert created.status_code == 201
    assert created.json()["id"] == str(ACCOUNT_ID)
    assert listed.status_code == 200
    assert listed.json()["pageSize"] == 20
    assert detail.status_code == 200
    assert detail.json()["symbol"] == "BTCUSDT"
    assert action.status_code == 200
    assert action.json()["actionOutcome"]["source"] == "manual"
    assert strategy.status_code == 200
    assert archived.status_code == 200
    assert service.manual_requests == [
        ManualPaperIntent(client_request_id=REQUEST_ID, action=IntentAction.OPEN_LONG)
    ]


@pytest.mark.asyncio
async def test_paper_account_routes_reject_non_string_cash_and_hide_storage_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    invalid = await _request(app, "POST", "/api/v1/paper-accounts", {"initialCash": 10000})

    monkeypatch.setattr("app.main.AppSettings", lambda: AppSettings(database_url=None))
    unavailable = await _request(create_app(), "GET", "/api/v1/paper-accounts")

    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "paper_storage_unavailable"
    assert "postgres" not in unavailable.text.lower()


@pytest.mark.asyncio
async def test_paper_performance_route_returns_a_local_read_only_snapshot() -> None:
    service = FakePaperTradingService(_detail())
    app = create_app()
    app.state.paper_trading_service = service

    response = await _request(
        app,
        "GET",
        f"/api/v1/paper-accounts/{ACCOUNT_ID}/performance",
    )

    assert response.status_code == 200
    assert response.json()["netPnl"] == "-500"
    assert response.json()["historyStatus"] == "complete"
    assert response.json()["equityCurve"] == [
        {
            "at": NOW.isoformat().replace("+00:00", "Z"),
            "cash": "9500",
            "positionQuantity": "0",
            "equity": "9500",
            "netPnl": "-500",
        }
    ]


@pytest.mark.asyncio
async def test_paper_performance_route_returns_safe_not_found_and_storage_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_service = MissingPaperTradingService(_detail())
    missing_app = create_app()
    missing_app.state.paper_trading_service = missing_service

    missing = await _request(
        missing_app,
        "GET",
        f"/api/v1/paper-accounts/{ACCOUNT_ID}/performance",
    )

    monkeypatch.setattr("app.main.AppSettings", lambda: AppSettings(database_url=None))
    unavailable = await _request(
        create_app(),
        "GET",
        f"/api/v1/paper-accounts/{ACCOUNT_ID}/performance",
    )

    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "paper_storage_unavailable"


class FakePaperTradingService:
    def __init__(self, detail: PaperAccountDetail) -> None:
        self.detail = detail
        self.manual_requests: list[ManualPaperIntent] = []

    async def get_performance(self, account_id: UUID) -> PaperPerformanceSnapshot:
        assert account_id == ACCOUNT_ID
        return _performance_snapshot()

    async def create_account(self, request: PaperAccountCreate) -> PaperAccountDetail:
        assert request.initial_cash == Decimal("10000")
        return self.detail

    async def list_accounts(self, filters: PaperAccountFilters) -> PaperAccountPage:
        return PaperAccountPage(
            items=(),
            page=filters.page,
            page_size=filters.page_size,
            total=0,
        )

    async def get_account(self, account_id: UUID) -> PaperAccountDetail:
        assert account_id == ACCOUNT_ID
        return self.detail

    async def submit_manual_intent(
        self,
        account_id: UUID,
        request: ManualPaperIntent,
    ) -> PaperAccountDetail:
        assert account_id == ACCOUNT_ID
        self.manual_requests.append(request)
        return self.detail

    async def evaluate_strategy(self, account_id: UUID) -> PaperAccountDetail:
        assert account_id == ACCOUNT_ID
        return self.detail

    async def archive_account(self, account_id: UUID) -> PaperAccountDetail:
        assert account_id == ACCOUNT_ID
        return self.detail


class MissingPaperTradingService(FakePaperTradingService):
    async def get_performance(self, account_id: UUID) -> PaperPerformanceSnapshot:
        assert account_id == ACCOUNT_ID
        raise PaperAccountNotFoundError("未找到模拟账户")


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, json=payload)


def _detail() -> PaperAccountDetail:
    account = PaperAccount(
        id=ACCOUNT_ID,
        status=PaperAccountStatus.ACTIVE,
        symbol=ContractSymbol.BTCUSDT,
        initial_cash=Decimal("10000"),
        cash=Decimal("10000"),
        equity=Decimal("10000"),
        peak_equity=Decimal("10000"),
        daily_start_equity=Decimal("10000"),
        daily_realized_loss=Decimal("0"),
        daily_day=NOW.date(),
        cooldown_remaining=0,
        last_closed_candle_at=None,
        risk_config=DEFAULT_RISK_CONFIG,
        execution_config=DEFAULT_EXECUTION_CONFIG,
        created_at=NOW,
        archived_at=None,
    )
    return PaperAccountDetail(
        account=account,
        position=PaperPosition(
            account_id=ACCOUNT_ID,
            quantity=Decimal("0"),
            average_entry_price=None,
            remaining_entry_cost=Decimal("0"),
            opened_at=None,
            updated_at=NOW,
        ),
        latest_snapshot=None,
        orders=(),
        fills=(),
        ledger_entries=(),
        events=(),
        action_outcome=PaperActionOutcome(
            kind=PaperActionOutcomeKind.FILLED,
            source=IntentSource.MANUAL,
            idempotency_key="paper:manual:test",
        ),
    )


def _performance_snapshot() -> PaperPerformanceSnapshot:
    return PaperPerformanceSnapshot(
        account_id=ACCOUNT_ID,
        initial_cash=Decimal("10000"),
        current_equity=Decimal("9500"),
        net_pnl=Decimal("-500"),
        return_fraction=Decimal("-0.05"),
        realized_pnl=Decimal("-500"),
        unrealized_pnl=Decimal("0"),
        total_fee=Decimal("5"),
        max_drawdown_amount=Decimal("500"),
        max_drawdown_fraction=Decimal("0.05"),
        open_fill_count=1,
        close_fill_count=1,
        profitable_close_count=0,
        unprofitable_close_count=1,
        break_even_close_count=0,
        close_win_rate=Decimal("0"),
        decision_stats=PaperDecisionStats(
            manual_intent_count=1,
            strategy_evaluation_count=0,
            no_signal_count=0,
            risk_rejected_count=0,
            risk_exit_count=0,
            order_count=2,
            fill_count=2,
        ),
        history_status=PaperHistoryStatus.COMPLETE,
        history_started_at=NOW,
        history_ended_at=NOW,
        equity_curve=(
            PaperPerformancePoint(
                at=NOW,
                cash=Decimal("9500"),
                position_quantity=Decimal("0"),
                equity=Decimal("9500"),
                net_pnl=Decimal("-500"),
            ),
        ),
        generated_at=NOW,
    )
