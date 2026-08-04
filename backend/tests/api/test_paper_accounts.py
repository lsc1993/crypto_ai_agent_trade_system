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
    PaperAccountPage,
    PaperAccountStatus,
    PaperActionOutcome,
    PaperActionOutcomeKind,
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


class FakePaperTradingService:
    def __init__(self, detail: PaperAccountDetail) -> None:
        self.detail = detail
        self.manual_requests: list[ManualPaperIntent] = []

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
