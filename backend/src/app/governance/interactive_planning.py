# 交互式规划片段的治理包装：为每个执行片段建立独立 Harness run 与四阶段审计。
# 治理内核只负责策略准入、审计协议和片段结果；不实现数据库、模型、工具或交易执行。
# 审计适配器把每次写入绑定到当前 RunFence；业务终态/等待由 commit coordinator 原子提交。
from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.agent.interactive.ports import SegmentExecution, SegmentRunner
from app.agent_runs.segments import ExecutionContext, RunFence, SegmentOutcome, graph_namespace
from app.governance.audit import (
    HarnessAuditEvent,
    HarnessAuditEventKind,
    HarnessAuditRepository,
    HarnessAuditRun,
    HarnessAuditTrace,
    HarnessEvaluation,
)
from app.governance.contracts import (
    GovernanceCapability,
    GovernanceRunKind,
    GovernanceRunRequest,
    GovernedWorkflow,
)
from app.governance.policy import INTERACTIVE_PLANNING_POLICY
from app.governance.runtime import GovernanceRuntime
from app.market.symbols import ResearchSymbol

_GRAPH_NAMESPACE_PREFIX = "ir"


# 片段级审计协调器端口；SQL 实现必须每次在行锁后核验 fence 与数据库时刻。
# 成功/等待的序号 3 由 commit 同事务写入；异常序号 3 也只能经此端口收尾。
class SegmentAuditCoordinator(Protocol):
    async def create_requested_run(
        self,
        fence: RunFence,
        run: HarnessAuditRun,
        event: HarnessAuditEvent,
    ) -> None: ...

    async def append_policy_evaluation(
        self,
        fence: RunFence,
        evaluation: HarnessEvaluation,
        event: HarnessAuditEvent,
    ) -> None: ...

    async def append_started_event(self, fence: RunFence, event: HarnessAuditEvent) -> None: ...

    async def commit_audit_failure(self, fence: RunFence, event: HarnessAuditEvent) -> bool: ...

    async def get_audit_trace(self, run_id: UUID) -> HarnessAuditTrace | None: ...


# 把无 fence 的 HarnessAuditRepository 协议适配到当前片段；记录异常是否已由协调器收尾。
# 适配器不缓存业务结果，也不把审计失败伪装成成功；调用方仍负责最终业务提交。
class SegmentAuditAdapter(HarnessAuditRepository):
    def __init__(
        self,
        *,
        fence: RunFence,
        coordinator: SegmentAuditCoordinator,
    ) -> None:
        self._fence = fence
        self._coordinator = coordinator
        self.failure_committed = False

    async def create_requested_run(
        self,
        run: HarnessAuditRun,
        event: HarnessAuditEvent,
    ) -> None:
        await self._coordinator.create_requested_run(self._fence, run, event)

    async def append_policy_evaluation(
        self,
        evaluation: HarnessEvaluation,
        event: HarnessAuditEvent,
    ) -> None:
        await self._coordinator.append_policy_evaluation(self._fence, evaluation, event)

    async def append_event(self, event: HarnessAuditEvent) -> None:
        # 序号 2 是 started 前缀；序号 3 是运行器异常，必须交给协调器同时收尾业务状态。
        if event.sequence == 2:
            await self._coordinator.append_started_event(self._fence, event)
            return
        if event.sequence == 3 and event.kind is HarnessAuditEventKind.WORKFLOW_FAILED:
            # worker 因心跳失败/停机取消协程时不属于业务失败；保留 running 片段交给恢复器，
            # 不把“取消等待”写成 workflow_failed 终态。
            if event.details.error_type == "CancelledError":
                self.failure_committed = False
                return
            self.failure_committed = await self._coordinator.commit_audit_failure(
                self._fence,
                event,
            )
            return
        raise ValueError("片段审计适配器只接受 started 或 failed 终态事件")

    async def get_trace(self, run_id: UUID) -> HarnessAuditTrace | None:
        return await self._coordinator.get_audit_trace(run_id)


# 固定治理工作流：请求只确认类别/标识，实际执行使用服务端构造的 ExecutionContext。
# 运行器不能修改策略/权限/预算；其返回值仍是片段结果，不等于业务任务已提交。
class InteractivePlanningWorkflow(GovernedWorkflow[SegmentOutcome]):
    kind = GovernanceRunKind.INTERACTIVE_PLANNING
    required_capabilities: tuple[GovernanceCapability, ...] = (
        INTERACTIVE_PLANNING_POLICY.allowed_capabilities
    )

    def __init__(self, runner: SegmentRunner, context: ExecutionContext) -> None:
        self._runner = runner
        self._context = context

    async def run(self, request: GovernanceRunRequest) -> SegmentOutcome:
        if (
            request.kind is not GovernanceRunKind.INTERACTIVE_PLANNING
            or request.run_id != self._context.fence.segment_id
        ):
            raise ValueError("交互式规划治理请求与当前片段不匹配")
        expected_namespace = graph_namespace(
            self._context.fence,
            prefix=_GRAPH_NAMESPACE_PREFIX,
        )
        if not re.fullmatch(
            r"ir:[0-9a-f-]{36}:[0-9]+:[0-9a-f-]{36}",
            expected_namespace,
        ):
            raise ValueError("片段 namespace 不合法")
        return await self._runner.run(self._context)


# 受治理片段执行器：组装运行时、审计适配器与工作流，消费 SegmentRunner 协议。
# 正常/等待结果返回给 worker 提交；运行器异常时若协调器已写入合法失败终态，
# 返回 terminal_committed=True，worker 不得再次提交或覆盖。
class GovernedSegmentExecutor:
    def __init__(
        self,
        *,
        runner: SegmentRunner,
        coordinator: SegmentAuditCoordinator,
        clock: Callable[[], datetime],
    ) -> None:
        self._runner = runner
        self._coordinator = coordinator
        self._clock = clock

    async def run(
        self,
        context: ExecutionContext,
        *,
        symbol: ResearchSymbol,
        requested_at: datetime,
    ) -> SegmentExecution:
        # clock 由装配层保留为服务端时间源；当前请求时刻由 worker 在领取后注入。
        _ = self._clock
        adapter = SegmentAuditAdapter(
            fence=context.fence,
            coordinator=self._coordinator,
        )
        runtime = GovernanceRuntime[SegmentOutcome](
            policies=(INTERACTIVE_PLANNING_POLICY,),
            workflows=(InteractivePlanningWorkflow(self._runner, context),),
            audit_repository=adapter,
        )
        request = GovernanceRunRequest(
            run_id=context.fence.segment_id,
            kind=GovernanceRunKind.INTERACTIVE_PLANNING,
            symbol=symbol,
            requested_at=requested_at,
        )
        try:
            outcome = await runtime.run(request)
        except asyncio.CancelledError:
            # 已由协调器原子收尾时返回完成标志；否则让取消继续向上传播，交由恢复器处理。
            if adapter.failure_committed:
                return SegmentExecution(outcome=None, terminal_committed=True)
            raise
        except Exception:
            if adapter.failure_committed:
                return SegmentExecution(outcome=None, terminal_committed=True)
            raise
        return SegmentExecution(outcome=outcome)


__all__ = [
    "INTERACTIVE_PLANNING_POLICY",
    "GovernedSegmentExecutor",
    "InteractivePlanningWorkflow",
    "SegmentAuditAdapter",
    "SegmentAuditCoordinator",
]
