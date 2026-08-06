from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.paper_trading.contracts import (
    PaperAccountCreate,
    PaperAccountDetail,
    PaperAccountFilters,
    PaperAccountPage,
    PaperActionOutcome,
    PaperPerformanceData,
    PaperTransition,
)


class PaperTradingRepository(Protocol):
    async def create_account(
        self,
        request: PaperAccountCreate,
        *,
        occurred_at: datetime,
    ) -> PaperAccountDetail: ...

    async def list(self, filters: PaperAccountFilters) -> PaperAccountPage: ...

    async def get_by_id(self, account_id: UUID) -> PaperAccountDetail | None: ...

    async def get_performance_data(
        self,
        account_id: UUID,
    ) -> PaperPerformanceData | None: ...

    async def find_outcome(
        self,
        account_id: UUID,
        idempotency_key: str,
    ) -> PaperActionOutcome | None: ...

    async def apply_transition(
        self,
        account_id: UUID,
        idempotency_key: str,
        transition: PaperTransition,
        *,
        occurred_at: datetime,
    ) -> PaperAccountDetail: ...

    async def record_market_failure(
        self,
        account_id: UUID,
        idempotency_key: str,
        *,
        code: str,
        occurred_at: datetime,
    ) -> PaperAccountDetail: ...

    async def archive(
        self,
        account_id: UUID,
        *,
        occurred_at: datetime,
    ) -> PaperAccountDetail: ...
