# 验证同键并发请求可复用一次成功且未过期的缓存加载。
# 固定时钟排除时间漂移，加载器让出事件循环以产生并发等待。
# 本用例只断言成功值复用和加载次数，不覆盖过期或失败后的重新加载。
import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.market.cache import AsyncTtlCache


# 两个请求并发进入同一键，检查成功加载在有效期内只执行一次。
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
