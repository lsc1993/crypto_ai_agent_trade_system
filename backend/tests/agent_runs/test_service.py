# 验证 T04 Agent 任务服务的薄封装边界：工作台注入、幂等委托和错误透传。
# 使用内存替身证明服务不解析默认值、不吞掉仓储错误；SQL 事务与事件序由持久化测试证明。
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.agent_runs.contracts import AgentRunError, RunInput, RunSnapshot, RunStatus
from app.agent_runs.events import RunEventPage
from app.agent_runs.service import AgentRunService
from app.market.contracts import MarketTimeframe
from app.shared.agent_types import ProductKey, VersionRef
from app.trade_planning.inputs import PlanningRefs

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)


# 构造不包含真实财务值的合成任务输入。
def _input() -> RunInput:
    ref = VersionRef(version_id=uuid4(), sha256="a" * 64)
    planning = PlanningRefs(
        profile=VersionRef(version_id=uuid4(), sha256="b" * 64),
        policy=VersionRef(version_id=uuid4(), sha256="c" * 64),
        venue_rules=VersionRef(version_id=uuid4(), sha256="d" * 64),
        costs=VersionRef(version_id=uuid4(), sha256="e" * 64),
        pool_id=uuid4(),
        pool_generation=1,
    )
    return RunInput(
        request_id=uuid4(),
        product=ProductKey(
            venue="binance_usdm",
            symbol="BTCUSDT",
            settlement="USDT",
            kind="linear_perpetual",
        ),
        timeframes=(MarketTimeframe.H1,),
        goal="分析合成行情",
        strategy=ref,
        parameters={"lookback": 20},
        planning=planning,
    )


# 构造服务返回的合法快照，避免替身引入未验证的数据库字段。
def _snapshot(data: RunInput) -> RunSnapshot:
    return RunSnapshot(
        run_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        parent_run_id=None,
        revision=1,
        status=RunStatus.QUEUED,
        state_version=0,
        input=data,
        received_message_seq=0,
        applied_message_seq=0,
        current_interaction_id=None,
        result_refs=(),
        result_quality=None,
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        finished_at=None,
    )


# 内存仓储替身记录服务传入的工作台与输入，并按配置返回快照或稳定错误。
class RecordingRepository:
    def __init__(
        self,
        *,
        result: RunSnapshot | None = None,
        error: AgentRunError | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.workspaces: list[UUID] = []
        self.inputs: list[RunInput] = []

    async def enqueue(self, workspace_id: UUID, data: RunInput) -> RunSnapshot:
        self.workspaces.append(workspace_id)
        self.inputs.append(data)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    async def get(self, workspace_id: UUID, run_id: UUID) -> RunSnapshot | None:
        return None

    async def list_events(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        after_seq: int = 0,
        limit: int = 50,
    ) -> RunEventPage:
        return RunEventPage(items=(), next_after=None)


@pytest.mark.asyncio
async def test_start_passes_server_workspace_and_original_input() -> None:
    # 工作台由服务端提供，服务不得从客户端输入推断或改写它。
    data = _input()
    snapshot = _snapshot(data)
    repository = RecordingRepository(result=snapshot)
    service = AgentRunService(repository)

    workspace_id = uuid4()
    started = await service.start(workspace_id, data)

    assert started == snapshot
    assert repository.workspaces == [workspace_id]
    assert repository.inputs == [data]


@pytest.mark.asyncio
async def test_start_propagates_stable_repository_error() -> None:
    # 队列容量或请求冲突属于业务错误，服务不能吞掉后返回伪成功。
    repository = RecordingRepository(error=AgentRunError("queue_full"))
    service = AgentRunService(repository)

    with pytest.raises(AgentRunError) as captured:
        await service.start(uuid4(), _input())
    assert captured.value.code == "queue_full"
