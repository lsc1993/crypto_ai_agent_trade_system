# 验证 T07 交互式 Agent worker 的领取、心跳、取消与提交编排边界。
# 使用纯替身隔离数据库/模型/工具：只证明 worker 在失租、取消和审计失败时不误提交。
# 真实租约、并发与审计原子性由 persistence 用例和实际子进程终止用例另行证明。
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.agent.interactive.ports import SegmentExecution
from app.agent.interactive.worker import InteractiveAgentWorker
from app.agent_runs.contracts import RunInput, RunSnapshot, RunStatus
from app.agent_runs.segments import (
    CompletionDecision,
    CompletionDecisionKind,
    ExecutionContext,
    RunFence,
    SegmentOutcome,
    SegmentOutcomeKind,
)
from app.market.contracts import MarketTimeframe
from app.shared.agent_types import ProductKey, VersionRef


# 构造只含安全引用与合成输入的运行快照；不包含真实财务资料或账户信息。
def _run_input() -> RunInput:
    return RunInput(
        request_id=uuid4(),
        product=ProductKey(
            venue="binance_usdm",
            symbol="BTCUSDT",
            settlement="USDT",
            kind="linear_perpetual",
        ),
        timeframes=(MarketTimeframe.H1,),
        goal="合成研究目标",
        strategy=VersionRef(version_id=uuid4(), sha256="a" * 64),
        parameters={"threshold": "1"},
    )


def _context(run_input: RunInput | None = None) -> ExecutionContext:
    data = run_input or _run_input()
    return ExecutionContext(
        fence=RunFence(
            workspace_id=uuid4(),
            run_id=uuid4(),
            revision=1,
            segment_id=uuid4(),
            owner=uuid4(),
            lease_epoch=1,
        ),
        strategy_ref=data.strategy,
        tool_catalog_sha256="b" * 64,
        policy_version="interactive_planning_v1",
        budget_authorization_id=uuid4(),
    )


def _snapshot(
    context: ExecutionContext,
    *,
    data: RunInput | None = None,
    cancel_requested_at: datetime | None = None,
) -> RunSnapshot:
    now = datetime.now(UTC)
    return RunSnapshot(
        run_id=context.fence.run_id,
        workspace_id=context.fence.workspace_id,
        thread_id=uuid4(),
        revision=context.fence.revision,
        status=RunStatus.RUNNING,
        state_version=2,
        input=data or _run_input(),
        received_message_seq=0,
        applied_message_seq=0,
        created_at=now,
        updated_at=now,
        started_at=now,
        cancel_requested_at=cancel_requested_at,
    )


# 最小任务仓储替身：worker 只用 get 读取取消标记与产品范围。
# 传入列表可模拟“运行中取消”导致同一任务第二次读取出现新标记。
class FakeRuns:
    def __init__(self, snapshot: RunSnapshot | list[RunSnapshot]) -> None:
        self._snapshots = snapshot if isinstance(snapshot, list) else [snapshot]
        self._index = 0
        self.get_calls: list[tuple[UUID, UUID]] = []

    async def get(self, workspace_id: UUID, run_id: UUID) -> RunSnapshot | None:
        self.get_calls.append((workspace_id, run_id))
        index = min(self._index, len(self._snapshots) - 1)
        self._index += 1
        return self._snapshots[index]


# 片段仓储替身：记录恢复/领取/心跳/提交调用，并可控制心跳失败。
@dataclass
class FakeSegments:
    contexts: list[ExecutionContext]
    heartbeat_result: bool = True
    recovered: int = 0
    recover_calls: int = 0
    heartbeat_calls: int = 0
    commits: list[tuple[RunFence, SegmentOutcome]] = field(
        default_factory=list[tuple[RunFence, SegmentOutcome]]
    )

    async def recover_expired(self) -> int:
        self.recover_calls += 1
        return self.recovered

    async def claim(self, owner: UUID) -> ExecutionContext | None:
        _ = owner
        return self.contexts.pop(0) if self.contexts else None

    async def heartbeat(self, fence: RunFence) -> bool:
        _ = fence
        self.heartbeat_calls += 1
        return self.heartbeat_result

    async def commit(
        self,
        fence: RunFence,
        outcome: SegmentOutcome,
    ) -> CompletionDecision:
        self.commits.append((fence, outcome))
        return CompletionDecision(kind=CompletionDecisionKind.COMMITTED, state_version=3)


# 执行器替身：记录调用并返回预先声明的片段结果或等待取消。
class FakeExecutor:
    def __init__(
        self,
        *,
        outcome: SegmentOutcome | None = None,
        terminal_committed: bool = False,
        block: bool = False,
    ) -> None:
        self.outcome = outcome
        self.terminal_committed = terminal_committed
        self.block = block
        self.calls = 0
        self.cancelled = False
        self.started = asyncio.Event()

    async def run(
        self,
        context: ExecutionContext,
        *,
        symbol: str,
        requested_at: datetime,
    ) -> SegmentExecution:
        _ = context, symbol, requested_at
        self.calls += 1
        self.started.set()
        if self.block:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return SegmentExecution(
            outcome=self.outcome,
            terminal_committed=self.terminal_committed,
        )


def _worker(
    *,
    runs: FakeRuns,
    segments: FakeSegments,
    executor: FakeExecutor,
    heartbeat_interval: float = 0.01,
) -> InteractiveAgentWorker:
    return InteractiveAgentWorker(
        run_repository=runs,
        segment_repository=segments,
        executor=executor,
        owner=uuid4(),
        heartbeat_interval=heartbeat_interval,
        poll_interval=0.01,
    )


def _pending_tasks() -> list[asyncio.Task[Any]]:
    # worker 取消后不得遗留执行器/心跳任务；调用方负责在断言失败时清理。
    current = asyncio.current_task()
    return [task for task in asyncio.all_tasks() if task is not current and not task.done()]


async def _cancel_and_drain(task: asyncio.Task[Any]) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    pending = _pending_tasks()
    try:
        assert pending == []
    finally:
        for item in pending:
            item.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_run_once_recovers_then_claims_and_commits_outcome() -> None:
    context = _context()
    runs = FakeRuns(_snapshot(context))
    segments = FakeSegments(contexts=[context])
    executor = FakeExecutor(outcome=SegmentOutcome(kind=SegmentOutcomeKind.COMPLETED))

    worker = _worker(runs=runs, segments=segments, executor=executor)

    assert await worker.run_once() is True
    assert segments.recover_calls == 1
    assert executor.calls == 1
    assert len(segments.commits) == 1
    fence, outcome = segments.commits[0]
    assert fence == context.fence
    assert outcome.kind is SegmentOutcomeKind.COMPLETED


@pytest.mark.asyncio
async def test_run_once_returns_false_without_claiming_work() -> None:
    context = _context()
    runs = FakeRuns(_snapshot(context))
    segments = FakeSegments(contexts=[])
    executor = FakeExecutor(outcome=SegmentOutcome(kind=SegmentOutcomeKind.COMPLETED))

    worker = _worker(runs=runs, segments=segments, executor=executor)

    assert await worker.run_once() is False
    assert executor.calls == 0
    assert segments.commits == []


@pytest.mark.asyncio
async def test_cancelled_run_skips_runner_and_commits_cancellation() -> None:
    context = _context()
    runs = FakeRuns(_snapshot(context, cancel_requested_at=datetime.now(UTC)))
    segments = FakeSegments(contexts=[context])
    executor = FakeExecutor(outcome=SegmentOutcome(kind=SegmentOutcomeKind.COMPLETED))

    worker = _worker(runs=runs, segments=segments, executor=executor)

    assert await worker.run_once() is True
    assert executor.calls == 0
    assert len(segments.commits) == 1
    assert segments.commits[0][1].kind is SegmentOutcomeKind.CANCELLED


@pytest.mark.asyncio
async def test_heartbeat_loss_cancels_runner_without_commit() -> None:
    context = _context()
    runs = FakeRuns(_snapshot(context))
    segments = FakeSegments(contexts=[context], heartbeat_result=False)
    executor = FakeExecutor(block=True)

    worker = _worker(runs=runs, segments=segments, executor=executor)

    assert await worker.run_once() is True
    assert await asyncio.wait_for(executor.started.wait(), timeout=1) is True
    assert executor.cancelled is True
    assert segments.heartbeat_calls >= 1
    assert segments.commits == []


@pytest.mark.asyncio
async def test_cancelling_run_once_stops_executor_without_commit() -> None:
    # 外层取消必须传播到 create_task 启动的执行器，并在 CancelledError 继续上抛前清空任务。
    context = _context()
    runs = FakeRuns(_snapshot(context))
    segments = FakeSegments(contexts=[context])
    executor = FakeExecutor(block=True)
    worker = _worker(runs=runs, segments=segments, executor=executor)

    task = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(executor.started.wait(), timeout=1)
    except BaseException:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    await _cancel_and_drain(task)

    assert executor.cancelled is True
    assert segments.commits == []


@pytest.mark.asyncio
async def test_cancelling_run_forever_stops_executor_without_commit() -> None:
    # run_forever 被取消时同样必须清理执行器；停止事件不需要被设置。
    context = _context()
    runs = FakeRuns(_snapshot(context))
    segments = FakeSegments(contexts=[context])
    executor = FakeExecutor(block=True)
    worker = _worker(runs=runs, segments=segments, executor=executor)
    stop = asyncio.Event()

    task = asyncio.create_task(worker.run_forever(stop))
    try:
        await asyncio.wait_for(executor.started.wait(), timeout=1)
    except BaseException:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    await _cancel_and_drain(task)

    assert executor.cancelled is True
    assert segments.commits == []
    assert not stop.is_set()


@pytest.mark.asyncio
async def test_cancel_during_run_stops_on_heartbeat_and_commits_cancellation() -> None:
    context = _context()
    first = _snapshot(context)
    second = _snapshot(context, cancel_requested_at=datetime.now(UTC))
    runs = FakeRuns([first, second])
    segments = FakeSegments(contexts=[context], heartbeat_result=False)
    executor = FakeExecutor(block=True)

    worker = _worker(runs=runs, segments=segments, executor=executor)

    assert await worker.run_once() is True
    assert executor.cancelled is True
    assert len(segments.commits) == 1
    assert segments.commits[0][1].kind is SegmentOutcomeKind.CANCELLED
    assert len(runs.get_calls) == 2


@pytest.mark.asyncio
async def test_terminal_commit_from_audit_failure_skips_second_commit() -> None:
    context = _context()
    runs = FakeRuns(_snapshot(context))
    segments = FakeSegments(contexts=[context])
    executor = FakeExecutor(terminal_committed=True)

    worker = _worker(runs=runs, segments=segments, executor=executor)

    assert await worker.run_once() is True
    assert executor.calls == 1
    assert segments.commits == []


@pytest.mark.asyncio
async def test_run_forever_stops_when_event_is_set() -> None:
    context = _context()
    runs = FakeRuns(_snapshot(context))
    segments = FakeSegments(contexts=[])
    executor = FakeExecutor(outcome=SegmentOutcome(kind=SegmentOutcomeKind.COMPLETED))
    worker = _worker(runs=runs, segments=segments, executor=executor)
    stop = asyncio.Event()

    task = asyncio.create_task(worker.run_forever(stop))
    await asyncio.sleep(0.03)
    stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert segments.recover_calls >= 1
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_revision_mismatch_fails_closed_without_running() -> None:
    context = _context()
    stale = _snapshot(context)
    stale = stale.model_copy(update={"revision": 2})
    runs = FakeRuns(stale)
    segments = FakeSegments(contexts=[context])
    executor = FakeExecutor(outcome=SegmentOutcome(kind=SegmentOutcomeKind.COMPLETED))

    worker = _worker(runs=runs, segments=segments, executor=executor)

    assert await worker.run_once() is True
    assert executor.calls == 0
    assert len(segments.commits) == 1
    assert segments.commits[0][1].kind is SegmentOutcomeKind.FAILED


# 防止测试辅助代码被误当成生产契约；未使用导入在此显式消费。
_ = Any
