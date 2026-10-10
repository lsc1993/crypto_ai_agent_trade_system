from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.market.symbols import ResearchSymbol
from app.reports.technical_runs import TechnicalRun, TechnicalRunPhase, TechnicalRunStatus


class TechnicalRunRepository(Protocol):
    async def enqueue(
        self, symbol: ResearchSymbol, *, request_id: UUID, now: datetime
    ) -> TechnicalRun: ...
    async def get(self, run_id: UUID) -> TechnicalRun | None: ...
    async def claim(self, *, owner: UUID, now: datetime) -> TechnicalRun | None: ...
    async def heartbeat(self, run_id: UUID, *, owner: UUID, now: datetime) -> bool: ...
    async def advance(
        self, run_id: UUID, *, owner: UUID, phase: TechnicalRunPhase, now: datetime
    ) -> bool: ...
    async def finish(
        self,
        run_id: UUID,
        *,
        owner: UUID,
        status: TechnicalRunStatus,
        report_id: UUID | None,
        error_code: str | None,
        now: datetime,
    ) -> bool: ...
    async def recover_expired(self, *, now: datetime) -> int: ...
