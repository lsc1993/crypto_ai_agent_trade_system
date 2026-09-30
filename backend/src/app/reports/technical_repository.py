from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.market.symbols import ResearchSymbol
from app.reports.contracts import ReportStorageUnavailableError
from app.reports.technical import TechnicalReport


class TechnicalReportPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True, extra="forbid")
    items: tuple[TechnicalReport, ...]
    page: int = Field(ge=1)
    page_size: int = Field(serialization_alias="pageSize", ge=1, le=100)
    total: int = Field(ge=0)


class TechnicalReportRepository(Protocol):
    async def persist(
        self, report: TechnicalReport, evidence: dict[str, JsonValue]
    ) -> TechnicalReport: ...

    async def get(self, report_id: UUID) -> TechnicalReport | None: ...

    async def list(
        self,
        *,
        symbol: ResearchSymbol | None,
        page: int,
        page_size: int,
    ) -> TechnicalReportPage: ...


class UnavailableTechnicalReportRepository:
    async def persist(
        self, report: TechnicalReport, evidence: dict[str, JsonValue]
    ) -> TechnicalReport:
        raise ReportStorageUnavailableError("技术研究报告存储不可用")

    async def get(self, report_id: UUID) -> TechnicalReport | None:
        raise ReportStorageUnavailableError("技术研究报告存储不可用")

    async def list(
        self,
        *,
        symbol: ResearchSymbol | None,
        page: int,
        page_size: int,
    ) -> TechnicalReportPage:
        raise ReportStorageUnavailableError("技术研究报告存储不可用")
