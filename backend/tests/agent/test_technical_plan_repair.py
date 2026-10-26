# 验证有限纠错保留已通过校验的段落与引用。
# 缺少价格角色或等待原因的段落不能被当作合法内容保留。
# 纠正可缩短过长计划书，但不得重写原先合法的声明或回放外来引用。
import json
from typing import Any, cast

import httpx
import pytest
from pydantic import SecretStr

from app.agent.technical.plan_model import DeepSeekTechnicalPlanLanguageModel
from app.shared.config import AppSettings
from tests.agent.test_technical_references import context, decision


# 复制结构段落到入场条件也不满足价格角色，合法文字仍须满足字段用途才可保留。
def test_missing_price_role_is_not_retained_for_retry() -> None:
    from app.agent.technical.plan_repair import validated_retry_claims
    from app.agent.technical.references import build_reference_catalog

    ctx = context()
    payload = decision(ctx).model_dump(mode="json")
    payload["entryConditions"] = payload["marketStructure"]
    retained = validated_retry_claims(json.dumps(payload), build_reference_catalog(ctx))
    assert "entryConditions" not in retained
    assert "marketStructure" in retained


# 等待条件必须引用真实无候选原因，不能以通用市场结构段落替代。
def test_missing_waiting_reason_is_not_retained_for_retry() -> None:
    from app.agent.technical.plan_repair import validated_retry_claims
    from app.agent.technical.references import build_reference_catalog

    ctx = context(waiting=True)
    payload = decision(ctx).model_dump(mode="json")
    payload["waitingConditions"] = payload["marketStructure"]
    retained = validated_retry_claims(json.dumps(payload), build_reference_catalog(ctx))
    assert "waitingConditions" not in retained


# 过长正文不锁定为已验证内容，给下一次纠正缩短篇幅留下空间。
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


# 仅回传已通过引用与文本校验的段落；非法正文、外来字段和思考原文全部排除。
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
    # 只保留已合法段落的索引和内容，非法段落不得进入下一次模型上下文。
    assert retry["validatedClaims"]["marketStructure"] == [
        {"index": 0, "claim": valid["marketStructure"][0]}
    ]
    assert "risks" not in retry["validatedClaims"]
    assert "counterEvidence" not in retry["validatedClaims"]
    assert "PRIVATE" not in json.dumps(retry)


# 重试候选即使重写合法段落，也不能替换先前已经验证的原始声明。
# 第二次输出刻意改写先前合法段落，合并结果必须保留第一次已验证的声明。
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
