# 验证研究币种输入规范化与关键词长度限制。
# 用户文本可归一化，但不能扩大静态交易币种集合。
# 非法符号和非纯文本关键词在准入之前拒绝。
from importlib import import_module
from importlib.util import find_spec
from types import ModuleType

import pytest
from pydantic import ValidationError


def contracts() -> ModuleType:
    assert find_spec('app.symbols') is not None, 'Research symbol management is not implemented'
    return import_module('app.symbols.contracts')


def test_symbol_input_normalizes_user_text_without_expanding_trading_symbols():
    models = contracts()
    request = models.SymbolInput(symbol=' solusdt ', keywords=[' Solana ', 'Solana'])
    assert request.symbol == 'SOLUSDT'
    assert request.keywords == ('Solana',)
    from app.market.contracts import ContractSymbol

    with pytest.raises(ValueError):
        ContractSymbol('SOLUSDT')


@pytest.mark.parametrize('symbol', ['SOLBTC', '../BTCUSDT', 'BTC/USDT', 'USDT', 'A' * 30 + 'USDT'])
def test_symbol_input_rejects_values_outside_the_research_contract(symbol: str) -> None:
    with pytest.raises(ValidationError):
        contracts().SymbolInput(symbol=symbol)


@pytest.mark.parametrize('keywords', [['https://example.com'], ['.*'], ['x'] * 21])
def test_news_keywords_are_bounded_plain_text(keywords: list[str]) -> None:
    with pytest.raises(ValidationError):
        contracts().SymbolInput(symbol='SOLUSDT', keywords=keywords)
