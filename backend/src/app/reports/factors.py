# 综合报告专题契约区分确定性事实、官方事件、覆盖状态和模型定性解释。
# 解释必须属于同一专题并引用该专题冻结证据，缺失或失败不能形成方向观点。
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


# 数值使用字符串或空值表达，空值表示未知而非零，单位单独保存。
class FactorFact(_FactorModel):
    label: str = Field(min_length=1, max_length=160)
    value: str | None = Field(default=None, max_length=1000)
    unit: Literal["text", "rate", "usd", "count"] = "text"


# 保存批准政策元数据与单条冻结引用，发布时间不代替政策实际生效时间。
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


# 模型解释使用受限中文文本与去重引用，单个专题整体长度有上限。
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


# 聚合窗口、事实、事件、引用和限制；状态与解释可用性必须一致。
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


# 组合三个独立专题并核对解释类别，禁止把另一专题的解读错位挂载。
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


# 分别表示未采集到与来源失败，保留本次窗口终点和原因，不制造事实。
def unavailable_topic(*, as_of: datetime, failed: bool = False, reason: str) -> FactorTopic:
    return FactorTopic(
        status="failed" if failed else "missing", window_end=as_of, limitations=(reason,)
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("专题时间必须是 UTC 且带时区")
    return value
