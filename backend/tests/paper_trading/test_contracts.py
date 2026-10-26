# 验证模拟账户初始现金必须使用精确十进制输入。
# 合法金额用于确认契约可构造，浮点值则在边界处拒绝。
# 测试针对本地账户模型，不访问交易所账户。
from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest

from app.paper_trading.contracts import PaperAccountCreate


def test_paper_account_creation_accepts_decimal_cash_and_rejects_float_input() -> None:
    creation = PaperAccountCreate(initial_cash=Decimal("10000"))

    assert creation.initial_cash == Decimal("10000")
    with pytest.raises(ValueError, match="浮点数"):
        PaperAccountCreate(initial_cash=cast(Decimal, 10000.0))
