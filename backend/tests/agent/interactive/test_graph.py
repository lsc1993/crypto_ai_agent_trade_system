# T11 有限 LangGraph 测试：验证模型决策路由、原生工具观察回灌、预算结算和等待边界。
# 使用合成上下文/证据与异步替身，不连接数据库、模型、网络或工具实现。
# 断言重点是“模型只是提案”：计划只进入待审、禁止动作不创建待办、预算失败不伪装完成，
# 以及工具批次在硬错误后不会继续执行后续调用。
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from app.agent.interactive.context import ContextBuildError
from app.agent.interactive.deepseek import ModelCallError
from app.agent.interactive.graph import (
    GraphDependencies,
    build_interactive_graph,
    not_executed_tool_message,
)
from app.agent.interactive.model_port import (
    AnalysisStagingError,
    ModelDecision,
)
from app.agent.interactive.state import SegmentOutcomeKind
from app.agent_runs.contracts import AgentRunError
from app.agent_runs.decisions import ControlAction
from app.agent_runs.segments import ExecutionContext, SegmentOutcome
from tests.agent.interactive import graph_fixtures as fixtures


# 汇总一次片段运行的全部替身，便于用例分别断言模型、工具、预算和交互副作用。
@dataclass
class _Harness:
    context: ExecutionContext
    runs: fixtures.FakeRuns
    budget: fixtures.FakeBudget
    evidence: fixtures.FakeEvidence
    contexts: fixtures.FakeContexts
    tools: fixtures.FakeTools
    model: fixtures.FakeModel
    interactions: fixtures.FakeInteractions
    stager: fixtures.FakeStager


# 阻塞模型替身：用于证明 runner 在等待模型时被取消也会在 finally 记录活动时间。
class _BlockingModel:
    requested_model = "synthetic-blocking-model"
    available = True

    def __init__(self) -> None:
        self.started = asyncio.Event()

    def estimate_request(self, context: fixtures.ModelContext) -> int:
        return context.input_reservation

    async def decide(self, context: fixtures.ModelContext) -> ModelDecision:
        _ = context
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("阻塞模型不会返回")


# 运行一次完整片段；所有端口均由测试替身提供，clock 固定以保证交互期限可复现。
async def _run(
    *,
    decisions: list[object],
    tools: fixtures.FakeTools | None = None,
    stager: fixtures.FakeStager | None = None,
    interactions: fixtures.FakeInteractions | None = None,
    runs: fixtures.FakeRuns | None = None,
    budget: fixtures.FakeBudget | None = None,
    contexts: fixtures.FakeContexts | None = None,
    evidence: fixtures.FakeEvidence | None = None,
    model: fixtures.FakeModel | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[SegmentOutcome, _Harness]:
    execution_context = fixtures.context()
    snapshot = fixtures.snapshot(execution_context)
    harness = _Harness(
        context=execution_context,
        runs=runs or fixtures.FakeRuns(snapshot),
        budget=budget or fixtures.FakeBudget(),
        evidence=evidence or fixtures.FakeEvidence(),
        contexts=contexts or fixtures.FakeContexts(fixtures.model_context(execution_context)),
        tools=tools or fixtures.FakeTools(),
        model=model or fixtures.FakeModel(decisions),
        interactions=interactions or fixtures.FakeInteractions(),
        stager=stager or fixtures.FakeStager(),
    )
    runner = build_interactive_graph(
        GraphDependencies(
            runs=harness.runs,
            budget=harness.budget,
            evidence=harness.evidence,
            contexts=harness.contexts,
            tools=harness.tools,
            model=harness.model,
            interactions=harness.interactions,
            artifacts=harness.stager,
            clock=clock or (lambda: fixtures.NOW),
        )
    )
    outcome = await runner.run(execution_context)
    return outcome, harness


@pytest.mark.asyncio
async def test_tool_observation_is_appended_and_model_loop_finishes() -> None:
    batch = fixtures.tool_batch(fixtures.tool_request())
    outcome, harness = await _run(
        decisions=[batch, fixtures.final_analysis()],
    )

    assert len(harness.model.contexts) == 2
    assert len(harness.tools.calls) == 1
    assert len(harness.stager.calls) == 1
    assert outcome.kind is SegmentOutcomeKind.COMPLETED
    assert len(outcome.artifact_refs) == 1

    # 第二次请求必须真实包含 assistant tool_call 与同 call_id 的 tool 结果。
    second_messages = harness.model.contexts[1].messages
    assert second_messages[-2].role == "assistant"
    assert second_messages[-2].tool_calls[0].call_id == "call_1"
    assert second_messages[-1].role == "tool"
    assert second_messages[-1].tool_call_id == "call_1"
    assert "合成只读工具观察" in (second_messages[-1].content or "")

    # 每次模型决策都先预留并提交发送，成功后才结算；没有把工具调用冒充为模型调用。
    assert len(harness.budget.reserve_calls) == 2
    assert len(harness.budget.marked_sent) == 2
    assert len(harness.budget.settled) == 2
    assert all(item[1].status.value == "succeeded" for item in harness.budget.settled)
    assert harness.budget.settled[0][1].result_ref is not None
    assert (
        harness.budget.reserve_calls[0].reserved_input_tokens
        == harness.model.contexts[0].input_reservation
    )
    assert (
        harness.budget.reserve_calls[1].reserved_input_tokens
        == harness.model.contexts[1].input_reservation
    )


@pytest.mark.asyncio
async def test_model_budget_exhaustion_degrades_without_calling_model_or_stager() -> None:
    budget = fixtures.FakeBudget(reserve_error_at=1)
    outcome, harness = await _run(
        decisions=[fixtures.final_analysis()],
        budget=budget,
    )

    assert outcome.kind is SegmentOutcomeKind.DEGRADED
    assert outcome.safe_reason == "budget_exhausted"
    assert harness.model.contexts == []
    assert harness.stager.calls == []
    assert budget.settled == []
    assert budget.marked_sent == []


@pytest.mark.asyncio
async def test_mark_sent_failure_releases_prepared_attempt_and_degrades() -> None:
    budget = fixtures.FakeBudget(mark_sent_error_at=1)
    outcome, harness = await _run(
        decisions=[fixtures.final_analysis()],
        budget=budget,
    )

    assert outcome.kind is SegmentOutcomeKind.DEGRADED
    assert outcome.safe_reason == "budget_exhausted"
    assert len(budget.reserve_calls) == 1
    assert len(budget.settled) == 1
    assert budget.settled[0][1].status.value == "failed"
    assert harness.model.contexts == []


@pytest.mark.asyncio
async def test_model_failure_settles_failed_and_does_not_stage_analysis() -> None:
    outcome, harness = await _run(
        decisions=[
            ModelCallError(
                "model_invalid_response",
                usage=fixtures.TokenUsage(input_tokens=10, output_tokens=2),
            )
        ],
    )

    assert outcome.kind is SegmentOutcomeKind.DEGRADED
    assert outcome.safe_reason == "model_invalid_response"
    assert len(harness.budget.settled) == 1
    settled = harness.budget.settled[0][1]
    assert settled.status.value == "failed"
    assert settled.usage is not None
    assert harness.stager.calls == []


@pytest.mark.asyncio
async def test_model_timeout_is_unknown_and_not_retried() -> None:
    outcome, harness = await _run(
        decisions=[ModelCallError("model_timeout")],
    )

    assert outcome.kind is SegmentOutcomeKind.DEGRADED
    assert outcome.safe_reason == "model_timeout"
    assert len(harness.budget.reserve_calls) == 1
    assert len(harness.budget.settled) == 1
    assert harness.budget.settled[0][1].status.value == "unknown"
    assert harness.budget.settled[0][1].usage is None
    assert len(harness.model.contexts) == 1


@pytest.mark.asyncio
async def test_clarification_ends_segment_without_polling_or_staging() -> None:
    interactions = fixtures.FakeInteractions()
    outcome, harness = await _run(
        decisions=[fixtures.control_proposal(ControlAction.CLARIFY)],
        interactions=interactions,
    )

    assert outcome.kind is SegmentOutcomeKind.WAIT_INPUT
    assert outcome.preparing_interaction_id is not None
    assert len(interactions.drafts) == 1
    assert interactions.drafts[0].action is ControlAction.CLARIFY
    assert len(harness.model.contexts) == 1
    assert harness.stager.calls == []


@pytest.mark.asyncio
async def test_plan_final_analysis_waits_for_approval_and_is_not_executable() -> None:
    reference = fixtures.plan_ref()
    report_reference = fixtures.ArtifactRef(artifact_id=fixtures.uuid4(), sha256="7" * 64)
    stager = fixtures.FakeStager(refs=(report_reference, reference))
    interactions = fixtures.FakeInteractions()
    outcome, harness = await _run(
        decisions=[
            fixtures.final_analysis(
                plan_ref=reference,
                selected_candidate_id="candidate_1",
            )
        ],
        stager=stager,
        interactions=interactions,
    )

    assert outcome.kind is SegmentOutcomeKind.WAIT_APPROVAL
    assert outcome.plan_proposal is None
    assert outcome.artifact_refs == (report_reference, reference)
    assert len(interactions.drafts) == 1
    draft = interactions.drafts[0]
    assert draft.action is ControlAction.ADOPT_MANUAL_PLAN
    assert draft.material_refs == (report_reference, reference)
    assert draft.material_hash
    assert draft.safe_reason == "human_review_required"
    assert len(harness.stager.calls) == 1


@pytest.mark.asyncio
async def test_prohibited_control_action_is_rejected_without_interaction() -> None:
    interactions = fixtures.FakeInteractions()
    outcome, _ = await _run(
        decisions=[
            fixtures.control_proposal(
                ControlAction.EXECUTE_TRADE,
                safe_reason="trade_execution_prohibited",
            )
        ],
        interactions=interactions,
    )

    assert outcome.kind is SegmentOutcomeKind.DEGRADED
    assert outcome.safe_reason == "trade_execution_prohibited"
    assert interactions.drafts == []


@pytest.mark.asyncio
async def test_live_tool_turn_that_exceeds_input_budget_is_degraded() -> None:
    execution_context = fixtures.context()
    base = fixtures.model_context(execution_context, content_repeat=9_000)
    tools = fixtures.FakeTools(summary="x" * 8_192)
    outcome, harness = await _run(
        decisions=[fixtures.tool_batch(fixtures.tool_request()), fixtures.final_analysis()],
        tools=tools,
        contexts=fixtures.FakeContexts(base),
    )

    assert outcome.kind is SegmentOutcomeKind.DEGRADED
    assert outcome.safe_reason == "context_budget_exceeded"
    assert len(harness.model.contexts) == 1
    assert harness.stager.calls == []


@pytest.mark.asyncio
async def test_remaining_tool_calls_are_not_executed_after_hard_tool_error() -> None:
    first = fixtures.tool_request(call_id="call_1")
    second = fixtures.tool_request(call_id="call_2")
    tools = fixtures.FakeTools(
        error_at=1,
        error=AgentRunError("budget_exhausted"),
    )
    outcome, harness = await _run(
        decisions=[fixtures.tool_batch(first, second)],
        tools=tools,
    )

    assert outcome.kind is SegmentOutcomeKind.DEGRADED
    assert outcome.safe_reason == "budget_exhausted"
    assert len(tools.calls) == 1
    assert len(harness.model.contexts) == 1

    message = not_executed_tool_message(second, "tool_batch_stopped")
    assert message.role == "tool"
    assert message.tool_call_id == "call_2"
    assert json.loads(message.content or "{}") == {
        "status": "not_executed",
        "reason": "tool_batch_stopped",
    }


@pytest.mark.asyncio
async def test_cancel_observed_after_model_decision_prevents_tool_execution() -> None:
    execution_context = fixtures.context()
    running = fixtures.snapshot(execution_context)
    cancelled = fixtures.snapshot(execution_context, cancelled_at=fixtures.NOW)
    runs = fixtures.FakeRuns([running, running, cancelled])
    tools = fixtures.FakeTools()
    outcome, _ = await _run(
        decisions=[fixtures.tool_batch(fixtures.tool_request())],
        runs=runs,
        tools=tools,
    )

    assert outcome.kind is SegmentOutcomeKind.CANCELLED
    assert outcome.safe_reason == "user_cancelled"
    assert tools.calls == []


@pytest.mark.asyncio
async def test_initial_cancel_does_not_call_model_or_evidence() -> None:
    execution_context = fixtures.context()
    cancelled = fixtures.snapshot(execution_context, cancelled_at=fixtures.NOW)
    outcome, harness = await _run(
        decisions=[fixtures.final_analysis()],
        runs=fixtures.FakeRuns(cancelled),
    )

    assert outcome.kind is SegmentOutcomeKind.CANCELLED
    assert harness.model.contexts == []
    assert harness.evidence.calls == []


@pytest.mark.asyncio
async def test_context_build_error_is_degraded_without_model_call() -> None:
    outcome, harness = await _run(
        decisions=[fixtures.final_analysis()],
        contexts=fixtures.FakeContexts(error=ContextBuildError("context_budget_exceeded")),
    )

    assert outcome.kind is SegmentOutcomeKind.DEGRADED
    assert outcome.safe_reason == "context_budget_exceeded"
    assert harness.model.contexts == []


@pytest.mark.asyncio
async def test_unknown_analysis_evidence_is_rejected_before_staging() -> None:
    analysis = fixtures.final_analysis(evidence_id=fixtures.uuid4())
    stager = fixtures.FakeStager()
    outcome, _ = await _run(
        decisions=[analysis],
        stager=stager,
    )

    assert outcome.kind is SegmentOutcomeKind.DEGRADED
    assert outcome.safe_reason == "analysis_evidence_unknown"
    assert stager.calls == []


@pytest.mark.asyncio
async def test_artifact_staging_error_is_degraded() -> None:
    stager = fixtures.FakeStager(error=AnalysisStagingError("artifact_invalid"))
    interactions = fixtures.FakeInteractions()
    outcome, _ = await _run(
        decisions=[fixtures.final_analysis()],
        stager=stager,
        interactions=interactions,
    )

    assert outcome.kind is SegmentOutcomeKind.DEGRADED
    assert outcome.safe_reason == "artifact_invalid"
    assert interactions.drafts == []


@pytest.mark.asyncio
async def test_activity_budget_stops_following_calls_after_first_model_elapsed() -> None:
    clock_value = [fixtures.NOW]

    def clock() -> datetime:
        return clock_value[0]

    def advance_20_seconds() -> None:
        clock_value[0] = fixtures.NOW + timedelta(seconds=20)

    budget = fixtures.FakeBudget(initial_active_seconds=570)
    model = fixtures.FakeModel(
        [fixtures.tool_batch(fixtures.tool_request()), fixtures.final_analysis()],
        on_decide=advance_20_seconds,
    )
    tools = fixtures.FakeTools()
    outcome, _ = await _run(
        decisions=[],
        model=model,
        clock=clock,
        budget=budget,
        tools=tools,
    )

    assert outcome.kind is SegmentOutcomeKind.DEGRADED
    assert outcome.safe_reason == "budget_exhausted"
    assert tools.calls == []
    assert len(model.contexts) == 1
    assert budget.activity == [20]


@pytest.mark.asyncio
async def test_activity_time_is_recorded_when_runner_raises() -> None:
    clock_value = [fixtures.NOW]

    def clock() -> datetime:
        return clock_value[0]

    def advance_20_seconds() -> None:
        clock_value[0] = fixtures.NOW + timedelta(seconds=20)

    budget = fixtures.FakeBudget()
    model = fixtures.FakeModel(
        [fixtures.tool_batch(fixtures.tool_request())],
        on_decide=advance_20_seconds,
    )
    tools = fixtures.FakeTools(error_at=1, error=RuntimeError("synthetic tool failure"))
    with pytest.raises(RuntimeError):
        await _run(
            decisions=[],
            model=model,
            clock=clock,
            budget=budget,
            tools=tools,
        )

    assert budget.activity == [20]


@pytest.mark.asyncio
async def test_activity_time_is_recorded_when_runner_is_cancelled() -> None:
    execution_context = fixtures.context()
    snapshot = fixtures.snapshot(execution_context)
    clock_value = [fixtures.NOW]

    def clock() -> datetime:
        return clock_value[0]

    budget = fixtures.FakeBudget()
    model = _BlockingModel()
    runner = build_interactive_graph(
        GraphDependencies(
            runs=fixtures.FakeRuns(snapshot),
            budget=budget,
            evidence=fixtures.FakeEvidence(),
            contexts=fixtures.FakeContexts(fixtures.model_context(execution_context)),
            tools=fixtures.FakeTools(),
            model=model,
            interactions=fixtures.FakeInteractions(),
            artifacts=fixtures.FakeStager(),
            clock=clock,
        )
    )
    task = asyncio.create_task(runner.run(execution_context))
    await model.started.wait()
    clock_value[0] = fixtures.NOW + timedelta(seconds=20)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert budget.activity == [20]


@pytest.mark.asyncio
async def test_finalized_artifact_list_is_bounded_before_state_validation() -> None:
    refs = tuple(
        fixtures.ArtifactRef(artifact_id=fixtures.uuid4(), sha256="5" * 64) for _ in range(33)
    )
    stager = fixtures.FakeStager(refs=refs)
    outcome, _ = await _run(
        decisions=[fixtures.final_analysis()],
        stager=stager,
    )

    assert outcome.kind is SegmentOutcomeKind.DEGRADED
    assert outcome.safe_reason == "artifact_limit_exceeded"
    assert outcome.artifact_refs == ()


@pytest.mark.asyncio
async def test_plan_reference_must_be_in_staged_artifacts() -> None:
    reference = fixtures.plan_ref()
    stager = fixtures.FakeStager(
        refs=(fixtures.ArtifactRef(artifact_id=fixtures.uuid4(), sha256="6" * 64),)
    )
    interactions = fixtures.FakeInteractions()
    outcome, _ = await _run(
        decisions=[
            fixtures.final_analysis(
                plan_ref=reference,
                selected_candidate_id="candidate_1",
            )
        ],
        stager=stager,
        interactions=interactions,
    )

    assert outcome.kind is SegmentOutcomeKind.DEGRADED
    assert outcome.safe_reason == "artifact_plan_missing"
    assert interactions.drafts == []
