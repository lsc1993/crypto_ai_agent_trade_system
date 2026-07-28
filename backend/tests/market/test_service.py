import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.market.cache import AsyncTtlCache


@pytest.mark.asyncio
async def test_cache_coalesces_concurrent_loads_until_its_ttl_expires() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    calls = 0
    cache = AsyncTtlCache[str](clock=lambda: now)

    async def load() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return "68000.30"

    first, second = await asyncio.gather(
        cache.get_or_load("summary:BTCUSDT", load, timedelta(seconds=10)),
        cache.get_or_load("summary:BTCUSDT", load, timedelta(seconds=10)),
    )

    assert (first, second) == ("68000.30", "68000.30")
    assert calls == 1
