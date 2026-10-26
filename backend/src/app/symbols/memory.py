# 无数据库目录替身：只提供预置 BTC/ETH 只读记录，写入和排队明确失败；
# 不能把内存返回值当作持久化同步。
# 研究币种目录：公开合约检查通过后登记币种并排队初始同步；研究准入不扩展交易契约。
"""Small read-only directory used when the application has no database.

It preserves existing BTC/ETH read-only routes in local development while
making mutations fail explicitly instead of pretending that sync was durable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.symbols.contracts import (
    Capability,
    CheckResult,
    ResearchSymbolEntry,
    SymbolError,
    SyncRun,
    SyncSource,
)


# 无数据库模式的只读 BTC/ETH 目录，写入和任务排队明确不可用。
class StaticSymbolRepository:
    # 建立两个预置币种的只读目录，能力来自固定声明而非本次同步结果。
    def __init__(self) -> None:
        now = datetime.now(UTC)
        capabilities = (
            Capability(name="market", status="supported", message="公开行情可用。"),
            Capability(name="candles", status="supported", message="公开 K 线可用。"),
            Capability(name="derivatives", status="supported", message="公开衍生品指标可用。"),
            Capability(name="funding", status="supported", message="公开资金费率可用。"),
            Capability(name="news", status="supported", message="公开资讯可用。"),
            Capability(name="sentiment", status="supported", message="公开情绪数据可用。"),
            Capability(name="etf", status="unsupported", message="当前数据源不支持"),
        )
        self._entries = {
            f"{base}USDT": ResearchSymbolEntry(
                symbol=f"{base}USDT",
                base_asset=base,
                quote_asset="USDT",
                margin_asset="USDT",
                contract_type="PERPETUAL",
                enabled=True,
                capabilities=capabilities,
                version=1,
                created_at=now,
                can_research=True,
            )
            for base in ("BTC", "ETH")
        }

    # 忽略归档参数，始终返回全部预置条目；该只读替身没有归档状态变化。
    async def list(self, *, include_archived: bool = False) -> tuple[ResearchSymbolEntry, ...]:
        del include_archived
        return tuple(self._entries.values())

    # 按研究标识读取目录条目，不存在时返回空值。
    async def get(self, symbol: str) -> ResearchSymbolEntry | None:
        return self._entries.get(symbol)

    # 无数据库模式禁止此写入操作，明确抛出存储不可用错误；不创建假持久化结果。
    async def add(
        self,
        check: CheckResult,
        *,
        keywords: tuple[str, ...],
        now: datetime,
    ) -> ResearchSymbolEntry:
        del check, keywords, now
        raise _unavailable()

    # 无数据库模式禁止此写入操作，明确抛出存储不可用错误；不创建假持久化结果。
    async def archive(self, symbol: str, *, now: datetime) -> ResearchSymbolEntry:
        del symbol, now
        raise _unavailable()

    # 无数据库模式禁止此写入操作，明确抛出存储不可用错误；不创建假持久化结果。
    async def enqueue(self, symbol: str, *, now: datetime) -> SyncRun:
        del symbol, now
        raise _unavailable()

    # 无数据库模式没有持久化同步任务，此方法返回空值或失败标记。
    async def get_run(self, run_id: UUID) -> SyncRun | None:
        del run_id
        return None

    # 无数据库模式没有持久化同步任务，此方法返回空值或失败标记。
    async def claim(self, *, now: datetime) -> SyncRun | None:
        del now
        return None

    # 无数据库模式没有持久化同步任务，此方法返回空值或失败标记。
    async def renew(self, run: SyncRun, *, now: datetime) -> bool:
        del run, now
        return False

    # 无数据库模式没有持久化同步任务，此方法返回空值或失败标记。
    async def finish(
        self,
        run: SyncRun,
        *,
        status: str,
        sources: tuple[SyncSource, ...],
        snapshot_id: UUID | None,
        error: str | None,
        now: datetime,
    ) -> bool:
        del run, status, sources, snapshot_id, error, now
        return False

    # 无数据库模式禁止此写入操作，明确抛出存储不可用错误；不创建假持久化结果。
    async def record_check(self, check: CheckResult, *, now: datetime) -> None:
        del check, now
        raise _unavailable()


# 构造或抛出本模块统一的安全不可用错误，避免向调用方暴露底层细节。
def _unavailable() -> SymbolError:
    return SymbolError("research_symbol_storage_unavailable", "研究币对存储暂时不可用。", 503)
