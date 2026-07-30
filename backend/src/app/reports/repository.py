from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.market.contracts import ContractSymbol
from app.reports.contracts import (
    AnalysisReportCreation,
    AnalysisReportStatus,
    PersistedAnalysisReport,
    ReportPage,
)


class AnalysisReportRepository(Protocol):
    async def persist(
        self,
        creation: AnalysisReportCreation,
    ) -> PersistedAnalysisReport: ...

    async def get_by_id(self, report_id: UUID) -> PersistedAnalysisReport | None: ...

    async def get_by_analysis_id(
        self,
        analysis_id: UUID,
    ) -> PersistedAnalysisReport | None: ...

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        symbol: ContractSymbol | None,
        status: AnalysisReportStatus | None,
    ) -> ReportPage: ...
