# 验证技术 v2 的规则反馈和拒绝诊断只含白名单元数据。
# 纠正反馈可指出文本规则，但不能携带模型原文或不可信验证上下文。
# 日志与成功重试一起断言，防止可观测性修复扩大信息暴露。
import json

import pytest
from pydantic import ValidationError

from app.agent.technical.plan_model import safe_correction
from app.reports.technical_plan import PlanClaim
from tests.agent.test_technical_references import context


# 将数值或操作语言转成有限规则码，反馈可以定位问题但不能重复拒绝文本。
@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("短周期四小时的变化仍有冲突，需要等待收盘方向重新一致。", "unbound_number"),
        ("本次证据不能保证收益，后续需要继续观察市场结构变化。", "execution_language"),
    ],
)
def test_correction_names_text_rule_without_replaying_model_text(text: str, code: str) -> None:
    with pytest.raises(ValidationError) as error:
        PlanClaim(
            text=text, evidence_id=context().analysis.evidence_id, fact_refs=("dataCutoffAt",)
        )
    correction = json.loads(safe_correction(error.value))
    assert correction["issues"] == [{"fieldPath": "text", "code": code}]
    assert text not in json.dumps(correction, ensure_ascii=False)


# 人工构造带敏感输入和异常上下文的验证错误，专门检查错误对象不成为反馈泄露入口。
def test_correction_does_not_expose_untrusted_validation_context() -> None:
    error = ValidationError.from_exception_data(
        "PlanClaim",
        [
            {
                "type": "value_error",
                "loc": ("text",),
                "input": "PRIVATE_INPUT",
                "ctx": {"error": ValueError("PRIVATE_MESSAGE")},
            }
        ],
    )
    # 错误对象含输入和异常上下文，反馈只应抽取白名单路径与类别。
    correction = json.loads(safe_correction(error))
    assert correction["issues"] == [{"fieldPath": "text", "code": "schema"}]
    assert "PRIVATE" not in json.dumps(correction)


# 第一次非法、第二次合法，把重试恢复与日志和反馈脱敏作为同一场景核验。
@pytest.mark.asyncio
async def test_rejection_logs_safe_rules_and_retry_recovers() -> None:
    import httpx
    from pydantic import SecretStr
    from structlog.testing import capture_logs

    from app.agent.technical.plan_model import DeepSeekTechnicalPlanLanguageModel
    from app.shared.config import AppSettings
    from tests.agent.test_technical_references import decision

    ctx = context()
    valid = decision(ctx).model_dump(mode="json")
    invalid = json.loads(json.dumps(valid))
    invalid["risks"][0]["text"] = "本次证据不能保证收益，PRIVATE_BODY，后续需继续观察结构。"
    calls = 0
    correction = ""

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls, correction
        calls += 1
        if calls == 2:
            correction = json.loads(request.content)["messages"][-1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(invalid if calls == 1 else valid),
                            "reasoning_content": "PRIVATE_REASONING",
                        },
                    }
                ]
            },
        )

    with capture_logs() as logs:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            model = DeepSeekTechnicalPlanLanguageModel(
                client=client,
                api_key=SecretStr("test-only"),
                model="deepseek-v4-pro",
                settings=AppSettings(),
            )
            result = await model.analyze(ctx)
    assert result.summary.stance == "long"
    assert [item.outcome for item in result.diagnostics] == ["invalid", "success"]
    rejected = next(item for item in logs if item["event"] == "technical_plan_response_rejected")
    assert {"fieldPath": "risks.0.text", "code": "execution_language"} in rejected["validation"][
        "issues"
    ]
    assert "execution_language" in correction
    # 恢复成功不能牺牲诊断脱敏，思考和拒绝原文标记都不得出现在日志或反馈。
    assert "PRIVATE" not in json.dumps(logs) + correction
