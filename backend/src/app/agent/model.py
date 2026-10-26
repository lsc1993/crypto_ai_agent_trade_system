# 综合研究模型适配器只把冻结证据格式化为中文双周期提案，最终保存前仍需业务层校验。
# 格式失败最多三次；超时及上游错误直接交给降级，诊断仅保留有界字段和错误类别。
"""语言模型提案边界模块。

数据流：冻结的 ModelEvidence 与确定性 MarketStructure → 受限 JSON 请求 → Pydantic
格式与证据 ID 校验 → AgentAnalysisProposal。模型输出始终是待业务层验证的提案。
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable, Mapping
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

from app.agent.factors import apply_interpretations
from app.agent.market_structure import MarketStructure
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
_VALIDATION_FIELD_PATH = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.(?:[a-z][a-z0-9_]*|[0-9]+))*$"
)
_MAX_FORMAT_ATTEMPTS = 3
_FORMAT_RETRY_INSTRUCTION = (
    "上一份候选未通过机器格式校验。请从头重新生成一个完整 JSON 对象："
    "不得使用 Markdown 或额外说明；必须包含所有 schema 字段，"
    "只引用提供的 UUID；"
    "市场概况、两个 thesis 与所有 driver.detail 拼接后必须达到 1800 至 2200 个中文字符；"
    "市场概况不少于 350 个中文字符，两个 thesis 各不少于 350 个中文字符，"
    "短期和长期各列出二至三个 driver，每个 driver.detail 不少于 175 个中文字符；"
    "所有面向读者的字符串字段均不得出现买入、卖出、做多、做空、开仓、建仓、平仓等操作词，"
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

    @model_validator(mode="after")
    def require_unique_evidence_ids(self) -> ResearchModelRequest:
        if len({evidence.id for evidence in self.evidences}) != len(self.evidences):
            raise ValueError("模型证据 ID 必须唯一")
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
    ) -> None:
        super().__init__(message)
        self.code = code
        self.validation_issue_count = validation_issue_count
        self.validation_field_paths = validation_field_paths
        self.validation_error_categories = validation_error_categories
        self.validation_narrative_length = validation_narrative_length
        self.format_attempt_count = format_attempt_count


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
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._model = model

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
        logger.debug(
            "agent_model_response_received",
            model=self._model,
            status_code=response.status_code,
            duration_ms=_duration_ms(started_at),
            attempt=attempt,
        )
        # 字面量解包和完整句压缩只是预处理，之后仍走全文契约及引用校验。
        content = _compact_overlong_narrative_content(
            _normalize_json_object_content(_response_content(response))
        )
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
        if request.factor_analysis is not None:
            try:
                # 专题还要检查引用所属类别，引用了本次另一专题也不能放行。
                apply_interpretations(request.factor_analysis, proposal.factor_interpretations)
            except ValueError as error:
                raise ModelOutputError(
                    "model_invalid_evidence", "模型引用了错误专题证据"
                ) from error
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
            validation_narrative_length=error.validation_narrative_length,
        )
        logger.debug(
            "agent_model_response_rejection_details",
            model=self._model,
            attempt=attempt,
            validation_field_paths=error.validation_field_paths,
            validation_error_categories=error.validation_error_categories,
            validation_narrative_length=error.validation_narrative_length,
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
    return (
        f"{_FORMAT_RETRY_INSTRUCTION}\n"
        f"上一份候选的校验字段：{field_paths}。"
        f"校验类别：{categories}。"
        f"{narrative_length_instruction}"
        "请仅修正这些格式问题，仍须完整返回全部 JSON。"
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
        f"请删减正文至约 1800 至 {_TARGET_NARRATIVE_DISPLAY_LENGTH} 个字符。"
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
        safe_path = candidate if _VALIDATION_FIELD_PATH.fullmatch(candidate) else "schema"
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
def _compact_overlong_narrative_content(content: str) -> str:
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
        reducible = len(value) - minimum_length
        reduction = min(remaining, reducible)
        reductions.append((container, field_name, minimum_length, reduction))
        remaining -= reduction
        if remaining == 0:
            break
    # 总预算无法缩到目标时保持原候选，让统一校验明确拒绝或触发格式纠正。
    if remaining != 0:
        return content
    for container, field_name, minimum_length, reduction in reductions:
        if reduction == 0:
            continue
        value = cast(str, container[field_name])
        truncated = _truncate_research_text(
            value,
            maximum_length=len(value) - reduction,
        )
        # 不能找到完整句边界就放弃压缩，防止截断金额、证据条件或句义。
        if truncated is None:
            return content
        container[field_name] = truncated
    compacted_length = _raw_narrative_display_length(mutable_payload)
    # 完整句裁剪可能比预算多删，因此重新验证整份正文的上下界。
    if compacted_length is None or not (
        _MIN_NARRATIVE_DISPLAY_LENGTH
        <= compacted_length
        <= _MAX_NARRATIVE_DISPLAY_LENGTH
    ):
        return content
    logger.info(
        "agent_model_narrative_compacted",
        original_display_length=original_length,
        compacted_display_length=compacted_length,
    )
    return json.dumps(mutable_payload, ensure_ascii=False, separators=(",", ":"))


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
) -> str | None:
    """Return a whole sentence within the requested bound, never a character slice."""
    candidate = value[:maximum_length].rstrip()
    sentence_end = max(candidate.rfind(mark) for mark in "。！？；")
    if sentence_end < 0:
        return None
    # 返回至末个完整中文句末，不将任意字符切片直接当成可保存叙事。
    return candidate[: sentence_end + 1].rstrip()


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


# 只提取首个响应中的非空正文，响应形态异常映射为稳定错误，不回显原始报文。
def _response_content(response: httpx.Response) -> str:
    """从上游响应中安全提取非空文本内容，并将异常形态映射为模型错误。"""
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
    return content


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
