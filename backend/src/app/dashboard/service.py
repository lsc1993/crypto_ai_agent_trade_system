import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, PlainSerializer, field_validator

from app.market.contracts import ContractSymbol, MarketSummary, UtcDateTime
from app.market.service import MarketQueryService
from app.reports.contracts import (
    AnalysisReportStatus,
    AnalysisReportSummary,
    ReportGeneratorKind,
)
from app.reports.repository import AnalysisReportRepository


def _serialize_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


DashboardUtcDateTime = Annotated[
    datetime,
    PlainSerializer(_serialize_utc, return_type=str, when_used="json"),
]


class _DashboardModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda value: "".join(
            [
                value.split("_")[0],
                *(part.capitalize() for part in value.split("_")[1:]),
            ]
        ),
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class DashboardReportSummary(_DashboardModel):
    id: UUID
    analysis_id: UUID
    symbol: ContractSymbol
    status: AnalysisReportStatus
    title: str
    summary: str
    created_at: UtcDateTime
    data_cutoff_at: UtcDateTime | None
    generator_kind: ReportGeneratorKind

    @classmethod
    def from_report(cls, report: AnalysisReportSummary) -> "DashboardReportSummary":
        return cls(
            id=report.id,
            analysis_id=report.analysis_id,
            symbol=report.symbol,
            status=report.status,
            title=report.title,
            summary=report.summary,
            created_at=report.created_at,
            data_cutoff_at=report.data_cutoff_at,
            generator_kind=report.generator_kind,
        )


class DashboardSnapshot(_DashboardModel):
    markets: tuple[MarketSummary, ...]
    news: tuple[()]
    recent_reports: tuple[DashboardReportSummary, ...]
    generated_at: DashboardUtcDateTime

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("仪表盘生成时间必须是 UTC 且带时区")
        return value


class DashboardService:
    def __init__(
        self,
        market: MarketQueryService,
        reports: AnalysisReportRepository,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._market = market
        self._reports = reports
        self._clock = clock

    async def get_snapshot(self) -> DashboardSnapshot:
        markets, reports = await asyncio.gather(
            self._market.get_summaries(
                (ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT),
            ),
            self._reports.list(
                page=1,
                page_size=5,
                symbol=None,
                status=None,
            ),
        )
        return DashboardSnapshot(
            markets=markets,
            news=(),
            recent_reports=tuple(
                DashboardReportSummary.from_report(report) for report in reports.items
            ),
            generated_at=self._clock(),
        )
