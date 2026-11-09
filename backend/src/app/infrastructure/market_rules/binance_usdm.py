# Binance USDⓈ-M 公开 exchangeInfo 规则适配器：把真实过滤器冻结为 VenueRuleSnapshot。
# 数据流：受控公开网关 -> 类型化合约元数据 -> PRICE_FILTER/LOT_SIZE/MARKET_LOT_SIZE/
# MIN_NOTIONAL 严格 Decimal 解析 -> 带来源/时刻/60 分钟有效期的不可变规则快照。
# 不使用 pricePrecision/quantityPrecision 推断 tick/step，不读取账户、仓位、杠杆档位或签名接口。
from __future__ import annotations

from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from app.market.binance_usdm import PublicExchangeFilter, PublicExchangeSymbol
from app.market.contracts import MarketDataUnavailableError
from app.shared.agent_types import ProductKey, parse_decimal_text, require_utc
from app.trade_planning.inputs import (
    VENUE_RULE_VALIDITY,
    PlanningRuleUnavailableError,
    VenueRuleSnapshot,
)

RULE_SOURCE = "binance_usdm_public_exchange_info"


# 公开网关协议只暴露类型化 exchangeInfo 读取；测试替身不能借此访问私有接口。
class ExchangeSymbolGateway(Protocol):
    async def get_exchange_symbol_rules(self, symbol: str) -> PublicExchangeSymbol | None: ...


# 规则读取器；观测时间来自网关真实抓取时间，不按本地读取时刻重算。
class BinanceUsdmPublicRuleReader:
    def __init__(self, *, gateway: ExchangeSymbolGateway) -> None:
        self._gateway = gateway

    # 读取并冻结一个产品的公开规则快照；缺失、重复或不支持的字段明确失败。
    async def load(self, product: ProductKey) -> VenueRuleSnapshot:
        symbol = str(product.symbol)
        try:
            typed = await self._gateway.get_exchange_symbol_rules(symbol)
        except MarketDataUnavailableError as error:
            # 网关只把受控公开读取的类型化失败抛到这里；不吞掉未知异常或回显上游正文。
            raise PlanningRuleUnavailableError("公开规则读取不可用") from error
        if typed is None:
            raise PlanningRuleUnavailableError("公开 exchangeInfo 未提供该产品")
        _validate_product(product, typed)
        filters = _filters_by_type(typed.filters)
        price = _require_filter(filters, "PRICE_FILTER")
        lot = _require_filter(filters, "LOT_SIZE")
        market_lot = _require_filter(filters, "MARKET_LOT_SIZE")
        notional = _require_filter(filters, "MIN_NOTIONAL")

        min_price = _decimal_field(price, "minPrice")
        max_price = _decimal_field(price, "maxPrice")
        price_tick = _decimal_field(price, "tickSize")
        quantity_step = _decimal_field(lot, "stepSize")
        min_quantity = _decimal_field(lot, "minQty")
        max_quantity = _decimal_field(lot, "maxQty")
        market_quantity_step = _decimal_field(market_lot, "stepSize")
        market_min_quantity = _decimal_field(market_lot, "minQty")
        market_max_quantity = _decimal_field(market_lot, "maxQty")
        min_notional = _decimal_field(
            notional,
            "notional" if "notional" in notional.values else "minNotional",
        )

        observed_at = require_utc(typed.fetched_at)
        try:
            return VenueRuleSnapshot.build(
                version_id=uuid4(),
                product=product,
                contract_multiplier=Decimal("1"),
                quantity_unit="base_asset",
                price_tick=price_tick,
                min_price=min_price,
                max_price=max_price,
                quantity_step=quantity_step,
                min_quantity=min_quantity,
                max_quantity=max_quantity,
                market_min_quantity=market_min_quantity,
                market_max_quantity=market_max_quantity,
                market_quantity_step=market_quantity_step,
                min_notional=min_notional,
                trading_status=typed.status,
                order_types=typed.order_types,
                time_in_force=typed.time_in_force,
                observed_at=observed_at,
                expires_at=observed_at + VENUE_RULE_VALIDITY,
                source=RULE_SOURCE,
            )
        except ValueError as error:
            raise PlanningRuleUnavailableError("公开规则快照内容无效") from error


# 校验公开合约元数据与请求产品一致；结算/产品不一致直接拒绝，避免同名不同产品混用。
def _validate_product(product: ProductKey, typed: PublicExchangeSymbol) -> None:
    if str(product.symbol) != typed.symbol:
        raise PlanningRuleUnavailableError("公开规则标的不一致")
    if product.settlement != "USDT" or product.kind != "linear_perpetual":
        raise PlanningRuleUnavailableError("首期只支持 USDT 线性永续公开规则")
    if typed.contract_type != "PERPETUAL":
        raise PlanningRuleUnavailableError("公开规则合约类型不是永续")
    if typed.quote_asset != "USDT" or typed.margin_asset != "USDT":
        raise PlanningRuleUnavailableError("公开规则不是 USDT 结算产品")


# 按 filterType 建唯一索引；重复类型无法确定性选择，按不可用拒绝。
def _filters_by_type(
    filters: tuple[PublicExchangeFilter, ...],
) -> dict[str, PublicExchangeFilter]:
    result: dict[str, PublicExchangeFilter] = {}
    for item in filters:
        if item.filter_type in result:
            raise PlanningRuleUnavailableError("公开规则包含重复过滤器")
        result[item.filter_type] = item
    return result


# 读取必需过滤器；缺失时不能以默认值猜测 tick/step/最小名义额。
def _require_filter(
    filters: dict[str, PublicExchangeFilter],
    filter_type: str,
) -> PublicExchangeFilter:
    value = filters.get(filter_type)
    if value is None:
        raise PlanningRuleUnavailableError(f"公开规则缺少 {filter_type} 过滤器")
    return value


# 严格解析公开过滤器中的十进制字符串；拒绝指数、NaN/Infinity 和非正边界值。
def _decimal_field(item: PublicExchangeFilter, field: str) -> Decimal:
    raw = item.values.get(field)
    if raw is None:
        raise PlanningRuleUnavailableError("公开规则过滤器字段缺失")
    try:
        value = parse_decimal_text(raw)
    except ValueError as error:
        raise PlanningRuleUnavailableError("公开规则过滤器字段无效") from error
    if value <= 0:
        raise PlanningRuleUnavailableError("公开规则过滤器边界必须大于零")
    return value


__all__ = ["BinanceUsdmPublicRuleReader", "RULE_SOURCE"]
