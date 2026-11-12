# 定义 T06 连续消息契约：用户文本/类型化资料引用、单调序号、recorded/applied 水位与回执。
# 消息只提供上下文，不构成审核批准、预算追加或交易指令；结构化财务表单不写入聊天。
# 本模块不调用模型、不轮询等待任务；应用水位由 worker 在安全边界通过围栏推进。
from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from app.agent_runs.contracts import AgentRunError, RunSnapshot
from app.agent_runs.segments import RunFence
from app.shared.agent_types import AgentModel, UtcDateTime, VersionRef, sha256_json

MAX_MESSAGE_TEXT = 4_000


# 消息类型只允许自由文本或指向已版本化资料；不允许内嵌账户/订单对象。
class MessageKind(StrEnum):
    TEXT = "text"
    PLANNING_REF = "planning_ref"


# 用户消息输入；request_id 是幂等键，不进入消息内容指纹。
class UserMessage(AgentModel):
    request_id: UUID
    kind: MessageKind
    text: str | None = Field(default=None, max_length=MAX_MESSAGE_TEXT)
    planning_ref: VersionRef | None = None

    @model_validator(mode="after")
    def validate_content(self) -> UserMessage:
        if self.kind is MessageKind.TEXT:
            if self.text is None or not self.text.strip():
                raise ValueError("文本消息必须包含非空白内容")
            if self.planning_ref is not None:
                raise ValueError("文本消息不能携带规划资料引用")
        else:
            if self.planning_ref is None:
                raise ValueError("资料引用消息必须提供版本引用")
            if self.text is not None:
                raise ValueError("资料引用消息不能夹带自由文本")
        if self.text is not None and "\x00" in self.text:
            raise ValueError("消息文本不能包含 NUL 字符")
        return self


# 消息回执；received 只表示已记录，applied 由后续 worker 异步推进。
class MessageReceipt(AgentModel):
    request_id: UUID
    message_id: UUID
    run_id: UUID
    sequence: int = Field(ge=1)
    receipt_state: Literal["recorded"] = "recorded"
    received_message_seq: int = Field(ge=0)
    applied_message_seq: int = Field(ge=0)
    recorded_at: UtcDateTime

    @model_validator(mode="after")
    def validate_watermarks(self) -> MessageReceipt:
        if self.applied_message_seq > self.received_message_seq:
            raise ValueError("已应用消息水位不能超过已记录水位")
        if self.sequence > self.received_message_seq:
            raise ValueError("消息序号不能超过已记录水位")
        return self


# 消息仓储端口；SQL 实现负责行锁、序号分配和幂等映射。
class MessageRepository(Protocol):
    async def record(
        self,
        workspace_id: UUID,
        run_id: UUID,
        message: UserMessage,
    ) -> MessageReceipt: ...

    async def mark_applied(self, fence: RunFence, up_to_seq: int) -> RunSnapshot: ...


# 消息应用服务；record 只记录，mark_applied 必须带当前 worker 围栏。
class MessageService:
    def __init__(self, repository: MessageRepository) -> None:
        self._repository = repository

    async def record(
        self,
        workspace_id: UUID,
        run_id: UUID,
        message: UserMessage,
    ) -> MessageReceipt:
        return await self._repository.record(workspace_id, run_id, message)

    async def mark_applied(self, fence: RunFence, up_to_seq: int) -> RunSnapshot:
        if up_to_seq < 1:
            raise AgentRunError("invalid_message")
        return await self._repository.mark_applied(fence, up_to_seq)


# 消息幂等指纹：绑定任务与完整内容，不包含 request_id。
def user_message_sha256(run_id: UUID, message: UserMessage) -> str:
    payload = {
        "runId": str(run_id),
        "message": message.model_dump(mode="json", exclude={"request_id"}),
    }
    return sha256_json(payload)  # type: ignore[arg-type]


__all__ = [
    "MAX_MESSAGE_TEXT",
    "MessageKind",
    "MessageReceipt",
    "MessageRepository",
    "MessageService",
    "UserMessage",
    "user_message_sha256",
]
