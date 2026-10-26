# 研究标识格式：只验证 USDT 标识形态；目录负责实际准入，动态字符串不进入静态交易、回测或模拟盘契约。
# 公开行情领域：统一研究行情模型、固定公开来源适配器与冻结快照读取；不访问私有账户。
"""Research identifiers are format validated; admission belongs to the directory."""

import re
from typing import Annotated

from pydantic import PlainValidator, WithJsonSchema

_RESEARCH_SYMBOL_PATTERN = r"^[A-Z0-9]+USDT$"


# 验证研究标识长度和大写 USDT 格式；预置币种保留静态枚举身份，其他标识仍是研究字符串。
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
