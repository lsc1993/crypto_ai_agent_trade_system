# 验证技术 v2 服务只冻结一次输入并逐阶段保留降级结果。
# 模型和进度替身使两阶段调用、总截止时间及保存前所有权检查可观测。
# 行情无效时跳过模型，租约丢失时不能写入报告。
from typing import Any
from uuid import uuid4

import pytest

from app.agent.technical.plan_model import TechnicalDecisionResult, TechnicalPlanModelError
from app.agent.technical.plan_service import TechnicalPlanResearchService
from app.reports.technical_plan import TechnicalContext, TechnicalDecisionSummary
from tests.agent.test_technical_references import decision
from tests.agent.test_technical_service import Market, Repository, technical_clock


# 两阶段模型替身按阶段注入失败并记录上下文对象，检验冻结只发生一次且降级粒度准确。
class Model:
    def __init__(self, failure: str | None = None) -> None:
        self.failure = failure
        self.calls: list[TechnicalContext] = []

    async def analyze(self, context: TechnicalContext) -> TechnicalDecisionResult:
        self.calls.append(context)
        if self.failure == "analysis":
            raise TechnicalPlanModelError("model_output_limit", "analysis")
        return TechnicalDecisionResult(decision(context), ())

    async def compose(
        self, context: TechnicalContext, decision: TechnicalDecisionSummary
    ) -> TechnicalDecisionResult:
        self.calls.append(context)
        if self.failure == "composition":
            raise TechnicalPlanModelError("model_empty_response", "composition")
        return TechnicalDecisionResult(decision, ())


async def noop(*args: Any) -> None:
    pass


# 成功、分析失败和编排失败分别应有不同质量状态；确定性候选始终保留。
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,quality",
    [
        (None, "complete"),
        ("analysis", "analysis_unavailable"),
        ("composition", "composition_fallback"),
    ],
)
async def test_v2_freezes_once_and_preserves_phase_fallback(
    failure: str | None, quality: str
) -> None:
    repository, model = Repository(), Model(failure)
    service = TechnicalPlanResearchService(
        market=Market(), repository=repository, model=model, clock=technical_clock
    )
    report = await service.generate("BTCUSDT", analysis_id=uuid4(), progress=noop, before_save=noop)
    assert report.version == "technical-v2"
    assert report.generation.quality == quality
    assert report.status == ("completed" if failure is None else "degraded")
    assert report.analysis.plans
    assert len(repository.records) == 1
    # 比较对象身份而非值相等，证明两阶段确实共享同一份冻结上下文。
    assert all(ctx is model.calls[0] for ctx in model.calls)
    assert (report.decision is None) == (failure == "analysis")


# 行情质量不足先结束为等待报告，分析与编排都不应调用模型。
@pytest.mark.asyncio
async def test_invalid_market_skips_both_calls() -> None:
    repository, model = Repository(), Model()
    service = TechnicalPlanResearchService(
        market=Market(failed=True), repository=repository, model=model, clock=technical_clock
    )
    report = await service.generate("BTCUSDT", analysis_id=uuid4(), progress=noop, before_save=noop)
    assert report.generation.quality == "data_insufficient"
    assert report.plan_book.stance == "wait"
    assert not model.calls


# 保存前回调模拟租约丢失，即使分析完成也不能继续写入失去所有权的报告。
@pytest.mark.asyncio
async def test_lost_ownership_prevents_save() -> None:
    repository = Repository()
    service = TechnicalPlanResearchService(
        market=Market(), repository=repository, model=Model(), clock=technical_clock
    )

    async def denied() -> None:
        raise RuntimeError("lease_lost")

    with pytest.raises(RuntimeError, match="lease_lost"):
        await service.generate("BTCUSDT", analysis_id=uuid4(), progress=noop, before_save=denied)
    # 保存替身仍为空，证明所有权检查在持久化动作之前生效。
    assert repository.records == []


# 慢分析耗尽总预算后降级，确定性计划仍保存一次，不能把超时当作整次研究不存在。
@pytest.mark.asyncio
async def test_total_deadline_preserves_rules_report() -> None:
    import asyncio

    class SlowModel(Model):
        async def analyze(self, context: TechnicalContext) -> TechnicalDecisionResult:
            await asyncio.sleep(2)
            return await super().analyze(context)

    repository = Repository()
    service = TechnicalPlanResearchService(
        market=Market(),
        repository=repository,
        model=SlowModel(),
        clock=technical_clock,
        timeout_seconds=16,
    )
    report = await service.generate("BTCUSDT", analysis_id=uuid4(), progress=noop, before_save=noop)
    assert report.status == "degraded" and report.error_code == "run_timeout"
    assert report.analysis.plans
    assert len(repository.records) == 1
