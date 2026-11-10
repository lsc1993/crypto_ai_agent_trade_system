# C4 Agent 任务的公共不可变契约：运行输入、请求指纹、状态、快照与稳定错误码。
# 本模块只表达业务任务事实，不执行模型、工具、风控或交易；完整财务值不进入快照。
# 请求键与内容指纹分离：同一 request_id 只能对应同一有效输入，不同请求键不按币种合并。
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, cast
from uuid import UUID

from pydantic import Field, JsonValue, field_validator, model_validator

from app.market.contracts import MarketTimeframe
from app.shared.agent_types import (
    AgentModel,
    ArtifactRef,
    ProductKey,
    UtcDateTime,
    VersionRef,
    require_utc,
    sha256_json,
)
from app.trade_planning.inputs import PlanningRefs

# 单工作台可同时排队的可运行任务上限；等待态不占用该并发槽。
RUNNABLE_CAPACITY = 20
# 单工作台人工等待上限；T06/T07 在进入等待时原子检查，T04 只提供容量口径。
WAITING_CAPACITY_PER_WORKSPACE = 100


# 任务状态机与本项目设计第 6.1 节一致；终态不允许重新打开。
class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.DEGRADED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.EXPIRED,
    }
)
RUNNABLE_RUN_STATUSES = frozenset({RunStatus.QUEUED, RunStatus.RUNNING})
WAITING_RUN_STATUSES = frozenset({RunStatus.WAITING_INPUT, RunStatus.WAITING_APPROVAL})

# 结果质量沿用安全投影的最小枚举；未知质量必须显式为 None，不能伪装完整。
RunQuality = Literal["complete", "degraded", "unknown"]

# 仓储对外错误码；API 及后续 worker 据此映射安全错误，不依赖异常文本。
AgentRunErrorCode = Literal[
    "request_conflict",
    "queue_full",
    "waiting_capacity_full",
    "thread_not_found",
    "thread_conflict",
    "parent_not_found",
    "parent_not_terminal",
    "run_not_found",
    "invalid_event_page",
    "integrity_violation",
    "storage_unavailable",
]


# 稳定业务错误；消息仅供本地诊断，不包含连接串、SQL 或用户财务资料。
class AgentRunError(RuntimeError):
    # 保存固定原因码，调用方据此区分冲突、容量、找不到与存储故障。
    def __init__(self, code: AgentRunErrorCode, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


# 客户端提交的任务输入快照；工作台身份由服务端另行注入，不在本模型中。
class RunInput(AgentModel):
    request_id: UUID
    thread_id: UUID | None = None
    parent_run_id: UUID | None = None
    product: ProductKey
    timeframes: tuple[MarketTimeframe, ...]
    goal: str = Field(min_length=1, max_length=2000)
    strategy: VersionRef
    parameters: dict[str, JsonValue]
    planning: PlanningRefs | None = None
    analysis_mode: Literal["current", "historical"] = "current"
    as_of: UtcDateTime | None = None
    budget_profile: Literal["standard"] = "standard"

    # 策略参数必须能稳定序列化为有限 JSON；NaN/Infinity 会使请求指纹不可复现。
    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        try:
            sha256_json(cast(JsonValue, value))
        except (TypeError, ValueError) as error:
            raise ValueError("策略参数必须是有限 JSON 值") from error
        return value

    # 目标必须包含实际文本；纯空白不能占用一个研究任务。
    @field_validator("goal")
    @classmethod
    def validate_goal(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("研究目标不能为空白")
        return value

    # 至少一个周期且不得重复；顺序保留用户选择，不去重掩盖输入差异。
    @field_validator("timeframes")
    @classmethod
    def validate_timeframes(cls, value: tuple[MarketTimeframe, ...]) -> tuple[MarketTimeframe, ...]:
        if not value:
            raise ValueError("至少需要一个市场周期")
        if len(set(value)) != len(value):
            raise ValueError("市场周期不能重复")
        return value

    # 历史模式必须有分析截至时刻；当前模式不能携带伪历史截止时间。
    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def validate_analysis_time(self) -> RunInput:
        if self.analysis_mode == "historical" and self.as_of is None:
            raise ValueError("历史分析模式必须提供 as_of")
        if self.analysis_mode == "current" and self.as_of is not None:
            raise ValueError("当前分析模式不能提供 as_of")
        return self


# 任务快照只携带不可变修订输入、引用和状态水位；不内嵌完整财务资料。
class RunSnapshot(AgentModel):
    run_id: UUID
    workspace_id: UUID
    thread_id: UUID
    parent_run_id: UUID | None = None
    revision: int = Field(ge=1)
    status: RunStatus
    state_version: int = Field(ge=0)
    input: RunInput
    received_message_seq: int = Field(ge=0)
    applied_message_seq: int = Field(ge=0)
    current_interaction_id: UUID | None = None
    result_refs: tuple[ArtifactRef, ...] = ()
    result_quality: RunQuality | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    started_at: UtcDateTime | None = None
    finished_at: UtcDateTime | None = None

    # 所有时间必须是带零偏移的 UTC；本地时间或伪时区不能进入审计事实。
    @field_validator("created_at", "updated_at", "started_at", "finished_at")
    @classmethod
    def validate_times(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    # 已应用消息不能超过已记录消息；终态与完成时刻必须相互一致。
    @model_validator(mode="after")
    def validate_lifecycle(self) -> RunSnapshot:
        if self.applied_message_seq > self.received_message_seq:
            raise ValueError("已应用消息水位不能超过已记录水位")
        terminal = self.status in TERMINAL_RUN_STATUSES
        if terminal != (self.finished_at is not None):
            raise ValueError("终态状态与完成时刻必须同时成立")
        return self


# 请求内容指纹覆盖工作台和除 request_id 外的规范化输入；默认值在解析后自然进入指纹。
def run_input_sha256(workspace_id: UUID, data: RunInput) -> str:
    payload = data.model_dump(mode="json", by_alias=False, exclude={"request_id"})
    content: dict[str, JsonValue] = {
        "workspaceId": str(workspace_id),
        "runInput": cast(JsonValue, payload),
    }
    return sha256_json(content)


__all__ = [
    "RUNNABLE_CAPACITY",
    "RUNNABLE_RUN_STATUSES",
    "TERMINAL_RUN_STATUSES",
    "WAITING_CAPACITY_PER_WORKSPACE",
    "WAITING_RUN_STATUSES",
    "AgentRunError",
    "AgentRunErrorCode",
    "RunInput",
    "RunQuality",
    "RunSnapshot",
    "RunStatus",
    "run_input_sha256",
]
