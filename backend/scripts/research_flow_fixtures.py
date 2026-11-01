# 为离线流程评估提供受限合成行情与内存仓储，绝不读取环境、网络或测试私有 helper。
# 行情由版本化 recipe 确定性展开为 Decimal/UTC 领域契约；内存保存先走公开 JSON 解析，
# 只证明服务保存/读取契约，真实数据库保证由专门 migrated_database 回归覆盖。
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.agent.service import CapturedAgentMarket
from app.market.contracts import (
    Candle,
    CandleSeries,
    DataFreshness,
    FreshnessStatus,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.research import PersistedMarketSnapshot
from app.market.symbols import ResearchSymbol
from app.news.service import NewsCollection
from app.reports.contracts import (
    AgentReportCreation,
    PersistedAnalysisEvidence,
    PersistedAnalysisReport,
)
from app.reports.technical_plan import TechnicalReportDocument, parse_technical_report
from app.reports.technical_repository import TechnicalReportPage
from app.reports.technical_runs import TechnicalRunLease

NOW = datetime(2026, 8, 10, tzinfo=UTC)


class MarketRecipe(BaseModel):
    """固定构造算法的版本标识与精确十进制量，不接收任意代码或网络地址。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: Literal["synthetic-breakout-v1"]
    initial_price: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    step: str = Field(pattern=r"^0\.[0-9]+$")
    plateau: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    last_close: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    swing_low: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    swing_high: str = Field(pattern=r"^[0-9]+\.[0-9]+$")


def build_market(recipe: MarketRecipe) -> MarketDetail:
    """展开八十根已收盘多周期行情；转折点与末根量能只用于合成契约场景。"""
    series: list[CandleSeries] = []
    durations = {
        MarketTimeframe.M15: timedelta(minutes=15),
        MarketTimeframe.H1: timedelta(hours=1),
        MarketTimeframe.H4: timedelta(hours=4),
        MarketTimeframe.D1: timedelta(days=1),
    }
    for timeframe, duration in durations.items():
        candles: list[Candle] = []
        for index in range(80):
            close_at = NOW - duration * (79 - index)
            price = Decimal(recipe.initial_price) + Decimal(index) * Decimal(recipe.step)
            if timeframe is MarketTimeframe.H1 and index >= 59:
                price = Decimal(recipe.last_close if index == 79 else recipe.plateau)
            high, low = price + Decimal("1"), price - Decimal("1")
            if timeframe is MarketTimeframe.H1 and index == 70:
                low = Decimal(recipe.swing_low)
            if timeframe is MarketTimeframe.H4 and index == 64:
                high = Decimal(recipe.swing_high)
            candles.append(
                Candle(
                    symbol="BTCUSDT",
                    timeframe=timeframe,
                    open_at=close_at - duration,
                    close_at=close_at,
                    open_price=price,
                    high_price=high,
                    low_price=low,
                    close_price=price,
                    volume=Decimal("200") if index == 79 else Decimal("100"),
                    observed_at=close_at,
                    fetched_at=NOW,
                )
            )
        series.append(CandleSeries(timeframe=timeframe, candles=tuple(candles)))
    return MarketDetail(
        summary=MarketSummary(
            symbol="BTCUSDT",
            price=Decimal(recipe.last_close),
            change_24h=Decimal("0"),
            volume_24h=Decimal("1000"),
            funding_rate=Decimal("0"),
            open_interest=Decimal("100"),
            freshness=DataFreshness(
                status=FreshnessStatus.FRESH,
                source="offline-synthetic",
                observed_at=NOW,
                fetched_at=NOW,
            ),
        ),
        series=tuple(series),
    )


class OfflineMarket:
    """同时满足技术公开网关和综合冻结采集端口；不足场景确定性移除日线。"""

    def __init__(self, detail: MarketDetail, *, insufficient: bool = False) -> None:
        self.detail = detail.model_copy(
            update={
                "series": tuple(
                    item
                    for item in detail.series
                    if not insufficient or item.timeframe is not MarketTimeframe.D1
                )
            }
        )

    async def get_market(
        self, symbol: ResearchSymbol, timeframes: tuple[MarketTimeframe, ...]
    ) -> MarketDetail:
        """只返回请求的冻结周期，绝不向公开交易所发请求。"""
        if symbol != self.detail.summary.symbol:
            raise ValueError("offline_symbol")
        return self.detail.model_copy(
            update={
                "series": tuple(item for item in self.detail.series if item.timeframe in timeframes)
            }
        )

    async def capture(
        self, symbol: ResearchSymbol, *, captured_at: datetime
    ) -> CapturedAgentMarket:
        """综合图收到同一合成摘要与序列；不模拟真实行情数据库已保存的保证。"""
        if symbol != self.detail.summary.symbol or captured_at != NOW:
            raise ValueError("offline_capture")
        return CapturedAgentMarket(
            snapshot_id=uuid4(),
            snapshot=PersistedMarketSnapshot(summary=self.detail.summary, captured_at=NOW),
            detail=self.detail,
        )

    async def get_summaries(self, symbols: tuple[ResearchSymbol, ...]) -> tuple[MarketSummary, ...]:
        """完整实现只读网关端口；评估服务不需要额外读取摘要。"""
        return (self.detail.summary,) if self.detail.summary.symbol in symbols else ()


class OfflineNews:
    """显式的空公开新闻集合；新闻缺失不冒充来源采集成功。"""

    async def collect(
        self, symbol: ResearchSymbol, *, since: datetime, until: datetime
    ) -> NewsCollection:
        """仅满足固定图采集契约，不将合成文字声明为真实新闻证据。"""
        return NewsCollection(
            items=(),
            source_count=0,
            successful_source_count=0,
            failed_source_count=0,
            error_codes=(),
        )


class MemoryTechnicalRepository:
    """以 JSON 冻结技术文档并重新解析读取，使保存结果不会借对象身份假通过。"""

    def __init__(self) -> None:
        self.documents: dict[UUID, dict[str, JsonValue]] = {}

    async def persist(
        self,
        report: TechnicalReportDocument,
        evidence: dict[str, JsonValue],
        *,
        lease: TechnicalRunLease | None = None,
    ) -> TechnicalReportDocument:
        """只追加一次；内存替身不验证租约或提供数据库原子审计保证。"""
        if report.id in self.documents:
            raise ValueError("offline_duplicate")
        self.documents[report.id] = report.model_dump(mode="json")
        return parse_technical_report(self.documents[report.id])

    async def get(self, report_id: UUID) -> TechnicalReportDocument | None:
        """读取冻结副本，不重算指标或重新调用模型。"""
        document = self.documents.get(report_id)
        return None if document is None else parse_technical_report(document)

    async def get_by_analysis_id(self, analysis_id: UUID) -> TechnicalReportDocument | None:
        """按研究标识查询保存副本，支持服务合同检查。"""
        for document in self.documents.values():
            report = parse_technical_report(document)
            if report.analysis_id == analysis_id:
                return report
        return None

    async def list(
        self, *, symbol: ResearchSymbol | None, page: int, page_size: int
    ) -> TechnicalReportPage:
        """按与生产协议一致的分页形状返回内存历史。"""
        reports = tuple(parse_technical_report(item) for item in self.documents.values())
        reports = tuple(item for item in reports if symbol is None or item.symbol == symbol)
        return TechnicalReportPage(
            items=reports[(page - 1) * page_size : page * page_size],
            page=page,
            page_size=page_size,
            total=len(reports),
        )


class MemoryResearchRepository:
    """把真实综合服务创建请求映射成公开报告后冻结，保留其安全错误及证据关系。"""

    def __init__(self) -> None:
        self.documents: dict[UUID, str] = {}

    async def persist_agent(self, creation: AgentReportCreation) -> PersistedAnalysisReport:
        """内存保存报告和证据只用于离线契约，不代表真实 SQL 仓储已获验证。"""
        report = PersistedAnalysisReport(
            **creation.report.model_dump(),
            created_at=creation.completed_at,
            generator_kind=creation.generator_kind,
            evidence=tuple(
                PersistedAnalysisEvidence(
                    id=evidence.id,
                    **evidence.model_dump(),
                    created_at=creation.completed_at,
                )
                for evidence in creation.evidences
            ),
            agent_analysis=creation.agent_analysis,
            validation_failure=creation.validation_failure,
        )
        self.documents[report.id] = report.model_dump_json()
        return PersistedAnalysisReport.model_validate_json(self.documents[report.id])

    async def get(self, report_id: UUID) -> PersistedAnalysisReport | None:
        """仅解析已保存 JSON，避免返回未真正经过保存接口的临时对象。"""
        value = self.documents.get(report_id)
        return None if value is None else PersistedAnalysisReport.model_validate_json(value)
