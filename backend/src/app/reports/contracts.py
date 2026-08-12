from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
    model_validator,
)

from app.market.contracts import (
    ContractSymbol,
    DecimalValue,
    FreshnessStatus,
    MarketTimeframe,
    UtcDateTime,
)
from app.market.repository import snapshot_payload_sha256

_MAX_TEXT_LENGTH = 1_000
_MAX_LIST_ITEMS = 12
_MAX_PAYLOAD_BYTES = 64 * 1024
_PROHIBITED_PHRASES = (
    "买入",
    "卖出",
    "开仓",
    "平仓",
    "仓位",
    "杠杆",
    "止损",
    "保证收益",
    "自动交易",
)


class AnalysisReportStatus(StrEnum):
    COMPLETED = "completed"
    DEGRADED = "degraded"


class ReportGeneratorKind(StrEnum):
    DETERMINISTIC = "deterministic"
    LANGGRAPH_DEEPSEEK = "langgraph_deepseek"


class MarketOutlook(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class TrendDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class ReportStorageUnavailableError(RuntimeError):
    """报告无法持久化或读取时的安全错误。"""


def report_payload_sha256(payload: dict[str, JsonValue]) -> str:
    """计算证据载荷的稳定 SHA-256。"""
    return snapshot_payload_sha256(payload)


class _ReportModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是 UTC 且带时区")
    return value.astimezone(UTC)


def _validate_display_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("报告文本不能为空")
    if len(normalized) > _MAX_TEXT_LENGTH:
        raise ValueError("报告文本不能超过 1000 个字符")
    guard_text = _normalize_text(normalized).replace("未平仓量", "")
    prohibited = next(
        (phrase for phrase in _PROHIBITED_PHRASES if phrase in guard_text),
        None,
    )
    if prohibited is not None:
        raise ValueError(f"报告文本不能包含交易指令：{prohibited}")
    return normalized


def _validate_source_url(value: str) -> str:
    normalized = value.strip()
    if not normalized.startswith(("https://", "http://")):
        raise ValueError("证据来源 URL 必须使用 HTTP(S)")
    return normalized


class AnalysisEvidenceDraft(_ReportModel):
    id: UUID = Field(default_factory=uuid4, exclude=True)
    report_id: UUID
    symbol: ContractSymbol
    source: Annotated[str, Field(min_length=1, max_length=100)]
    source_url: str
    observed_at: UtcDateTime
    fetched_at: UtcDateTime
    summary: str
    payload: dict[str, JsonValue]
    payload_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("证据来源不能为空")
        return normalized

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        return _validate_source_url(value)

    @field_validator("observed_at", "fetched_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _validate_display_text(value)

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if len(str(value).encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            raise ValueError("证据载荷不能超过 64 KiB")
        report_payload_sha256(value)
        return value

    @model_validator(mode="after")
    def validate_evidence(self) -> AnalysisEvidenceDraft:
        if self.fetched_at < self.observed_at:
            raise ValueError("抓取时间不能早于观测时间")
        if self.payload_sha256 != report_payload_sha256(self.payload):
            raise ValueError("证据载荷哈希不匹配")
        return self


class AnalysisReportDraft(_ReportModel):
    id: UUID = Field(default_factory=uuid4)
    analysis_id: UUID = Field(default_factory=uuid4)
    symbol: ContractSymbol
    status: AnalysisReportStatus
    title: str
    summary: str
    facts: tuple[str, ...]
    inferences: tuple[str, ...]
    risks: tuple[str, ...]
    limitations: tuple[str, ...]
    generated_at: UtcDateTime
    data_cutoff_at: UtcDateTime | None

    @field_validator("title", "summary")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_display_text(value)

    @field_validator("facts", "inferences", "risks", "limitations")
    @classmethod
    def validate_text_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > _MAX_LIST_ITEMS:
            raise ValueError("报告列表不能超过 12 项")
        return tuple(_validate_display_text(item) for item in value)

    @field_validator("generated_at", "data_cutoff_at")
    @classmethod
    def validate_utc_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)

    @model_validator(mode="after")
    def validate_status_fields(self) -> AnalysisReportDraft:
        if self.data_cutoff_at is not None and self.data_cutoff_at > self.generated_at:
            raise ValueError("数据截止时间不能晚于生成时间")
        if self.status is AnalysisReportStatus.DEGRADED:
            if self.facts or self.inferences:
                raise ValueError("降级报告不能包含市场事实或推断")
            if not self.risks or not self.limitations:
                raise ValueError("降级报告必须说明风险和限制")
        return self


class AnalysisReportCreation(_ReportModel):
    report: AnalysisReportDraft
    evidences: tuple[AnalysisEvidenceDraft, ...]

    @model_validator(mode="after")
    def validate_creation(self) -> AnalysisReportCreation:
        if any(evidence.report_id != self.report.id for evidence in self.evidences):
            raise ValueError("证据报告 ID 必须与报告一致")
        if self.report.status is AnalysisReportStatus.COMPLETED and not self.evidences:
            raise ValueError("完成报告必须至少包含一条证据")
        return self


class PriceZone(_ReportModel):
    lower: DecimalValue
    upper: DecimalValue
    timeframe: MarketTimeframe
    rationale: str

    @field_validator("lower", "upper", mode="before")
    @classmethod
    def validate_decimal(cls, value: object) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (Decimal, str)):
            raise ValueError("价位必须是 Decimal 或十进制字符串")
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError) as error:
            raise ValueError("价位必须是有效十进制数") from error
        if not parsed.is_finite() or parsed <= 0:
            raise ValueError("价位必须是有限正十进制数")
        return parsed

    @field_validator("rationale")
    @classmethod
    def validate_rationale(cls, value: str) -> str:
        return _validate_display_text(value)

    @model_validator(mode="after")
    def validate_bounds(self) -> PriceZone:
        if self.upper < self.lower:
            raise ValueError("价位区间上界不能低于下界")
        return self


class Catalyst(_ReportModel):
    category: Annotated[str, Field(min_length=1, max_length=100)]
    direction: MarketOutlook
    claim: str
    evidence_ids: tuple[UUID, ...]
    timing: str

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        return value.strip()

    @field_validator("claim", "timing")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_display_text(value)

    @field_validator("evidence_ids")
    @classmethod
    def require_evidence(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if not value:
            raise ValueError("催化事件必须引用冻结证据")
        return value


class RiskAndInvalidation(_ReportModel):
    condition: str
    impact: str
    evidence_ids: tuple[UUID, ...]

    @field_validator("condition", "impact")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_display_text(value)

    @field_validator("evidence_ids")
    @classmethod
    def require_evidence(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if not value:
            raise ValueError("风险与失效条件必须引用冻结证据")
        return value


class AgentDataQuality(_ReportModel):
    freshness: FreshnessStatus
    missing_inputs: tuple[Annotated[str, Field(min_length=1, max_length=100)], ...]
    source_coverage: Literal["none", "partial", "complete"]


class AgentAnalysis(_ReportModel):
    horizon: Literal["1_to_3_days"]
    outlook: MarketOutlook
    confidence: Literal["low", "medium", "high"]
    trend_alignment: dict[MarketTimeframe, TrendDirection] = Field(
        default_factory=dict[MarketTimeframe, TrendDirection]
    )
    support_zones: tuple[PriceZone, ...]
    resistance_zones: tuple[PriceZone, ...]
    catalysts: tuple[Catalyst, ...]
    risks_and_invalidation: tuple[RiskAndInvalidation, ...]
    data_quality: AgentDataQuality
    limitations: tuple[str, ...] = ()

    @field_validator("limitations")
    @classmethod
    def validate_limitations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > _MAX_LIST_ITEMS:
            raise ValueError("报告限制不能超过 12 项")
        return tuple(_validate_display_text(item) for item in value)


class AgentReportCreation(AnalysisReportCreation):
    started_at: UtcDateTime
    completed_at: UtcDateTime
    generator_kind: ReportGeneratorKind = ReportGeneratorKind.LANGGRAPH_DEEPSEEK
    error_code: Annotated[str | None, Field(max_length=100)] = None
    agent_analysis: AgentAnalysis

    @field_serializer("evidences", when_used="json")
    def serialize_agent_evidences(
        self,
        evidences: tuple[AnalysisEvidenceDraft, ...],
    ) -> tuple[dict[str, JsonValue], ...]:
        return tuple(
            cast(
                dict[str, JsonValue],
                {"id": str(evidence.id), **evidence.model_dump(mode="json")},
            )
            for evidence in evidences
        )

    @field_validator("started_at", "completed_at")
    @classmethod
    def validate_run_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("error_code")
    @classmethod
    def normalize_error_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or re.fullmatch(r"[a-z0-9_]+", normalized) is None:
            raise ValueError("Agent 错误码必须是最小安全标识")
        return normalized

    @model_validator(mode="after")
    def validate_agent_creation(self) -> AgentReportCreation:
        if self.generator_kind is not ReportGeneratorKind.LANGGRAPH_DEEPSEEK:
            raise ValueError("Agent 报告生成器类型无效")
        if self.completed_at < self.started_at:
            raise ValueError("Agent 完成时间不能早于开始时间")
        evidence_ids = {evidence.id for evidence in self.evidences}
        referenced_ids = {
            evidence_id
            for item in (
                *self.agent_analysis.catalysts,
                *self.agent_analysis.risks_and_invalidation,
            )
            for evidence_id in item.evidence_ids
        }
        if not referenced_ids <= evidence_ids:
            raise ValueError("Agent 结论只能引用本报告的冻结证据")
        return self


class PersistedAnalysisEvidence(AnalysisEvidenceDraft):
    id: UUID = Field(default_factory=uuid4)
    created_at: UtcDateTime


class AnalysisReportSummary(AnalysisReportDraft):
    created_at: UtcDateTime
    generator_kind: ReportGeneratorKind = ReportGeneratorKind.DETERMINISTIC


class PersistedAnalysisReport(AnalysisReportSummary):
    evidence: tuple[PersistedAnalysisEvidence, ...]
    agent_analysis: AgentAnalysis | None = None


class ReportPage(_ReportModel):
    items: tuple[AnalysisReportSummary, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: Annotated[int, Field(ge=0)]
