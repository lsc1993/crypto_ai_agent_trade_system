# 验证 T06 连续消息与取消的应用服务边界：只记录/委托，不提前标记已应用或已采纳。
# 使用内存替身证明服务传递服务端工作台、围栏与请求参数；真实 SQL 水位和竞态另由持久化测试证明。
# 本文件不调用模型、不轮询等待中的任务，也不包含真实资金、账户或交易数据。
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.agent_runs.contracts import AgentRunError, RunInput, RunSnapshot, RunStatus
from app.agent_runs.events import RunEventPage
from app.agent_runs.interactions import FeedbackReceipt, InteractionDecision, InteractionStatus
from app.agent_runs.messages import (
    MessageKind,
    MessageReceipt,
    MessageService,
    UserMessage,
)
from app.agent_runs.segments import RunFence
from app.agent_runs.service import AgentRunService
from app.market.contracts import MarketTimeframe
from app.shared.agent_types import ProductKey, VersionRef

NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)


# 构造最小任务输入；消息测试不依赖目标正文或规划金额。
def _input() -> RunInput:
    return RunInput(
        request_id=uuid4(),
        product=ProductKey(
            venue="binance_usdm",
            symbol="BTCUSDT",
            settlement="USDT",
            kind="linear_perpetual",
        ),
        timeframes=(MarketTimeframe.H1,),
        goal="验证连续消息与取消",
        strategy=VersionRef(version_id=uuid4(), sha256="a" * 64),
        parameters={"lookback": 20},
    )


# 构造合法任务快照；received/applied 分开表达，取消字段默认为空。
def _snapshot(data: RunInput) -> RunSnapshot:
    return RunSnapshot(
        run_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        parent_run_id=None,
        revision=1,
        status=RunStatus.WAITING_INPUT,
        state_version=2,
        input=data,
        received_message_seq=2,
        applied_message_seq=1,
        current_interaction_id=uuid4(),
        result_refs=(),
        result_quality=None,
        created_at=NOW,
        updated_at=NOW,
        started_at=NOW,
        finished_at=None,
    )


# 记录服务传入参数的仓储替身；不实现模型、工具或计划采纳。
class RecordingRunRepository:
    def __init__(self, *, snapshot: RunSnapshot | None = None) -> None:
        self.snapshot = snapshot
        self.cancel_calls: list[tuple[UUID, UUID, UUID, int]] = []

    async def enqueue(self, workspace_id: UUID, data: RunInput) -> RunSnapshot:
        raise AssertionError("unexpected enqueue")

    async def get(self, workspace_id: UUID, run_id: UUID) -> RunSnapshot | None:
        return self.snapshot

    async def list_events(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        after_seq: int = 0,
        limit: int = 50,
    ) -> RunEventPage:
        return RunEventPage(items=(), next_after=None)

    async def cancel(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        request_id: UUID,
        expected_version: int,
    ) -> RunSnapshot:
        self.cancel_calls.append((workspace_id, run_id, request_id, expected_version))
        if self.snapshot is None:
            raise AgentRunError("run_not_found")
        return self.snapshot


# 消息仓储替身记录服务传入的输入并返回记录态回执。
class RecordingMessageRepository:
    def __init__(self) -> None:
        self.record_calls: list[tuple[UUID, UUID, UserMessage]] = []
        self.applied_calls: list[tuple[RunFence, int]] = []

    async def record(
        self,
        workspace_id: UUID,
        run_id: UUID,
        message: UserMessage,
    ) -> MessageReceipt:
        self.record_calls.append((workspace_id, run_id, message))
        return MessageReceipt(
            request_id=message.request_id,
            message_id=uuid4(),
            run_id=run_id,
            sequence=1,
            receipt_state="recorded",
            received_message_seq=1,
            applied_message_seq=0,
            recorded_at=NOW,
        )

    async def mark_applied(self, fence: RunFence, up_to_seq: int) -> RunSnapshot:
        self.applied_calls.append((fence, up_to_seq))
        return _snapshot(_input())


@pytest.mark.asyncio
async def test_message_record_only_confirms_receipt_and_keeps_applied_separate() -> None:
    repository = RecordingMessageRepository()
    service = MessageService(repository)
    workspace_id = uuid4()
    run_id = uuid4()
    message = UserMessage(
        request_id=uuid4(),
        kind=MessageKind.TEXT,
        text="请补充反证，但不要改变当前策略",
    )

    receipt = await service.record(workspace_id, run_id, message)

    assert repository.record_calls == [(workspace_id, run_id, message)]
    assert receipt.receipt_state == "recorded"
    assert receipt.received_message_seq == 1
    assert receipt.applied_message_seq == 0


@pytest.mark.asyncio
async def test_mark_applied_requires_worker_fence_and_bounded_watermark() -> None:
    repository = RecordingMessageRepository()
    service = MessageService(repository)
    fence = RunFence(
        workspace_id=uuid4(),
        run_id=uuid4(),
        revision=1,
        segment_id=uuid4(),
        owner=uuid4(),
        lease_epoch=1,
    )

    snapshot = await service.mark_applied(fence, 2)
    assert repository.applied_calls == [(fence, 2)]
    assert snapshot.messages_pending is True

    # 负数或非递增水位不能在服务层进入仓储；真实上限由 SQL 行锁核对。
    for invalid in (-1, 0):
        with pytest.raises(AgentRunError) as captured:
            await service.mark_applied(fence, invalid)
        assert captured.value.code == "invalid_message"
    assert len(repository.applied_calls) == 1


@pytest.mark.asyncio
async def test_cancel_delegates_server_workspace_request_key_and_expected_version() -> None:
    data = _input()
    snapshot = _snapshot(data)
    repository = RecordingRunRepository(snapshot=snapshot)
    service = AgentRunService(repository)
    workspace_id = uuid4()
    run_id = uuid4()
    request_id = uuid4()

    result = await service.cancel(
        workspace_id,
        run_id,
        request_id=request_id,
        expected_version=2,
    )

    assert result == snapshot
    assert repository.cancel_calls == [(workspace_id, run_id, request_id, 2)]

    # 终态/取消冲突由仓储返回稳定错误，服务不能吞掉后伪造成功。
    missing = AgentRunService(RecordingRunRepository(snapshot=None))
    with pytest.raises(AgentRunError) as captured:
        await missing.cancel(workspace_id, run_id, request_id=uuid4(), expected_version=0)
    assert captured.value.code == "run_not_found"


def test_message_receipt_is_recorded_only_and_rejects_application_claims() -> None:
    receipt = MessageReceipt(
        request_id=uuid4(),
        message_id=uuid4(),
        run_id=uuid4(),
        sequence=1,
        receipt_state="recorded",
        received_message_seq=1,
        applied_message_seq=0,
        recorded_at=NOW,
    )
    assert receipt.receipt_state == "recorded"

    with pytest.raises(ValueError):
        MessageReceipt.model_validate(
            {**receipt.model_dump(by_alias=False), "receipt_state": "applied"}
        )


def test_message_and_feedback_receipts_are_different_fact_types() -> None:
    # 用户消息记录与审核反馈回执不能互相冒充；计划采纳仍为 False。
    feedback = FeedbackReceipt(
        request_id=uuid4(),
        interaction_id=uuid4(),
        run_id=uuid4(),
        decision=InteractionDecision.REQUEST_CHANGES,
        receipt_state="recorded",
        adoption_applied=False,
        run_status=RunStatus.QUEUED,
        interaction_status=InteractionStatus.ANSWERED,
        state_version=1,
        recorded_at=NOW,
    )
    assert feedback.adoption_applied is False
    assert not hasattr(feedback, "message_id")
