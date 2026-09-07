"""Frozen factual topics and evidence-bound model interpretations for report enrichment."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from app.market.contracts import UtcDateTime

FactorKind = Literal["policy", "funding", "etf"]
FactorStatus = Literal["available", "partial", "missing", "failed"]


class _FactorModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", alias_generator=to_camel, populate_by_name=True
    )


class FactorFact(_FactorModel):
    label: str = Field(min_length=1, max_length=160)
    value: str | None = Field(default=None, max_length=1000)
    unit: Literal["text", "rate", "usd", "count"] = "text"


class PolicyEvent(_FactorModel):
    institution: str
    title: str = Field(max_length=4000)
    summary: str = Field(max_length=4000)
    published_at: UtcDateTime
    evidence_id: UUID
    source_url: str

    @field_validator("published_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        return _utc(value)


class FactorInterpretation(_FactorModel):
    topic: FactorKind
    outlook: Literal["bullish", "bearish", "neutral"]
    summary: str
    short_term: str
    long_term: str
    invalidation: str
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=12)

    @field_validator("summary", "short_term", "long_term", "invalidation")
    @classmethod
    def validate_display_text(cls, value: str) -> str:
        # Deferred import keeps the report contracts independent of their nested topic types.
        from app.reports.contracts import validate_research_display_text

        return validate_research_display_text(value)

    @model_validator(mode="after")
    def validate_interpretation(self) -> FactorInterpretation:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("专题证据引用不能重复")
        if sum(map(len, (self.summary, self.short_term, self.long_term, self.invalidation))) > 2400:
            raise ValueError("每个专题解释不能超过 2400 字符")
        return self


class FactorTopic(_FactorModel):
    status: FactorStatus
    window_start: UtcDateTime | None = None
    window_end: UtcDateTime
    observed_at: UtcDateTime | None = None
    fetched_at: UtcDateTime | None = None
    facts: tuple[FactorFact, ...] = Field(default=(), max_length=30)
    events: tuple[PolicyEvent, ...] = Field(default=(), max_length=12)
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=12)
    interpretation: FactorInterpretation | None = None
    limitations: tuple[str, ...] = Field(default=(), max_length=12)

    @field_validator("window_start", "window_end", "observed_at", "fetched_at")
    @classmethod
    def require_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def validate_topic(self) -> FactorTopic:
        if self.window_start is not None and self.window_start > self.window_end:
            raise ValueError("专题时间窗口无效")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("专题证据引用不能重复")
        if not {event.evidence_id for event in self.events} <= set(self.evidence_ids):
            raise ValueError("政策事件必须引用专题证据")
        if self.interpretation is not None:
            if self.status in {"missing", "failed"}:
                raise ValueError("缺失数据不能形成专题观点")
            if not set(self.interpretation.evidence_ids) <= set(self.evidence_ids):
                raise ValueError("解释必须引用本专题证据")
        return self


class FactorAnalysis(_FactorModel):
    policy: FactorTopic
    funding: FactorTopic
    etf: FactorTopic

    @model_validator(mode="after")
    def validate_topics(self) -> FactorAnalysis:
        for kind in ("policy", "funding", "etf"):
            topic: FactorTopic = getattr(self, kind)
            if topic.interpretation is not None and topic.interpretation.topic != kind:
                raise ValueError("专题类别与解释不一致")
        return self

    def evidence_ids(self) -> set[UUID]:
        return set((*self.policy.evidence_ids, *self.funding.evidence_ids, *self.etf.evidence_ids))


def unavailable_topic(*, as_of: datetime, failed: bool = False, reason: str) -> FactorTopic:
    return FactorTopic(
        status="failed" if failed else "missing", window_end=as_of, limitations=(reason,)
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("专题时间必须是 UTC 且带时区")
    return value
