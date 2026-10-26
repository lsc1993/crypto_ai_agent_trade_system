# 技术 v2 契约区分冻结上下文、模型数值占位模板、程序渲染正文与阶段诊断。
# 完成结果必须是完整模型生成且无错误；规则降级保留质量原因，原始思考不属于契约。
"""Versioned, evidence-bound research plans. No execution contracts."""

from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.market.symbols import ResearchSymbol
from app.reports.technical import (
    DecimalText,
    TechnicalAnalysis,
    TechnicalBase,
    TechnicalReport,
    contains_quantitative_number,
    require_utc,
)

SECTIONS = (
    "market_structure",
    "supporting_evidence",
    "counter_evidence",
    "method_applications",
    "entry_conditions",
    "stop_rationale",
    "target_rationale",
    "invalidation",
    "alternative",
    "waiting_conditions",
    "risks",
)


# 保存摘要价格、最新已收盘价格与分析截止，提供统一的冻结引用根。
class TechnicalContext(TechnicalBase):
    analysis: TechnicalAnalysis
    summary_price: DecimalText | None
    latest_closed_prices: dict[str, DecimalText]
    data_cutoff_at: datetime

    @field_validator("data_cutoff_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)


# 正文仅允许已绑定事实占位符；直接数值、即时执行语言及重复单位均拒绝。
class PlanClaim(TechnicalBase):
    text: str = Field(min_length=20, max_length=1200)
    evidence_id: UUID
    fact_refs: tuple[str, ...] = Field(min_length=1, max_length=12)
    method_refs: tuple[str, ...] = Field(default=(), max_length=4)

    @field_validator("text")
    @classmethod
    def bounded_template(cls, value: str) -> str:
        import re

        text = value.strip()
        # 先排除合法占位符再检查直接数量，保证引用路径的数字不被误当正文金融数值。
        plain = re.sub(r"\{\{[A-Za-z0-9_.]+\}\}", "", text)
        if "{" in plain or "}" in plain or contains_quantitative_number(plain):
            raise ValueError("unbound_number")
        if re.search(
            r"(?<![\u4e00-\u9fff])[零〇一二三四五六七八九十两壹贰叁肆伍陆柒捌玖](?![\u4e00-\u9fff])|(?:止损|入场|目标|价格).{0,8}(?:设为|定为|取|为)[零〇一二三四五六七八九十两](?=$|[，。；\s])",
            plain,
        ):
            raise ValueError("unbound_number")
        if re.search(
            r"(?:立即|马上|现在|当前|直接).{0,8}(?:执行|入场)|无需等待|不必等待|全部条件.{0,4}(?:成立|满足)|(?:已经|已).{0,4}满足全部条件",
            plain,
        ):
            raise ValueError("live_execution_language")
        if re.search(r"\}\}\s*(?:美元|美金|USDT|元|倍|%|％|小时|分钟)", text, re.I):
            raise ValueError("placeholder_unit")
        if not re.search(r"[\u4e00-\u9fff]", plain):
            raise ValueError("chinese_required")
        if re.search(
            r"下单|买入|卖出|开仓|平仓|建仓|加仓|减仓|仓位|杠杆|满仓|半仓|保证|稳赚|必涨|必跌|胜率|收益承诺|内幕|\b(?:buy|sell|order|leverage|guarantee)\b",
            plain,
            re.I,
        ):
            raise ValueError("execution_language")
        return text


ClaimList = Annotated[tuple[PlanClaim, ...], Field(min_length=1, max_length=6)]


# 模型分析或编排的同一结构，章节和整体长度有界；候选归属还需引用校验。
class TechnicalDecisionSummary(TechnicalBase):
    stance: Literal["long", "short", "wait"]
    selected_plan_ref: Literal["plans.0"] | None
    market_structure: ClaimList
    supporting_evidence: ClaimList
    counter_evidence: ClaimList
    method_applications: Annotated[tuple[PlanClaim, ...], Field(min_length=1, max_length=4)]
    entry_conditions: ClaimList
    stop_rationale: ClaimList
    target_rationale: ClaimList
    invalidation: ClaimList
    alternative: ClaimList
    waiting_conditions: ClaimList
    risks: ClaimList

    @model_validator(mode="after")
    def length(self) -> "TechnicalDecisionSummary":
        if sum(len(claim.text) for key in SECTIONS for claim in getattr(self, key)) > 16000:
            raise ValueError("book_length")
        return self


TechnicalPlanBook = TechnicalDecisionSummary


# 程序替换占位符后的可展示正文，仍保留证据、事实及方法引用供复核。
class RenderedClaim(TechnicalBase):
    text: str = Field(min_length=1, max_length=5000)
    evidence_id: UUID
    fact_refs: tuple[str, ...]
    method_refs: tuple[str, ...]


# 冻结渲染结果，不能根据访问时的行情自行刷新触发状态。
class RenderedPlanBook(TechnicalBase):
    stance: Literal["long", "short", "wait"]
    selected_plan_ref: Literal["plans.0"] | None
    market_structure: tuple[RenderedClaim, ...]
    supporting_evidence: tuple[RenderedClaim, ...]
    counter_evidence: tuple[RenderedClaim, ...]
    method_applications: tuple[RenderedClaim, ...]
    entry_conditions: tuple[RenderedClaim, ...]
    stop_rationale: tuple[RenderedClaim, ...]
    target_rationale: tuple[RenderedClaim, ...]
    invalidation: tuple[RenderedClaim, ...]
    alternative: tuple[RenderedClaim, ...]
    waiting_conditions: tuple[RenderedClaim, ...]
    risks: tuple[RenderedClaim, ...]


# 只保存阶段、尝试、结果和有界用量统计，不保存模型思考正文。
class TechnicalStageDiagnostic(TechnicalBase):
    stage: Literal["analysis", "composition"]
    attempt: int = Field(ge=1, le=2)
    outcome: Literal[
        "success", "length", "empty", "invalid", "timeout", "upstream", "not_configured"
    ]
    finish_reason: Literal["stop", "length"] | None = None
    reasoning_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    model: Literal["deepseek-v4-pro", "deepseek-v4-flash"]
    thinking: bool
    reasoning_effort: Literal["high", "low"] | None
    max_tokens: int = Field(ge=1, le=65536)


# 明确区分完整模型、编排降级、分析不可用及数据不足，不能把规则结果包装成模型成功。
class TechnicalGeneration(TechnicalBase):
    source: Literal["model", "rules"]
    quality: Literal[
        "complete", "composition_fallback", "analysis_unavailable", "data_insufficient"
    ]
    prompt_version: Literal["technical-plan-1"] = "technical-plan-1"
    diagnostics: tuple[TechnicalStageDiagnostic, ...] = Field(default=(), max_length=4)


# 校验分析与上下文相同、截止早于创建时间，完成状态与来源、质量和错误一致。
class TechnicalPlanReport(TechnicalBase):
    version: Literal["technical-v2"] = "technical-v2"
    id: UUID
    analysis_id: UUID
    symbol: ResearchSymbol
    status: Literal["completed", "degraded"]
    created_at: datetime
    data_cutoff_at: datetime
    analysis: TechnicalAnalysis
    context: TechnicalContext
    decision: TechnicalDecisionSummary | None
    plan_book: RenderedPlanBook
    generation: TechnicalGeneration
    error_code: (
        Literal[
            "market_unavailable",
            "data_quality_insufficient",
            "model_not_configured",
            "model_timeout",
            "model_upstream_error",
            "model_invalid_response",
            "model_output_limit",
            "model_empty_response",
            "run_timeout",
        ]
        | None
    )

    @field_validator("created_at", "data_cutoff_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def consistent(self) -> "TechnicalPlanReport":
        if (
            self.analysis != self.context.analysis
            or self.data_cutoff_at != self.context.data_cutoff_at
            or self.data_cutoff_at > self.created_at
        ):
            raise ValueError("context_mismatch")
        # 只有完整模型来源才是完成；规则输出即使文本丰富，也必须保持明确降级状态。
        complete = self.generation.quality == "complete" and self.generation.source == "model"
        if complete != (self.status == "completed") or complete != (self.error_code is None):
            raise ValueError("generation_status")
        if complete and self.decision is None:
            raise ValueError("decision_required")
        return self


TechnicalReportDocument = TechnicalReport | TechnicalPlanReport


# 按显式 v2 版本解析新契约，其余交给 v1 验证，使旧报告保持可读取。
def parse_technical_report(payload: object) -> TechnicalReportDocument:
    if (
        isinstance(payload, dict)
        and cast(dict[str, object], payload).get("version") == "technical-v2"
    ):
        return TechnicalPlanReport.model_validate(payload)
    return TechnicalReport.model_validate(payload)
