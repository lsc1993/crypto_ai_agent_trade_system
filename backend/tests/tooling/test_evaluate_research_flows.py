# 离线流程评估的独立回归样本只写入 tmp_path，不读取开发评估目录。
# 断言真实服务的两阶段分类、保存后读取和证据门控，并验证坏配置与安全产物失败语义。
from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

from scripts.evaluate_research_flows import FixtureTransport, evaluate, main


@pytest.fixture
def independent_suite(tmp_path: Path) -> Path:
    """测试专用候选与正文不导入开发样本，防止修改开发预期一起掩盖回归。"""
    recipe = {
        "version": "synthetic-breakout-v1",
        "initial_price": "80.0",
        "step": "0.3",
        "plateau": "105.0",
        "last_close": "106.2",
        "swing_low": "98.0",
        "swing_high": "125.0",
    }

    def claim(ref: str) -> dict[str, object]:
        return {
            "text": "独立测试依据{{" + ref + "}}形成待复核研究，后续收盘仍需检查相反证据。",
            "evidenceId": "__EVIDENCE_ID__",
            "factRefs": [ref],
            "methodRefs": [],
        }

    general = claim("facts.volumeRatio")
    decision = {
        "stance": "long",
        "selectedPlanRef": "plans.0",
        **{
            key: [general]
            for key in (
                "marketStructure",
                "supportingEvidence",
                "counterEvidence",
                "invalidation",
                "alternative",
                "waitingConditions",
                "risks",
            )
        },
        "methodApplications": [{**general, "methodRefs": ["volume_price"]}],
        "entryConditions": [claim("plans.0.triggerLevel")],
        "stopRationale": [claim("plans.0.stopLoss")],
        "targetRationale": [claim("plans.0.target")],
    }
    envelope = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(decision, ensure_ascii=False),
                    "reasoning_content": "PRIVATE_TEST_REASONING_DO_NOT_ARCHIVE",
                },
            }
        ]
    }
    # 综合研究测试正文与开发语料独立，长度通过生产 1100–2500 字符约束。
    prose = (
        "作为离线回归的固定研究输入，当前公开结构只用于验证报告契约，"
        "趋势与量能仍需结合后续证据复核，观察到的信息不包含确定结论，"
        "也不能替代重新采集后的研究。"
    )
    perspective = {
        "outlook": "neutral",
        "heading": "独立综合流程的证据解释",
        "thesis": prose * 6,
        "drivers": [
            {"label": "冻结结构", "detail": prose * 2, "evidence_ids": ["__EVIDENCE_ID__"]}
        ],
        "invalidation": [
            {
                "condition": "公开结构出现相反变化。",
                "impact": "需要重新研究。",
                "evidence_ids": ["__EVIDENCE_ID__"],
            }
        ],
    }
    research = {
        "horizon": "dual_horizon",
        "outlook": "neutral",
        "confidence": "low",
        "market_overview": {
            "headline": "独立固定综合观点",
            "summary": prose * 6,
            "evidence_ids": ["__EVIDENCE_ID__"],
        },
        "short_term": {**perspective, "horizon": "short_term"},
        "long_term": {**perspective, "horizon": "long_term"},
        "limitations": ["仅验证合成样本下的研究服务契约。"],
    }
    cases: list[dict[str, object]] = []
    for name, scenario, outcome, quality, error, calls in (
        ("unit-complete", "valid", "accepted", "complete", None, ["analysis", "composition"]),
        (
            "unit-composition",
            "composition_timeout",
            "degraded",
            "composition_fallback",
            "model_timeout",
            ["analysis", "composition", "composition"],
        ),
        (
            "unit-invalid",
            "invalid",
            "rejected",
            "analysis_unavailable",
            "model_invalid_response",
            ["analysis", "analysis"],
        ),
        (
            "unit-gated",
            "insufficient",
            "insufficient",
            "data_insufficient",
            "data_quality_insufficient",
            [],
        ),
    ):
        cases.append(
            {
                "id": name,
                "flow": "technical",
                "scenario": scenario,
                "response_file": "invalid.json" if scenario == "invalid" else "valid.json",
                "expected": {
                    "outcome": outcome,
                    "quality": quality,
                    "error_code": error,
                    "calls": calls,
                },
            }
        )
    for name, scenario, outcome, error, calls in (
        ("unit-research-complete", "valid", "accepted", None, ["research"]),
        (
            "unit-research-invalid",
            "invalid",
            "rejected",
            "model_invalid_response",
            ["research", "research", "research"],
        ),
        ("unit-research-timeout", "timeout", "degraded", "model_timeout", ["research"]),
        ("unit-research-gated", "insufficient", "insufficient", "market_closed_candle_missing", []),
    ):
        cases.append(
            {
                "id": name,
                "flow": "research",
                "scenario": scenario,
                "response_file": "invalid.json" if scenario == "invalid" else "research.json",
                "expected": {
                    "outcome": outcome,
                    "quality": "research_complete"
                    if outcome == "accepted"
                    else "research_degraded",
                    "error_code": error,
                    "calls": calls,
                },
            }
        )
    documents: dict[str, object] = {
        "market.json": recipe,
        "valid.json": envelope,
        "research.json": {
            "choices": [{"message": {"content": json.dumps(research, ensure_ascii=False)}}]
        },
        "invalid.json": {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "PRIVATE_TEST_INVALID_OUTPUT"}}
            ]
        },
        "suite.json": {"version": "unit-flows-v1", "market_file": "market.json", "cases": cases},
    }
    for name, document in documents.items():
        (tmp_path / name).write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return tmp_path / "suite.json"


@pytest.mark.asyncio
async def test_independent_two_stage_outcomes_and_safe_fingerprints(
    independent_suite: Path,
) -> None:
    """真实适配器经过成功/拒绝/超时/门控且每次保存后读取，原始思考不进入报告。"""
    first = await evaluate(independent_suite)
    second = await evaluate(independent_suite)
    assert first["status"] == "passed"
    assert first["summary"] == {
        "total": 8,
        "matched": 8,
        "accepted": 2,
        "rejected": 2,
        "degraded": 2,
        "insufficient": 2,
    }
    assert first["versions"] == second["versions"]
    versions = cast(dict[str, str], first["versions"])
    for key in (
        "corpus_sha256",
        "technical_prompt_sha256",
        "research_prompt_sha256",
        "method_sha256",
        "contract_sha256",
    ):
        assert len(versions[key]) == 64
    assert "PRIVATE_TEST" not in json.dumps(first)
    assert "独立测试依据" not in json.dumps(first, ensure_ascii=False)


def test_mismatched_expectation_is_nonzero_and_archived(
    independent_suite: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """改变阶段调用预期应得到失败状态和非零退出，不能仅打印一份成功率。"""
    suite = json.loads(independent_suite.read_text(encoding="utf-8"))
    suite["cases"][0]["expected"]["calls"] = ["analysis"]
    independent_suite.write_text(json.dumps(suite), encoding="utf-8")
    output = tmp_path.parent / (tmp_path.name + "-safe-report.json")
    assert main(["--suite", str(independent_suite), "--output", str(output)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed"
    assert result["summary"]["matched"] == 7
    assert json.loads(output.read_text(encoding="utf-8")) == result
    assert "PRIVATE_TEST" not in output.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_process_model_configuration_is_not_loaded(
    independent_suite: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """外部模型设置与密钥不能改变离线预算、凭证或结果；不读取或输出其值。"""
    monkeypatch.setenv("TECHNICAL_ANALYSIS_MAX_TOKENS", "PRIVATE_TEST_INVALID_CONFIG")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "PRIVATE_TEST_ENV_KEY")
    result = await evaluate(independent_suite)
    assert result["status"] == "passed"
    assert "PRIVATE_TEST" not in json.dumps(result)


@pytest.mark.parametrize("fault", ["tools", "reasoning"])
def test_request_integrity_failure_cannot_be_swallowed_as_model_rejection(
    independent_suite: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fault: str,
) -> None:
    """适配器会捕获HTTP替身异常，因此完整性错误另立失败标记，不能仅看拒绝分类。"""
    original = FixtureTransport.handle

    def unsafe_request(self: FixtureTransport, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if fault == "tools":
            payload["tools"] = []
        else:
            payload["messages"][0]["content"] += "PRIVATE_TEST_REASONING_DO_NOT_ARCHIVE"
        changed = httpx.Request(request.method, request.url, json=payload)
        return original(self, changed)

    monkeypatch.setattr(FixtureTransport, "handle", unsafe_request)
    assert main(["--suite", str(independent_suite)]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "failed",
        "error_code": "evaluation_failed",
    }


@pytest.mark.parametrize(
    "fault", ["duplicate", "unknown-field", "bad-flow", "escape", "bad-envelope"]
)
def test_invalid_configuration_never_masquerades_as_expected_rejection(
    independent_suite: Path, capsys: pytest.CaptureFixture[str], fault: str
) -> None:
    """配置错误属于评估器失败；不得伪装成案例预期的模型拒绝而通过。"""
    suite = json.loads(independent_suite.read_text(encoding="utf-8"))
    if fault == "duplicate":
        suite["cases"].append(suite["cases"][0])
    elif fault == "unknown-field":
        suite["PRIVATE_TEST_CONFIG"] = "PRIVATE_TEST_SECRET"
    elif fault == "bad-flow":
        suite["cases"][1]["flow"] = "research"
    elif fault == "escape":
        suite["cases"][0]["response_file"] = "../PRIVATE_TEST_SECRET.json"
    else:
        (independent_suite.parent / "invalid.json").write_text('{"choices": []}', encoding="utf-8")
    independent_suite.write_text(json.dumps(suite), encoding="utf-8")
    assert main(["--suite", str(independent_suite)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result == {"status": "failed", "error_code": "evaluation_failed"}


def test_empty_or_invalid_suite_fails_safely(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """空集、额外字段与原文异常不能被错误归档为通过。"""
    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps({"version": "test-only", "cases": []}), encoding="utf-8")
    assert main(["--suite", str(suite)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result == {"status": "failed", "error_code": "evaluation_failed"}
    suite.write_text("PRIVATE_INVALID_CONFIGURATION", encoding="utf-8")
    assert main(["--suite", str(suite)]) == 1
    assert "PRIVATE" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_development_suite_has_all_flow_outcomes() -> None:
    """仅此烟雾检查运行开发集合；语义与故障注入由独立测试集合覆盖。"""
    from scripts.evaluate_research_flows import DEFAULT_SUITE

    result = await evaluate(DEFAULT_SUITE)
    assert result["status"] == "passed"
    summary = cast(dict[str, int], result["summary"])
    assert all(summary[key] > 0 for key in ("accepted", "rejected", "degraded", "insufficient"))
