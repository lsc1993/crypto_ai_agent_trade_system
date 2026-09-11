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


class StaticSymbolRepository:
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

    async def list(self, *, include_archived: bool = False) -> tuple[ResearchSymbolEntry, ...]:
        del include_archived
        return tuple(self._entries.values())

    async def get(self, symbol: str) -> ResearchSymbolEntry | None:
        return self._entries.get(symbol)

    async def add(
        self,
        check: CheckResult,
        *,
        keywords: tuple[str, ...],
        now: datetime,
    ) -> ResearchSymbolEntry:
        del check, keywords, now
        raise _unavailable()

    async def archive(self, symbol: str, *, now: datetime) -> ResearchSymbolEntry:
        del symbol, now
        raise _unavailable()

    async def enqueue(self, symbol: str, *, now: datetime) -> SyncRun:
        del symbol, now
        raise _unavailable()

    async def get_run(self, run_id: UUID) -> SyncRun | None:
        del run_id
        return None

    async def claim(self, *, now: datetime) -> SyncRun | None:
        del now
        return None

    async def renew(self, run: SyncRun, *, now: datetime) -> bool:
        del run, now
        return False

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

    async def record_check(self, check: CheckResult, *, now: datetime) -> None:
        del check, now
        raise _unavailable()


def _unavailable() -> SymbolError:
    return SymbolError("research_symbol_storage_unavailable", "研究币对存储暂时不可用。", 503)
