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
    "做多",
    "做空",
    "开仓",
    "建仓",
    "平仓",
    "保证收益",
    "自动交易",
)
_CHINESE_DIRECT_TRADING_PATTERNS = (
    re.compile(
        r"(?:建议|推荐|应当|应该|可以|宜|不宜|考虑|请|立即|现在|逢低|逢高|分批|直接|择机|优先|避免)"
        r"\s*(?:买入|卖出|做多|做空|开仓|建仓|平仓|加仓|减仓|止损)"
    ),
    re.compile(
        r"(?:买入|卖出|做多|做空|开仓|建仓|平仓|加仓|减仓)"
        r"\s*(?:BTC|ETH|比特币|以太坊)(?:USDT)?\b",
        flags=re.IGNORECASE,
    ),
    re.compile(r"(?:设置|设定|使用|采用|调整)\s*(?:止损|杠杆|仓位)"),
)
_PROHIBITED_ENGLISH_PATTERNS = (
    re.compile(r"\b(?:buy|sell|long|short)\s+(?:btc|eth|bitcoin|ethereum)(?:usdt)?\b"),
    re.compile(r"\b(?:buy|sell)\b.*\b(?:now|immediately|today|btc|eth|bitcoin|ethereum)\b"),
    re.compile(r"\b(?:consider|recommend|advise|suggest)\s+(?:buying|selling|to\s+(?:buy|sell))\b"),
    re.compile(r"\bworth\s+(?:buying|selling)\b"),
    re.compile(r"\b(?:go|stay)\s+(?:long|short)\b"),
    re.compile(r"\b(?:open|close)\s+(?:a\s+)?(?:long|short)?\s*position\b"),
    re.compile(r"\b(?:take\s+profit|stop\s+loss|entry\s+price|exit\s+price|use\s+leverage)\b"),
    re.compile(r"\b(?:recommend|advice)\s+(?:buying|selling|to\s+buy|to\s+sell)\b"),
    re.compile(r"\b(?:increase|reduce)\s+(?:your\s+)?(?:crypto\s+)?exposure\b"),
    re.compile(r"\b(?:add\s+to|trim)\s+(?:your\s+)?(?:position|exposure)\b"),
    re.compile(r"\b(?:enter|place|execute)\s+(?:a\s+)?(?:trade|order)\b"),
    re.compile(
        r"\b(?:invest|purchase|accumulate)\s+(?:in\s+)?(?:btc|eth|bitcoin|ethereum)(?:usdt)?\b"
    ),
    re.compile(
        r"\b(?:invest|purchase|accumulate)\b.*\b(?:now|immediately|today|btc|eth|bitcoin|ethereum)\b"
    ),
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
    chinese_direct_trading = next(
        (
            pattern.pattern
            for pattern in _CHINESE_DIRECT_TRADING_PATTERNS
            if pattern.search(guard_text) is not None
        ),
        None,
    )
    if chinese_direct_trading is not None:
        raise ValueError(f"报告文本不能包含交易指令：{chinese_direct_trading}")
    english_prohibited = next(
        (
            pattern.pattern
            for pattern in _PROHIBITED_ENGLISH_PATTERNS
            if pattern.search(normalized.casefold()) is not None
        ),
        None,
    )
    if english_prohibited is not None:
        raise ValueError(f"报告文本不能包含交易指令：{english_prohibited}")
    return normalized


def validate_research_display_text(value: str) -> str:
    """Validate text that may be returned by the constrained research model."""
    return _validate_display_text(value)


def _validate_chinese_research_display_text(value: str) -> str:
    normalized = _validate_display_text(value)
    if re.search(r"[\u3400-\u9fff]", normalized) is None:
        raise ValueError("中文市场研究章节必须包含中文文本")
    return normalized


def _require_evidence_ids(value: tuple[UUID, ...]) -> tuple[UUID, ...]:
    if not 1 <= len(value) <= _MAX_LIST_ITEMS:
        raise ValueError("研究结论必须引用一至十二条冻结证据")
    if len(set(value)) != len(value):
        raise ValueError("研究结论不能重复引用冻结证据")
    return value


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

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("催化事件类别不能为空")
        return _validate_display_text(normalized)

    @field_validator("claim", "timing")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_display_text(value)

    @field_validator("evidence_ids")
    @classmethod
    def require_evidence(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return _require_evidence_ids(value)


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
        return _require_evidence_ids(value)


class EvidenceBackedClaim(_ReportModel):
    label: str
    detail: str
    evidence_ids: tuple[UUID, ...]

    @field_validator("label", "detail")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_chinese_research_display_text(value)

    @field_validator("evidence_ids")
    @classmethod
    def require_evidence(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return _require_evidence_ids(value)


class MarketOverview(_ReportModel):
    headline: str
    summary: str
    evidence_ids: tuple[UUID, ...]

    @field_validator("headline", "summary")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_chinese_research_display_text(value)

    @field_validator("evidence_ids")
    @classmethod
    def require_evidence(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return _require_evidence_ids(value)


class ResearchPerspective(_ReportModel):
    horizon: Literal["short_term", "long_term"]
    outlook: MarketOutlook
    heading: str
    thesis: str
    drivers: tuple[EvidenceBackedClaim, ...]
    invalidation: tuple[RiskAndInvalidation, ...]

    @field_validator("heading", "thesis")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_chinese_research_display_text(value)

    @field_validator("drivers")
    @classmethod
    def validate_drivers(
        cls,
        value: tuple[EvidenceBackedClaim, ...],
    ) -> tuple[EvidenceBackedClaim, ...]:
        if not 1 <= len(value) <= 4:
            raise ValueError("市场观点必须包含一至四项驱动因素")
        return value

    @field_validator("invalidation")
    @classmethod
    def validate_invalidation(
        cls,
        value: tuple[RiskAndInvalidation, ...],
    ) -> tuple[RiskAndInvalidation, ...]:
        if not 1 <= len(value) <= 4:
            raise ValueError("市场观点必须包含一至四项失效条件")
        return value


class AgentResearchNarrative(_ReportModel):
    market_overview: MarketOverview
    short_term: ResearchPerspective
    long_term: ResearchPerspective

    @model_validator(mode="after")
    def validate_perspective_horizons(self) -> AgentResearchNarrative:
        if self.short_term.horizon != "short_term":
            raise ValueError("短期市场观点必须使用 short_term 周期")
        if self.long_term.horizon != "long_term":
            raise ValueError("长期市场观点必须使用 long_term 周期")
        return self


class AgentDataQuality(_ReportModel):
    freshness: FreshnessStatus
    missing_inputs: tuple[Annotated[str, Field(min_length=1, max_length=100)], ...]
    source_coverage: Literal["none", "partial", "complete"]


class FrozenMarketMetrics(_ReportModel):
    """只读报告展示用的冻结公开市场指标。"""

    price: DecimalValue
    change_24h: DecimalValue
    volume_24h: DecimalValue
    funding_rate: DecimalValue
    open_interest: DecimalValue
    fear_greed_value: int | None = Field(default=None, ge=0, le=100)
    fear_greed_classification: Annotated[str | None, Field(max_length=100)] = None
    fear_greed_change_7d: int | None = Field(default=None, ge=-100, le=100)

    @field_validator(
        "price",
        "change_24h",
        "volume_24h",
        "funding_rate",
        "open_interest",
        mode="before",
    )
    @classmethod
    def parse_decimal_value(cls, value: object) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (Decimal, str)):
            raise ValueError("冻结市场指标必须是 Decimal 或十进制字符串")
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError) as error:
            raise ValueError("冻结市场指标必须是有效十进制数") from error
        if not parsed.is_finite():
            raise ValueError("冻结市场指标必须是有限十进制数")
        return parsed

    @field_validator("fear_greed_classification")
    @classmethod
    def normalize_fear_greed_classification(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("冻结情绪分类不能为空")
        return normalized

    @model_validator(mode="after")
    def validate_market_metrics(self) -> FrozenMarketMetrics:
        if self.price <= 0:
            raise ValueError("冻结市场价格必须为正数")
        if self.volume_24h < 0 or self.open_interest < 0:
            raise ValueError("冻结市场成交额和未平仓量不能为负数")
        sentiment = (
            self.fear_greed_value,
            self.fear_greed_classification,
            self.fear_greed_change_7d,
        )
        if any(value is None for value in sentiment) and any(
            value is not None for value in sentiment
        ):
            raise ValueError("冻结情绪指标必须完整提供或全部缺失")
        return self


class AgentAnalysis(_ReportModel):
    horizon: Literal["1_to_3_days", "dual_horizon"]
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
    narrative: AgentResearchNarrative | None = None
    market_metrics: FrozenMarketMetrics | None = None

    @field_validator("limitations")
    @classmethod
    def validate_limitations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > _MAX_LIST_ITEMS:
            raise ValueError("报告限制不能超过 12 项")
        return tuple(_validate_display_text(item) for item in value)

    @model_validator(mode="after")
    def validate_narrative(self) -> AgentAnalysis:
        if self.horizon == "1_to_3_days":
            if self.narrative is not None:
                raise ValueError("历史一至三天报告不能包含双层叙事")
            if self.market_metrics is not None:
                raise ValueError("历史一至三天报告不能包含冻结市场指标")
            return self
        if self.narrative is None:
            raise ValueError("双层市场报告必须包含中文叙事")
        if self.market_metrics is None:
            raise ValueError("双层市场报告必须包含冻结市场指标")
        display_length = _narrative_display_length(self.narrative)
        if not 1_500 <= display_length <= 2_500:
            raise ValueError("双层市场报告正文必须为 1500 至 2500 个字符")
        return self


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
        referenced_ids = _agent_analysis_evidence_ids(self.agent_analysis)
        if not referenced_ids <= evidence_ids:
            raise ValueError("Agent 结论只能引用本报告的冻结证据")
        return self


def _narrative_display_length(narrative: AgentResearchNarrative) -> int:
    return len(
        "".join(
            (
                narrative.market_overview.headline,
                narrative.market_overview.summary,
                narrative.short_term.thesis,
                narrative.long_term.thesis,
                *(driver.detail for driver in narrative.short_term.drivers),
                *(driver.detail for driver in narrative.long_term.drivers),
            )
        )
    )


def _agent_analysis_evidence_ids(analysis: AgentAnalysis) -> set[UUID]:
    referenced_ids = {
        evidence_id
        for item in (
            *analysis.catalysts,
            *analysis.risks_and_invalidation,
        )
        for evidence_id in item.evidence_ids
    }
    if analysis.narrative is None:
        return referenced_ids
    narrative = analysis.narrative
    for item in (
        narrative.market_overview,
        *narrative.short_term.drivers,
        *narrative.short_term.invalidation,
        *narrative.long_term.drivers,
        *narrative.long_term.invalidation,
    ):
        referenced_ids.update(item.evidence_ids)
    return referenced_ids


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
