# 验证 Binance USDⓈ-M 公开 exchangeInfo 规则解析：使用真实过滤器而非精度字段。
# 测试使用固定合成响应、真实网关 MockTransport 和可控时钟，不联网、不访问账户或私有档位。
# 同时证明缓存命中沿用来源抓取时间，以及网关异常在适配器边界转换为规划领域错误。
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import httpx
import pytest

from app.infrastructure.market_rules.binance_usdm import BinanceUsdmPublicRuleReader
from app.market.binance_usdm import (
    BINANCE_USDM_BASE_URL,
    BinanceUsdmPublicMarketGateway,
    PublicExchangeFilter,
    PublicExchangeSymbol,
)
from app.shared.agent_types import ProductKey
from app.trade_planning.input_repository import PlanningInputRepository
from app.trade_planning.input_service import PlanningInputService, PlanningServiceError
from app.trade_planning.inputs import PlanningRuleUnavailableError

NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)


# 构造首期产品键；规则读取器只接受 USDT 线性永续产品。
def _product(symbol: str = "BTCUSDT") -> ProductKey:
    return ProductKey(
        venue="binance_usdm",
        symbol=symbol,
        settlement="USDT",
        kind="linear_perpetual",
    )


# 构造完整合成 exchangeInfo 标的；pricePrecision 故意与 tickSize 不一致。
def _symbol(
    *,
    symbol: str = "BTCUSDT",
    contract_type: str = "PERPETUAL",
    quote_asset: str = "USDT",
    margin_asset: str = "USDT",
    status: str = "TRADING",
    filters: tuple[PublicExchangeFilter, ...] | None = None,
    fetched_at: datetime = NOW,
) -> PublicExchangeSymbol:
    return PublicExchangeSymbol(
        symbol=symbol,
        contract_type=contract_type,
        status=status,
        base_asset="BTC",
        quote_asset=quote_asset,
        margin_asset=margin_asset,
        price_precision=2,
        quantity_precision=3,
        filters=filters
        or (
            PublicExchangeFilter(
                "PRICE_FILTER",
                {"minPrice": "556.80", "maxPrice": "4529764", "tickSize": "0.10"},
            ),
            PublicExchangeFilter(
                "LOT_SIZE",
                {"minQty": "0.001", "maxQty": "1000", "stepSize": "0.001"},
            ),
            PublicExchangeFilter(
                "MARKET_LOT_SIZE",
                {"minQty": "0.001", "maxQty": "120", "stepSize": "0.001"},
            ),
            PublicExchangeFilter("MIN_NOTIONAL", {"notional": "100"}),
        ),
        order_types=("LIMIT", "MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET"),
        time_in_force=("GTC", "IOC", "FOK"),
        fetched_at=fetched_at,
    )


# 固定返回预置标的的替身网关；不发起 HTTP，也不模拟未声明的私有接口。
@dataclass
class FakeGateway:
    symbol: PublicExchangeSymbol | None

    async def get_exchange_symbol_rules(self, symbol: str) -> PublicExchangeSymbol | None:
        if self.symbol is None or self.symbol.symbol != symbol:
            return None
        return self.symbol


# 可推进时钟用于验证网关缓存命中和重新抓取边界。
@dataclass
class MutableClock:
    value: datetime = NOW

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


async def no_sleep(_: float) -> None:
    return None


# 真实网关测试使用的最小 exchangeInfo 响应；只含规则解析所需公开字段。
def _exchange_info_payload(*, filters: object | None = None) -> dict[str, object]:
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "contractType": "PERPETUAL",
                "status": "TRADING",
                "baseAsset": "BTC",
                "quoteAsset": "USDT",
                "marginAsset": "USDT",
                "pricePrecision": 2,
                "quantityPrecision": 3,
                "filters": filters
                if filters is not None
                else [
                    {
                        "filterType": "PRICE_FILTER",
                        "minPrice": "556.80",
                        "maxPrice": "4529764",
                        "tickSize": "0.10",
                    },
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.001",
                        "maxQty": "1000",
                        "stepSize": "0.001",
                    },
                    {
                        "filterType": "MARKET_LOT_SIZE",
                        "minQty": "0.001",
                        "maxQty": "120",
                        "stepSize": "0.001",
                    },
                    {"filterType": "MIN_NOTIONAL", "notional": "100"},
                ],
                "orderTypes": ["LIMIT", "MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET"],
                "timeInForce": ["GTC", "IOC", "FOK"],
            }
        ]
    }


# 构造真实网关和 MockTransport；requests 用于证明缓存命中未发起新 HTTP。
def _gateway(
    clock: MutableClock,
    requests: list[httpx.Request],
    *,
    payload: Callable[[], object] | None = None,
    fail_network: bool = False,
) -> tuple[httpx.AsyncClient, BinanceUsdmPublicMarketGateway]:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if fail_network:
            raise httpx.ConnectError("synthetic network failure", request=request)
        return httpx.Response(
            200, json=payload() if payload is not None else _exchange_info_payload()
        )

    client = httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    return client, BinanceUsdmPublicMarketGateway(client=client, clock=clock, sleep=no_sleep)


@pytest.mark.asyncio
async def test_parses_tick_size_not_price_precision() -> None:
    reader = BinanceUsdmPublicRuleReader(gateway=FakeGateway(_symbol()))
    snapshot = await reader.load(_product())

    # pricePrecision=2 会得到 0.01；正确实现必须采用 PRICE_FILTER.tickSize=0.10。
    assert snapshot.price_tick == Decimal("0.10")
    assert snapshot.quantity_step == Decimal("0.001")
    assert snapshot.market_quantity_step == Decimal("0.001")
    assert snapshot.min_notional == Decimal("100")
    assert snapshot.contract_multiplier == Decimal("1")
    assert snapshot.quantity_unit == "base_asset"
    assert snapshot.observed_at == NOW
    assert snapshot.expires_at == NOW + timedelta(minutes=60)
    assert snapshot.source == "binance_usdm_public_exchange_info"


@pytest.mark.asyncio
async def test_rejects_missing_or_duplicate_required_filters() -> None:
    missing_price = _symbol(
        filters=(
            PublicExchangeFilter(
                "LOT_SIZE",
                {"minQty": "0.001", "maxQty": "1000", "stepSize": "0.001"},
            ),
            PublicExchangeFilter(
                "MARKET_LOT_SIZE",
                {"minQty": "0.001", "maxQty": "120", "stepSize": "0.001"},
            ),
            PublicExchangeFilter("MIN_NOTIONAL", {"notional": "100"}),
        )
    )
    with pytest.raises(PlanningRuleUnavailableError):
        await BinanceUsdmPublicRuleReader(gateway=FakeGateway(missing_price)).load(_product())

    duplicate = _symbol(filters=(*_symbol().filters, _symbol().filters[0]))
    with pytest.raises(PlanningRuleUnavailableError):
        await BinanceUsdmPublicRuleReader(gateway=FakeGateway(duplicate)).load(_product())


@pytest.mark.asyncio
async def test_rejects_wrong_product_and_invalid_decimal_rules() -> None:
    with pytest.raises(PlanningRuleUnavailableError):
        await BinanceUsdmPublicRuleReader(
            gateway=FakeGateway(_symbol(contract_type="CURRENT_QUARTER"))
        ).load(_product())

    with pytest.raises(PlanningRuleUnavailableError):
        await BinanceUsdmPublicRuleReader(gateway=FakeGateway(_symbol(margin_asset="BTC"))).load(
            _product()
        )

    invalid_price = _symbol(
        filters=(
            PublicExchangeFilter(
                "PRICE_FILTER",
                {"minPrice": "1", "maxPrice": "2", "tickSize": "NaN"},
            ),
            *_symbol().filters[1:],
        )
    )
    with pytest.raises(PlanningRuleUnavailableError):
        await BinanceUsdmPublicRuleReader(gateway=FakeGateway(invalid_price)).load(_product())


@pytest.mark.asyncio
async def test_missing_symbol_and_non_trading_status_are_explicit() -> None:
    with pytest.raises(PlanningRuleUnavailableError):
        await BinanceUsdmPublicRuleReader(gateway=FakeGateway(None)).load(_product())

    # 规则快照可以记录非交易状态，但调用方必须能确定性识别不可用。
    halted = await BinanceUsdmPublicRuleReader(gateway=FakeGateway(_symbol(status="HALT"))).load(
        _product()
    )
    assert halted.trading_status == "HALT"
    assert halted.is_trading is False


@pytest.mark.asyncio
async def test_cache_hit_preserves_source_time_and_expiry_window() -> None:
    clock = MutableClock()
    requests: list[httpx.Request] = []
    client, gateway = _gateway(clock, requests)
    try:
        first = await gateway.get_exchange_symbol_rules("BTCUSDT")
        assert first is not None
        assert first.fetched_at == NOW
        assert len(requests) == 1

        # 缓存命中时 gate 只复用原响应，不能把本地读取时间当作新的来源观测。
        clock.advance(timedelta(minutes=4, seconds=59))
        cached = await gateway.get_exchange_symbol_rules("BTCUSDT")
        assert cached is not None
        assert cached.fetched_at == NOW
        assert len(requests) == 1

        reader = BinanceUsdmPublicRuleReader(gateway=gateway)
        snapshot = await reader.load(_product())
        assert snapshot.observed_at == NOW
        assert snapshot.expires_at == NOW + timedelta(minutes=60)

        # 越过 5 分钟缓存后才重新抓取并推进来源时间。
        clock.advance(timedelta(seconds=2))
        refreshed = await gateway.get_exchange_symbol_rules("BTCUSDT")
        assert refreshed is not None
        assert refreshed.fetched_at == clock.value
        assert len(requests) == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_gateway_errors_become_planning_rule_errors() -> None:
    clock = MutableClock()
    requests: list[httpx.Request] = []
    client, gateway = _gateway(
        clock,
        requests,
        payload=lambda: _exchange_info_payload(filters="invalid"),
    )
    try:
        reader = BinanceUsdmPublicRuleReader(gateway=gateway)
        with pytest.raises(PlanningRuleUnavailableError) as error:
            await reader.load(_product())
        assert error.value.code == "planning_rule_unavailable"
    finally:
        await client.aclose()

    network_requests: list[httpx.Request] = []
    network_client, network_gateway = _gateway(
        clock,
        network_requests,
        fail_network=True,
    )
    try:
        reader = BinanceUsdmPublicRuleReader(gateway=network_gateway)
        with pytest.raises(PlanningRuleUnavailableError) as network_error:
            await reader.load(_product())
        assert network_error.value.code == "planning_rule_unavailable"
    finally:
        await network_client.aclose()


@pytest.mark.asyncio
async def test_rule_expiry_boundary_is_sixty_minutes_from_source_time() -> None:
    # 来源时刻 + 60 分钟整点即失效；本地重建快照不能把窗口继续顺延。
    source_time = NOW - timedelta(minutes=60)
    gateway = FakeGateway(_symbol(fetched_at=source_time))
    service = PlanningInputService(
        cast(PlanningInputRepository, _ReplayMissRepository()),
        rule_reader=BinanceUsdmPublicRuleReader(gateway=gateway),
        clock=lambda: NOW,
    )
    with pytest.raises(PlanningRuleUnavailableError, match="已过期"):
        await service.refresh_venue_rules(uuid4(), _product(), request_id=uuid4())


class _ReplayMissRepository:
    # 服务边界测试只需证明上游错误可由 PlanningServiceError 捕获；不写数据库。
    async def replay_venue_rules(
        self,
        workspace_id: object,
        product: ProductKey,
        *,
        request_id: object,
    ) -> None:
        return None


@pytest.mark.asyncio
async def test_service_caller_can_catch_planning_rule_error() -> None:
    clock = MutableClock()
    requests: list[httpx.Request] = []
    client, gateway = _gateway(
        clock,
        requests,
        payload=lambda: _exchange_info_payload(filters="invalid"),
    )
    try:
        service = PlanningInputService(
            cast(PlanningInputRepository, _ReplayMissRepository()),
            rule_reader=BinanceUsdmPublicRuleReader(gateway=gateway),
        )
        with pytest.raises(PlanningServiceError) as error:
            await service.refresh_venue_rules(uuid4(), _product(), request_id=uuid4())
        assert isinstance(error.value, PlanningRuleUnavailableError)
    finally:
        await client.aclose()
