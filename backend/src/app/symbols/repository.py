from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.symbols.contracts import CheckResult, ResearchSymbolEntry, SyncRun, SyncSource


class SymbolRepository(Protocol):
    async def list(self, *, include_archived: bool = False) -> tuple[ResearchSymbolEntry, ...]: ...

    async def get(self, symbol: str) -> ResearchSymbolEntry | None: ...

    async def add(
        self, check: CheckResult, *, keywords: tuple[str, ...], now: datetime
    ) -> ResearchSymbolEntry: ...

    async def archive(self, symbol: str, *, now: datetime) -> ResearchSymbolEntry: ...

    async def enqueue(self, symbol: str, *, now: datetime) -> SyncRun: ...

    async def get_run(self, run_id: UUID) -> SyncRun | None: ...

    async def claim(self, *, now: datetime) -> SyncRun | None: ...

    async def renew(self, run: SyncRun, *, now: datetime) -> bool: ...

    async def finish(
        self,
        run: SyncRun,
        *,
        status: str,
        sources: tuple[SyncSource, ...],
        snapshot_id: UUID | None,
        error: str | None,
        now: datetime,
    ) -> bool: ...

    async def record_check(self, check: CheckResult, *, now: datetime) -> None: ...
