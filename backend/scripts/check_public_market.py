from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

from app.market.binance_usdm import (
    BINANCE_USDM_BASE_URL,
    BinanceUsdmPublicMarketGateway,
)
from app.market.contracts import ContractSymbol


async def check_public_market() -> None:
    """Print a small, credential-free snapshot from the public Binance USDⓈ-M API."""
    async with httpx.AsyncClient(
        base_url=BINANCE_USDM_BASE_URL,
        headers={"Accept": "application/json"},
    ) as client:
        gateway = BinanceUsdmPublicMarketGateway(
            client=client,
            clock=lambda: datetime.now(UTC),
        )
        summaries = await gateway.get_summaries(
            (ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT),
        )

    for summary in summaries:
        print(
            f"{summary.symbol.value}: price={summary.price}, "
            f"source={summary.freshness.source}, "
            f"observed_at={summary.freshness.observed_at.isoformat()}, "
            f"fetched_at={summary.freshness.fetched_at.isoformat()}"
        )


if __name__ == "__main__":
    asyncio.run(check_public_market())
