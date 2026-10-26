# 保存受控研究运行的请求与策略指纹、固定序号生命周期事件及白名单评估。
# 详情只包含安全计数和类型，不能记录模型、凭证、新闻正文或任意外部载荷。
"""受控工作流审计领域模型。

数据流：运行请求与策略指纹 → 固定四阶段事件及白名单评估 → 按 run_id、sequence 重建
不可自相矛盾的审计轨迹。详情字段受限，避免把原始请求、凭证或不可信正文写入审计。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

from app.harness.contracts import HarnessPolicy, HarnessRunKind, HarnessRunRequest
from app.market.contracts import UtcDateTime
from app.market.symbols import ResearchSymbol

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
StableErrorCode = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,100}$")]


class HarnessAuditEventKind(StrEnum):
    """受控运行生命周期允许的事件类型，事件类型决定其唯一合法 sequence。"""
    REQUESTED = "requested"
    POLICY_AUTHORIZED = "policy_authorized"
    POLICY_REJECTED = "policy_rejected"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_DEGRADED = "workflow_degraded"
    WORKFLOW_FAILED = "workflow_failed"


_EVENT_SEQUENCE_BY_KIND = {
    # 固定的四阶段生命周期禁止调用方任意编排事件，读回时可据此验证审计链完整性。
    HarnessAuditEventKind.REQUESTED: 0,
    HarnessAuditEventKind.POLICY_AUTHORIZED: 1,
    HarnessAuditEventKind.POLICY_REJECTED: 1,
    HarnessAuditEventKind.WORKFLOW_STARTED: 2,
    HarnessAuditEventKind.WORKFLOW_COMPLETED: 3,
    HarnessAuditEventKind.WORKFLOW_DEGRADED: 3,
    HarnessAuditEventKind.WORKFLOW_FAILED: 3,
}


class HarnessEvaluationDecision(StrEnum):
    """策略白名单评估的两种终态：通过或拒绝。"""
    PASSED = "passed"
    REJECTED = "rejected"


# 当前审计只接受手动接口触发，队列消费不代表允许定时研究或自动交易。
class HarnessInitiatorKind(StrEnum):
    MANUAL_API = "manual_api"


class _AuditModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HarnessEventDetails(_AuditModel):
    """仅允许写入计数、类型等非敏感诊断字段的审计详情。"""
    declared_capability_count: Annotated[int, Field(ge=0)] | None = None
    allowed_capability_count: Annotated[int, Field(ge=0)] | None = None
    workflow_kind: HarnessRunKind | None = None
    error_type: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,99}$")] | None = None

    @model_serializer
    def serialize(self) -> dict[str, int | str]:
        """仅序列化已提供的白名单诊断字段，避免输出 None 或扩展性敏感数据。"""
        serialized: dict[str, int | str] = {}
        if self.declared_capability_count is not None:
            serialized["declared_capability_count"] = self.declared_capability_count
        if self.allowed_capability_count is not None:
            serialized["allowed_capability_count"] = self.allowed_capability_count
        if self.workflow_kind is not None:
            serialized["workflow_kind"] = self.workflow_kind.value
        if self.error_type is not None:
            serialized["error_type"] = self.error_type
        return serialized

    def is_empty(self) -> bool:
        """判断事件是否缺少任何可供审计的安全详情。"""
        return all(value is None for value in self.__dict__.values())


class HarnessEvaluationDetails(_AuditModel):
    declared_capability_count: Annotated[int, Field(ge=0)] | None = None
    allowed_capability_count: Annotated[int, Field(ge=0)] | None = None


class HarnessAuditRun(_AuditModel):
    """一次受控运行的不可变标识、请求指纹和策略版本快照。"""
    run_id: UUID
    run_kind: HarnessRunKind
    policy_version: str
    policy_sha256: Sha256
    symbol: ResearchSymbol
    requested_at: UtcDateTime
    initiator_kind: HarnessInitiatorKind
    request_sha256: Sha256

    @field_validator("requested_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)


class HarnessAuditEvent(_AuditModel):
    """审计生命周期中的单条事件，受事件类型、序号、错误码和详情联合约束。"""
    run_id: UUID
    sequence: Annotated[int, Field(ge=0, le=3)]
    kind: HarnessAuditEventKind
    occurred_at: UtcDateTime
    duration_ms: Annotated[int, Field(ge=0)]
    error_code: StableErrorCode | None
    details: HarnessEventDetails

    @field_validator("occurred_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def validate_event(self) -> HarnessAuditEvent:
        # 事件类型、序号、错误码相互约束，避免出现“成功但带错误码”之类自相矛盾的记录。
        if self.sequence != _EVENT_SEQUENCE_BY_KIND[self.kind]:
            raise ValueError("审计事件生命周期序号与事件类型不匹配")
        if self.kind in {
            HarnessAuditEventKind.WORKFLOW_COMPLETED,
            HarnessAuditEventKind.WORKFLOW_DEGRADED,
        }:
            if self.sequence != 3 or self.error_code is not None:
                raise ValueError("终态事件必须为序号 3 且不含错误码")
        elif self.kind in {
            HarnessAuditEventKind.POLICY_REJECTED,
            HarnessAuditEventKind.WORKFLOW_FAILED,
        }:
            if self.error_code is None:
                raise ValueError("拒绝或失败事件必须含错误码")
        elif self.error_code is not None:
            raise ValueError("该事件不能含错误码")

        if self.details.is_empty() and self.kind not in {
            HarnessAuditEventKind.WORKFLOW_COMPLETED,
            HarnessAuditEventKind.WORKFLOW_DEGRADED,
        }:
            raise ValueError("非终态事件详情不能为空")
        return self


class HarnessEvaluation(_AuditModel):
    """策略白名单对一次运行进行的独立、可排序评估记录。"""
    run_id: UUID
    sequence: Annotated[int, Field(ge=0)]
    evaluator_name: Literal["policy_allowlist"]
    evaluator_version: Literal["1"]
    decision: HarnessEvaluationDecision
    reason_code: StableErrorCode | None
    evaluated_at: UtcDateTime
    details: HarnessEvaluationDetails

    @field_validator("evaluated_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def validate_reason(self) -> HarnessEvaluation:
        if self.decision is HarnessEvaluationDecision.PASSED and self.reason_code is not None:
            raise ValueError("通过评估不能含原因码")
        if self.decision is HarnessEvaluationDecision.REJECTED and self.reason_code is None:
            raise ValueError("拒绝评估必须含原因码")
        return self


class HarnessAuditTrace(_AuditModel):
    """一个运行的请求、事件和评估集合，读取时验证归属与顺序。"""
    run: HarnessAuditRun
    events: tuple[HarnessAuditEvent, ...]
    evaluations: tuple[HarnessEvaluation, ...]

    @model_validator(mode="after")
    def validate_ordered_trace(self) -> HarnessAuditTrace:
        # Trace 是按 run_id 和单调序号重建的，不接受跨运行事件或乱序事件。
        if any(event.run_id != self.run.run_id for event in self.events):
            raise ValueError("审计事件必须属于同一运行")
        if any(evaluation.run_id != self.run.run_id for evaluation in self.evaluations):
            raise ValueError("审计评估必须属于同一运行")
        if tuple(event.sequence for event in self.events) != tuple(
            sorted(event.sequence for event in self.events)
        ):
            raise ValueError("审计事件必须按序号升序")
        if tuple(evaluation.sequence for evaluation in self.evaluations) != tuple(
            sorted(evaluation.sequence for evaluation in self.evaluations)
        ):
            raise ValueError("审计评估必须按序号升序")
        return self


# 安全存储错误供上层映射，不包含连接信息或原始数据库异常。
class HarnessAuditStorageUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Harness 审计存储不可用")


# 仓储端口需关联保存请求和事件、评估和授权结果；不能以日志代替持久化审计。
class HarnessAuditRepository(Protocol):
    async def create_requested_run(
        self, run: HarnessAuditRun, event: HarnessAuditEvent
    ) -> None: ...

    async def append_policy_evaluation(
        self, evaluation: HarnessEvaluation, event: HarnessAuditEvent
    ) -> None: ...

    async def append_event(self, event: HarnessAuditEvent) -> None: ...

    async def get_trace(self, run_id: UUID) -> HarnessAuditTrace | None: ...


# 规范 JSON 固定键顺序；白名单列表保留给定顺序，指纹不额外排序列表元素。
def policy_sha256(policy: HarnessPolicy) -> str:
    """对策略白名单的规范 JSON 求哈希，使审计能固定本次运行所用规则。"""
    # 规范化 JSON 后再哈希，集合枚举顺序不会造成同一策略产生不同的审计指纹。
    canonical_payload = {
        "allowed_capabilities": [capability.value for capability in policy.allowed_capabilities],
        "allowed_symbols": [symbol for symbol in policy.allowed_symbols],
        "run_kind": policy.run_kind.value,
        "version": policy.version,
    }
    serialized = json.dumps(
        canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def request_sha256(request: HarnessRunRequest, policy_version: str) -> str:
    """对请求范围和策略版本求哈希，供审计追踪而不保存额外原始输入。"""
    canonical_payload = {
        "kind": request.kind.value,
        "policy_version": policy_version,
        "requested_at": _utc_isoformat(request.requested_at),
        "run_id": str(request.run_id),
        "symbol": request.symbol,
    }
    serialized = json.dumps(
        canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是 UTC 且带时区")
    return value.astimezone(UTC)


def _utc_isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
