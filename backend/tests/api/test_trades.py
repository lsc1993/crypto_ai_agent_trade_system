from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from app.main import create_app
from app.market.contracts import ContractSymbol
from app.trades.contracts import (
    PersistedTrade,
    TradeDirection,
    TradeDraft,
    TradeFilters,
    TradeHorizon,
    TradeLegAction,
    TradeLegDraft,
    TradePage,
    TradeStatus,
)
from app.trades.service import TradeNotFoundError

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
TRADE_ID = UUID("00000000-0000-0000-0000-000000000333")


@pytest.mark.asyncio
async def test_trade_routes_create_list_update_and_archive_with_safe_json() -> None:
    service = FakeTradeService()
    repository = FakeTradeRepository(service.trade)
    app = _app(service, repository)
    payload = _draft_payload()

    created = await _request(app, "POST", "/api/v1/trades", payload)
    listed = await _request(
        app,
        "GET",
        "/api/v1/trades?page=2&page_size=10&symbol=BTCUSDT&label=manual",
    )
    updated = await _request(app, "PUT", f"/api/v1/trades/{TRADE_ID}", payload)
    archived = await _request(app, "POST", f"/api/v1/trades/{TRADE_ID}/archive")

    assert created.status_code == 201
    assert created.json()["netPnl"] == "19.7"
    assert created.json()["cashflows"] == []
    assert listed.status_code == 200
    assert listed.json()["page_size"] == 10
    assert repository.filters is not None
    assert repository.filters.page == 2
    assert repository.filters.symbol is ContractSymbol.BTCUSDT
    assert repository.filters.label == "manual"
    assert updated.status_code == 200
    assert service.updated_trade_id == TRADE_ID
    assert archived.status_code == 204
    assert service.archived_trade_id == TRADE_ID


@pytest.mark.asyncio
async def test_trade_routes_use_standard_not_found_and_safe_validation_envelopes() -> None:
    service = FakeTradeService(missing=True)
    app = _app(service, FakeTradeRepository(service.trade))
    invalid_payload = _draft_payload()
    legs = cast(list[dict[str, object]], invalid_payload["legs"])
    first_leg = legs[0]
    invalid_payload["legs"] = [{**first_leg, "price": 99.5}]

    missing = await _request(
        app,
        "PUT",
        "/api/v1/trades/00000000-0000-0000-0000-000000000999",
        _draft_payload(),
    )
    invalid = await _request(app, "POST", "/api/v1/trades", invalid_payload)

    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"
    assert "99.5" not in invalid.text


class FakeTradeService:
    def __init__(self, *, missing: bool = False) -> None:
        self.trade = _persisted_trade()
        self.missing = missing
        self.created: TradeDraft | None = None
        self.updated_trade_id: UUID | None = None
        self.archived_trade_id: UUID | None = None

    async def create_trade(self, draft: TradeDraft) -> PersistedTrade:
        self.created = draft
        return self.trade

    async def update_trade(self, trade_id: UUID, draft: TradeDraft) -> PersistedTrade:
        if self.missing:
            raise TradeNotFoundError("交易不存在或已归档")
        self.updated_trade_id = trade_id
        self.created = draft
        return self.trade

    async def archive_trade(self, trade_id: UUID) -> None:
        if self.missing:
            raise TradeNotFoundError("交易不存在或已归档")
        self.archived_trade_id = trade_id


class FakeTradeRepository:
    def __init__(self, trade: PersistedTrade) -> None:
        self.trade = trade
        self.filters: TradeFilters | None = None

    async def list(self, filters: TradeFilters) -> TradePage:
        self.filters = filters
        return TradePage(
            items=(self.trade,),
            page=filters.page,
            page_size=filters.page_size,
            total=1,
        )


def _app(service: FakeTradeService, repository: FakeTradeRepository) -> FastAPI:
    app = create_app()
    app.state.trade_service = service
    app.state.trade_repository = repository
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


def _draft_payload() -> dict[str, object]:
    return {
        "symbol": "BTCUSDT",
        "direction": "long",
        "horizon": "short_term",
        "labels": ["manual"],
        "linkedReportId": None,
        "leverage": "2",
        "legs": [
            {
                "id": "00000000-0000-0000-0000-000000000101",
                "action": "open",
                "executedAt": "2026-07-31T12:00:00Z",
                "price": "100",
                "quantity": "1",
                "fee": "0.1",
            },
            {
                "id": "00000000-0000-0000-0000-000000000102",
                "action": "close",
                "executedAt": "2026-07-31T13:00:00Z",
                "price": "120",
                "quantity": "1",
                "fee": "0.2",
            },
        ],
        "cashflows": [],
        "thesis": "thesis",
        "review": "review",
    }


def _persisted_trade() -> PersistedTrade:
    draft = TradeDraft(
        symbol=ContractSymbol.BTCUSDT,
        direction=TradeDirection.LONG,
        horizon=TradeHorizon.SHORT_TERM,
        labels=("manual",),
        linked_report_id=None,
        leverage=Decimal("2"),
        legs=(
            TradeLegDraft(
                id=UUID("00000000-0000-0000-0000-000000000101"),
                action=TradeLegAction.OPEN,
                executed_at=NOW,
                sequence=0,
                price=Decimal("100"),
                quantity=Decimal("1"),
                fee=Decimal("0.1"),
            ),
            TradeLegDraft(
                id=UUID("00000000-0000-0000-0000-000000000102"),
                action=TradeLegAction.CLOSE,
                executed_at=NOW.replace(hour=13),
                sequence=1,
                price=Decimal("120"),
                quantity=Decimal("1"),
                fee=Decimal("0.2"),
            ),
        ),
        cashflows=(),
        thesis="thesis",
        review="review",
    )
    return PersistedTrade(
        **draft.model_dump(),
        id=TRADE_ID,
        status=TradeStatus.CLOSED,
        gross_realized_pnl=Decimal("20"),
        total_fees=Decimal("0.3"),
        total_funding_cashflow=Decimal("0"),
        net_pnl=Decimal("19.7"),
        opened_at=NOW,
        closed_at=NOW.replace(hour=13),
        archived_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
