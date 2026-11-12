# 定义交互式 Agent worker 与执行片段之间的纯协议，不依赖数据库、模型或工具实现。
# T07 使用确定性 SegmentRunner 验证租约/审计/提交边界；T11 才注入真实 LangGraph 运行器。
# 执行器返回“已提交的审计终态”标志，避免 worker 在协调器已收尾后重复提交。
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.agent_runs.segments import ExecutionContext, SegmentOutcome
from app.market.symbols import ResearchSymbol


# 一次片段执行的返回值；outcome 与 terminal_committed 至多一个成立。
@dataclass(frozen=True)
class SegmentExecution:
    outcome: SegmentOutcome | None
    terminal_committed: bool = False


# 单个片段内的研究/规划运行器；输入只能读取服务端装配的 ExecutionContext。
class SegmentRunner(Protocol):
    async def run(self, context: ExecutionContext) -> SegmentOutcome: ...


# worker 消费的执行器协议；符号与请求时刻由 worker 从已提交任务/服务端时钟传入。
class SegmentExecutor(Protocol):
    async def run(
        self,
        context: ExecutionContext,
        *,
        symbol: ResearchSymbol,
        requested_at: datetime,
    ) -> SegmentExecution: ...


__all__ = ["SegmentExecution", "SegmentExecutor", "SegmentRunner"]
