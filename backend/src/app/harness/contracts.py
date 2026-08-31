from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.market.contracts import ContractSymbol, UtcDateTime


class HarnessRunKind(StrEnum):
    MARKET_RESEARCH = "market_research"


class HarnessCapability(StrEnum):
    READ_PUBLIC_MARKET = "read_public_market"
    READ_APPROVED_NEWS = "read_approved_news"
    CALL_RESEARCH_MODEL = "call_research_model"
    PERSIST_IMMUTABLE_REPORT = "persist_immutable_report"


class HarnessRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    kind: HarnessRunKind
    symbol: ContractSymbol
    requested_at: UtcDateTime

    @field_validator("requested_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("时间必须是 UTC 且带时区")
        return value.astimezone(UTC)


class HarnessPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_kind: HarnessRunKind
    allowed_symbols: tuple[ContractSymbol, ...]
    allowed_capabilities: tuple[HarnessCapability, ...]

    @field_validator("allowed_symbols", "allowed_capabilities")
    @classmethod
    def validate_nonempty_and_deduplicated(
        cls,
        value: tuple[ContractSymbol, ...] | tuple[HarnessCapability, ...],
    ) -> tuple[ContractSymbol, ...] | tuple[HarnessCapability, ...]:
        if not value:
            raise ValueError("策略允许列表不能为空")
        if len(value) != len(set(value)):
            raise ValueError("策略允许列表不能包含重复项")
        return value


class HarnessPolicyViolation(RuntimeError):
    """Safe rejection raised before workflow invocation."""


class HarnessWorkflow[ResultT](Protocol):
    kind: HarnessRunKind
    required_capabilities: tuple[HarnessCapability, ...]

    async def run(self, request: HarnessRunRequest) -> ResultT: ...
