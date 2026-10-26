# 验证技术 v1 的行情冻结、模型降级和报告关联。
# 行情、模型、仓储与固定时钟替身隔离外部依赖，观察保存内容与运行标识。
# 缺失模型仍保留确定性结果，行情故障不调用模型也不暴露异常原文。
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue

from app.agent.technical.engine import calculate_technical_analysis
from app.agent.technical.model import TechnicalModelError
from app.agent.technical.service import TechnicalResearchService
from app.market.contracts import MarketDataUnavailableError, MarketDetail, MarketTimeframe
from app.reports.technical import TechnicalAnalysis, TechnicalNarrative
from app.reports.technical_plan import TechnicalReportDocument
from app.reports.technical_runs import TechnicalRunLease
from tests.agent.test_technical_engine import NOW, make_technical_detail


# 公开行情替身断言标的和三个周期，失败时返回含敏感文本的领域异常以检查安全映射。
class Market:
    def __init__(self, *, failed: bool = False) -> None:
        self.failed = failed

    async def get_market(
        self, symbol: Any, timeframes: tuple[MarketTimeframe, ...]
    ) -> MarketDetail:
        assert str(symbol) == "BTCUSDT"
        assert timeframes == (MarketTimeframe.H1, MarketTimeframe.H4, MarketTimeframe.D1)
        if self.failed:
            raise MarketDataUnavailableError("untrusted_error", "private upstream payload")
        return make_technical_detail()

    async def get_summaries(self, symbols: tuple[Any, ...]) -> tuple[Any, ...]:
        return ()


# 记录报告与冻结证据保存参数，供验证公开响应与内部审计载荷的分离。
class Repository:
    def __init__(self) -> None:
        self.records: list[tuple[TechnicalReportDocument, dict[str, JsonValue]]] = []

    async def persist(
        self,
        report: TechnicalReportDocument,
        evidence: dict[str, JsonValue],
        *,
        lease: TechnicalRunLease | None = None,
    ) -> TechnicalReportDocument:
        self.records.append((report, evidence))
        return report

    async def get(self, report_id: UUID) -> TechnicalReportDocument | None:
        return next((report for report, _ in self.records if report.id == report_id), None)

    async def get_by_analysis_id(self, analysis_id: UUID) -> TechnicalReportDocument | None:
        return next(
            (report for report, _ in self.records if report.analysis_id == analysis_id), None
        )

    async def list(self, *, symbol: Any, page: int, page_size: int) -> Any:
        raise NotImplementedError


# 只引用传入分析证据的定性模型替身，记录次数并模拟未配置模型的降级。
class Model:
    def __init__(self, *, failed: bool = False) -> None:
        self.calls = 0
        self.failed = failed

    async def generate(self, analysis: TechnicalAnalysis) -> TechnicalNarrative:
        self.calls += 1
        if self.failed:
            raise TechnicalModelError("model_not_configured")
        claim = {
            "text": "量价结构存在延续可能，仍需等待后续收盘确认。",
            "evidenceIds": [str(analysis.evidence_id)],
        }
        return TechnicalNarrative.model_validate(
            {"thesis": claim, "alternative": claim, "risks": [claim]}
        )


def technical_clock() -> datetime:
    return NOW


# 冻结证据保存行情和方法，但公开报告不暴露原始行情；运行标识贯穿保存结果。
@pytest.mark.asyncio
async def test_freezes_closed_evidence_and_saves_report_with_run_id() -> None:
    repository, model = Repository(), Model()
    service = TechnicalResearchService(
        market=Market(), repository=repository, model=model, clock=technical_clock
    )
    run_id = uuid4()
    report = await service.generate("BTCUSDT", analysis_id=run_id)
    assert report.analysis_id == run_id
    assert report.status == "completed"
    assert model.calls == 1
    assert repository.records[0][1]["market"] is not None
    assert "market" not in report.model_dump()
    assert repository.records[0][1]["methodInstructions"]


@pytest.mark.asyncio
async def test_missing_model_preserves_deterministic_result_as_degraded() -> None:
    repository = Repository()
    service = TechnicalResearchService(
        market=Market(), repository=repository, model=Model(failed=True), clock=technical_clock
    )
    report = await service.generate("BTCUSDT", analysis_id=uuid4())
    assert report.status == "degraded"
    assert report.error_code == "model_not_configured"
    assert report.narrative is None
    assert report.analysis.facts is not None
    assert len(repository.records) == 1


@pytest.mark.asyncio
async def test_market_failure_never_calls_model_or_leaks_exception() -> None:
    repository, model = Repository(), Model()
    service = TechnicalResearchService(
        market=Market(failed=True), repository=repository, model=model, clock=technical_clock
    )
    report = await service.generate("BTCUSDT", analysis_id=uuid4())
    assert report.status == "degraded"
    assert report.error_code == "market_unavailable"
    assert report.analysis.plans == ()
    assert model.calls == 0
    assert "private" not in report.model_dump_json()


# 早期重复行必须被完整冻结，重新用保存样本回放应复现相同质量失败而非得到正常分析。
@pytest.mark.asyncio
async def test_frozen_series_reproduce_quality_failure_in_older_rows() -> None:
    detail = make_technical_detail()
    hourly = detail.series[0]
    duplicate = hourly.model_copy(
        update={"candles": hourly.candles[:5] + (hourly.candles[4],) + hourly.candles[5:]}
    )
    detail = detail.model_copy(update={"series": (duplicate, *detail.series[1:])})

    class DefectiveMarket(Market):
        async def get_market(
            self, symbol: Any, timeframes: tuple[MarketTimeframe, ...]
        ) -> MarketDetail:
            return detail

    repository, model = Repository(), Model()
    service = TechnicalResearchService(
        market=DefectiveMarket(), repository=repository, model=model, clock=technical_clock
    )
    report = await service.generate("BTCUSDT", analysis_id=uuid4())
    frozen = repository.records[0][1]["market"]
    assert isinstance(frozen, dict)
    # 用已保存原样行情重新计算，检验冻结证据足以复现早期坏行的质量判定。
    replay = MarketDetail.model_validate({"summary": frozen["summary"], "series": frozen["series"]})
    assert calculate_technical_analysis(replay, captured_at=NOW) == report.analysis
    assert report.analysis.quality.status == "invalid"
    assert model.calls == 0
