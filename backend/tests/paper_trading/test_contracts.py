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
