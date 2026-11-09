# 验证首期手动规划支持目录：仅 BTC/ETH、USDT 线性永续、逐仓、单向、新入场。
# 支持判断是确定性纯函数，不读取账户、不查询交易所、不扩大研究或模拟盘目录。
from __future__ import annotations

from decimal import Decimal

from app.shared.agent_types import ProductKey
from app.trade_planning.product_support import PlanningProductCatalog


# 构造首期产品键；测试不依赖研究币种动态目录。
def _product(symbol: str = "BTCUSDT") -> ProductKey:
    return ProductKey(
        venue="binance_usdm",
        symbol=symbol,
        settlement="USDT",
        kind="linear_perpetual",
    )


def test_catalog_accepts_only_supported_products_and_isolated_one_way() -> None:
    catalog = PlanningProductCatalog()

    assert catalog.accepts("BTCUSDT", mode="isolated")
    assert catalog.accepts("ETHUSDT", mode="isolated")
    assert not catalog.accepts("BTCUSDT", mode="cross")
    assert not catalog.accepts("BTCUSDT", position_mode="hedge")
    assert not catalog.accepts("SOLUSDT", mode="isolated")
    assert {item.symbol for item in catalog.supported_products} == {"BTCUSDT", "ETHUSDT"}


def test_existing_exposure_unknown_blocks_instead_of_treating_as_zero() -> None:
    # 未知已有仓位/挂单不能被当作空仓；未知与显式零必须产生不同结论。
    catalog = PlanningProductCatalog()
    unknown = catalog.evaluate(
        product=_product(),
        margin_mode="isolated",
        position_mode="one_way",
        existing_position_notional=Decimal("0"),
        existing_position_margin=Decimal("0"),
        existing_position_risk=None,
        open_order_notional=Decimal("0"),
        open_order_margin=Decimal("0"),
        open_order_risk=Decimal("0"),
    )
    assert unknown.supported is False
    assert unknown.reason_code == "existing_exposure_unknown"

    empty = catalog.evaluate(
        product=_product(),
        margin_mode="isolated",
        position_mode="one_way",
        existing_position_notional=Decimal("0"),
        existing_position_margin=Decimal("0"),
        existing_position_risk=Decimal("0"),
        open_order_notional=Decimal("0"),
        open_order_margin=Decimal("0"),
        open_order_risk=Decimal("0"),
    )
    assert empty.supported is True
    assert empty.reason_code == "supported"

    occupied = catalog.evaluate(
        product=_product(),
        margin_mode="isolated",
        position_mode="one_way",
        existing_position_notional=Decimal("0"),
        existing_position_margin=Decimal("0"),
        existing_position_risk=Decimal("10"),
        open_order_notional=Decimal("0"),
        open_order_margin=Decimal("0"),
        open_order_risk=Decimal("0"),
    )
    assert occupied.supported is False
    assert occupied.reason_code == "existing_position_unsupported"

    # 风险为零但名义占用非零同样阻断；同品种合并风险未实现，不能只看风险字段。
    notional_only = catalog.evaluate(
        product=_product(),
        margin_mode="isolated",
        position_mode="one_way",
        existing_position_notional=Decimal("100"),
        existing_position_margin=Decimal("0"),
        existing_position_risk=Decimal("0"),
        open_order_notional=Decimal("0"),
        open_order_margin=Decimal("0"),
        open_order_risk=Decimal("0"),
    )
    assert notional_only.supported is False
    assert notional_only.reason_code == "existing_position_unsupported"


def test_unsupported_mode_and_order_type_are_rejected_explicitly() -> None:
    catalog = PlanningProductCatalog()
    cross = catalog.evaluate(
        product=_product(),
        margin_mode="cross",
        position_mode="one_way",
        existing_position_notional=Decimal("0"),
        existing_position_margin=Decimal("0"),
        existing_position_risk=Decimal("0"),
        open_order_notional=Decimal("0"),
        open_order_margin=Decimal("0"),
        open_order_risk=Decimal("0"),
    )
    assert cross.supported is False
    assert cross.reason_code == "margin_mode_unsupported"

    unlimited = catalog.evaluate(
        product=_product(),
        margin_mode="isolated",
        position_mode="one_way",
        existing_position_notional=Decimal("0"),
        existing_position_margin=Decimal("0"),
        existing_position_risk=Decimal("0"),
        open_order_notional=Decimal("0"),
        open_order_margin=Decimal("0"),
        open_order_risk=Decimal("0"),
        requested_order_types=("TRAILING_STOP_MARKET",),
    )
    assert unlimited.supported is False
    assert unlimited.reason_code == "order_type_unsupported"

    unsupported = catalog.evaluate(
        product=_product("SOLUSDT"),
        margin_mode="isolated",
        position_mode="one_way",
        existing_position_notional=Decimal("0"),
        existing_position_margin=Decimal("0"),
        existing_position_risk=Decimal("0"),
        open_order_notional=Decimal("0"),
        open_order_margin=Decimal("0"),
        open_order_risk=Decimal("0"),
    )
    assert unsupported.supported is False
    assert unsupported.reason_code == "product_not_supported"
