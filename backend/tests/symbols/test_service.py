# 验证合约元数据和核心公开数据的研究准入检查。
# 探针替身区分明确不兼容与因网络故障无法验证。
# ETF 非核心条件；币种错配和存储缺失不能通过，失败详情仅含安全摘要。
# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from importlib.util import find_spec
from typing import Any

import pytest

from app.market.binance_usdm import PublicDerivativesMetrics
from app.market.contracts import MarketDataUnavailableError, MarketDetail, MarketTimeframe
from app.market.funding_history import FundingHistory

NOW = datetime(2026, 9, 7, 8, tzinfo=UTC)


def service(gateway: object) -> Any:
    assert find_spec('app.symbols.service') is not None, 'Capability service is missing'
    return import_module('app.symbols.service').SymbolService(None, gateway, clock=lambda: NOW)


class Probe:
    status = 'TRADING'
    quote = 'USDT'
    unavailable = False
    wrong_symbol = False
    oversized_contract_directory = False
    derivatives_unavailable = False
    market_reads = 0

    async def get_exchange_info(self, symbol: str) -> dict[str, str] | None:
        if self.unavailable:
            raise MarketDataUnavailableError('market_data_rate_limited', 'upstream detail')
        if self.oversized_contract_directory:
            raise MarketDataUnavailableError('market_data_response_too_large', 'upstream detail')
        if symbol == 'UNKNOWNUSDT':
            return None
        return dict(symbol=symbol, baseAsset=symbol[:-4], quoteAsset=self.quote,
                    marginAsset='USDT', contractType='PERPETUAL', status=self.status)

    async def get_market(self, symbol: str, timeframes: tuple[MarketTimeframe, ...]) -> MarketDetail:
        self.market_reads += 1
        return MarketDetail.model_validate({
            'summary': {'symbol': 'BTCUSDT' if self.wrong_symbol else symbol,
                'price': '125', 'change24h': '1', 'volume24h': '1000', 'fundingRate': '0.0001',
                'openInterest': '500', 'freshness': {'status': 'fresh', 'source': 'test_public',
                    'observedAt': NOW, 'fetchedAt': NOW}},
            'series': [{'timeframe': frame, 'candles': [{'symbol': symbol, 'timeframe': frame,
                'openAt': NOW - timedelta(days=1), 'closeAt': NOW - timedelta(hours=1),
                'openPrice': '124', 'closePrice': '125', 'highPrice': '126', 'lowPrice': '123',
                'volume': '100', 'observedAt': NOW - timedelta(hours=1), 'fetchedAt': NOW}]}
                for frame in timeframes]})

    async def get_research_metrics(self, symbol: str) -> PublicDerivativesMetrics:
        if self.derivatives_unavailable:
            raise MarketDataUnavailableError('market_data_rate_limited', 'upstream detail')
        return PublicDerivativesMetrics(basis_rate=Decimal('0.01'),
            long_short_account_ratio=Decimal('1.2'), taker_buy_sell_ratio=Decimal('1.1'),
            observed_at=NOW, fetched_at=NOW)

    async def get_funding_history(self, symbol: str, *, since: datetime,
                                  until: datetime) -> FundingHistory:
        return FundingHistory(symbol=symbol, since=since, until=until, fetched_at=NOW, points=())


@pytest.mark.asyncio
async def test_supported_core_does_not_require_etf_coverage() -> None:
    result = await service(Probe()).check('SOLUSDT')
    assert result.supported is True
    assert [(c.status, c.message) for c in result.checks if c.name == 'etf'] == [
        ('unsupported', '当前数据源不支持')]
    assert len(result.checks) == 7


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('status', 'SETTLING'), ('quote', 'USDC')])
async def test_incompatible_contract_is_rejected_before_market_requests(field: str, value: str):
    probe = Probe()
    setattr(probe, field, value)
    result = await service(probe).check('SOLUSDT')
    assert not result.supported
    assert result.checks[0].status == 'unsupported'
    assert probe.market_reads == 0


@pytest.mark.asyncio
async def test_network_failure_is_unverified_not_unsupported() -> None:
    probe = Probe()
    probe.unavailable = True
    result = await service(probe).check('SOLUSDT')
    assert not result.supported
    assert result.checks[0].status == 'unverified'
    assert 'upstream detail' not in result.model_dump_json()


@pytest.mark.asyncio
async def test_derivatives_rate_limit_has_a_safe_actionable_reason() -> None:
    probe = Probe()
    probe.derivatives_unavailable = True

    result = await service(probe).check('ZECUSDT')

    derivatives = next(check for check in result.checks if check.name == 'derivatives')
    assert derivatives.status == 'unverified'
    assert derivatives.message == '公开衍生品指标请求频率受限，请稍后重试。'
    assert 'upstream detail' not in result.model_dump_json()


@pytest.mark.asyncio
async def test_wrong_market_symbol_never_passes_the_core_probe() -> None:
    probe = Probe()
    probe.wrong_symbol = True
    result = await service(probe).check('SOLUSDT')
    assert not result.supported


@pytest.mark.asyncio
async def test_missing_storage_cannot_enable_a_symbol() -> None:
    with pytest.raises(RuntimeError, match='存储'):
        await service(Probe()).add(import_module('app.symbols.contracts').SymbolInput(symbol='SOLUSDT'))


@pytest.mark.asyncio
async def test_add_rejection_includes_safe_admission_check_details() -> None:
    class RecordingRepository:
        async def record_check(self, _check: object, *, now: datetime) -> None:
            assert now == NOW

    probe = Probe()
    probe.oversized_contract_directory = True
    symbol_contracts = import_module('app.symbols.contracts')
    subject = import_module('app.symbols.service').SymbolService(
        RecordingRepository(), probe, clock=lambda: NOW,
    )

    with pytest.raises(symbol_contracts.SymbolError) as rejection:
        await subject.add(symbol_contracts.SymbolInput(symbol='ZECUSDT'))

    assert rejection.value.code == 'research_symbol_unsupported'
    assert rejection.value.details == {
        'check': {
            'symbol': 'ZECUSDT',
            'supported': False,
            'checks': [
                {
                    'name': 'market',
                    'status': 'unverified',
                    'message': '公开合约信息响应超过系统可接受的大小上限，请稍后重试。',
                },
                {
                    'name': 'candles',
                    'status': 'unverified',
                    'message': '公开合约信息响应超过系统可接受的大小上限，请稍后重试。',
                },
                {
                    'name': 'derivatives',
                    'status': 'unverified',
                    'message': '公开合约信息响应超过系统可接受的大小上限，请稍后重试。',
                },
                {
                    'name': 'funding',
                    'status': 'unverified',
                    'message': '公开合约信息响应超过系统可接受的大小上限，请稍后重试。',
                },
                {
                    'name': 'news',
                    'status': 'unverified',
                    'message': '公开合约信息响应超过系统可接受的大小上限，请稍后重试。',
                },
                {
                    'name': 'sentiment',
                    'status': 'unverified',
                    'message': '公开合约信息响应超过系统可接受的大小上限，请稍后重试。',
                },
                {
                    'name': 'etf',
                    'status': 'unverified',
                    'message': '公开合约信息响应超过系统可接受的大小上限，请稍后重试。',
                },
            ],
            'metadata': None,
        },
    }
