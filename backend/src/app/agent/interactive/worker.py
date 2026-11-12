# 交互式 Agent 片段 worker：领取队列任务、维持租约心跳、运行受治理片段并原子提交结果。
# 不直接调用模型/工具；SegmentExecutor 由治理包装提供，worker 只消费其安全结果。
# 心跳失败立即取消未提交工作；迟到提交由协调器以 lease_lost 拒绝，不覆盖新 owner。
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog

from app.agent.interactive.ports import SegmentExecution, SegmentExecutor
from app.agent_runs.contracts import AgentRunError, RunSnapshot
from app.agent_runs.ports import AgentRunReader, SegmentRepository
from app.agent_runs.segments import (
    HEARTBEAT_SECONDS,
    ExecutionContext,
    SegmentOutcome,
    SegmentOutcomeKind,
)


# 单进程本地 worker；同一 owner 贯穿多次 run_once，用于证明租约代次归属。
# poll_interval/heartbeat_interval 可注入以便测试，生产默认仍为 30/10 秒契约。
class InteractiveAgentWorker:
    def __init__(
        self,
        *,
        run_repository: AgentRunReader,
        segment_repository: SegmentRepository,
        executor: SegmentExecutor,
        owner: UUID | None = None,
        clock: Callable[[], datetime] | None = None,
        heartbeat_interval: float = HEARTBEAT_SECONDS,
        poll_interval: float = 1.0,
    ) -> None:
        if heartbeat_interval <= 0 or poll_interval <= 0:
            raise ValueError("worker 心跳与轮询间隔必须为正数")
        self._runs = run_repository
        self._segments = segment_repository
        self._executor = executor
        self._owner = owner or uuid4()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._heartbeat_interval = heartbeat_interval
        self._poll_interval = poll_interval

    # 单次调度：先恢复过期片段，再领取一个 queued 任务；没有工作时返回 False。
    # 只有协调器 commit 才改变业务状态；异常/失租时不伪造失败或成功。
    async def run_once(self) -> bool:
        try:
            await self._segments.recover_expired()
        except AgentRunError:
            self._log("interactive_agent_recovery_unavailable", level="warning")
            return False

        context = await self._segments.claim(self._owner)
        if context is None:
            return False

        snapshot = await self._runs.get(context.fence.workspace_id, context.fence.run_id)
        if snapshot is None or snapshot.revision != context.fence.revision:
            # 已提交修订与围栏不一致时不执行模型/工具；只允许协调器写安全失败终态。
            await self._commit_safely(
                context,
                SegmentOutcome(
                    kind=SegmentOutcomeKind.FAILED,
                    safe_reason="run_state_conflict",
                ),
            )
            return True

        if snapshot.cancel_requested_at is not None:
            await self._commit_safely(
                context,
                SegmentOutcome(
                    kind=SegmentOutcomeKind.CANCELLED,
                    safe_reason="user_cancelled",
                ),
            )
            return True

        try:
            execution = await self._run_with_heartbeat(
                context,
                snapshot=snapshot,
            )
        except asyncio.CancelledError:
            # worker 自身被取消时不提交：保留 running 片段，由过期恢复器处理。
            raise
        except Exception:
            # 执行器/审计不可用时停止本次工作，不把未知结果写成成功或失败。
            self._log("interactive_agent_execution_failed", level="warning")
            return True

        if execution is None:
            # 心跳停止可能是用户取消而非失租；仍持有有效 fence 时立即提交取消终态。
            latest = await self._runs.get(context.fence.workspace_id, context.fence.run_id)
            if latest is not None and latest.cancel_requested_at is not None:
                await self._commit_safely(
                    context,
                    SegmentOutcome(
                        kind=SegmentOutcomeKind.CANCELLED,
                        safe_reason="user_cancelled",
                    ),
                )
                return True
            # 失租：未提交工作已被取消，等待新 owner 在租约过期后恢复。
            self._log("interactive_agent_lease_lost", level="warning")
            return True
        if execution.terminal_committed:
            return True
        if execution.outcome is None:
            await self._commit_safely(
                context,
                SegmentOutcome(
                    kind=SegmentOutcomeKind.FAILED,
                    safe_reason="invalid_segment_execution",
                ),
            )
            return True
        await self._commit_safely(context, execution.outcome)
        return True

    # 持续消费直到停止事件；无工作时用可中断等待而不是忙轮询。
    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                worked = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._log("interactive_agent_worker_error", level="warning")
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self._poll_interval)
                except TimeoutError:
                    continue

    # 并发执行片段与心跳；任一方先结束都先停止另一方，避免失租后继续外部调用。
    async def _run_with_heartbeat(
        self,
        context: ExecutionContext,
        *,
        snapshot: RunSnapshot,
    ) -> SegmentExecution | None:
        lost = asyncio.Event()
        runner_task = asyncio.create_task(
            self._executor.run(
                context,
                symbol=snapshot.input.product.symbol,
                requested_at=self._clock(),
            )
        )
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(context, lost))
        try:
            done, _ = await asyncio.wait(
                {runner_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if lost.is_set():
                return None
            if runner_task in done:
                return runner_task.result()
            # 心跳任务异常结束也按失租处理，不继续信任当前 fence。
            return None
        finally:
            # asyncio.wait 不会把外层取消传播给 create_task 创建的任务；必须在
            # CancelledError 继续上抛前取消并等待执行器与心跳，避免无心跳的旧执行器
            # 继续计算或调用外部服务。清理阶段不写业务状态，迟到提交仍由协调器 fencing 拒绝。
            runner_task.cancel()
            heartbeat_task.cancel()
            await asyncio.gather(runner_task, heartbeat_task, return_exceptions=True)

    async def _heartbeat_loop(self, context: ExecutionContext, lost: asyncio.Event) -> None:
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval)
                if not await self._segments.heartbeat(context.fence):
                    lost.set()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            lost.set()

    async def _commit_safely(
        self,
        context: ExecutionContext,
        outcome: SegmentOutcome,
    ) -> None:
        try:
            decision = await self._segments.commit(context.fence, outcome)
        except AgentRunError:
            self._log("interactive_agent_commit_unavailable", level="warning")
            return
        if decision.kind.value != "committed":
            self._log(
                "interactive_agent_commit_not_applied",
                level="warning",
                reason=decision.safe_reason,
            )

    def _log(self, event: str, *, level: str, reason: str | None = None) -> None:
        logger = structlog.get_logger(__name__)
        fields: dict[str, str] = {"phase": level}
        if reason is not None:
            fields["reason"] = reason
        logger.info(event, **fields)


__all__ = ["InteractiveAgentWorker"]
