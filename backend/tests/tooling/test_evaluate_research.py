# 验证离线评估器执行真实适配器校验，并对空集、损坏样本和错误预期失败关闭。
# 底层真实网络被禁止；合成样本不需要真实模型、凭证或数据库。
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest


def evaluator() -> Any:
    """延迟导入入口，让尚未实现的评估器在执行阶段产生明确红灯。"""
    return importlib.import_module("scripts.evaluate_research")


def test_offline_suite_matches_without_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """禁用真实传输后运行固定集，合法接受、安全拒绝与降级分别统计。"""

    async def deny_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("real network forbidden")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny_network)
    assert evaluator().main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "passed"
    assert report["summary"]["accepted"] >= 1
    assert report["summary"]["rejected"] >= 3
    assert report["summary"]["degraded"] >= 1
    assert all(case["matched"] for case in report["cases"])
    assert len(report["versions"]["prompt_sha256"]) == 64
    assert len(report["versions"]["contract_sha256"]) == 64
    assert "raw_response" not in json.dumps(report)


def test_output_artifact_matches_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """可选 JSON 产物与安全标准输出一致，便于 CI 归档。"""
    output = tmp_path / "evaluation.json"
    assert evaluator().main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == json.loads(capsys.readouterr().out)


@pytest.mark.parametrize(
    "damage", ["empty", "invalid", "mismatch", "response", "request", "duplicate", "traversal"]
)
def test_invalid_corpus_or_expectation_fails_safely(
    damage: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """空集、错误预期、损坏响应及路径越界不能假绿或泄漏样本。"""
    module = evaluator()
    source = module.DEFAULT_SUITE
    payload = json.loads(source.read_text(encoding="utf-8"))
    for fixture in source.parent.glob("*.json"):
        (tmp_path / fixture.name).write_bytes(fixture.read_bytes())
    if damage == "empty":
        payload["cases"] = []
    elif damage == "invalid":
        payload["cases"][0]["expected"]["outcome"] = "secret-marker"
    elif damage == "mismatch":
        payload["cases"][0]["expected"] = {
            "outcome": "rejected",
            "error_code": "model_invalid_response",
            "attempts": 3,
        }
    elif damage == "response":
        (tmp_path / payload["cases"][0]["response_file"]).write_text(
            '{"secret-marker":', encoding="utf-8"
        )
    elif damage == "request":
        (tmp_path / payload["cases"][0]["request_file"]).write_text(
            '{"evidences": [], "secret-marker": true}', encoding="utf-8"
        )
    elif damage == "duplicate":
        payload["cases"].append(payload["cases"][0])
    else:
        payload["cases"][0]["response_file"] = "../secret-marker.json"
    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps(payload), encoding="utf-8")
    assert module.main(["--suite", str(suite)]) != 0
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "failed"
    assert "secret-marker" not in output.out + output.err


def test_unwritable_artifact_is_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """产物不能写入时不能报告完成，且不得输出路径中的任意敏感标记。"""
    output = tmp_path / "secret-marker" / "missing-parent.json"
    assert evaluator().main(["--output", str(output)]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "failed", "error_code": "evaluation_failed"}
    assert "secret-marker" not in captured.out + captured.err
