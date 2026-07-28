from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class _CacheEntry[T]:
    value: T
    expires_at: datetime


class AsyncTtlCache[T]:
    """进程内短时缓存；同键并发读取只执行一次加载器。"""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._entries: dict[str, _CacheEntry[T]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get_or_load(
        self,
        key: str,
        loader: Callable[[], Awaitable[T]],
        ttl: timedelta,
    ) -> T:
        now = self._clock()
        cached = self._entries.get(key)
        if cached is not None and cached.expires_at > now:
            return cached.value

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = self._clock()
            cached = self._entries.get(key)
            if cached is not None and cached.expires_at > now:
                return cached.value
            value = await loader()
            self._entries[key] = _CacheEntry(value=value, expires_at=now + ttl)
            return value
