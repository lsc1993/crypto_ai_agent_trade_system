from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.market.symbols import ResearchSymbol
from app.reports.contracts import ReportStorageUnavailableError
from app.reports.technical_plan import TechnicalReportDocument
from app.reports.technical_runs import TechnicalRunLease


class TechnicalReportPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True, extra="forbid")
    items: tuple[TechnicalReportDocument, ...]
    page: int = Field(ge=1)
    page_size: int = Field(serialization_alias="pageSize", ge=1, le=100)
    total: int = Field(ge=0)


class TechnicalReportRepository(Protocol):
    async def persist(
        self,
        report: TechnicalReportDocument,
        evidence: dict[str, JsonValue],
        *,
        lease: TechnicalRunLease | None = None,
    ) -> TechnicalReportDocument: ...

    async def get(self, report_id: UUID) -> TechnicalReportDocument | None: ...

    async def get_by_analysis_id(self, analysis_id: UUID) -> TechnicalReportDocument | None: ...

    async def list(
        self,
        *,
        symbol: ResearchSymbol | None,
        page: int,
        page_size: int,
    ) -> TechnicalReportPage: ...


class UnavailableTechnicalReportRepository:
    async def persist(
        self,
        report: TechnicalReportDocument,
        evidence: dict[str, JsonValue],
        *,
        lease: TechnicalRunLease | None = None,
    ) -> TechnicalReportDocument:
        raise ReportStorageUnavailableError("技术研究报告存储不可用")

    async def get(self, report_id: UUID) -> TechnicalReportDocument | None:
        raise ReportStorageUnavailableError("技术研究报告存储不可用")

    async def get_by_analysis_id(self, analysis_id: UUID) -> TechnicalReportDocument | None:
        raise ReportStorageUnavailableError("技术研究报告存储不可用")

    async def list(
        self,
        *,
        symbol: ResearchSymbol | None,
        page: int,
        page_size: int,
    ) -> TechnicalReportPage:
        raise ReportStorageUnavailableError("技术研究报告存储不可用")
