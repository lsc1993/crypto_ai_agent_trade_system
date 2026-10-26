# 独立技术报告仓储协议支持 v1/v2 联合结果，并保存不可变证据与可选队列租约。
# 未装配仓储时查询和保存都明确失败，不返回虚假的空结果或未保存报告。
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.market.symbols import ResearchSymbol
from app.reports.contracts import ReportStorageUnavailableError
from app.reports.technical_plan import TechnicalReportDocument
from app.reports.technical_runs import TechnicalRunLease


# 分页允许混合历史 v1 与当前 v2 文档，页码、大小和总数各自有界。
class TechnicalReportPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True, extra="forbid")
    items: tuple[TechnicalReportDocument, ...]
    page: int = Field(ge=1)
    page_size: int = Field(serialization_alias="pageSize", ge=1, le=100)
    total: int = Field(ge=0)


# 保存结果需同时固定证据，可选租约供实现核对当前队列所有权。
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


# 占位实现统一报告安全存储错误，不能当成已落库或暂无历史数据。
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
