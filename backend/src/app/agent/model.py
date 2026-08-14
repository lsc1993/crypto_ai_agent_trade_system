from __future__ import annotations

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
    Catalyst,
    MarketOutlook,
    RiskAndInvalidation,
    validate_research_display_text,
)

_DEEPSEEK_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
_MAX_TOKENS = 1_200
_MAX_EVIDENCE_CONTENT_LENGTH = 4_000
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
    horizon: Literal["1_to_3_days"] = "1_to_3_days"

    @model_validator(mode="after")
    def require_unique_evidence_ids(self) -> ResearchModelRequest:
        if len({evidence.id for evidence in self.evidences}) != len(self.evidences):
            raise ValueError("模型证据 ID 必须唯一")
        return self


class AgentAnalysisProposal(_AgentModel):
    horizon: Literal["1_to_3_days"] = "1_to_3_days"
    outlook: MarketOutlook
    confidence: Literal["low", "medium", "high"]
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
        referenced_ids = {
            evidence_id
            for item in (*self.catalysts, *self.risks_and_invalidation)
            for evidence_id in item.evidence_ids
        }
        if not referenced_ids:
            raise ValueError("模型结论必须引用冻结证据")
        return self


class ModelOutputError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
            try:
                response = await self._client.post(
                    _DEEPSEEK_COMPLETIONS_URL,
                    headers={"Authorization": f"Bearer {secret_value}"},
                    json={
                        "model": self._model,
                        "messages": (
                            {"role": "system", "content": system_prompt()},
                            {"role": "user", "content": research_user_message(request)},
                        ),
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
            )
            content = _response_content(response)
            try:
                proposal = AgentAnalysisProposal.model_validate_json(content)
            except (ValidationError, ValueError, json.JSONDecodeError) as error:
                raise ModelOutputError(
                    "model_invalid_response",
                    "DeepSeek 返回了无效研究 JSON",
                ) from error
            if proposal.horizon != request.horizon:
                raise ModelOutputError("model_invalid_response", "DeepSeek 返回了无效研究窗口")
            _require_known_evidence_ids(proposal, request.evidences)
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


def _duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1_000))


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


def _require_known_evidence_ids(
    proposal: AgentAnalysisProposal,
    evidences: Iterable[ModelEvidence],
) -> None:
    known_ids = {evidence.id for evidence in evidences}
    referenced_ids = {
        evidence_id
        for item in (*proposal.catalysts, *proposal.risks_and_invalidation)
        for evidence_id in item.evidence_ids
    }
    if not referenced_ids <= known_ids:
        raise ModelOutputError("model_invalid_evidence", "DeepSeek 引用了未知冻结证据")
