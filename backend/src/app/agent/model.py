# 综合研究模型适配器只把冻结证据格式化为中文双周期提案，最终保存前仍需业务层校验。
# 格式失败最多三次；超时及上游错误直接交给降级，诊断仅保留有界字段和错误类别。
"""语言模型提案边界模块。

数据流：冻结的 ModelEvidence 与确定性 MarketStructure → 受限 JSON 请求 → Pydantic
事实引用绑定与程序渲染、格式及证据 ID 校验 → AgentAnalysisProposal。
模型输出始终是待业务层验证的提案，不构成自然语言语义已经被证明的结论。
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from time import perf_counter
from typing import Literal, Protocol, cast
from uuid import UUID

import httpx
import structlog
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import ErrorDetails

from app.agent.fact_references import (
    StructuredFactRenderResult,
    render_structured_fact_references_partially,
)
from app.agent.factors import apply_interpretations
from app.agent.market_structure import MarketStructure
from app.agent.model_diagnostics import schema_error_kinds
from app.agent.numeric_facts import (
    NumericFact,
    NumericReferenceError,
    select_numeric_facts,
)
from app.agent.prompt import research_user_message, system_prompt
from app.market.contracts import UtcDateTime
from app.market.symbols import ResearchSymbol
from app.reports.contracts import (
    AgentResearchNarrative,
    Catalyst,
    MarketOutlook,
    MarketOverview,
    ResearchPerspective,
    RiskAndInvalidation,
    validate_research_display_text,
)
from app.reports.factors import FactorAnalysis, FactorInterpretation

_DEEPSEEK_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
_MAX_TOKENS = 4_000
# 单条证据与整份正文分开限长，防止输入载荷或失败诊断无限膨胀。
_MAX_EVIDENCE_CONTENT_LENGTH = 4_000
_MAX_VALIDATION_FIELD_PATHS = 8
_MAX_VALIDATION_ISSUES = 99
_MIN_NARRATIVE_DISPLAY_LENGTH = 1_100
_MAX_NARRATIVE_DISPLAY_LENGTH = 2_500
_TARGET_NARRATIVE_DISPLAY_LENGTH = 2_200
_VALIDATION_FIELD_PATH = re.compile(r"^[a-z][a-z0-9_]*(?:\.(?:[a-z][a-z0-9_]*|[0-9]+))*$")
_MAX_FORMAT_ATTEMPTS = 3
_FORMAT_RETRY_INSTRUCTION = (
    "上一份候选未通过机器格式校验。请从头重新生成一个完整 JSON 对象："
    "不得使用 Markdown 或额外说明；必须包含所有 schema 字段，"
    "只引用提供的 UUID；"
    "数值事实只能通过根级 fact_refs 引用，target 只能指向带 evidence_ids 的叶子段落，"
    "thesis 不接受 fact_refs；每个 target 最多五条，重复引用和超额都会被拒绝；"
    "不得使用①、②、Ⅰ、Ⅱ、½、² 等符号数字或十亿、两万、百分之五、三分之一等中文数量；"
    "市场概况、两个 thesis 与所有 driver.detail 拼接后必须达到 1800 至 2200 个中文字符；"
    "全文合计不得超过 2500 个字符；headline 和 heading 各不超过 30 个中文字符；"
    "市场概况不少于 350 个中文字符，两个 thesis 各不少于 350 个中文字符，"
    "短期和长期各列出二至三个 driver，每个 driver.detail 不少于 175 个中文字符；"
    "所有面向读者的字符串字段均不得出现买入、卖出、做多、做空、开仓、建仓、平仓等操作词，"
    "即使描述市场情绪也不要用做多/做空；"
    "也不得使用 buy/sell/long/short、入场、出场、止损、加仓或减仓等操作表述；"
    "改用多头或空头仓位、上行或下行风险、需要复核等中性研究表述；"
    'direction 字段只能取 "bullish"、"bearish" 或 "neutral"，'
    "不得使用 positive、negative、up、down 等同义值。"
)
logger = structlog.get_logger(__name__)


# 区分市场、新闻及专题证据，便于为不可信新闻和专题引用应用不同边界。
class ModelEvidenceKind(StrEnum):
    MARKET = "market"
    NEWS = "news"
    FUNDING = "funding"
    ETF = "etf"


class _AgentModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelEvidence(_AgentModel):
    """可传递给模型的单条冻结证据，包含来源、时间和受长度限制的内容。"""

    id: UUID
    kind: ModelEvidenceKind
    source: str = Field(min_length=1, max_length=100)
    observed_at: UtcDateTime
    content: str = Field(min_length=1, max_length=_MAX_EVIDENCE_CONTENT_LENGTH)

    @field_validator("source", "content")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("模型证据文本不能为空")
        return normalized

    @field_validator("observed_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("模型证据时间必须是 UTC 且带时区")
        return value.astimezone(UTC)


class ResearchModelRequest(_AgentModel):
    """一次模型研究请求：目标标的、确定性结构和去重后的证据集合。"""

    symbol: ResearchSymbol
    structure: MarketStructure
    evidences: tuple[ModelEvidence, ...] = Field(min_length=1, max_length=30)
    report_language: Literal["zh-CN"] = "zh-CN"
    horizon: Literal["dual_horizon"] = "dual_horizon"
    factor_analysis: FactorAnalysis | None = None
    numeric_facts: tuple[NumericFact, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def require_unique_evidence_ids(self) -> ResearchModelRequest:
        if len({evidence.id for evidence in self.evidences}) != len(self.evidences):
            raise ValueError("模型证据 ID 必须唯一")
        if not {fact.evidence_id for fact in self.numeric_facts} <= {e.id for e in self.evidences}:
            raise ValueError("数值事实必须属于本次冻结证据")
        if len({fact.token for fact in self.numeric_facts}) != len(self.numeric_facts):
            raise ValueError("数值事实引用不能重复")
        return self


# 长度和引用存在性在提案构造时校验；引用是否属于当前输入需额外核对。
class AgentAnalysisProposal(_AgentModel):
    """模型返回的候选研究结论，必须引用本次请求中已知的证据 ID。"""

    horizon: Literal["dual_horizon"] = "dual_horizon"
    outlook: MarketOutlook
    confidence: Literal["low", "medium", "high"]
    market_overview: MarketOverview
    short_term: ResearchPerspective
    long_term: ResearchPerspective
    catalysts: tuple[Catalyst, ...] = ()
    risks_and_invalidation: tuple[RiskAndInvalidation, ...] = ()
    limitations: tuple[str, ...] = ()
    factor_interpretations: tuple[FactorInterpretation, ...] = Field(default=(), max_length=3)

    @field_validator("limitations")
    @classmethod
    def normalize_limitations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > 12:
            raise ValueError("模型限制不能超过 12 项")
        return tuple(validate_research_display_text(item) for item in value)

    @model_validator(mode="after")
    def require_frozen_evidence_reference(self) -> AgentAnalysisProposal:
        referenced_ids = _proposal_evidence_ids(self)
        if not referenced_ids:
            raise ValueError("模型结论必须引用冻结证据")
        # 主正文只统计概况、两篇论点和驱动详情，专题解读另受独立长度限制。
        display_length = _narrative_display_length(self.narrative)
        if not _MIN_NARRATIVE_DISPLAY_LENGTH <= display_length <= _MAX_NARRATIVE_DISPLAY_LENGTH:
            raise ValueError("模型双层市场报告正文必须为 1100 至 2500 个字符")
        return self

    @property
    def narrative(self) -> AgentResearchNarrative:
        return AgentResearchNarrative(
            market_overview=self.market_overview,
            short_term=self.short_term,
            long_term=self.long_term,
        )


# 保存有限的校验元数据供安全诊断，不保存被拒模型正文或完整上游响应。
class ModelOutputError(RuntimeError):
    """将上游、格式和校验失败折叠为可安全记录的稳定模型错误码。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        validation_issue_count: int = 0,
        validation_field_paths: tuple[str, ...] = (),
        validation_error_categories: tuple[str, ...] = (),
        validation_narrative_length: int | None = None,
        format_attempt_count: int = 0,
        validation_numeric_kinds: tuple[str, ...] = (),
        validation_schema_kinds: tuple[str, ...] = (),
        validation_hints: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.validation_issue_count = validation_issue_count
        self.validation_field_paths = validation_field_paths
        self.validation_error_categories = validation_error_categories
        self.validation_narrative_length = validation_narrative_length
        self.format_attempt_count = format_attempt_count
        self.validation_numeric_kinds = validation_numeric_kinds
        self.validation_schema_kinds = validation_schema_kinds
        # 纠错提示只包含服务端构造的字段、事实标签和 evidence UUID，不保存模型正文。
        self.validation_hints = validation_hints


# 模型实现只返回候选研究结构；它不能扩展证据、修改确定性指标或执行交易。
class ResearchLanguageModel(Protocol):
    async def generate(self, request: ResearchModelRequest) -> AgentAnalysisProposal: ...


class DeepSeekResearchLanguageModel(ResearchLanguageModel):
    """受限的 DeepSeek JSON 研究提案适配器。

    它只产出待验证的提案；证据引用校验和最终持久化仍由确定性业务层完成。
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: SecretStr | None,
        model: Literal["deepseek-v4-flash", "deepseek-v4-pro"],
        validation_observer: Callable[[ModelOutputError, int], None] | None = None,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._model = model
        # 受信调用方可收集有界校验诊断，不依赖进程日志配置；模型不能选择或调用此回调。
        # 回调按参数传递每次错误，实例不保存跨请求的候选/诊断列表。
        self._validation_observer = validation_observer

    async def generate(self, request: ResearchModelRequest) -> AgentAnalysisProposal:
        """请求 DeepSeek 生成 JSON 提案，并只记录不含密钥和正文的运行元数据。"""
        started_at = perf_counter()
        logger.info(
            "agent_model_request_started",
            model=self._model,
        )
        logger.debug(
            "agent_model_request_details",
            model=self._model,
            phase="started",
            evidence_count=len(request.evidences),
        )
        api_key = self._api_key
        # 密钥只在构造请求头时暂存于局部变量，日志始终只记录模型名和受控错误码。
        secret_value = "" if api_key is None else api_key.get_secret_value().strip()
        if not secret_value:
            logger.info(
                "agent_model_request_failed",
                model=self._model,
                error_code="model_not_configured",
            )
            logger.debug(
                "agent_model_request_details",
                model=self._model,
                phase="failed",
                evidence_count=len(request.evidences),
                duration_ms=_duration_ms(started_at),
            )
            raise ModelOutputError("model_not_configured", "DeepSeek 模型密钥未配置")
        try:
            proposal = await self._generate_with_format_retry(
                request=request,
                secret_value=secret_value,
                started_at=started_at,
            )
        except ModelOutputError as error:
            logger.info(
                "agent_model_request_failed",
                model=self._model,
                error_code=error.code,
            )
            logger.debug(
                "agent_model_request_details",
                model=self._model,
                phase="failed",
                evidence_count=len(request.evidences),
                duration_ms=_duration_ms(started_at),
                validation_issue_count=error.validation_issue_count,
                validation_field_paths=error.validation_field_paths,
                validation_error_categories=error.validation_error_categories,
            )
            raise
        else:
            logger.info(
                "agent_model_request_completed",
                model=self._model,
            )
            logger.debug(
                "agent_model_request_details",
                model=self._model,
                phase="completed",
                evidence_count=len(request.evidences),
                duration_ms=_duration_ms(started_at),
            )
            return proposal

    async def _generate_with_format_retry(
        self,
        *,
        request: ResearchModelRequest,
        secret_value: str,
        started_at: float,
    ) -> AgentAnalysisProposal:
        """仅对 JSON 格式无效的响应执行有限次格式纠正重试。"""
        # 只对可恢复的“格式无效”响应有限重试；超时和上游故障直接交给降级路径。
        retry_error: ModelOutputError | None = None
        for attempt in range(1, _MAX_FORMAT_ATTEMPTS + 1):
            try:
                proposal = await self._generate_once(
                    request=request,
                    secret_value=secret_value,
                    started_at=started_at,
                    attempt=attempt,
                    retry_error=retry_error,
                )
            except ModelOutputError as error:
                if error.code != "model_invalid_response":
                    raise
                self._log_response_rejected(error=error, attempt=attempt)
                if self._validation_observer is not None:
                    self._validation_observer(error, attempt)
                # 最后一次仍失败才标注格式尝试次数，供报告保存有限失败摘要。
                if attempt == _MAX_FORMAT_ATTEMPTS:
                    error.format_attempt_count = attempt
                    raise
                retry_error = error
                logger.info(
                    "agent_model_format_retry_started",
                    model=self._model,
                    attempt=attempt + 1,
                )
                continue
            if attempt > 1:
                logger.info(
                    "agent_model_format_retry_completed",
                    model=self._model,
                    attempt=attempt,
                )
            return proposal
        raise RuntimeError("模型格式重试未能返回结果")

    async def _generate_once(
        self,
        *,
        request: ResearchModelRequest,
        secret_value: str,
        started_at: float,
        attempt: int,
        retry_error: ModelOutputError | None,
    ) -> AgentAnalysisProposal:
        """发送单次受限请求、提取 JSON 对象并验证其为可引用的提案模型。"""
        messages: tuple[dict[str, str], ...] = (
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": research_user_message(request)},
        )
        # 后续尝试只增加格式纠正指令，不改变冻结证据或系统约束。
        if attempt > 1:
            messages = (
                *messages,
                {
                    "role": "user",
                    "content": _format_retry_instruction(error=retry_error),
                },
            )
        try:
            response = await self._client.post(
                _DEEPSEEK_COMPLETIONS_URL,
                headers={"Authorization": f"Bearer {secret_value}"},
                json={
                    "model": self._model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "thinking": {"type": "disabled"},
                    "max_tokens": _MAX_TOKENS if request.factor_analysis is None else 7_000,
                },
            )
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ModelOutputError("model_timeout", "DeepSeek 研究请求超时") from error
        except httpx.HTTPStatusError as error:
            raise ModelOutputError("model_upstream_error", "DeepSeek 研究请求失败") from error
        except httpx.HTTPError as error:
            raise ModelOutputError("model_transport_error", "DeepSeek 研究连接失败") from error
        model_response = _response_content(response)
        logger.debug(
            "agent_model_response_received",
            model=self._model,
            status_code=response.status_code,
            duration_ms=_duration_ms(started_at),
            attempt=attempt,
            finish_reason=model_response.finish_reason,
            completion_tokens=model_response.completion_tokens,
        )
        # 长度截断会破坏 JSON 结构；先给出专门的纠错方向，不把它误报成普通字段错误。
        if model_response.finish_reason == "length":
            raise ModelOutputError(
                "model_invalid_response",
                "DeepSeek 输出因长度上限被截断",
                validation_issue_count=1,
                validation_field_paths=("schema",),
                validation_error_categories=("model_output_truncated",),
                validation_schema_kinds=("truncated",),
                validation_hints=("输出因长度上限被截断；请压缩专题解释和正文，先保证完整 JSON。",),
            )
        # 先校验原候选，不能让压缩删除不可信数值后将其冒充合格输出。
        # 引用渲染后才做全文长度/交易措辞验证，持久化的是确定性语句而非模型占位符。
        content = _normalize_json_object_content(model_response.content)
        try:
            render_result = render_structured_fact_references_partially(
                content, select_numeric_facts(request.numeric_facts), symbol=request.symbol
            )
        except NumericReferenceError as error:
            raise ModelOutputError(
                "model_invalid_response",
                "模型数值事实引用不合法",
                validation_issue_count=error.issue_count,
                validation_field_paths=error.field_paths,
                validation_error_categories=error.categories,
                validation_numeric_kinds=error.literal_kinds,
                validation_schema_kinds=error.schema_kinds,
                validation_hints=error.hints,
            ) from None
        except (ValueError, TypeError) as error:
            raise ModelOutputError(
                "model_invalid_response",
                "DeepSeek 返回了无效研究 JSON",
                validation_issue_count=1,
                validation_field_paths=("schema",),
                validation_error_categories=("schema",),
                validation_schema_kinds=(
                    "json" if isinstance(error, json.JSONDecodeError) else "wrong_type",
                ),
            ) from None
        protected_statements = tuple(
            fact.statement for fact in select_numeric_facts(request.numeric_facts)
        )
        content = _compact_overlong_narrative_content(
            render_result.content,
            protected_statements=protected_statements,
        )
        content, length_dropped = _drop_fact_statements_for_length(content, protected_statements)
        if length_dropped:
            render_result = replace(render_result, length_dropped_fact_count=length_dropped)
        try:
            proposal = AgentAnalysisProposal.model_validate_json(content)
        except (ValidationError, ValueError, json.JSONDecodeError) as error:
            raise _invalid_model_response_error(error) from error
        if proposal.horizon != request.horizon:
            raise ModelOutputError(
                "model_invalid_response",
                "DeepSeek 返回了无效研究窗口",
                validation_issue_count=1,
                validation_field_paths=("horizon",),
            )
        # 格式合格不代表有证据；所有嵌套引用必须属于本次冻结输入集合。
        _require_known_evidence_ids(proposal, request.evidences)
        # 未启用专题时没有专题准入集合；即使引用了合法市场ID也不能凭空增加政策等解读。
        # 与错误专题引用保持同一失败类别，不进入仅针对格式问题的纠错循环。
        if request.factor_analysis is None and proposal.factor_interpretations:
            raise ModelOutputError("model_invalid_evidence", "模型生成了未请求的专题解读")
        if request.factor_analysis is not None:
            try:
                # 专题还要检查引用所属类别，引用了本次另一专题也不能放行。
                apply_interpretations(request.factor_analysis, proposal.factor_interpretations)
            except ValueError as error:
                raise ModelOutputError(
                    "model_invalid_evidence", "模型引用了错误专题证据"
                ) from error
        # 绑定失败的事实项已经丢弃，含自由数字的句子已按句省略；保留正文仍须通过全部契约。
        if (
            render_result.dropped_count
            or render_result.redacted_claim_count
            or render_result.length_dropped_fact_count
        ):
            proposal = _with_partial_model_warning(proposal, render_result)
            logger.info(
                "agent_model_partial_recovery_applied",
                model=self._model,
                dropped_count=render_result.dropped_count,
                dropped_paths=render_result.dropped_paths,
                dropped_categories=render_result.dropped_categories,
                redacted_claim_count=render_result.redacted_claim_count,
                redacted_paths=render_result.redacted_paths,
                length_dropped_fact_count=render_result.length_dropped_fact_count,
            )
        return proposal

    def _log_response_rejected(self, *, error: ModelOutputError, attempt: int) -> None:
        logger.info(
            "agent_model_response_rejected",
            model=self._model,
            attempt=attempt,
            error_code=error.code,
            validation_issue_count=error.validation_issue_count,
            validation_field_paths=error.validation_field_paths,
            validation_error_categories=error.validation_error_categories,
            validation_numeric_kinds=error.validation_numeric_kinds,
            validation_schema_kinds=error.validation_schema_kinds,
            validation_narrative_length=error.validation_narrative_length,
        )
        logger.debug(
            "agent_model_response_rejection_details",
            model=self._model,
            attempt=attempt,
            validation_field_paths=error.validation_field_paths,
            validation_error_categories=error.validation_error_categories,
            validation_numeric_kinds=error.validation_numeric_kinds,
            validation_schema_kinds=error.validation_schema_kinds,
            validation_narrative_length=error.validation_narrative_length,
        )


def _with_partial_model_warning(
    proposal: AgentAnalysisProposal, result: StructuredFactRenderResult
) -> AgentAnalysisProposal:
    """把被丢弃事实与按句省略数量写进既有 limitations，不新增持久化字段。"""
    parts: list[str] = []
    if result.dropped_count:
        parts.append(f"{result.dropped_count} 条数值事实引用未通过校验，已省略")
    if result.redacted_claim_count:
        parts.append(f"{result.redacted_claim_count} 句含未绑定数值，已省略")
    if result.length_dropped_fact_count:
        parts.append(f"{result.length_dropped_fact_count} 条事实因篇幅上限省略")
    if not parts:
        return proposal
    warning = "；".join(parts) + "；其余分析保留。"
    # 警告放首位，确保后续新闻/来源限制截断到 12 项时仍优先保留。
    limitations = tuple(dict.fromkeys((warning, *proposal.limitations)))[:12]
    return AgentAnalysisProposal.model_validate(
        {**proposal.model_dump(), "limitations": limitations}
    )


def _duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1_000))


def _format_retry_instruction(*, error: ModelOutputError | None) -> str:
    """Append only bounded validation metadata to the correction request."""
    if error is None or (
        not error.validation_field_paths and not error.validation_error_categories
    ):
        return _FORMAT_RETRY_INSTRUCTION
    field_paths = ", ".join(error.validation_field_paths) or "未定位字段"
    categories = ", ".join(error.validation_error_categories) or "schema"
    narrative_length_instruction = _narrative_length_retry_instruction(error)
    numeric_instruction = _numeric_reference_retry_instruction(error)
    truncation_instruction = _truncation_retry_instruction(error)
    schema_instruction = _schema_retry_instruction(error)
    return (
        f"{_FORMAT_RETRY_INSTRUCTION}\n"
        f"上一份候选的校验字段：{field_paths}。"
        f"校验类别：{categories}。"
        f"{truncation_instruction}"
        f"{schema_instruction}"
        f"{narrative_length_instruction}"
        f"{numeric_instruction}"
        "请仅修正这些格式问题，仍须完整返回全部 JSON。"
    )


def _schema_retry_instruction(error: ModelOutputError) -> str:
    """把安全 schema 子类转成方向明确的纠错，不回显未知键或模型原文。"""
    kinds = set(error.validation_schema_kinds)
    hints: list[str] = []
    if "extra_field" in kinds:
        hints.append(
            "只能返回 system prompt schema 中列出的根字段，"
            "不要回显 factor_analysis、market_structure、numeric_facts、evidences 等输入键。"
        )
    if "missing_field" in kinds:
        hints.append("补齐所有必填字段，尤其是 market_overview、两个观点和专题字段。")
    if "json" in kinds:
        hints.append("只返回一个完整 JSON 对象，不要 Markdown 围栏、前后说明或被截断的内容。")
    if "enum" in kinds:
        hints.append('枚举字段只能使用 schema 给出的取值，例如 "bullish"/"bearish"/"neutral"。')
    if "wrong_type" in kinds:
        hints.append("检查对象、数组和字符串字段的类型，不要用 null 或对象替代必需数组。")
    if not hints:
        return ""
    return "结构纠错：" + " ".join(hints)


def _truncation_retry_instruction(error: ModelOutputError) -> str:
    """长度截断需要专门的纠错方向，不能与普通 schema 字段错误混为一谈。"""
    if "truncated" not in error.validation_schema_kinds:
        return ""
    return (
        "上一份输出因长度上限被截断，而不是字段内容错误。"
        "请压缩专题解释和正文，保留全部 JSON 字段与 fact_refs，先保证 JSON 完整；"
        "不要省略 long_term、catalysts、risks_and_invalidation 或 factor_interpretations。"
    )


def _numeric_reference_retry_instruction(error: ModelOutputError) -> str:
    """按机器类别解释输出协议，不回显被拒正文；日期和根数同样属于未经绑定数字。"""
    if not {
        "unbound_numeric_claim",
        "numeric_reference",
        "fact_reference_schema",
        "unknown_fact_reference",
        "unknown_fact_target",
        "fact_evidence_mismatch",
        "duplicate_fact_reference",
        "excess_fact_reference",
        "duplicate_or_excess_fact_reference",
    }.intersection(error.validation_error_categories):
        return ""
    hint_instruction = ""
    if error.validation_hints:
        hint_instruction = "\n本次具体问题：\n" + "\n".join(
            f"- {hint}" for hint in error.validation_hints
        )
    return (
        "本次需要修正数值引用：价格、成交量、百分比、日期、时刻、时间周期的数字及K线根数，"
        "即使存在于证据中，也不能自行写入正文。请使用小时级、短期、长期等定性周期名称。"
        "需要具体数值时，在根级 fact_refs 数组填写target与fact_id；正文不写token或数值。"
        "不要照抄 statement，它是程序渲染结果说明而不是模型输出。"
        "每个 fact_id 的 evidence_id 必须出现在目标段落自身的 evidence_ids 中；"
        "一个段落可以列多个 evidence_id。target只能使用 fact_reference_rules 中的叶子段落，"
        "thesis 不接受 fact_refs。每个 target 最多五条，重复引用和单段超额都会被拒绝。"
        "不得使用①、②、Ⅰ、Ⅱ、½、² 等符号数字或十亿、两万、百分之五、三分之一等中文数量；"
        "需要具体数值时只使用 fact_refs，其他位置只写定性文字。"
        "字段位置是有界摘要，请同时检查整份JSON的所有读者字符串，不只修补首个字段。"
        "没有对应fact_id时使用非数量化解释。目录筛选不等于证据缺失，"
        "只有输入明确缺失证据时才说明数据缺口。"
        f"{hint_instruction}"
    )


def _narrative_length_retry_instruction(error: ModelOutputError) -> str:
    """Describe the bounded length direction without retaining model text."""
    length = error.validation_narrative_length
    if "narrative_length" not in error.validation_error_categories or length is None:
        return ""
    if length < _MIN_NARRATIVE_DISPLAY_LENGTH:
        return (
            f"上一份正文约 {length} 个字符，低于 {_MIN_NARRATIVE_DISPLAY_LENGTH}；"
            f"请补充正文至约 1800 至 {_TARGET_NARRATIVE_DISPLAY_LENGTH} 个字符。"
        )
    return (
        f"上一份正文约 {length} 个字符，超过 {_MAX_NARRATIVE_DISPLAY_LENGTH}；"
        f"请删减正文至约 1800 至 {_TARGET_NARRATIVE_DISPLAY_LENGTH} 个字符，"
        "headline 和 heading 各不超过 30 个中文字符；不要重复三个专题的解释。"
    )


def _invalid_model_response_error(error: Exception) -> ModelOutputError:
    if not isinstance(error, ValidationError):
        return ModelOutputError("model_invalid_response", "DeepSeek 返回了无效研究 JSON")
    # 不读取输入值或验证上下文，避免诊断把模型原文间接带回重试提示。
    issues = error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    )
    return ModelOutputError(
        "model_invalid_response",
        "DeepSeek 返回了无效研究 JSON",
        validation_issue_count=min(len(issues), _MAX_VALIDATION_ISSUES),
        validation_field_paths=_validation_field_paths(issues),
        validation_error_categories=_validation_error_categories(
            str(issue["msg"]) for issue in issues
        ),
        validation_narrative_length=_narrative_length_from_validation_error(error),
        validation_schema_kinds=schema_error_kinds(str(issue["type"]) for issue in issues),
    )


def _validation_error_categories(messages: Iterable[str]) -> tuple[str, ...]:
    """Return bounded error classes without retaining model-generated text."""
    return tuple(sorted({_validation_error_category(message) for message in messages}))


def _validation_field_paths(issues: Iterable[ErrorDetails]) -> tuple[str, ...]:
    """Return bounded field paths without carrying arbitrary model-supplied keys."""
    paths: list[str] = []
    for issue in issues:
        location = issue["loc"]
        candidate = ".".join(str(part) for part in location)
        # 不符合有界路径格式的未知键统一退回类别名称，避免任意文本透出。
        safe_path = NumericReferenceError(candidate).path
        if safe_path not in paths:
            paths.append(safe_path)
        if len(paths) == _MAX_VALIDATION_FIELD_PATHS:
            break
    return tuple(paths)


def _narrative_length_from_validation_error(error: ValidationError) -> int | None:
    """Calculate only a bounded display-length number from the rejected input."""
    for issue in error.errors(include_url=False, include_context=False, include_input=True):
        if _validation_error_category(str(issue["msg"])) != "narrative_length":
            continue
        # 仅临时读取被拒输入计算数值，返回有界长度而不保留任何正文。
        return _raw_narrative_display_length(issue.get("input"))
    return None


# 输入可以是被拒的原始对象；字段缺失或类型异常时返回未知，不能猜测长度。
def _raw_narrative_display_length(value: object) -> int | None:
    root = _object_mapping(value)
    if root is None:
        return None
    market_overview = _object_mapping(root.get("market_overview"))
    short_term = _object_mapping(root.get("short_term"))
    long_term = _object_mapping(root.get("long_term"))
    if market_overview is None or short_term is None or long_term is None:
        return None
    text_parts: list[str] = []
    for section, field_names in (
        (market_overview, ("headline", "summary")),
        (short_term, ("thesis",)),
        (long_term, ("thesis",)),
    ):
        for field_name in field_names:
            field_value = section.get(field_name)
            if not isinstance(field_value, str):
                return None
            text_parts.append(field_value)
    for section in (short_term, long_term):
        drivers = section.get("drivers")
        if not isinstance(drivers, list):
            return None
        for driver in cast(list[object], drivers):
            driver_mapping = _object_mapping(driver)
            if driver_mapping is None:
                return None
            detail = driver_mapping.get("detail")
            if not isinstance(detail, str):
                return None
            text_parts.append(detail)
    return min(len("".join(text_parts)), 9_999)


def _object_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


# 只压缩可解析的正文，按章节最低长度分配删减预算；无法保留完整句子则返回原文。
def _compact_overlong_narrative_content(
    content: str, *, protected_statements: tuple[str, ...] = ()
) -> str:
    """Deterministically shorten only a complete, otherwise parseable model narrative."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content
    if not isinstance(payload, dict):
        return content
    mutable_payload = cast(dict[str, object], payload)
    original_length = _raw_narrative_display_length(mutable_payload)
    if original_length is None or original_length <= _MAX_NARRATIVE_DISPLAY_LENGTH:
        return content
    fields = _narrative_text_fields(mutable_payload)
    if fields is None:
        return content
    # 优先删减可用余量较多的章节，但不能低于各章节要求的最低长度。
    remaining = original_length - _TARGET_NARRATIVE_DISPLAY_LENGTH
    reductions: list[tuple[dict[str, object], str, int, int]] = []
    for container, field_name, minimum_length in sorted(
        fields,
        key=lambda field: len(cast(str, field[0][field[1]])) - field[2],
        reverse=True,
    ):
        value = cast(str, container[field_name])
        reducible = max(0, len(value) - minimum_length)
        reduction = min(remaining, reducible)
        reductions.append((container, field_name, minimum_length, reduction))
        remaining -= reduction
        if remaining == 0:
            break
    for container, field_name, minimum_length, reduction in reductions:
        if reduction == 0:
            continue
        value = cast(str, container[field_name])
        truncated = _truncate_research_text(
            value,
            maximum_length=len(value) - reduction,
            protected_statements=protected_statements,
        )
        # 标题没有句末标点时允许字符级限长；它不是事实或交易条件载体。
        if truncated is None and field_name in {"headline", "heading"}:
            truncated = value[: len(value) - reduction].rstrip()
        # 叙述字段不能找到完整句/分句边界就放弃压缩，防止截断金额、证据条件或句义。
        if truncated is None:
            logger.info(
                "agent_model_narrative_compaction_failed",
                original_display_length=original_length,
                field_name=field_name,
                reason="no_safe_boundary",
            )
            return content
        container[field_name] = truncated
    compacted_length = _raw_narrative_display_length(mutable_payload)
    # 完整句裁剪可能比预算多删，因此重新验证整份正文的上下界。
    # 即使没有达到目标 2200，只要不超过硬上限 2500 就接受，避免“差一点”回退原文。
    if compacted_length is None or not (
        _MIN_NARRATIVE_DISPLAY_LENGTH <= compacted_length <= _MAX_NARRATIVE_DISPLAY_LENGTH
    ):
        logger.info(
            "agent_model_narrative_compaction_failed",
            original_display_length=original_length,
            compacted_display_length=compacted_length,
            reason="outside_bounds",
        )
        return content
    logger.info(
        "agent_model_narrative_compacted",
        original_display_length=original_length,
        compacted_display_length=compacted_length,
    )
    return json.dumps(mutable_payload, ensure_ascii=False, separators=(",", ":"))


# 事实语句已达压缩下限仍超长时，按整条事实省略，保留叙述并写入限制。
def _drop_fact_statements_for_length(
    content: str, protected_statements: tuple[str, ...]
) -> tuple[str, int]:
    """只删除程序追加的完整事实行，不切割叙述、数值或事实内部内容。"""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content, 0
    if not isinstance(payload, dict):
        return content, 0
    mutable_payload = cast(dict[str, object], payload)
    current_length = _raw_narrative_display_length(mutable_payload)
    if current_length is None or current_length <= _MAX_NARRATIVE_DISPLAY_LENGTH:
        return content, 0
    candidates = sorted(
        {statement for statement in protected_statements if statement and statement in content},
        key=len,
        reverse=True,
    )
    dropped = 0
    for statement in candidates:
        # 省略该条后仍须满足正文下限；否则保留上一条结果并回退整份降级。
        if current_length - len(statement) - 1 < _MIN_NARRATIVE_DISPLAY_LENGTH:
            continue
        if not _remove_first_statement(mutable_payload, statement):
            continue
        dropped += 1
        updated = _raw_narrative_display_length(mutable_payload)
        if updated is None:
            return content, 0
        current_length = updated
        if current_length <= _MAX_NARRATIVE_DISPLAY_LENGTH:
            break
    if dropped == 0 or not (
        _MIN_NARRATIVE_DISPLAY_LENGTH <= current_length <= _MAX_NARRATIVE_DISPLAY_LENGTH
    ):
        return content, 0
    logger.info(
        "agent_model_fact_statements_dropped_for_length",
        dropped_count=dropped,
        display_length=current_length,
    )
    return (
        json.dumps(mutable_payload, ensure_ascii=False, separators=(",", ":")),
        dropped,
    )


def _remove_first_statement(value: object, statement: str) -> bool:
    """只移除“换行+完整事实语句”一次；返回是否找到并删除。"""
    marker = "\n" + statement
    if isinstance(value, dict):
        mapping = cast(dict[str, object], value)
        for key, child in mapping.items():
            if isinstance(child, str):
                if marker in child and child != statement:
                    mapping[key] = child.replace(marker, "", 1)
                    return True
            elif _remove_first_statement(child, statement):
                return True
    elif isinstance(value, list):
        items = cast(list[object], value)
        for index, child in enumerate(items):
            if isinstance(child, str):
                if marker in child and child != statement:
                    items[index] = child.replace(marker, "", 1)
                    return True
            elif _remove_first_statement(child, statement):
                return True
    return False


# 返回可压缩正文及各自下限；引用、价格区间、风险和专题不进入压缩候选。
def _narrative_text_fields(
    payload: dict[str, object],
) -> list[tuple[dict[str, object], str, int]] | None:
    market_overview = _mutable_object_mapping(payload.get("market_overview"))
    short_term = _mutable_object_mapping(payload.get("short_term"))
    long_term = _mutable_object_mapping(payload.get("long_term"))
    if market_overview is None or short_term is None or long_term is None:
        return None
    fields: list[tuple[dict[str, object], str, int]] = [
        (market_overview, "headline", 20),
        (market_overview, "summary", 350),
        (short_term, "thesis", 350),
        (long_term, "thesis", 350),
    ]
    for section in (short_term, long_term):
        drivers = section.get("drivers")
        if not isinstance(drivers, list):
            return None
        for driver in cast(list[object], drivers):
            driver_mapping = _mutable_object_mapping(driver)
            if driver_mapping is None or not isinstance(driver_mapping.get("detail"), str):
                return None
            fields.append((driver_mapping, "detail", 175))
    if any(not isinstance(container.get(field_name), str) for container, field_name, _ in fields):
        return None
    return fields


def _mutable_object_mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast(dict[str, object], value)


def _truncate_research_text(
    value: str,
    *,
    maximum_length: int,
    protected_statements: tuple[str, ...] = (),
) -> str | None:
    """Return a whole sentence within the requested bound, never a character slice."""
    # 事实由程序追加在段尾；先为完整事实尾部预留预算，再仅裁剪定性前文。
    # 不能容纳尾部时交给原长度门禁拒绝，绝不静默丢弃用户明确选择的事实。
    # 只匹配本次冻结目录中真实渲染的完整语句，普通【定性标题】不占事实预算。
    fact_start = min(
        (index for statement in protected_statements if (index := value.find(statement)) >= 0),
        default=-1,
    )
    if fact_start >= 0:
        suffix = value[fact_start:]
        prefix_budget = maximum_length - len(suffix) - 1
        if prefix_budget <= 0:
            return None
        prefix = _truncate_research_text(value[:fact_start].rstrip(), maximum_length=prefix_budget)
        return None if prefix is None else f"{prefix}\n{suffix}"
    candidate = value[:maximum_length].rstrip()
    # 程序渲染的【事实】内部也有分号，不能把时刻或窗口之后的分号当成句尾。
    # 若预算落在事实内部，只能回退至前一个外部完整句；调用方再决定是否保留原文。
    sentence_end = -1
    clause_end = -1
    fact_depth = 0
    for index, character in enumerate(candidate):
        if character == "【":
            fact_depth += 1
        elif character == "】":
            fact_depth = max(0, fact_depth - 1)
        elif fact_depth == 0:
            if character in "。！？；":
                sentence_end = index
            elif character in "，、：":
                clause_end = index
    if sentence_end >= 0:
        # 返回至末个完整中文句末，不将任意字符切片直接当成可保存叙事。
        return candidate[: sentence_end + 1].rstrip()
    if clause_end >= 0:
        # 极端长句没有句号时退到完整分句；仍不切断事实尾部或句中数字。
        return candidate[: clause_end + 1].rstrip()
    return None


# 将内部校验说明折叠成有限类别，不将未知消息原样放入日志或纠正请求。
def _validation_error_category(message: str) -> str:
    if "交易指令" in message:
        return "trading_instruction"
    if "报告文本不能超过" in message:
        return "text_length"
    if "报告文本不能为空" in message:
        return "text_empty"
    if "中文市场研究章节必须包含中文" in message:
        return "chinese_text_required"
    if "模型双层市场报告正文" in message:
        return "narrative_length"
    return "schema"


# 一次上游响应的安全投影：正文只用于本次校验，完成原因与 token 数可安全记录。
@dataclass(frozen=True)
class _ModelResponse:
    content: str
    finish_reason: str | None
    completion_tokens: int | None


def _safe_finish_reason(value: object) -> str | None:
    """把供应商完成原因折叠为固定枚举，避免任意字符串进入日志。"""
    if not isinstance(value, str):
        return None
    if value in {"stop", "length", "content_filter", "tool_calls", "insufficient_system_resource"}:
        return value
    return "other"


def _completion_tokens(body: dict[str, object]) -> int | None:
    """只接受非负整数的 usage 计数；缺失或异常形态保持未知。"""
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None
    value = cast(dict[str, object], usage).get("completion_tokens")
    if type(value) is int and value >= 0:
        return value
    return None


# 只提取首个响应中的非空正文与完成原因，响应形态异常映射为稳定错误，不回显原始报文。
def _response_content(response: httpx.Response) -> _ModelResponse:
    """从上游响应中安全提取正文、完成原因和完成 token 数。"""
    try:
        body: object = response.json()
    except (json.JSONDecodeError, ValueError) as error:
        raise ModelOutputError("model_invalid_response", "DeepSeek 返回了无效响应") from error
    if not isinstance(body, dict):
        raise ModelOutputError("model_empty_response", "DeepSeek 未返回研究内容")
    typed_body = cast(dict[str, object], body)
    choices = typed_body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelOutputError("model_empty_response", "DeepSeek 未返回研究内容")
    typed_choices = cast(list[object], choices)
    first_choice = typed_choices[0]
    if not isinstance(first_choice, dict):
        raise ModelOutputError("model_empty_response", "DeepSeek 未返回研究内容")
    typed_choice = cast(dict[str, object], first_choice)
    message = typed_choice.get("message")
    if not isinstance(message, dict):
        raise ModelOutputError("model_empty_response", "DeepSeek 未返回研究内容")
    typed_message = cast(dict[str, object], message)
    content = typed_message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ModelOutputError("model_empty_response", "DeepSeek 未返回研究内容")
    return _ModelResponse(
        content=content,
        finish_reason=_safe_finish_reason(typed_choice.get("finish_reason")),
        completion_tokens=_completion_tokens(typed_body),
    )


# 仅对单引号包裹的字符串做安全字面量解包；不执行代码，其他格式留给契约校验。
def _normalize_json_object_content(content: str) -> str:
    """去除 Markdown 围栏并确认模型回复是一个 JSON 对象，而非任意文本。"""
    """Unwrap a model's quoted JSON-object string without evaluating code."""
    candidate = content.strip()
    if not (candidate.startswith("'") and candidate.endswith("'")):
        return candidate
    try:
        unwrapped = ast.literal_eval(candidate)
    except (SyntaxError, ValueError):
        return candidate
    if not isinstance(unwrapped, str):
        return candidate
    normalized = unwrapped.strip()
    return normalized if normalized.startswith("{") else candidate


def _require_known_evidence_ids(
    proposal: AgentAnalysisProposal,
    evidences: Iterable[ModelEvidence],
) -> None:
    """验证提案引用的全部证据都属于本次冻结请求。"""
    known_ids = {evidence.id for evidence in evidences}
    referenced_ids = _proposal_evidence_ids(proposal)
    if not referenced_ids <= known_ids:
        raise ModelOutputError("model_invalid_evidence", "DeepSeek 引用了未知冻结证据")


# 统一收集主报告、双周期驱动和专题引用，防止只检查顶层而遗漏嵌套伪造标识。
def _proposal_evidence_ids(proposal: AgentAnalysisProposal) -> set[UUID]:
    return {
        evidence_id
        for item in (
            *proposal.factor_interpretations,
            *proposal.catalysts,
            *proposal.risks_and_invalidation,
            proposal.market_overview,
            *proposal.short_term.drivers,
            *proposal.short_term.invalidation,
            *proposal.long_term.drivers,
            *proposal.long_term.invalidation,
        )
        for evidence_id in item.evidence_ids
    }


# 长度口径与报告契约一致，避免模型端认为合格而持久化端使用另一正文范围。
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
