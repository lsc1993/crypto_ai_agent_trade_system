# 进程内异步缓存：有效期内直接返回，过期后按键加锁加载并更新；加载失败不会创建缓存值。
# 公开行情领域：统一研究行情模型、固定公开来源适配器与冻结快照读取；不访问私有账户。
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta


# 不可变缓存记录，将加载结果与到期时刻一起保存。
@dataclass(frozen=True)
class _CacheEntry[T]:
    value: T
    expires_at: datetime


# 同键加载串行化，成功且未过期的结果可供等待者复用；失败不缓存。
class AsyncTtlCache[T]:
    """进程内短时缓存；同键并发读取只执行一次加载器。"""

    # 初始化本实例依赖和配置；输入 clock。
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._entries: dict[str, _CacheEntry[T]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # 按键读取有效缓存；过期后在同键锁内二次检查，再运行加载器并按读取时钟设置过期时间。
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

        # 每个键使用独立锁，不同标的不会互相阻塞；锁内必须再次检查缓存，复用其他协程刚完成的加载。
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = self._clock()
            cached = self._entries.get(key)
            if cached is not None and cached.expires_at > now:
                return cached.value
            # 只在加载器成功返回后写入缓存；异常继续上抛，不能用旧结果冒充本次成功。
            value = await loader()
            # 到期时刻以本次加载前读取的时钟为基准，较慢的请求会消耗部分有效期。
            self._entries[key] = _CacheEntry(value=value, expires_at=now + ttl)
            return value
