import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.agent.technical.plan_model import (
    DeepSeekTechnicalPlanLanguageModel,
    TechnicalPlanModelError,
)
from app.shared.config import AppSettings
from tests.agent.test_technical_references import context, decision


@pytest.mark.asyncio
async def test_analysis_thinks_composition_does_not() -> None:
    ctx = context()
    calls: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": decision(ctx).model_dump_json(),
                            "reasoning_content": "PRIVATE_REASONING",
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = DeepSeekTechnicalPlanLanguageModel(
            client=client,
            api_key=SecretStr("test-only"),
            model="deepseek-v4-pro",
            settings=AppSettings(),
        )
        result = await model.analyze(ctx)
        await model.compose(ctx, result.summary)
    assert calls[0]["thinking"] == {"type": "enabled"}
    assert calls[0]["reasoning_effort"] == "high"
    assert calls[0]["max_tokens"] == 32768
    assert calls[1]["thinking"] == {"type": "disabled"}
    assert calls[1]["max_tokens"] == 8192
    assert "PRIVATE_REASONING" not in json.dumps(calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["length", "empty", "invalid", "tools", "auth", "timeout"])
async def test_failures_are_bounded_and_safe(failure: str) -> None:
    ctx = context()
    calls: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        if failure == "auth":
            return httpx.Response(401, text="PRIVATE_ERROR")
        if failure == "timeout":
            raise httpx.ReadTimeout("PRIVATE_ERROR")
        message: dict[str, Any] = {"content": "" if failure == "empty" else "PRIVATE_BAD_JSON"}
        if failure == "tools":
            message["tool_calls"] = [{"name": "PRIVATE_TOOL"}]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length" if failure == "length" else "stop",
                        "message": message,
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = DeepSeekTechnicalPlanLanguageModel(
            client=client,
            api_key=SecretStr("test-only"),
            model="deepseek-v4-pro",
            settings=AppSettings(),
        )
        with pytest.raises(TechnicalPlanModelError) as error:
            await model.analyze(ctx)
    assert len(calls) == (1 if failure == "auth" else 2)
    assert "PRIVATE" not in str(error.value)
    assert "PRIVATE" not in json.dumps(calls)
    if failure in {"length", "empty"}:
        assert calls[1]["reasoning_effort"] == "low"
        assert calls[1]["thinking"]["type"] == "enabled"
    assert (
        error.value.code
        == {
            "length": "model_output_limit",
            "empty": "model_empty_response",
            "invalid": "model_invalid_response",
            "tools": "model_invalid_response",
            "auth": "model_upstream_error",
            "timeout": "model_timeout",
        }[failure]
    )


@pytest.mark.asyncio
async def test_retry_after_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    ctx = context()
    delays: list[int] = []
    calls = 0

    async def sleep(seconds: int) -> None:
        delays.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", sleep)

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "100000"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": decision(ctx).model_dump_json()},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = DeepSeekTechnicalPlanLanguageModel(
            client=client,
            api_key=SecretStr("test-only"),
            model="deepseek-v4-pro",
            settings=AppSettings(),
        )
        assert (await model.analyze(ctx)).summary.stance == "long"
    assert delays == [5]


@pytest.mark.asyncio
async def test_retry_requires_remaining_full_call_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent.technical import plan_model

    elapsed = 0.0
    calls = 0
    monkeypatch.setattr(plan_model, "monotonic", lambda: elapsed)

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal elapsed, calls
        calls += 1
        elapsed = 90.0
        return httpx.Response(503)

    token = plan_model.model_deadline.set(120.0)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            model = DeepSeekTechnicalPlanLanguageModel(
                client=client,
                api_key=SecretStr("test-only"),
                model="deepseek-v4-pro",
                settings=AppSettings(technical_analysis_timeout_seconds=90),
            )
            with pytest.raises(TechnicalPlanModelError) as error:
                await model.analyze(context())
            assert len(error.value.diagnostics) == 1
        assert calls == 1
    finally:
        plan_model.model_deadline.reset(token)


@pytest.mark.asyncio
async def test_format_retry_uses_safe_field_path_without_rejected_text() -> None:
    import json

    ctx = context()
    invalid = decision(ctx).model_copy(
        update={
            "stop_rationale": (
                decision(ctx)
                .stop_rationale[0]
                .model_copy(update={"text": "未经证据支持的止损价格是123456，私有响应不要回传。"}),
            )
        }
    )
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        summary = invalid if len(requests) == 1 else decision(ctx)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": summary.model_dump_json()}}
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = DeepSeekTechnicalPlanLanguageModel(
            client=client,
            api_key=SecretStr("test-only"),
            model="deepseek-v4-pro",
            settings=AppSettings(),
        )
        assert (await model.analyze(ctx)).summary.stance == "long"
    correction = json.loads(requests[1].content)["messages"][-1]["content"]
    assert "stopRationale.0.text" in correction
    assert "123456" not in correction
    assert "私有响应" not in correction
