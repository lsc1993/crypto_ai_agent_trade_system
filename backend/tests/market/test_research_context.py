# 验证公开衍生品与恐惧贪婪历史的上下文采集。
# 固定网关替身保留指标范围，非法指数值映射安全错误。
# 来源地址必须固定且安全，生产装配只复用公开行情网关。
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.market.binance_usdm import (
    BINANCE_USDM_BASE_URL,
    BinanceUsdmPublicMarketGateway,
    PublicDerivativesMetrics,
)
from app.market.contracts import ContractSymbol, MarketDataUnavailableError
from app.market.research_context import (
    ALTERNATIVE_ME_BASE_URL,
    AlternativeMeFearGreedGateway,
    PublicResearchContextCollector,
)

NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


class StubDerivativesGateway:
    async def get_research_metrics(
        self,
        symbol: ContractSymbol,
    ) -> PublicDerivativesMetrics:
        assert symbol is ContractSymbol.BTCUSDT
        return PublicDerivativesMetrics(
            basis_rate=Decimal("0.0004"),
            long_short_account_ratio=Decimal("1.2345"),
            taker_buy_sell_ratio=Decimal("0.8765"),
            observed_at=NOW,
            fetched_at=NOW,
        )


@pytest.mark.asyncio
async def test_public_context_uses_fixed_binance_metrics_and_fear_greed_history() -> None:
    requests: list[httpx.Request] = []
    history = [
        {
            "value": str(value),
            "value_classification": "Fear",
            "timestamp": str(int((NOW - timedelta(days=index)).timestamp())),
        }
        for index, value in enumerate((31, 32, 33, 34, 35, 36, 37, 39))
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": history})

    async with httpx.AsyncClient(
        base_url=ALTERNATIVE_ME_BASE_URL,
        transport=httpx.MockTransport(handler),
    ) as client:
        collector = PublicResearchContextCollector(
            derivatives=StubDerivativesGateway(),
            fear_greed=AlternativeMeFearGreedGateway(
                client=client,
                clock=lambda: NOW,
            ),
        )

        context = await collector.collect(ContractSymbol.BTCUSDT, captured_at=NOW)

    assert context.basis_rate == Decimal("0.0004")
    assert context.long_short_account_ratio == Decimal("1.2345")
    assert context.taker_buy_sell_ratio == Decimal("0.8765")
    assert context.fear_greed_value == 31
    assert context.fear_greed_classification == "Fear"
    assert context.fear_greed_change_7d == -8
    assert context.observed_at == NOW
    assert context.fear_greed_7d_start_at == NOW - timedelta(days=7)
    assert requests[0].url.path == "/fng/"
    assert requests[0].url.params == httpx.QueryParams({"limit": "8", "format": "json"})


@pytest.mark.asyncio
async def test_fear_greed_gateway_rejects_non_fixed_or_insecure_base_url() -> None:
    async with httpx.AsyncClient(base_url="http://api.alternative.me") as client:
        with pytest.raises(ValueError, match="Alternative.me"):
            AlternativeMeFearGreedGateway(
                client=client,
                clock=lambda: NOW,
            )


@pytest.mark.asyncio
async def test_context_maps_invalid_fear_greed_values_to_a_safe_error() -> None:
    async with httpx.AsyncClient(
        base_url=ALTERNATIVE_ME_BASE_URL,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "value": "101",
                            "value_classification": "Fear",
                            "timestamp": str(int((NOW - timedelta(days=index)).timestamp())),
                        }
                        for index in range(8)
                    ]
                },
            )
        ),
    ) as client:
        collector = PublicResearchContextCollector(
            derivatives=StubDerivativesGateway(),
            fear_greed=AlternativeMeFearGreedGateway(
                client=client,
                clock=lambda: NOW,
            ),
        )

        with pytest.raises(MarketDataUnavailableError) as error:
            await collector.collect(ContractSymbol.BTCUSDT, captured_at=NOW)

    assert error.value.code == "market_context_unavailable"


@pytest.mark.asyncio
async def test_production_context_factory_reuses_only_the_public_binance_gateway() -> None:
    from app.main import build_public_research_context_collector

    async with (
        httpx.AsyncClient(base_url=BINANCE_USDM_BASE_URL) as binance_client,
        httpx.AsyncClient(base_url=ALTERNATIVE_ME_BASE_URL) as alternative_client,
    ):
        collector = build_public_research_context_collector(
            market_gateway=BinanceUsdmPublicMarketGateway(
                client=binance_client,
                clock=lambda: NOW,
            ),
            alternative_client=alternative_client,
            clock=lambda: NOW,
        )

    assert isinstance(collector, PublicResearchContextCollector)
