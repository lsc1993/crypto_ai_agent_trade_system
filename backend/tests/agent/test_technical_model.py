# 验证技术 v1 模型只解释冻结事实与已审查方法。
# 响应替身覆盖合法中文、伪造引用、具体数值和操作措辞，合法内容保持原文。
# 格式纠正受次数限制且不回放拒绝原文；传输故障直接返回安全降级原因。
import json
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from app.agent.technical.engine import calculate_technical_analysis
from app.agent.technical.model import (
    DeepSeekTechnicalLanguageModel,
    TechnicalModelError,
    parse_technical_narrative,
)
from tests.agent.test_technical_engine import NOW, make_technical_detail


# 最小合法定性叙事复用当前证据身份，测试可只改目标文本以隔离拒绝原因。
def _payload(evidence_id: str) -> dict[str, object]:
    claim = {"text": "量价结构存在延续可能，仍需等待后续收盘确认。", "evidenceIds": [evidence_id]}
    return {"thesis": claim, "alternative": claim, "risks": [claim]}


def test_accepts_qualitative_narrative_with_current_evidence() -> None:
    evidence_id = uuid4()
    result = parse_technical_narrative(json.dumps(_payload(str(evidence_id))), evidence_id)
    assert result.thesis.evidence_ids == (evidence_id,)


# 包含普通中文数字字符的定性表达应保持原文，不能按字符一律删改。
@pytest.mark.parametrize(
    "text",
    [
        "周期方向一致，仍需等待后续结构确认。",
        "一旦量能回落，延续判断需要进一步复核。",
        "另一方面，单一形态不足以解释整体结构。",
        "唯一致命风险来自量能萎缩。",
        "三角形态尚待确认，不能孤立判断趋势。",
        "万一量价结构背离，需要重新复核。",
    ],
)
def test_preserves_normal_qualitative_chinese_without_rewriting(text: str) -> None:
    evidence_id = uuid4()
    payload = _payload(str(evidence_id))
    payload["thesis"] = {"text": text, "evidenceIds": [str(evidence_id)]}
    result = parse_technical_narrative(json.dumps(payload), evidence_id)
    assert result.thesis.text == text
    assert result.thesis.evidence_ids == (evidence_id,)


# 普通定性措辞与具体数量、比例或操作语义分别测试，避免放宽中文后漏过交易指令。
@pytest.mark.parametrize(
    "text",
    [
        "方向一致，目标价格为九万美元。",
        "一旦突破价格90000，建议立即买入。",
        "周期一致并不能保证收益或未来表现。",
        "同一价格附近出现三次确认信号。",
        "订单一万元需要进一步复核。",
        "合同一万元仍需后续确认。",
        "量比为一，仍需等待后续结构确认。",
        "价位是九，结构确认仍然不充分。",
        "三周期走势同步，仍需等待收盘确认。",
        "手续费百分之五，可能影响结构判断。",
        "幅度为零点五，仍需后续确认。",
        "三比一的量价比仍需收盘确认。",
        "均线仅覆盖三根，仍需谨慎复核。",
        "价位约壹萬美元，仍需等待后续确认。",
        "结构延续概率约½，仍需后续复核。",
        "波幅为十，需等待后续收盘确认。",
        "阻力在九，仍需后续量价结构确认。",
        "目标位于九，仍需后续结构确认。",
        "成交量达到五，仍需收盘确认。",
        "三条均线方向一致，仍需收盘确认。",
        "出现两种确认信号，仍需谨慎复核。",
        "市价为九，仍需等待结构确认。",
        "趋势延续概率为百分百，结构仍待确认。",
        "量能较前期减少一半，仍需等待结构确认。",
        "半数信号方向相反，仍需后续确认。",
        "量能仅为四分之三，仍需后续确认。",
        "支撑位在五，仍需等待后续确认。",
    ],
)
def test_rejects_quantities_or_trading_language_in_otherwise_qualitative_text(text: str) -> None:
    evidence_id = uuid4()
    payload = _payload(str(evidence_id))
    payload["thesis"] = {"text": text, "evidenceIds": [str(evidence_id)]}
    with pytest.raises(TechnicalModelError, match="model_invalid_response"):
        parse_technical_narrative(json.dumps(payload), evidence_id)


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


# 请求只提供定性投影和当前证据，不发送完整指标数值让模型重写事实。
@pytest.mark.asyncio
async def test_model_request_contains_frozen_facts_and_methods_without_tools() -> None:
    analysis = calculate_technical_analysis(make_technical_detail(), captured_at=NOW)
    assert analysis.facts is not None
    expected_volume_signal = analysis.facts.volume_signal

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "tools" not in body and "tool_choice" not in body
        assert body["response_format"] == {"type": "json_object"}
        assert str(analysis.evidence_id) in body["messages"][1]["content"]
        context = json.loads(body["messages"][1]["content"])
        assert "sma20" not in json.dumps(context)
        assert "atr14" not in json.dumps(context)
        assert "candleCounts" not in json.dumps(context)
        assert set(context["trendAlignment"]) == {"日线", "中周期", "短周期"}
        assert context["volumeSignal"] == expected_volume_signal
        assert context["evidenceId"] == str(analysis.evidence_id)
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


@pytest.mark.asyncio
async def test_generates_json_without_spending_budget_on_default_reasoning() -> None:
    analysis = calculate_technical_analysis(make_technical_detail(), captured_at=NOW)

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        disabled = body.get("thinking") == {"type": "disabled"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop" if disabled else "length",
                        "message": {
                            "content": json.dumps(_payload(str(analysis.evidence_id)))
                            if disabled
                            else ""
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = DeepSeekTechnicalLanguageModel(
            client=client, api_key=SecretStr("test-placeholder"), model="deepseek-v4-pro"
        )
        assert (await model.generate(analysis)).thesis.evidence_ids == (analysis.evidence_id,)


# 前两次返回不合法文本，第三次恢复；每次纠正必须复用原冻结请求且不回传拒绝原文。
@pytest.mark.asyncio
async def test_corrects_rejected_text_without_sending_raw_response_or_changing_evidence() -> None:
    analysis = calculate_technical_analysis(make_technical_detail(), captured_at=NOW)
    requests: list[dict[str, Any]] = []
    raw_text = "敏感上游原文：4h结构仍待确认。"

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        payload = _payload(str(analysis.evidence_id))
        if len(requests) < 3:
            payload["thesis"] = {"text": raw_text, "evidenceIds": [str(analysis.evidence_id)]}
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = DeepSeekTechnicalLanguageModel(
            client=client, api_key=SecretStr("test-placeholder"), model="deepseek-v4-pro"
        )
        assert (
            await model.generate(analysis)
        ).thesis.text == "量价结构存在延续可能，仍需等待后续收盘确认。"
    assert len(requests) == 3
    for body in requests[1:]:
        messages = body["messages"]
        # 逐次核对基础消息完全相同，纠正不重新采集或替换原冻结证据。
        assert messages[:2] == requests[0]["messages"]
        assert "thesis.text" in messages[-1]["content"]
        assert raw_text not in json.dumps(body, ensure_ascii=False)


# 持续格式错误最多三次，诊断字段必须落在白名单且没有响应敏感标记。
@pytest.mark.asyncio
async def test_invalid_responses_exhaust_bounded_attempts_with_safe_diagnostics() -> None:
    analysis = calculate_technical_analysis(make_technical_detail(), captured_at=NOW)
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"private-marker": "secret-value"}'}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = DeepSeekTechnicalLanguageModel(
            client=client, api_key=SecretStr("test-placeholder"), model="deepseek-v4-pro"
        )
        with capture_logs() as logs:
            with pytest.raises(TechnicalModelError, match="^model_invalid_response$"):
                await model.generate(analysis)
    assert calls == 3
    rejected = [entry for entry in logs if entry["event"] == "technical_model_response_rejected"]
    assert [entry["attempt"] for entry in rejected] == [1, 2, 3]
    assert all(
        entry["field_path"] in {"response", "thesis", "alternative", "risks"} for entry in rejected
    )
    assert "private-marker" not in json.dumps(logs)
    assert "secret-value" not in json.dumps(logs)


# 传输超时和上游错误无法靠正文纠正解决，此路径只能一次调用后安全失败。
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "upstream"])
async def test_does_not_format_retry_transport_failures(failure: str) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise httpx.ReadTimeout("private message", request=request)
        return httpx.Response(503, text="private message")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = DeepSeekTechnicalLanguageModel(
            client=client, api_key=SecretStr("test-placeholder"), model="deepseek-v4-pro"
        )
        with pytest.raises(
            TechnicalModelError,
            match=f"^model_{'timeout' if failure == 'timeout' else 'upstream_error'}$",
        ):
            await model.generate(
                calculate_technical_analysis(make_technical_detail(), captured_at=NOW)
            )
    assert calls == 1
