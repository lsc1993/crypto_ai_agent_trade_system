# C4 安全业务事件的稳定投影：事件类型、顺序号、UTC 时间与白名单载荷。
# 事件只保存可供前端/审计展示的安全字段，不保存 Prompt、原始模型输出、财务值或完整计划。
# 载荷采用逐类型精确键集合校验；新增事件类型必须同时在此登记，不能通过通用 JSON 注入。
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import cast
from uuid import UUID

from pydantic import Field, JsonValue, ValidationError, field_validator, model_validator

from app.shared.agent_types import AgentModel, ProductKey, UtcDateTime, is_sha256, require_utc


# T04 只产生入队与修订建立事件；T06/T07 的交互、步骤和终态事件在各自任务扩展。
class RunEventType(StrEnum):
    RUN_QUEUED = "run.queued"
    REVISION_CREATED = "revision.created"


# 每个事件类型的顶层键白名单；嵌套产品键由 ProductKey 再校验，防止夹带任意载荷。
_ALLOWED_PAYLOAD_KEYS: dict[RunEventType, frozenset[str]] = {
    RunEventType.RUN_QUEUED: frozenset({"status", "product"}),
    RunEventType.REVISION_CREATED: frozenset({"revision", "inputSha256", "strategyVersionId"}),
}


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
        return self


# 事件分页使用序号游标而不是页码；next_after 为 None 表示当前已无更晚事件。
class RunEventPage(AgentModel):
    items: tuple[RunEvent, ...]
    next_after: int | None = Field(default=None, ge=1)


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
    "build_enqueue_events",
]
