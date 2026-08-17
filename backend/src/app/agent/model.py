from __future__ import annotations

import ast
import json
from collections.abc import Iterable
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

from app.agent.market_structure import MarketStructure
from app.agent.prompt import research_user_message, system_prompt
from app.market.contracts import ContractSymbol, UtcDateTime
from app.reports.contracts import (
    AgentResearchNarrative,
    Catalyst,
    MarketOutlook,
    MarketOverview,
    ResearchPerspective,
    RiskAndInvalidation,
    validate_research_display_text,
)

_DEEPSEEK_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
_MAX_TOKENS = 4_000
_MAX_EVIDENCE_CONTENT_LENGTH = 4_000
_MAX_VALIDATION_FIELD_PATHS = 8
_MAX_FORMAT_ATTEMPTS = 3
_FORMAT_RETRY_INSTRUCTION = (
    "上一份候选未通过机器格式校验。请从头重新生成一个完整 JSON 对象："
    "不得使用 Markdown 或额外说明；必须包含所有 schema 字段，"
    "只引用提供的 UUID；"
    "市场概况、两个 thesis 与所有 driver.detail 拼接后必须达到 1800 至 2200 个中文字符；"
    "市场概况不少于 350 个中文字符，两个 thesis 各不少于 350 个中文字符，"
    "短期和长期各列出二至三个 driver，每个 driver.detail 不少于 175 个中文字符；"
    'direction 字段只能取 "bullish"、"bearish" 或 "neutral"，'
    "不得使用 positive、negative、up、down 等同义值。"
)
logger = structlog.get_logger(__name__)


class ModelEvidenceKind(StrEnum):
    MARKET = "market"
    NEWS = "news"


class _AgentModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelEvidence(_AgentModel):
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
    symbol: ContractSymbol
    structure: MarketStructure
    evidences: tuple[ModelEvidence, ...] = Field(min_length=1, max_length=30)
    report_language: Literal["zh-CN"] = "zh-CN"
    horizon: Literal["dual_horizon"] = "dual_horizon"

    @model_validator(mode="after")
    def require_unique_evidence_ids(self) -> ResearchModelRequest:
        if len({evidence.id for evidence in self.evidences}) != len(self.evidences):
            raise ValueError("模型证据 ID 必须唯一")
        return self


class AgentAnalysisProposal(_AgentModel):
    horizon: Literal["dual_horizon"] = "dual_horizon"
    outlook: MarketOutlook
    confidence: Literal["low", "medium", "high"]
    market_overview: MarketOverview
    short_term: ResearchPerspective
    long_term: ResearchPerspective
    catalysts: tuple[Catalyst, ...] = ()
    risks_and_invalidation: tuple[RiskAndInvalidation, ...] = ()
    limitations: tuple[str, ...] = ()

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
        display_length = _narrative_display_length(self.narrative)
        if not 1_100 <= display_length <= 2_500:
            raise ValueError("模型双层市场报告正文必须为 1100 至 2500 个字符")
        return self

    @property
    def narrative(self) -> AgentResearchNarrative:
        return AgentResearchNarrative(
            market_overview=self.market_overview,
            short_term=self.short_term,
            long_term=self.long_term,
        )


class ModelOutputError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        validation_issue_count: int = 0,
        validation_field_paths: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.validation_issue_count = validation_issue_count
        self.validation_field_paths = validation_field_paths


class ResearchLanguageModel(Protocol):
    async def generate(self, request: ResearchModelRequest) -> AgentAnalysisProposal: ...


class DeepSeekResearchLanguageModel(ResearchLanguageModel):
    """受限的单次 DeepSeek JSON 研究提案适配器。"""

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
        for attempt in range(1, _MAX_FORMAT_ATTEMPTS + 1):
            try:
                proposal = await self._generate_once(
                    request=request,
                    secret_value=secret_value,
                    started_at=started_at,
                    attempt=attempt,
                )
            except ModelOutputError as error:
                if error.code != "model_invalid_response":
                    raise
                self._log_response_rejected(error=error, attempt=attempt)
                if attempt == _MAX_FORMAT_ATTEMPTS:
                    raise
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
    ) -> AgentAnalysisProposal:
        messages: tuple[dict[str, str], ...] = (
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": research_user_message(request)},
        )
        if attempt > 1:
            messages = (*messages, {"role": "user", "content": _FORMAT_RETRY_INSTRUCTION})
        try:
            response = await self._client.post(
                _DEEPSEEK_COMPLETIONS_URL,
                headers={"Authorization": f"Bearer {secret_value}"},
                json={
                    "model": self._model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "thinking": {"type": "disabled"},
                    "max_tokens": _MAX_TOKENS,
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
        content = _normalize_json_object_content(_response_content(response))
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
        _require_known_evidence_ids(proposal, request.evidences)
        return proposal

    def _log_response_rejected(self, *, error: ModelOutputError, attempt: int) -> None:
        logger.info(
            "agent_model_response_rejected",
            model=self._model,
            attempt=attempt,
            error_code=error.code,
            validation_issue_count=error.validation_issue_count,
        )
        logger.debug(
            "agent_model_response_rejection_details",
            model=self._model,
            attempt=attempt,
            validation_field_paths=error.validation_field_paths,
        )


def _duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1_000))


def _invalid_model_response_error(error: Exception) -> ModelOutputError:
    if not isinstance(error, ValidationError):
        return ModelOutputError("model_invalid_response", "DeepSeek 返回了无效研究 JSON")
    issues = error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    )
    return ModelOutputError(
        "model_invalid_response",
        "DeepSeek 返回了无效研究 JSON",
        validation_issue_count=len(issues),
        validation_field_paths=tuple(
            ".".join(str(part) for part in issue["loc"])
            for issue in issues[:_MAX_VALIDATION_FIELD_PATHS]
        ),
    )


def _response_content(response: httpx.Response) -> str:
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


def _normalize_json_object_content(content: str) -> str:
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
    known_ids = {evidence.id for evidence in evidences}
    referenced_ids = _proposal_evidence_ids(proposal)
    if not referenced_ids <= known_ids:
        raise ModelOutputError("model_invalid_evidence", "DeepSeek 引用了未知冻结证据")


def _proposal_evidence_ids(proposal: AgentAnalysisProposal) -> set[UUID]:
    return {
        evidence_id
        for item in (
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
