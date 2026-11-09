# 验证 Binance USDⓈ-M 公开 exchangeInfo 规则解析：使用真实过滤器而非精度字段。
# 测试使用固定合成响应，不联网、不访问账户、不读取私有档位，也不打印真实规则资料。
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.infrastructure.market_rules.binance_usdm import BinanceUsdmPublicRuleReader
from app.market.binance_usdm import PublicExchangeFilter, PublicExchangeSymbol
from app.shared.agent_types import ProductKey
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


# 构造完整的合成 exchangeInfo 标的；pricePrecision 故意与 tickSize 不一致。
def _symbol(
    *,
    symbol: str = "BTCUSDT",
    contract_type: str = "PERPETUAL",
    quote_asset: str = "USDT",
    margin_asset: str = "USDT",
    status: str = "TRADING",
    filters: tuple[PublicExchangeFilter, ...] | None = None,
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
    )


# 固定返回预置标的的替身网关；不发起 HTTP，也不模拟未声明的私有接口。
@dataclass
class FakeGateway:
    symbol: PublicExchangeSymbol | None

    async def get_exchange_symbol_rules(self, symbol: str) -> PublicExchangeSymbol | None:
        if self.symbol is None or self.symbol.symbol != symbol:
            return None
        return self.symbol


@dataclass
class FixedClock:
    value: datetime = NOW

    def __call__(self) -> datetime:
        return self.value


@pytest.mark.asyncio
async def test_parses_tick_size_not_price_precision() -> None:
    reader = BinanceUsdmPublicRuleReader(gateway=FakeGateway(_symbol()), clock=FixedClock())
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
        await BinanceUsdmPublicRuleReader(
            gateway=FakeGateway(missing_price), clock=FixedClock()
        ).load(_product())

    duplicate = _symbol(filters=(*_symbol().filters, _symbol().filters[0]))
    with pytest.raises(PlanningRuleUnavailableError):
        await BinanceUsdmPublicRuleReader(gateway=FakeGateway(duplicate), clock=FixedClock()).load(
            _product()
        )


@pytest.mark.asyncio
async def test_rejects_wrong_product_and_invalid_decimal_rules() -> None:
    with pytest.raises(PlanningRuleUnavailableError):
        await BinanceUsdmPublicRuleReader(
            gateway=FakeGateway(_symbol(contract_type="CURRENT_QUARTER")),
            clock=FixedClock(),
        ).load(_product())

    with pytest.raises(PlanningRuleUnavailableError):
        await BinanceUsdmPublicRuleReader(
            gateway=FakeGateway(_symbol(margin_asset="BTC")),
            clock=FixedClock(),
        ).load(_product())

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
        await BinanceUsdmPublicRuleReader(
            gateway=FakeGateway(invalid_price), clock=FixedClock()
        ).load(_product())


@pytest.mark.asyncio
async def test_missing_symbol_and_non_trading_status_are_explicit() -> None:
    with pytest.raises(PlanningRuleUnavailableError):
        await BinanceUsdmPublicRuleReader(gateway=FakeGateway(None), clock=FixedClock()).load(
            _product()
        )

    # 规则快照可以记录非交易状态，但调用方必须能确定性识别不可用。
    halted = await BinanceUsdmPublicRuleReader(
        gateway=FakeGateway(_symbol(status="HALT")), clock=FixedClock()
    ).load(_product())
    assert halted.trading_status == "HALT"
    assert halted.is_trading is False
