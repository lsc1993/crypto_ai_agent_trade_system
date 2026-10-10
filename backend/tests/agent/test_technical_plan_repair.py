import json
from typing import Any, cast

import httpx
import pytest
from pydantic import SecretStr

from app.agent.technical.plan_model import DeepSeekTechnicalPlanLanguageModel
from app.shared.config import AppSettings
from tests.agent.test_technical_references import context, decision


def test_missing_price_role_is_not_retained_for_retry() -> None:
    from app.agent.technical.plan_repair import validated_retry_claims
    from app.agent.technical.references import build_reference_catalog

    ctx = context()
    payload = decision(ctx).model_dump(mode="json")
    payload["entryConditions"] = payload["marketStructure"]
    retained = validated_retry_claims(json.dumps(payload), build_reference_catalog(ctx))
    assert "entryConditions" not in retained
    assert "marketStructure" in retained


def test_missing_waiting_reason_is_not_retained_for_retry() -> None:
    from app.agent.technical.plan_repair import validated_retry_claims
    from app.agent.technical.references import build_reference_catalog

    ctx = context(waiting=True)
    payload = decision(ctx).model_dump(mode="json")
    payload["waitingConditions"] = payload["marketStructure"]
    retained = validated_retry_claims(json.dumps(payload), build_reference_catalog(ctx))
    assert "waitingConditions" not in retained


def test_oversized_book_can_be_shortened_during_retry() -> None:
    from app.agent.technical.plan_repair import validated_retry_claims
    from app.agent.technical.references import build_reference_catalog

    ctx = context()
    payload = decision(ctx).model_dump(mode="json")
    for key, items in payload.items():
        if isinstance(items, list):
            for item in cast(list[dict[str, Any]], items):
                item["text"] = "冻结事实需要结合后续收盘变化复核。" * 50
            payload[key] = items * 2
    assert (
        validated_retry_claims(
            json.dumps(payload, ensure_ascii=False), build_reference_catalog(ctx)
        )
        == {}
    )


@pytest.mark.asyncio
async def test_retry_preserves_valid_claims_without_replaying_rejected_or_foreign_claims() -> None:
    ctx = context()
    valid = decision(ctx).model_dump(mode="json")
    rejected = json.loads(json.dumps(valid))
    rejected["risks"][0]["text"] = "PRIVATE_REJECTED，数量为123456，本段不得回传。"
    rejected["counterEvidence"][0]["factRefs"] = ["PRIVATE_FOREIGN"]
    rejected["counterEvidence"][0]["text"] = (
        "PRIVATE_FOREIGN_BODY，这段引用不属于本次冻结证据，不能用于纠错。"
    )
    calls = 0
    retry = {}

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls, retry
        calls += 1
        if calls == 2:
            retry = json.loads(json.loads(request.content)["messages"][-1]["content"])
        payload = valid if calls == 2 else rejected
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(payload),
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
            model="deepseek-v4-flash",
            settings=AppSettings(),
        )
        assert (await model.analyze(ctx)).summary.stance == "long"
    assert retry["validatedClaims"]["marketStructure"] == [
        {"index": 0, "claim": valid["marketStructure"][0]}
    ]
    assert "risks" not in retry["validatedClaims"]
    assert "counterEvidence" not in retry["validatedClaims"]
    assert "PRIVATE" not in json.dumps(retry)


@pytest.mark.asyncio
async def test_retry_keeps_original_valid_claim_when_model_rewrites_it() -> None:
    ctx = context()
    valid = decision(ctx).model_dump(mode="json")
    rejected = json.loads(json.dumps(valid))
    rejected["risks"][0]["text"] = "数量为123456，未经冻结证据支持的数值不得使用。"
    changed = json.loads(json.dumps(valid))
    changed["marketStructure"][0]["text"] = "当前冻结结构存在其他变化，需要结合后续收盘数据复核。"
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(rejected if calls == 1 else changed),
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = DeepSeekTechnicalPlanLanguageModel(
            client=client,
            api_key=SecretStr("test-only"),
            model="deepseek-v4-flash",
            settings=AppSettings(),
        )
        result = await model.analyze(ctx)
    assert result.summary.market_structure[0].text == valid["marketStructure"][0]["text"]
