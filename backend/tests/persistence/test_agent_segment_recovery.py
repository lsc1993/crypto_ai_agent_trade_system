# 使用真实子进程终止验证 T07 片段恢复：preparing 待办、成功步骤与审计前缀不被重造。
# 子进程只运行生产片段/预算/治理/交互仓储，不连接模型或工具，阻塞点后由父进程强制终止。
# 恢复使用数据库行锁和真实时钟推进后的过期租约；不等待 30 秒，也不接触业务库。
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from app.agent.interactive.worker import InteractiveAgentWorker
from app.agent_runs.contracts import RunInput, RunStatus
from app.agent_runs.events import RunEventType
from app.agent_runs.interactions import InteractionStatus
from app.agent_runs.segments import (
    ExecutionContext,
    SegmentOutcome,
    SegmentOutcomeKind,
    SegmentStatus,
)
from app.governance.audit import HarnessAuditEventKind
from app.governance.interactive_planning import GovernedSegmentExecutor
from app.infrastructure.persistence.agent_commit_coordinator import (
    SqlAlchemyAgentCommitCoordinator,
)
from app.infrastructure.persistence.agent_interaction_repository import (
    SqlAlchemyAgentInteractionRepository,
)
from app.infrastructure.persistence.agent_run_repository import SqlAlchemyAgentRunRepository
from app.infrastructure.persistence.harness_audit_repository import (
    SqlAlchemyHarnessAuditRepository,
)
from app.infrastructure.persistence.models.agent_attempts import AgentStepRecord
from app.infrastructure.persistence.models.agent_runs import AgentRunRecord
from app.infrastructure.persistence.models.agent_segments import AgentSegmentRecord
from app.market.contracts import MarketTimeframe
from app.shared.agent_types import ProductKey, VersionRef
from tests.conftest import MigratedDatabase


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


async def _expire_leases(database: MigratedDatabase, run_id: UUID, segment_id: UUID) -> None:
    past = datetime.now(UTC) - timedelta(seconds=1)
    async with database.session_factory() as session, session.begin():
        await session.execute(
            update(AgentRunRecord).where(AgentRunRecord.id == run_id).values(lease_expires_at=past)
        )
        await session.execute(
            update(AgentSegmentRecord)
            .where(AgentSegmentRecord.id == segment_id)
            .values(lease_expires_at=past)
        )


# 新片段复用已保存的 preparing 待办，不重新发起模型调用或准备第二份材料。
class RecoverPreparingRunner:
    def __init__(self, interactions: SqlAlchemyAgentInteractionRepository) -> None:
        self._interactions = interactions
        self.calls = 0

    async def run(self, context: ExecutionContext) -> SegmentOutcome:
        self.calls += 1
        items = await self._interactions.list_interactions(
            context.fence.workspace_id,
            context.fence.run_id,
        )
        preparing = [item for item in items if item.status is InteractionStatus.PREPARING]
        assert len(preparing) == 1
        return SegmentOutcome(
            kind=SegmentOutcomeKind.WAIT_APPROVAL,
            preparing_interaction_id=preparing[0].interaction_id,
        )


@pytest.mark.asyncio
async def test_killed_worker_recovers_preparing_interaction_and_successful_step(
    migrated_database: MigratedDatabase,
    tmp_path: Path,
) -> None:
    factory = migrated_database.session_factory
    engine = factory.kw["bind"]
    mapping = engine.get_execution_options()["schema_translate_map"]
    schema = mapping[None]
    workspace = uuid4()
    created = await SqlAlchemyAgentRunRepository(factory).enqueue(workspace, _run_input())
    ready = tmp_path / "segment-ready.json"

    child = """
import asyncio, json, os, re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from app.agent.interactive.worker import InteractiveAgentWorker
from app.agent_runs.attempts import AttemptCategory, AttemptRequest, AttemptResult
from app.agent_runs.decisions import ControlAction
from app.agent_runs.interactions import InteractionDraft
from app.agent_runs.segments import SegmentOutcome, SegmentOutcomeKind
from app.governance.interactive_planning import GovernedSegmentExecutor
from app.infrastructure.persistence.agent_commit_coordinator import \
    SqlAlchemyAgentCommitCoordinator
from app.infrastructure.persistence.agent_interaction_repository import \
    SqlAlchemyAgentInteractionRepository
from app.infrastructure.persistence.agent_attempt_repository import SqlAlchemyBudgetLedger
from app.infrastructure.persistence.agent_run_repository import SqlAlchemyAgentRunRepository
from app.shared.agent_types import ArtifactRef
from app.shared.database import create_async_engine_from_secret, create_session_factory
from scripts.check_test_database import check_test_database

async def main():
    url = await check_test_database()
    schema = os.environ['RUNTIME_TEST_SCHEMA']
    assert re.fullmatch(r'market_test_[0-9a-f]{16}', schema)
    engine = create_async_engine_from_secret(url).execution_options(
        schema_translate_map={None: schema})
    factory = create_session_factory(engine)
    coordinator = SqlAlchemyAgentCommitCoordinator(factory, clock=lambda: datetime.now(UTC))
    interactions = SqlAlchemyAgentInteractionRepository(factory)
    ledger = SqlAlchemyBudgetLedger(factory)

    class Blocked:
        async def run(self, context):
            attempt = await ledger.reserve(context.fence, AttemptRequest(
                action_sequence=1,
                input_sha256='e' * 64,
                category=AttemptCategory.MODEL,
                reserved_input_tokens=100,
                reserved_output_tokens=50,
                timeout_seconds=30,
            ))
            await ledger.mark_sent(context.fence, attempt.attempt_id)
            await ledger.settle(context.fence, attempt.attempt_id, AttemptResult(
                status='succeeded',
                result_ref=ArtifactRef(artifact_id=uuid4(), sha256='f' * 64),
            ))
            draft = InteractionDraft(
                request_id=uuid4(),
                action=ControlAction.ADOPT_MANUAL_PLAN,
                material_hash='c' * 64,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                safe_reason='plan_ready',
            )
            item = await interactions.prepare(context.fence, draft)
            target = Path(os.environ['RUNTIME_TEST_READY'])
            target.with_suffix('.pending').write_text(json.dumps({
                'pid': os.getpid(),
                'interaction_id': str(item.interaction_id),
            }))
            target.with_suffix('.pending').replace(target)
            await asyncio.Event().wait()

    executor = GovernedSegmentExecutor(
        runner=Blocked(), coordinator=coordinator, clock=lambda: datetime.now(UTC))
    worker = InteractiveAgentWorker(
        run_repository=SqlAlchemyAgentRunRepository(factory),
        segment_repository=coordinator,
        executor=executor,
    )
    await worker.run_once()

asyncio.run(main())
"""
    environment = dict(os.environ)
    environment.update(
        RUNTIME_TEST_SCHEMA=schema,
        RUNTIME_TEST_READY=str(ready),
        PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"),
    )
    process = subprocess.Popen(
        [sys.executable, "-c", child],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    child_pid: int | None = None
    try:
        async with asyncio.timeout(20):
            while not ready.is_file():
                assert process.poll() is None, "worker process exited before blocking"
                await asyncio.sleep(0.05)
        payload = json.loads(ready.read_text())
        # Windows venv 的 python.exe 可能是转发器：实际 worker 是读取到的子进程 PID。
        child_pid = int(payload["pid"])
        interaction_id = UUID(payload["interaction_id"])

        runs = SqlAlchemyAgentRunRepository(factory)
        running = await runs.get(workspace, created.run_id)
        assert running is not None and running.status is RunStatus.RUNNING
        async with factory() as session:
            segment = await session.scalar(
                select(AgentSegmentRecord).where(AgentSegmentRecord.run_id == created.run_id)
            )
        assert segment is not None and segment.status == SegmentStatus.RUNNING.value
        trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(segment.id)
        assert trace is not None and len(trace.events) == 3
        interactions = SqlAlchemyAgentInteractionRepository(factory)
        preparing = await interactions.list_interactions(workspace, created.run_id)
        assert len(preparing) == 1
        assert preparing[0].interaction_id == interaction_id
        assert preparing[0].status is InteractionStatus.PREPARING
        assert preparing[0].can_respond is False

        os.kill(child_pid, signal.SIGTERM)
        await asyncio.to_thread(process.wait, 10)
        assert process.returncode is not None

        old_segment_id = segment.id
        await _expire_leases(migrated_database, created.run_id, old_segment_id)
        coordinator = SqlAlchemyAgentCommitCoordinator(
            factory,
            clock=lambda: datetime.now(UTC),
        )
        assert await coordinator.recover_expired() == 1

        recovered = await runs.get(workspace, created.run_id)
        assert recovered is not None and recovered.status is RunStatus.QUEUED
        async with factory() as session:
            old_segment = await session.get(AgentSegmentRecord, old_segment_id)
            succeeded_step = await session.scalar(
                select(AgentStepRecord).where(
                    AgentStepRecord.run_id == created.run_id,
                    AgentStepRecord.revision == 1,
                    AgentStepRecord.action_sequence == 1,
                )
            )
        assert old_segment is not None
        assert old_segment.status == SegmentStatus.INTERRUPTED.value
        assert succeeded_step is not None and succeeded_step.status == "succeeded"
        old_trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(old_segment_id)
        assert old_trace is not None
        assert len(old_trace.events) == 4
        assert old_trace.events[-1].kind is HarnessAuditEventKind.WORKFLOW_FAILED
        assert old_trace.events[-1].error_code == "lease_expired"
        still_preparing = await interactions.list_interactions(workspace, created.run_id)
        assert len(still_preparing) == 1
        assert still_preparing[0].status is InteractionStatus.PREPARING
        assert still_preparing[0].interaction_id == interaction_id

        # 新片段重新准入并复用 preparing 材料，发布为真正可响应待办。
        runner = RecoverPreparingRunner(interactions)
        governed = GovernedSegmentExecutor(
            runner=runner,
            coordinator=coordinator,
            clock=lambda: datetime.now(UTC),
        )
        worker = InteractiveAgentWorker(
            run_repository=runs,
            segment_repository=coordinator,
            executor=governed,
            owner=uuid4(),
            heartbeat_interval=0.01,
            poll_interval=0.01,
        )
        assert await worker.run_once() is True
        waiting = await runs.get(workspace, created.run_id)
        assert waiting is not None and waiting.status is RunStatus.WAITING_APPROVAL
        async with factory() as session:
            segments = list(
                (
                    await session.scalars(
                        select(AgentSegmentRecord)
                        .where(AgentSegmentRecord.run_id == created.run_id)
                        .order_by(AgentSegmentRecord.started_at)
                    )
                ).all()
            )
        assert [item.status for item in segments] == [
            SegmentStatus.INTERRUPTED.value,
            SegmentStatus.WAITING_APPROVAL.value,
        ]
        new_trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(segments[1].id)
        assert new_trace is not None
        assert new_trace.events[-1].kind is HarnessAuditEventKind.WORKFLOW_COMPLETED
        published = await interactions.list_interactions(workspace, created.run_id)
        assert len(published) == 1
        assert published[0].status is InteractionStatus.PENDING
        assert published[0].can_respond is True
        events = await runs.list_events(workspace, created.run_id, limit=100)
        assert RunEventType.RUN_REQUEUED in [item.event_type for item in events.items]
        assert RunEventType.RUN_WAITING in [item.event_type for item in events.items]
        assert runner.calls == 1
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGTERM)
            except OSError:
                pass
        if process.poll() is None:
            process.kill()
        await asyncio.to_thread(process.wait, 10)
