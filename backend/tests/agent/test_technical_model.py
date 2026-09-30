import json
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.agent.technical.engine import calculate_technical_analysis
from app.agent.technical.model import (
    DeepSeekTechnicalLanguageModel,
    TechnicalModelError,
    parse_technical_narrative,
)
from tests.agent.test_technical_engine import NOW, make_technical_detail


def _payload(evidence_id: str) -> dict[str, object]:
    claim = {"text": "量价结构存在延续可能，仍需等待后续收盘确认。", "evidenceIds": [evidence_id]}
    return {"thesis": claim, "alternative": claim, "risks": [claim]}


def test_accepts_qualitative_narrative_with_current_evidence() -> None:
    evidence_id = uuid4()
    result = parse_technical_narrative(json.dumps(_payload(str(evidence_id))), evidence_id)
    assert result.thesis.evidence_ids == (evidence_id,)


def test_rejects_fabricated_evidence() -> None:
    with pytest.raises(TechnicalModelError, match="model_invalid_response"):
        parse_technical_narrative(json.dumps(_payload(str(uuid4()))), uuid4())


@pytest.mark.parametrize(
    "text",
    [
        "建议在价格达到 90000 时立即买入。",
        "使用十倍杠杆，保证盈利。",
        "建议满仓做多，现在立刻开仓。",
        "确定庄家正在操纵市场。",
        "Set leverage and buy now.",
        "目标价格为九万美元。",
    ],
)
def test_rejects_unbounded_model_instructions_and_prices(text: str) -> None:
    evidence_id = uuid4()
    payload = _payload(str(evidence_id))
    payload["thesis"] = {"text": text, "evidenceIds": [str(evidence_id)]}
    with pytest.raises(TechnicalModelError, match="model_invalid_response"):
        parse_technical_narrative(json.dumps(payload), evidence_id)


def test_rejects_unexpected_plan_fields_and_unbounded_response() -> None:
    evidence_id = uuid4()
    payload = _payload(str(evidence_id))
    payload["plans"] = [{"entry": "90000"}]
    with pytest.raises(TechnicalModelError):
        parse_technical_narrative(json.dumps(payload), evidence_id)
    with pytest.raises(TechnicalModelError):
        parse_technical_narrative("x" * 30000, evidence_id)


@pytest.mark.asyncio
async def test_model_request_contains_frozen_facts_and_methods_without_tools() -> None:
    analysis = calculate_technical_analysis(make_technical_detail(), captured_at=NOW)

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "tools" not in body and "tool_choice" not in body
        assert body["response_format"] == {"type": "json_object"}
        assert str(analysis.evidence_id) in body["messages"][1]["content"]
        assert "量价" in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(_payload(str(analysis.evidence_id))),
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = DeepSeekTechnicalLanguageModel(
            client=client, api_key=SecretStr("test-placeholder"), model="deepseek-v4-pro"
        )
        assert (await model.generate(analysis)).thesis.evidence_ids == (analysis.evidence_id,)


@pytest.mark.asyncio
async def test_missing_model_key_does_not_make_http_request() -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError("No network call allowed without configured key")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        model = DeepSeekTechnicalLanguageModel(client=client, api_key=None, model="deepseek-v4-pro")
        with pytest.raises(TechnicalModelError, match="model_not_configured"):
            await model.generate(
                calculate_technical_analysis(make_technical_detail(), captured_at=NOW)
            )


@pytest.mark.asyncio
async def test_model_timeout_uses_safe_error_without_response_content() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private upstream message", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        model = DeepSeekTechnicalLanguageModel(
            client=client, api_key=SecretStr("test-placeholder"), model="deepseek-v4-pro"
        )
        with pytest.raises(TechnicalModelError, match="^model_timeout$"):
            await model.generate(
                calculate_technical_analysis(make_technical_detail(), captured_at=NOW)
            )
