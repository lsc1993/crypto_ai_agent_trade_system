# 定义 Agent 任务应用层依赖的仓储协议；具体 SQL 实现位于 infrastructure/persistence。
# T04 暴露创建、读取和事件分页；T05 增加预算账本端口，领取/心跳/恢复由 T07 扩展。
# 协议不包含模型、工具或交易依赖，调用方通过服务端注入工作台身份与租约围栏。
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.agent_runs.budget import BudgetLedger
from app.agent_runs.contracts import RunInput, RunSnapshot
from app.agent_runs.events import RunEventPage


# Agent 任务仓储端口；实现方负责事务、请求幂等、容量和事件序号。
class AgentRunRepository(Protocol):
    async def enqueue(self, workspace_id: UUID, data: RunInput) -> RunSnapshot: ...

    async def get(self, workspace_id: UUID, run_id: UUID) -> RunSnapshot | None: ...

    async def list_events(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        after_seq: int = 0,
        limit: int = 50,
    ) -> RunEventPage: ...


__all__ = ["AgentRunRepository", "BudgetLedger"]
