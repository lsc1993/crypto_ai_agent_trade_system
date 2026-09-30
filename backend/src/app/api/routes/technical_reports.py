from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from app.api.routes.research_symbols import get_symbol_repository, require_research_symbol
from app.harness.technical_research import TechnicalReportGenerator
from app.market.symbols import ResearchSymbol
from app.reports.technical import TechnicalReport
from app.reports.technical_repository import TechnicalReportPage, TechnicalReportRepository
from app.symbols.repository import SymbolRepository

router = APIRouter(prefix="/technical-reports", tags=["technical-reports"])


class StartTechnicalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: ResearchSymbol


def get_repository(request: Request) -> TechnicalReportRepository:
    return cast(TechnicalReportRepository, request.app.state.technical_report_repository)


def get_service(request: Request) -> TechnicalReportGenerator:
    return cast(TechnicalReportGenerator, request.app.state.technical_research_service)


@router.post("", status_code=201, response_model=TechnicalReport)
async def generate(
    body: StartTechnicalReport,
    service: Annotated[TechnicalReportGenerator, Depends(get_service)],
    symbols: Annotated[SymbolRepository, Depends(get_symbol_repository)],
) -> TechnicalReport:
    await require_research_symbol(symbols, body.symbol)
    return await service.generate(body.symbol)


@router.get("", response_model=TechnicalReportPage)
async def list_reports(
    repository: Annotated[TechnicalReportRepository, Depends(get_repository)],
    symbol: ResearchSymbol | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> TechnicalReportPage:
    # History remains readable after a symbol is archived.
    return await repository.list(symbol=symbol, page=page, page_size=page_size)


@router.get("/{report_id}", response_model=TechnicalReport)
async def get_report(
    report_id: UUID,
    repository: Annotated[TechnicalReportRepository, Depends(get_repository)],
) -> TechnicalReport:
    report = await repository.get(report_id)
    if report is None:
        raise HTTPException(404, "技术研究报告不存在")
    return report
