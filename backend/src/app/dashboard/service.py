# 看板聚合：并发读取行情与最近五条报告，投影报告安全摘要后返回快照；当前新闻字段固定为空。
# 看板领域：聚合公开行情与已保存报告的安全摘要，供只读展示；不执行研究或交易。
import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, PlainSerializer, field_validator

from app.market.contracts import MarketSummary, UtcDateTime
from app.market.service import MarketQueryService
from app.market.symbols import ResearchSymbol
from app.reports.contracts import (
    AnalysisReportStatus,
    AnalysisReportSummary,
    ReportGeneratorKind,
)
from app.reports.repository import AnalysisReportRepository


# 将带时区时间转为 UTC 的标准字符串，使用末尾 Z 表明零时区。
def _serialize_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


DashboardUtcDateTime = Annotated[
    datetime,
    PlainSerializer(_serialize_utc, return_type=str, when_used="json"),
]


# 看板响应公共基类，冻结值、拒绝额外字段并以驼峰字段名输出。
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


# 已保存报告的安全摘要投影，供看板展示标题、摘要、状态与关联元数据。
class DashboardReportSummary(_DashboardModel):
    id: UUID
    analysis_id: UUID
    symbol: ResearchSymbol
    status: AnalysisReportStatus
    title: str
    summary: str
    created_at: UtcDateTime
    data_cutoff_at: UtcDateTime | None
    generator_kind: ReportGeneratorKind

    # 将已保存报告摘要投影为看板字段，保留运行关联和生成方式。
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


# 只读看板结果，由行情、当前空新闻列表、最近报告和 UTC 生成时刻组成。
class DashboardSnapshot(_DashboardModel):
    markets: tuple[MarketSummary, ...]
    news: tuple[()]
    recent_reports: tuple[DashboardReportSummary, ...]
    generated_at: DashboardUtcDateTime

    # 校验generated_at 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：仪表盘生成时间必须是 UTC 且带时区。
    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("仪表盘生成时间必须是 UTC 且带时区")
        return value


# 并发读取行情与已保存报告，生成安全的只读看板响应。
class DashboardService:
    # 初始化本实例依赖和配置；输入 market、reports、clock。
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

    # 并发读取选定研究标的行情与最近五条报告，返回当前看板快照；新闻列表保持为空。
    async def get_snapshot(self, symbol: ResearchSymbol | None = None) -> DashboardSnapshot:
        symbols: tuple[ResearchSymbol, ...] = (
            (symbol,) if symbol is not None else ("BTCUSDT", "ETHUSDT")
        )
        markets, reports = await asyncio.gather(
            self._market.get_summaries(symbols),
            self._reports.list(
                page=1,
                page_size=5,
                symbol=symbol,
                status=None,
            ),
        )
        return DashboardSnapshot(
            markets=markets,
            # 当前看板没有新闻列表读取路径，字段为空不能解读为新一轮采集完成但没有条目。
            news=(),
            recent_reports=tuple(
                DashboardReportSummary.from_report(report) for report in reports.items
            ),
            generated_at=self._clock(),
        )
