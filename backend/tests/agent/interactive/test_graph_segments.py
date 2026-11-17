# T11 worker 与真实图执行器的接线测试：验证 SegmentRunner 注入后仍由治理包装收尾。
# 使用合成审计协调器、片段仓储和模型/工具替身，不连接数据库、网络或付费模型。
# 断言等待片段在模型提出澄清后立即结束，不会在等待期间继续轮询模型。
from __future__ import annotations

import pytest

from app.agent.interactive.graph import GraphDependencies, build_interactive_graph
from app.agent.interactive.state import SegmentOutcomeKind
from app.agent.interactive.worker import InteractiveAgentWorker
from app.agent_runs.decisions import ControlAction
from tests.agent.interactive import graph_fixtures as fixtures


@pytest.mark.asyncio
async def test_worker_with_graph_runner_commits_waiting_outcome_without_polling() -> None:
    execution_context = fixtures.context()
    snapshot = fixtures.snapshot(execution_context)
    runs = fixtures.FakeRuns(snapshot)
    segments = fixtures.FakeSegments(contexts=[execution_context])
    interactions = fixtures.FakeInteractions()
    model = fixtures.FakeModel([fixtures.control_proposal(ControlAction.CLARIFY)])
    runner = build_interactive_graph(
        GraphDependencies(
            runs=runs,
            budget=fixtures.FakeBudget(),
            evidence=fixtures.FakeEvidence(),
            contexts=fixtures.FakeContexts(fixtures.model_context(execution_context)),
            tools=fixtures.FakeTools(),
            model=model,
            interactions=interactions,
            artifacts=fixtures.FakeStager(),
            clock=lambda: fixtures.NOW,
        )
    )
    coordinator = fixtures.FakeAuditCoordinator()
    worker = InteractiveAgentWorker(
        run_repository=runs,
        segment_repository=segments,
        runner=runner,
        audit_coordinator=coordinator,
        owner=fixtures.uuid4(),
        clock=lambda: fixtures.NOW,
        heartbeat_interval=0.01,
        poll_interval=0.01,
    )

    assert await worker.run_once() is True

    assert len(segments.commits) == 1
    fence, outcome = segments.commits[0]
    assert fence == execution_context.fence
    assert outcome.kind is SegmentOutcomeKind.WAIT_INPUT
    assert outcome.preparing_interaction_id == interactions.prepared[0].interaction_id
    # 等待由片段结束表达；没有模型轮询或第二次决策。
    assert len(model.contexts) == 1
    # 治理包装仍为该片段建立请求、策略评估和开始前缀。
    assert len(coordinator.requested) == 1
    assert len(coordinator.evaluations) == 1
    assert len(coordinator.started) == 1


@pytest.mark.asyncio
async def test_worker_rejects_both_executor_and_runner() -> None:
    with pytest.raises(ValueError):
        InteractiveAgentWorker(
            run_repository=fixtures.FakeRuns(fixtures.snapshot(fixtures.context())),
            segment_repository=fixtures.FakeSegments(contexts=[]),
            executor=object(),  # type: ignore[arg-type]
            runner=fixtures.FakeModel([]),  # type: ignore[arg-type]
            owner=fixtures.uuid4(),
        )
