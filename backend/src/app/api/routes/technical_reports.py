from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes.research_symbols import get_symbol_repository, require_research_symbol
from app.harness.technical_research import TechnicalReportGenerator
from app.market.symbols import ResearchSymbol
from app.reports.technical import TechnicalReport
from app.reports.technical_plan import TechnicalReportDocument
from app.reports.technical_repository import TechnicalReportPage, TechnicalReportRepository
from app.reports.technical_run_repository import TechnicalRunRepository
from app.reports.technical_runs import TechnicalRun, TechnicalRunError
from app.symbols.repository import SymbolRepository

router = APIRouter(prefix="/technical-reports", tags=["technical-reports"])


class StartTechnicalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: ResearchSymbol


class StartTechnicalRun(StartTechnicalReport):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    request_id: UUID = Field(alias="requestId")


def get_runs(request: Request) -> TechnicalRunRepository:
    repository = request.app.state.technical_run_repository
    if repository is None:
        raise HTTPException(
            503,
            {"code": "storage_unavailable", "message": "技术研究任务存储不可用。", "details": {}},
        )
    return cast(TechnicalRunRepository, repository)


def run_error(error: TechnicalRunError) -> HTTPException:
    status = {"request_conflict": 409, "queue_full": 429, "storage_unavailable": 503}[error.code]
    return HTTPException(
        status, {"code": error.code, "message": "技术研究任务暂不可用。", "details": {}}
    )


@router.post("/runs", status_code=202, response_model=TechnicalRun)
async def start_run(
    body: StartTechnicalRun,
    repository: Annotated[TechnicalRunRepository, Depends(get_runs)],
    symbols: Annotated[SymbolRepository, Depends(get_symbol_repository)],
) -> TechnicalRun:
    await require_research_symbol(symbols, body.symbol)
    try:
        return await repository.enqueue(
            body.symbol, request_id=body.request_id, now=datetime.now(UTC)
        )
    except TechnicalRunError as error:
        raise run_error(error) from None


@router.get("/runs/{run_id}", response_model=TechnicalRun)
async def get_run(
    run_id: UUID, repository: Annotated[TechnicalRunRepository, Depends(get_runs)]
) -> TechnicalRun:
    try:
        run = await repository.get(run_id)
    except TechnicalRunError as error:
        raise run_error(error) from None
    if run is None:
        raise HTTPException(404, "技术研究任务不存在")
    return run


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


@router.get("/{report_id}", response_model=TechnicalReportDocument)
async def get_report(
    report_id: UUID,
    repository: Annotated[TechnicalReportRepository, Depends(get_repository)],
) -> TechnicalReportDocument:
    report = await repository.get(report_id)
    if report is None:
        raise HTTPException(404, "技术研究报告不存在")
    return report
