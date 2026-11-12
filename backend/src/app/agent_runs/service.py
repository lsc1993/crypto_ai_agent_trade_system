# Agent 任务应用服务：把服务端工作台身份和已校验输入交给仓储，不在此执行模型或金融计算。
# T04 不启动消费者；T06 增加取消委托，running 只置标记，queued/等待态由仓储原子取消。
from __future__ import annotations

from uuid import UUID

from app.agent_runs.contracts import RunInput, RunSnapshot
from app.agent_runs.ports import AgentRunRepository


# 任务服务保持薄边界，避免 API 或未来 worker 绕过仓储的幂等与容量事务。
class AgentRunService:
    def __init__(self, repository: AgentRunRepository) -> None:
        self._repository = repository

    # 创建或重放任务；工作台由服务端注入，客户端输入不能覆盖权限范围。
    # 相同 request_id 与相同规范化输入返回原任务；不同内容由仓储抛出稳定冲突。
    async def start(self, workspace_id: UUID, data: RunInput) -> RunSnapshot:
        return await self._repository.enqueue(workspace_id, data)

    # 取消委托给仓储的 CAS/幂等事务；服务不直接修改任务或交易所订单。
    async def cancel(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        request_id: UUID,
        expected_version: int,
    ) -> RunSnapshot:
        return await self._repository.cancel(
            workspace_id,
            run_id,
            request_id=request_id,
            expected_version=expected_version,
        )


__all__ = ["AgentRunService"]
