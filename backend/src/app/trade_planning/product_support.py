# 定义首期手动规划的受支持产品目录与确定性支持判断。
# 首期只发布 BTCUSDT、ETHUSDT 的 Binance USDT 线性永续、逐仓、单向、新入场；
# 研究币种准入、模拟盘和回测目录不会因本目录自动扩展。已有同品种仓位/挂单在缺少
# 合并风险计算时明确阻断，未知占用不能被当作空仓。
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.shared.agent_types import AgentModel, ProductKey
from app.trade_planning.inputs import (
    MarginMode,
    PlanningProductUnsupportedError,
    PositionMode,
)

# 首期允许的手动订单/触发类型；实际规则快照还须声明对应类型，目录不替代交易所规则。
SUPPORTED_ORDER_TYPES = frozenset({"LIMIT", "MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET"})


# 支持结论携带稳定原因码；调用方据此展示阻断或待补项，不能把 unsupported 当通过。
class ProductSupportDecision(AgentModel):
    product: ProductKey
    supported: bool
    reason_code: str = Field(min_length=1, max_length=64)


# 静态支持目录；目录项是产品身份，不包含账户、余额、杠杆档位或用户资料。
class PlanningProductCatalog:
    # 首批支持目录固定 BTC/ETH；新增产品必须同时提供规则和回归证据。
    _SUPPORTED_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT"})

    @property
    def supported_products(self) -> tuple[ProductKey, ...]:
        return tuple(
            ProductKey(
                venue="binance_usdm",
                symbol=symbol,
                settlement="USDT",
                kind="linear_perpetual",
            )
            for symbol in sorted(self._SUPPORTED_SYMBOLS)
        )

    # 快速判断产品/模式是否在首期范围；成交与资金占用判断由 evaluate 完成。
    def accepts(
        self,
        symbol: str,
        *,
        mode: MarginMode | str = MarginMode.ISOLATED,
        position_mode: PositionMode | str = PositionMode.ONE_WAY,
    ) -> bool:
        try:
            product = ProductKey(
                venue="binance_usdm",
                symbol=symbol,
                settlement="USDT",
                kind="linear_perpetual",
            )
        except ValueError:
            return False
        return self._is_supported(product) and _is_isolated(mode) and _is_one_way(position_mode)

    # 对产品、模式、已有仓位/挂单的全部占用字段和请求订单类型做确定性判断。
    # 任一占用字段未知都优先阻断；任一风险/名义额/保证金非零都表示同品种合并风险未实现。
    def evaluate(
        self,
        *,
        product: ProductKey,
        margin_mode: MarginMode | str | None,
        position_mode: PositionMode | str | None,
        existing_position_notional: Decimal | None,
        existing_position_margin: Decimal | None,
        existing_position_risk: Decimal | None,
        open_order_notional: Decimal | None,
        open_order_margin: Decimal | None,
        open_order_risk: Decimal | None,
        requested_order_types: tuple[str, ...] = ("LIMIT",),
    ) -> ProductSupportDecision:
        if not self._is_supported(product):
            return self._decision(product, "product_not_supported")
        if margin_mode is None or not _is_isolated(margin_mode):
            return self._decision(product, "margin_mode_unsupported")
        if position_mode is None or not _is_one_way(position_mode):
            return self._decision(product, "position_mode_unsupported")
        position_values = (
            existing_position_notional,
            existing_position_margin,
            existing_position_risk,
        )
        order_values = (
            open_order_notional,
            open_order_margin,
            open_order_risk,
        )
        if any(value is None for value in (*position_values, *order_values)):
            return self._decision(product, "existing_exposure_unknown")
        if any(value is not None and value > 0 for value in position_values):
            return self._decision(product, "existing_position_unsupported")
        if any(value is not None and value > 0 for value in order_values):
            return self._decision(product, "open_orders_unsupported")
        unsupported = tuple(
            order_type
            for order_type in requested_order_types
            if order_type not in SUPPORTED_ORDER_TYPES
        )
        if unsupported:
            return self._decision(product, "order_type_unsupported")
        return self._decision(product, "supported")

    # 任何调用方要求“必须是受支持产品”时使用；错误信息不包含用户财务值。
    def require_supported(self, product: ProductKey) -> None:
        if not self._is_supported(product):
            raise PlanningProductUnsupportedError("该产品尚未进入首期手动规划支持目录")

    # 产品身份必须同时匹配固定场所、结算、产品类型和首期币种目录。
    @classmethod
    def _is_supported(cls, product: ProductKey) -> bool:
        return (
            product.venue == "binance_usdm"
            and product.settlement == "USDT"
            and product.kind == "linear_perpetual"
            and str(product.symbol) in cls._SUPPORTED_SYMBOLS
        )

    @staticmethod
    def _decision(product: ProductKey, reason_code: str) -> ProductSupportDecision:
        return ProductSupportDecision(
            product=product,
            supported=reason_code == "supported",
            reason_code=reason_code,
        )


# 字符串/枚举统一比较；未知字符串不抛异常，返回不支持而不是猜测。
def _is_isolated(value: MarginMode | str) -> bool:
    return str(value) == MarginMode.ISOLATED.value


def _is_one_way(value: PositionMode | str) -> bool:
    return str(value) == PositionMode.ONE_WAY.value


# 首期原因码是有限集合；导出便于上层安全映射，不把自由文本错误码暴露给客户端。
SupportReason = Literal[
    "supported",
    "product_not_supported",
    "margin_mode_unsupported",
    "position_mode_unsupported",
    "existing_exposure_unknown",
    "existing_position_unsupported",
    "open_orders_unsupported",
    "order_type_unsupported",
]


__all__ = [
    "SUPPORTED_ORDER_TYPES",
    "PlanningProductCatalog",
    "ProductSupportDecision",
    "SupportReason",
]
