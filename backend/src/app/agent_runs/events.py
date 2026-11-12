# C4 安全业务事件的稳定投影：事件类型、顺序号、UTC 时间与白名单载荷。
# 事件只保存可供前端/审计展示的安全字段，不保存 Prompt、原始模型输出、财务值或完整计划。
# 载荷采用逐类型精确键集合校验；新增事件类型必须同时在此登记，不能通过通用 JSON 注入。
from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import cast
from uuid import UUID

from pydantic import Field, JsonValue, ValidationError, field_validator, model_validator

from app.agent_runs.decisions import ControlAction
from app.agent_runs.interactions import InteractionDecision
from app.shared.agent_types import AgentModel, ProductKey, UtcDateTime, is_sha256, require_utc


# T04 只产生入队与修订建立事件；T06 增加消息、审核与取消的安全事件。
# T07 增加片段开始/等待/终态/重排事件；等待与终态经协调器与业务写入同事务提交。
class RunEventType(StrEnum):
    RUN_QUEUED = "run.queued"
    REVISION_CREATED = "revision.created"
    MESSAGE_RECORDED = "message.recorded"
    MESSAGE_APPLIED = "message.applied"
    INTERACTION_PREPARED = "interaction.prepared"
    INTERACTION_PENDING = "interaction.pending"
    INTERACTION_RESPONDED = "interaction.responded"
    INTERACTION_APPLIED = "interaction.applied"
    INTERACTION_EXPIRED = "interaction.expired"
    RUN_CANCELLATION_REQUESTED = "run.cancellation_requested"
    RUN_CANCELLED = "run.cancelled"
    RUN_STARTED = "run.started"
    RUN_WAITING = "run.waiting"
    RUN_TERMINATED = "run.terminated"
    RUN_REQUEUED = "run.requeued"


# 每个事件类型的顶层键白名单；嵌套产品键由 ProductKey 再校验，防止夹带任意载荷。
_ALLOWED_PAYLOAD_KEYS: dict[RunEventType, frozenset[str]] = {
    RunEventType.RUN_QUEUED: frozenset({"status", "product"}),
    RunEventType.REVISION_CREATED: frozenset({"revision", "inputSha256", "strategyVersionId"}),
    RunEventType.MESSAGE_RECORDED: frozenset({"sequence"}),
    RunEventType.MESSAGE_APPLIED: frozenset({"appliedSeq"}),
    RunEventType.INTERACTION_PREPARED: frozenset({"interactionId", "action", "revision"}),
    RunEventType.INTERACTION_PENDING: frozenset({"interactionId", "action", "revision"}),
    RunEventType.INTERACTION_RESPONDED: frozenset({"interactionId", "decision", "revision"}),
    RunEventType.INTERACTION_APPLIED: frozenset({"interactionId", "revision"}),
    RunEventType.INTERACTION_EXPIRED: frozenset({"interactionId", "reason"}),
    RunEventType.RUN_CANCELLATION_REQUESTED: frozenset({"reason"}),
    RunEventType.RUN_CANCELLED: frozenset({"reason"}),
    RunEventType.RUN_STARTED: frozenset({"status"}),
    RunEventType.RUN_WAITING: frozenset({"status"}),
    RunEventType.RUN_TERMINATED: frozenset({"status"}),
    RunEventType.RUN_REQUEUED: frozenset({"reason"}),
}
_SAFE_EVENT_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_TERMINAL_EVENT_STATUSES = frozenset({"completed", "degraded", "failed", "cancelled", "expired"})


# 单条业务事件；序号在单个任务内从 1 单调递增，跨任务不共享序列。
class RunEvent(AgentModel):
    run_id: UUID
    revision: int = Field(ge=1)
    sequence: int = Field(ge=1)
    event_type: RunEventType
    occurred_at: UtcDateTime
    payload: dict[str, JsonValue]
    projection_version: int = Field(default=1, ge=1)

    # 事件时间必须为 UTC；不能把本地时间写入可重放轨迹。
    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    # 按事件类型校验精确键集合和字段语义；未知键或缺失键都拒绝。
    @model_validator(mode="after")
    def validate_payload(self) -> RunEvent:
        allowed = _ALLOWED_PAYLOAD_KEYS[self.event_type]
        if set(self.payload) != set(allowed):
            raise ValueError("事件载荷包含未登记字段或缺少必需字段")
        if self.event_type is RunEventType.RUN_QUEUED:
            if self.payload.get("status") != "queued":
                raise ValueError("入队事件状态必须为 queued")
            try:
                ProductKey.model_validate(self.payload.get("product"))
            except ValidationError as error:
                raise ValueError("入队事件产品投影不合法") from error
        if self.event_type is RunEventType.REVISION_CREATED:
            if self.payload.get("revision") != self.revision:
                raise ValueError("修订事件版本号与事件不一致")
            digest = self.payload.get("inputSha256")
            if not isinstance(digest, str) or not is_sha256(digest):
                raise ValueError("修订事件输入指纹不合法")
            strategy_version = self.payload.get("strategyVersionId")
            if not isinstance(strategy_version, str):
                raise ValueError("修订事件必须携带策略版本标识")
            try:
                UUID(strategy_version)
            except ValueError as error:
                raise ValueError("策略版本标识必须是 UUID") from error
        if self.event_type is RunEventType.MESSAGE_RECORDED:
            sequence = self.payload.get("sequence")
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
                raise ValueError("消息记录事件序号必须为正整数")
        if self.event_type is RunEventType.MESSAGE_APPLIED:
            applied_seq = self.payload.get("appliedSeq")
            if not isinstance(applied_seq, int) or isinstance(applied_seq, bool) or applied_seq < 1:
                raise ValueError("消息应用事件水位必须为正整数")
        if self.event_type in {
            RunEventType.INTERACTION_PREPARED,
            RunEventType.INTERACTION_PENDING,
            RunEventType.INTERACTION_RESPONDED,
            RunEventType.INTERACTION_APPLIED,
            RunEventType.INTERACTION_EXPIRED,
        }:
            _validate_interaction_event(self)
        if self.event_type in {
            RunEventType.RUN_CANCELLATION_REQUESTED,
            RunEventType.RUN_CANCELLED,
        }:
            reason = self.payload.get("reason")
            if reason != "user_request":
                raise ValueError("取消事件原因必须为 user_request")
        _validate_run_lifecycle_event(self)
        return self


# 片段生命周期事件只暴露任务状态或稳定原因，不能携带财务值、产物正文或模型文本。
def _validate_run_lifecycle_event(event: RunEvent) -> None:
    if event.event_type is RunEventType.RUN_STARTED:
        if event.payload.get("status") != "running":
            raise ValueError("开始事件状态必须为 running")
    elif event.event_type is RunEventType.RUN_WAITING:
        if event.payload.get("status") not in {"waiting_input", "waiting_approval"}:
            raise ValueError("等待事件状态必须是 waiting_input/approval")
    elif event.event_type is RunEventType.RUN_TERMINATED:
        if event.payload.get("status") not in _TERMINAL_EVENT_STATUSES:
            raise ValueError("终态事件状态必须是业务终态")
    elif event.event_type is RunEventType.RUN_REQUEUED:
        reason = event.payload.get("reason")
        if not isinstance(reason, str) or _SAFE_EVENT_REASON.fullmatch(reason) is None:
            raise ValueError("重排事件原因必须是稳定短码")


# 交互事件只暴露标识、动作/决定和修订；材料正文、用户文本和财务值不得进入安全事件。
def _validate_interaction_event(event: RunEvent) -> None:
    interaction_id = event.payload.get("interactionId")
    if not isinstance(interaction_id, str):
        raise ValueError("交互事件必须携带待办标识")
    try:
        UUID(interaction_id)
    except ValueError as error:
        raise ValueError("待办标识必须是 UUID") from error
    revision = event.payload.get("revision")
    if revision is not None and revision != event.revision:
        raise ValueError("交互事件修订号与事件不一致")
    action = event.payload.get("action")
    if action is not None and action not in {item.value for item in ControlAction}:
        raise ValueError("交互事件动作不在登记范围")
    decision = event.payload.get("decision")
    if decision is not None and decision not in {item.value for item in InteractionDecision}:
        raise ValueError("交互事件决定不在登记范围")
    reason = event.payload.get("reason")
    if reason is not None:
        if not isinstance(reason, str) or _SAFE_EVENT_REASON.fullmatch(reason) is None:
            raise ValueError("交互过期原因必须是稳定短码")


# 事件分页使用序号游标而不是页码；next_after 为 None 表示当前已无更晚事件。
class RunEventPage(AgentModel):
    items: tuple[RunEvent, ...]
    next_after: int | None = Field(default=None, ge=1)


# 供仓储追加事件时复用同一白名单校验；调用方负责分配序号并持有任务行锁。
def appendable_event(
    *,
    run_id: UUID,
    workspace_id: UUID,
    revision: int,
    sequence: int,
    event_type: RunEventType,
    payload: dict[str, JsonValue],
    occurred_at: datetime,
) -> RunEvent:
    _ = workspace_id
    return RunEvent(
        run_id=run_id,
        revision=revision,
        sequence=sequence,
        event_type=event_type,
        occurred_at=occurred_at,
        payload=payload,
    )


# 构造 T04 的两条入队事件；固定字段和顺序，便于幂等重放时核对事件序列。
def build_enqueue_events(
    *,
    run_id: UUID,
    revision: int,
    product: ProductKey,
    occurred_at: datetime,
    input_sha256: str,
    strategy_version_id: UUID,
) -> tuple[RunEvent, RunEvent]:
    return (
        RunEvent(
            run_id=run_id,
            revision=revision,
            sequence=1,
            event_type=RunEventType.RUN_QUEUED,
            occurred_at=occurred_at,
            payload={
                "status": "queued",
                "product": cast(
                    JsonValue,
                    product.model_dump(mode="json", by_alias=False),
                ),
            },
        ),
        RunEvent(
            run_id=run_id,
            revision=revision,
            sequence=2,
            event_type=RunEventType.REVISION_CREATED,
            occurred_at=occurred_at,
            payload={
                "revision": revision,
                "inputSha256": input_sha256,
                "strategyVersionId": str(strategy_version_id),
            },
        ),
    )


__all__ = [
    "RunEvent",
    "RunEventPage",
    "RunEventType",
    "appendable_event",
    "build_enqueue_events",
]
