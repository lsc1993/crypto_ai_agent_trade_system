"""Research identifiers are format validated; admission belongs to the directory."""

import re
from typing import Annotated

from pydantic import PlainValidator, WithJsonSchema

_RESEARCH_SYMBOL_PATTERN = r"^[A-Z0-9]+USDT$"


def _research_symbol(value: object) -> str:
    if not isinstance(value, str) or not 5 <= len(value) <= 32:
        raise ValueError("研究币对必须是有效的 USDT 合约标识")
    if re.fullmatch(_RESEARCH_SYMBOL_PATTERN, value) is None:
        raise ValueError("研究币对必须是有效的 USDT 合约标识")
    # Keep the static trading enum at its existing boundary. Dynamic research
    # symbols remain plain strings and cannot enter order, backtest, or paper paths.
    if value in {"BTCUSDT", "ETHUSDT"}:
        from app.market.contracts import ContractSymbol

        return ContractSymbol(value)
    return value


ResearchSymbol = Annotated[
    str,
    PlainValidator(_research_symbol),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": 5,
            "maxLength": 32,
            "pattern": _RESEARCH_SYMBOL_PATTERN,
        }
    ),
]
