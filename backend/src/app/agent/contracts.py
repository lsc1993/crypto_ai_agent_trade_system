from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.market.contracts import UtcDateTime
from app.market.symbols import ResearchSymbol

AgentNodeName = Literal[
    "started",
    "collect_market",
    "collect_news",
    "compute_structure",
    "generate_model_report",
    "persist_degraded_report",
    "validate_and_persist_report",
]


class AgentErrorCode(StrEnum):
    """Finite error identifiers that are safe to retain in a checkpoint."""

    NEWS_SOURCE_FAILED = "news_source_failed"
    MARKET_CONTEXT_UNAVAILABLE = "market_context_unavailable"
    MARKET_RESEARCH_UNAVAILABLE = "market_research_unavailable"
    MARKET_DATA_INVALID = "market_data_invalid"
    MARKET_DATA_MISSING = "market_data_missing"
    MARKET_STALE = "market_stale"
    MARKET_CLOSED_CANDLE_MISSING = "market_closed_candle_missing"
    MODEL_NOT_CONFIGURED = "model_not_configured"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_UPSTREAM_ERROR = "model_upstream_error"
    MODEL_TRANSPORT_ERROR = "model_transport_error"
    MODEL_INVALID_RESPONSE = "model_invalid_response"
    MODEL_EMPTY_RESPONSE = "model_empty_response"
    MODEL_INVALID_EVIDENCE = "model_invalid_evidence"


class AgentRunState(BaseModel):
    """Checkpoint-safe orchestration state containing no research payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_id: UUID
    symbol: ResearchSymbol
    started_at: UtcDateTime
    snapshot_id: UUID | None = None
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=30)
    news_source_count: Annotated[int, Field(ge=0, le=30)] = 0
    news_success_count: Annotated[int, Field(ge=0, le=30)] = 0
    news_failure_count: Annotated[int, Field(ge=0, le=30)] = 0
    node_name: AgentNodeName = "started"
    error_codes: tuple[AgentErrorCode, ...] = Field(default=(), max_length=30)

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

    @field_validator("error_codes", mode="before")
    @classmethod
    def require_safe_error_codes(cls, value: object) -> object:
        if not isinstance(value, (tuple, list)):
            raise ValueError("Agent 状态只能包含最小安全错误码")
        values = cast(tuple[object, ...] | list[object], value)
        try:
            for item in values:
                if not isinstance(item, (str, AgentErrorCode)):
                    raise ValueError
                AgentErrorCode(item)
        except (TypeError, ValueError) as error:
            raise ValueError("Agent 状态只能包含最小安全错误码") from error
        return values

    @model_validator(mode="after")
    def require_consistent_news_counts(self) -> AgentRunState:
        if self.news_success_count + self.news_failure_count != self.news_source_count:
            raise ValueError("Agent 新闻来源计数不一致")
        return self
