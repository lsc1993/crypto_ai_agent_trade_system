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
from app.market.contracts import ContractSymbol, UtcDateTime

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
StableErrorCode = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,100}$")]


class HarnessAuditEventKind(StrEnum):
    REQUESTED = "requested"
    POLICY_AUTHORIZED = "policy_authorized"
    POLICY_REJECTED = "policy_rejected"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_DEGRADED = "workflow_degraded"
    WORKFLOW_FAILED = "workflow_failed"


class HarnessEvaluationDecision(StrEnum):
    PASSED = "passed"
    REJECTED = "rejected"


class HarnessInitiatorKind(StrEnum):
    MANUAL_API = "manual_api"


class _AuditModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HarnessEventDetails(_AuditModel):
    declared_capability_count: Annotated[int, Field(ge=0)] | None = None
    allowed_capability_count: Annotated[int, Field(ge=0)] | None = None
    workflow_kind: HarnessRunKind | None = None
    error_type: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,99}$")] | None = None

    @model_serializer
    def serialize(self) -> dict[str, int | str]:
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
        return all(value is None for value in self.__dict__.values())


class HarnessEvaluationDetails(_AuditModel):
    declared_capability_count: Annotated[int, Field(ge=0)] | None = None
    allowed_capability_count: Annotated[int, Field(ge=0)] | None = None


class HarnessAuditRun(_AuditModel):
    run_id: UUID
    run_kind: HarnessRunKind
    policy_version: str
    policy_sha256: Sha256
    symbol: ContractSymbol
    requested_at: UtcDateTime
    initiator_kind: HarnessInitiatorKind
    request_sha256: Sha256

    @field_validator("requested_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)


class HarnessAuditEvent(_AuditModel):
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
    run: HarnessAuditRun
    events: tuple[HarnessAuditEvent, ...]
    evaluations: tuple[HarnessEvaluation, ...]

    @model_validator(mode="after")
    def validate_ordered_trace(self) -> HarnessAuditTrace:
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


class HarnessAuditStorageUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Harness 审计存储不可用")


class HarnessAuditRepository(Protocol):
    async def create_requested_run(
        self, run: HarnessAuditRun, event: HarnessAuditEvent
    ) -> None: ...

    async def append_policy_evaluation(
        self, evaluation: HarnessEvaluation, event: HarnessAuditEvent
    ) -> None: ...

    async def append_event(self, event: HarnessAuditEvent) -> None: ...

    async def get_trace(self, run_id: UUID) -> HarnessAuditTrace | None: ...


def policy_sha256(policy: HarnessPolicy) -> str:
    canonical_payload = {
        "allowed_capabilities": [capability.value for capability in policy.allowed_capabilities],
        "allowed_symbols": [symbol.value for symbol in policy.allowed_symbols],
        "run_kind": policy.run_kind.value,
        "version": policy.version,
    }
    serialized = json.dumps(
        canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def request_sha256(request: HarnessRunRequest, policy_version: str) -> str:
    canonical_payload = {
        "kind": request.kind.value,
        "policy_version": policy_version,
        "requested_at": _utc_isoformat(request.requested_at),
        "run_id": str(request.run_id),
        "symbol": request.symbol.value,
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
