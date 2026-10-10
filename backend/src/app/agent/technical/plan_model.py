"""Two independently bounded calls; raw reasoning is never retained."""

import asyncio
import json
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import Any, Literal, Protocol, cast

import httpx
import structlog
from pydantic import SecretStr, ValidationError

from app.agent.technical.plan_prompt import plan_messages
from app.agent.technical.references import build_reference_catalog, validate_decision
from app.reports.technical_plan import (
    PlanClaim,
    TechnicalContext,
    TechnicalDecisionSummary,
    TechnicalStageDiagnostic,
)
from app.shared.config import AppSettings

Stage = Literal["analysis", "composition"]
ErrorCode = Literal[
    "model_not_configured",
    "model_timeout",
    "model_upstream_error",
    "model_invalid_response",
    "model_output_limit",
    "model_empty_response",
]
Outcome = Literal["success", "length", "empty", "invalid", "timeout", "upstream", "not_configured"]
model_deadline: ContextVar[float | None] = ContextVar("technical_model_deadline", default=None)


def safe_correction(error: Exception) -> str:
    allowed = {
        field.alias or name
        for model in (TechnicalDecisionSummary, PlanClaim)
        for name, field in model.model_fields.items()
    }
    paths: list[str] = []
    issues: list[dict[str, str]] = []
    text_codes = {
        "unbound_number",
        "execution_language",
        "live_execution_language",
        "placeholder_unit",
        "chinese_required",
        "book_length",
    }
    if isinstance(error, ValidationError):
        for item in error.errors(include_input=False, include_context=False, include_url=False):
            parts = item["loc"]
            if parts and all(
                (type(part) is int and 0 <= part <= 6) or part in allowed for part in parts
            ):
                path = ".".join(str(part) for part in parts)
                paths.append(path)
                # Only static validator codes are exposed; never input, context or raw messages.
                code = item["msg"].removeprefix("Value error, ")
                issues.append({"fieldPath": path, "code": code if code in text_codes else "schema"})
        return json.dumps(
            {"category": "schema", "fieldPaths": paths[:12], "issues": issues[:12]},
            ensure_ascii=False,
        )
    reference_codes = {
        "wait_plan",
        "candidate_reference",
        "evidence_reference",
        "placeholder_reference",
        "method_reference",
        "wait_candidate_reference",
        "plan_role_reference",
        "waiting_reason_reference",
        "decision_changed",
    }
    return json.dumps({"category": str(error) if str(error) in reference_codes else "invalid"})


class TechnicalPlanModelError(RuntimeError):
    def __init__(
        self, code: ErrorCode, stage: Stage, diagnostics: tuple[TechnicalStageDiagnostic, ...] = ()
    ) -> None:
        super().__init__(code)
        self.code: ErrorCode = code
        self.stage: Stage = stage
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class TechnicalDecisionResult:
    summary: TechnicalDecisionSummary
    diagnostics: tuple[TechnicalStageDiagnostic, ...]


TechnicalCompositionResult = TechnicalDecisionResult


class TechnicalPlanLanguageModel(Protocol):
    async def analyze(self, context: TechnicalContext) -> TechnicalDecisionResult: ...
    async def compose(
        self, context: TechnicalContext, decision: TechnicalDecisionSummary
    ) -> TechnicalCompositionResult: ...


class DeepSeekTechnicalPlanLanguageModel:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: SecretStr | None,
        model: Literal["deepseek-v4-pro", "deepseek-v4-flash"],
        settings: AppSettings,
    ) -> None:
        self._client, self._key, self._settings = client, api_key, settings
        self._model: Literal["deepseek-v4-pro", "deepseek-v4-flash"] = model

    async def analyze(self, context: TechnicalContext) -> TechnicalDecisionResult:
        return await self._call(context, None, "analysis")

    async def compose(
        self, context: TechnicalContext, decision: TechnicalDecisionSummary
    ) -> TechnicalCompositionResult:
        return await self._call(context, decision, "composition")

    async def _call(
        self, context: TechnicalContext, decision: TechnicalDecisionSummary | None, stage: Stage
    ) -> TechnicalDecisionResult:
        key = "" if self._key is None else self._key.get_secret_value().strip()
        if not key:
            raise TechnicalPlanModelError("model_not_configured", stage)
        thinking = stage == "analysis"
        tokens = (
            self._settings.technical_analysis_max_tokens
            if thinking
            else self._settings.technical_composition_max_tokens
        )
        timeout = (
            self._settings.technical_analysis_timeout_seconds
            if thinking
            else self._settings.technical_composition_timeout_seconds
        )
        messages = plan_messages(context, decision)
        diagnostics: list[TechnicalStageDiagnostic] = []
        low = False
        for attempt in (1, 2):
            started = monotonic()
            deadline = model_deadline.get()
            remaining = timeout if deadline is None else deadline - started
            if remaining <= 0 or (attempt > 1 and remaining < timeout):
                raise TechnicalPlanModelError("model_timeout", stage, tuple(diagnostics))
            call_timeout = min(timeout, remaining)
            effort: Literal["high", "low"] | None = ("low" if low else "high") if thinking else None
            request: dict[str, object] = {
                "model": self._model,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "thinking": {"type": "enabled" if thinking else "disabled"},
                "max_tokens": tokens,
                "stream": False,
            }
            if effort:
                request["reasoning_effort"] = effort
            outcome: Outcome = "invalid"
            code: ErrorCode = "model_invalid_response"
            finish: Literal["stop", "length"] | None = None
            completion_tokens = reasoning_tokens = None
            retryable, delay = True, 0
            summary = None
            correction = ""
            try:
                async with asyncio.timeout(call_timeout):
                    response = await self._client.post(
                        "https://api.deepseek.com/chat/completions",
                        json=request,
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=call_timeout,
                    )
                    if response.status_code >= 400:
                        retryable = response.status_code in {408, 429, 500, 502, 503, 504}
                        if response.status_code == 429:
                            try:
                                delay = min(
                                    5, max(0, int(response.headers.get("Retry-After", "0")))
                                )
                            except ValueError:
                                delay = 0
                        code, outcome = "model_upstream_error", "upstream"
                    else:
                        if len(response.content) > 2 * 1024 * 1024:
                            raise ValueError("response_size")
                        envelope = response.json()
                        choice = envelope["choices"][0]
                        message = choice["message"]
                        if message.get("tool_calls") or message.get("function_call"):
                            raise ValueError("tools")
                        raw_finish = choice.get("finish_reason")
                        if raw_finish not in {"stop", "length"}:
                            raise ValueError("finish_reason")
                        finish = raw_finish
                        content = message.get("content")
                        if finish == "length":
                            code, outcome, low = "model_output_limit", "length", True
                        elif not isinstance(content, str):
                            raise ValueError("content_type")
                        elif not content.strip():
                            code, outcome, low = "model_empty_response", "empty", True
                        else:
                            if len(content) > 32000:
                                raise ValueError("content_size")
                            summary = validate_decision(
                                TechnicalDecisionSummary.model_validate_json(content),
                                build_reference_catalog(context),
                            )
                            if decision and (
                                summary.stance != decision.stance
                                or summary.selected_plan_ref != decision.selected_plan_ref
                            ):
                                raise ValueError("decision_changed")
                            outcome = "success"
                        usage: Any = envelope.get("usage", {})
                        if isinstance(usage, dict):
                            usage_record = cast(dict[str, Any], usage)
                            value = usage_record.get("completion_tokens")
                            completion_tokens = value if type(value) is int and value >= 0 else None
                            details: Any = usage_record.get("completion_tokens_details", {})
                            value = (
                                cast(dict[str, Any], details).get("reasoning_tokens")
                                if isinstance(details, dict)
                                else None
                            )
                            reasoning_tokens = value if type(value) is int and value >= 0 else None
            except (httpx.TimeoutException, TimeoutError):
                code, outcome = "model_timeout", "timeout"
            except httpx.HTTPError:
                code, outcome = "model_upstream_error", "upstream"
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
                summary = None
                correction = safe_correction(error)
                structlog.get_logger(__name__).info(
                    "technical_plan_response_rejected",
                    evidence_id=str(context.analysis.evidence_id),
                    stage=stage,
                    attempt=attempt,
                    validation=json.loads(correction),
                )
            diagnostic = TechnicalStageDiagnostic(
                stage=stage,
                attempt=attempt,
                outcome=outcome,
                finish_reason=finish,
                completion_tokens=completion_tokens,
                reasoning_tokens=reasoning_tokens,
                duration_ms=int((monotonic() - started) * 1000),
                model=self._model,
                thinking=thinking,
                reasoning_effort=effort,
                max_tokens=tokens,
            )
            diagnostics.append(diagnostic)
            structlog.get_logger(__name__).info(
                "technical_plan_model_stage",
                evidence_id=str(context.analysis.evidence_id),
                **diagnostic.model_dump(mode="json"),
            )
            if summary is not None and outcome == "success":
                return TechnicalDecisionResult(summary, tuple(diagnostics))
            if (
                not retryable
                or attempt == 2
                or (deadline is not None and deadline - monotonic() < timeout + delay)
            ):
                raise TechnicalPlanModelError(code, stage, tuple(diagnostics))
            if delay:
                await asyncio.sleep(delay)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"结果未通过校验，类别为{outcome}，安全字段诊断为{correction}。"
                        "依据同一冻结输入重新输出完整JSON；不要复述错误响应。"
                    ),
                }
            )
        raise AssertionError("unreachable")
