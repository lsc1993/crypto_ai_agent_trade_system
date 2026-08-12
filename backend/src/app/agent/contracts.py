from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.market.contracts import ContractSymbol, UtcDateTime

AgentNodeName = Literal[
    "started",
    "collect_market",
    "collect_news",
    "compute_structure",
    "generate_model_report",
    "persist_degraded_report",
    "validate_and_persist_report",
]


class AgentRunState(BaseModel):
    """Checkpoint-safe orchestration state containing no research payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_id: UUID
    symbol: ContractSymbol
    started_at: UtcDateTime
    snapshot_id: UUID | None = None
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=30)
    news_source_count: Annotated[int, Field(ge=0, le=30)] = 0
    news_success_count: Annotated[int, Field(ge=0, le=30)] = 0
    news_failure_count: Annotated[int, Field(ge=0, le=30)] = 0
    node_name: AgentNodeName = "started"
    error_codes: tuple[Annotated[str, Field(max_length=100)], ...] = Field(
        default=(),
        max_length=30,
    )

    @field_validator("started_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("Agent 开始时间必须是 UTC 且带时区")
        return value.astimezone(UTC)

    @field_validator("evidence_ids")
    @classmethod
    def require_unique_evidence_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("Agent 证据 ID 必须唯一")
        return value

    @field_validator("error_codes")
    @classmethod
    def require_safe_error_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(re.fullmatch(r"[a-z0-9_]+", item) is None for item in value):
            raise ValueError("Agent 状态只能包含最小安全错误码")
        return value

    @model_validator(mode="after")
    def require_consistent_news_counts(self) -> AgentRunState:
        if self.news_success_count + self.news_failure_count != self.news_source_count:
            raise ValueError("Agent 新闻来源计数不一致")
        return self
