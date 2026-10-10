from typing import Any
from uuid import uuid4

import pytest

from app.agent.technical.plan_model import TechnicalDecisionResult, TechnicalPlanModelError
from app.agent.technical.plan_service import TechnicalPlanResearchService
from app.reports.technical_plan import TechnicalContext, TechnicalDecisionSummary
from tests.agent.test_technical_references import decision
from tests.agent.test_technical_service import Market, Repository, technical_clock


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
    assert all(ctx is model.calls[0] for ctx in model.calls)
    assert (report.decision is None) == (failure == "analysis")


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
    assert repository.records == []


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
