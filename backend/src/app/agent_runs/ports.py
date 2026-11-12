# 定义 Agent 任务应用层依赖的仓储协议；具体 SQL 实现位于 infrastructure/persistence。
# T04 暴露创建、读取和事件分页；T05 增加预算账本端口；T07 增加片段租约/提交端口。
# 协议不包含模型、工具或交易依赖，调用方通过服务端注入工作台身份与租约围栏。
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.agent_runs.budget import BudgetLedger
from app.agent_runs.contracts import RunInput, RunSnapshot
from app.agent_runs.events import RunEventPage
from app.agent_runs.interactions import InteractionRepository
from app.agent_runs.messages import MessageRepository
from app.agent_runs.segments import (
    CompletionDecision,
    ExecutionContext,
    RunFence,
    SegmentOutcome,
)


# worker 只需要读取已提交任务快照；拆出窄端口避免把写入能力带入执行循环。
class AgentRunReader(Protocol):
    async def get(self, workspace_id: UUID, run_id: UUID) -> RunSnapshot | None: ...


# Agent 任务仓储端口；实现方负责事务、请求幂等、容量、取消和事件序号。
class AgentRunRepository(Protocol):
    async def enqueue(self, workspace_id: UUID, data: RunInput) -> RunSnapshot: ...

    async def get(self, workspace_id: UUID, run_id: UUID) -> RunSnapshot | None: ...

    async def cancel(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        request_id: UUID,
        expected_version: int,
    ) -> RunSnapshot: ...

    async def list_events(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        after_seq: int = 0,
        limit: int = 50,
    ) -> RunEventPage: ...


# 执行片段端口：SQL 协调器是唯一实现，负责领取、心跳、过期恢复与原子提交。
# 领取只在队列锁内把 queued 转为 running；恢复先写下合法审计终态，再重新排队。
class SegmentRepository(Protocol):
    async def claim(self, owner: UUID) -> ExecutionContext | None: ...

    async def heartbeat(self, fence: RunFence) -> bool: ...

    async def recover_expired(self) -> int: ...

    async def commit(
        self,
        fence: RunFence,
        outcome: SegmentOutcome,
    ) -> CompletionDecision: ...


__all__ = [
    "AgentRunReader",
    "AgentRunRepository",
    "BudgetLedger",
    "InteractionRepository",
    "MessageRepository",
    "SegmentRepository",
]
