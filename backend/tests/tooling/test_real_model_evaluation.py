# 真实模型工具的离线边界测试：仅 MockTransport 驱动生产适配器，不允许实际付费调用。
# 合成响应验证合同、额度与安全产物，不能用于证明真实模型的研究质量。
from __future__ import annotations

import asyncio
import gzip
import importlib
import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest


def evaluator() -> Any:
    """延迟导入，使先测试后实现的红灯定位到缺失入口。"""
    return importlib.import_module("scripts.evaluate_real_models")


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """复制公开合成证据至临时固定目录，避免测试修改版本化语料。"""
    module = evaluator()
    source = Path(__file__).resolve().parents[2] / "evaluation" / "request.json"
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "request.json").write_bytes(source.read_bytes())
    for name in ("provenance.json", "historical-market.json", "rubric.json"):
        (suite_dir / name).write_bytes((source.parent / "real-model" / name).read_bytes())
    suite = suite_dir / "suite.json"
    suite.write_text(
        json.dumps(
            {
                "version": "test-v1",
                "scope": "comprehensive-research-only",
                "cases": [{"id": "baseline", "request_file": "request.json"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "DEFAULT_SUITE", suite)
    monkeypatch.setattr(module, "REPORT_ROOT", tmp_path / "results")
    (tmp_path / "results").mkdir()
    return suite


def test_default_prepare_never_sends_even_with_key(
    corpus: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """默认只准备指纹；进程存在显式密钥也不能把离线命令升级为联网。"""

    async def deny(*args: object, **kwargs: object) -> None:
        raise AssertionError("network forbidden")

    monkeypatch.setenv("REAL_MODEL_EVAL_API_KEY", "private-test-marker")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny)
    assert evaluator().main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "prepared"
    assert report["summary"]["actual_requests"] == 0
    assert report["cases"][0]["semantic_review"] == "pending"
    assert "private-test-marker" not in json.dumps(report)


def test_live_requires_explicit_limits_and_key(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """显式 live 仍必须具备调用、输入、输出、时间额度和产物路径。"""
    assert evaluator().main(["--live"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["error_code"] == "live_configuration_required"
    assert report["summary"]["actual_requests"] == 0


def live_args(module: Any, name: str = "run", *extra: str) -> list[str]:
    """所有测试显式提供额度；路径只指向测试专属结果目录。"""
    return [
        "--live",
        "--model",
        "deepseek-v4-flash",
        "--max-requests",
        "8",
        "--max-input-bytes",
        "131072",
        "--max-output-tokens",
        "7000",
        "--request-timeout-seconds",
        "2",
        "--total-timeout-seconds",
        "20",
        "--output",
        str(module.REPORT_ROOT / f"{name}.json"),
        *extra,
    ]


@pytest.fixture
def responses() -> dict[str, Any]:
    """沿用固定离线合法正文，只在内存加上合成 usage；不会调用真实模型。"""
    path = Path(__file__).resolve().parents[2] / "evaluation" / "response-valid.json"
    response = json.loads(path.read_text(encoding="utf-8"))
    response["usage"] = {"prompt_tokens": 100, "completion_tokens": 200}
    return response


def mock_http(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request, int], httpx.Response]
) -> list[httpx.Request]:
    """保留真实生产模型/受治理transport，只替换最终HTTP层并记录实际请求。"""
    requests: list[httpx.Request] = []

    def checked(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert "tools" not in json.loads(request.content)
        return handler(request, len(requests))

    def factory(*args: object, **kwargs: object) -> httpx.MockTransport:
        assert kwargs["retries"] == 0
        assert kwargs["trust_env"] is False
        return httpx.MockTransport(checked)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", factory)
    monkeypatch.setenv("REAL_MODEL_EVAL_API_KEY", "private-test-marker")
    return requests


def test_live_uses_production_contract_and_safe_report(
    corpus: Path,
    responses: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """真实适配器接受合法JSON，但报告不得含正文、API key或任意原始响应。"""
    module = evaluator()
    requests = mock_http(monkeypatch, lambda request, number: httpx.Response(200, json=responses))
    assert (
        module.main(
            live_args(
                module,
                "accepted",
                "--input-price-per-million",
                "1.2",
                "--output-price-per-million",
                "2.4",
            )
        )
        == 0
    )
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["cases"][0]["outcome"] == "accepted"
    assert report["summary"]["actual_requests"] == len(requests) == 1
    assert Decimal(report["summary"]["estimated_cost"]) == Decimal("0.0006")
    assert json.loads(requests[0].content)["max_tokens"] == 4000
    assert report["cases"][0]["semantic_review"] == "pending"
    assert "private-test-marker" not in captured.out + captured.err
    assert "market_overview" not in captured.out
    assert json.loads((module.REPORT_ROOT / "accepted.json").read_text()) == report
    assert not list(module.REPORT_ROOT.glob("*.review.json"))


def test_rejected_numeric_claim_retains_only_safe_attempt_diagnostics(
    corpus: Path,
    responses: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """付费失败需能定位具体门禁，但报告只留类别、字段与次数，不留拒绝正文。"""
    import structlog

    module = evaluator()
    # 模拟应用已缓存的日志器：capture_logs无法替换其既有处理器，诊断不能依赖日志捕获。
    monkeypatch.setattr(
        module.model_module,
        "logger",
        structlog.BoundLogger(structlog.ReturnLogger(), processors=[], context={}),
    )
    response = json.loads(json.dumps(responses))
    proposal = json.loads(response["choices"][0]["message"]["content"])
    proposal["market_overview"]["summary"] += " private-numeric-marker 76717.00"
    response["choices"][0]["message"]["content"] = json.dumps(proposal)
    mock_http(monkeypatch, lambda request, number: httpx.Response(200, json=response))
    assert module.main(live_args(module, "numeric-rejected")) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    item = report["cases"][0]
    assert item["outcome"] == "rejected"
    assert len(item["validation_failures"]) == 3
    assert item["validation_failures"][0]["categories"] == ["unbound_numeric_claim"]
    assert item["validation_failures"][0]["field_paths"] == ["market_overview.summary"]
    assert "private-numeric-marker" not in output and "76717.00" not in output


def test_correction_attempts_count_as_actual_requests(
    corpus: Path,
    responses: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """格式纠错由生产适配器发起，三次均须经过同一个总调用额度。"""
    invalid = {"choices": [{"message": {"content": "{invalid"}}], "usage": responses["usage"]}
    module = evaluator()
    sent = mock_http(monkeypatch, lambda request, number: httpx.Response(200, json=invalid))
    assert module.main(live_args(module)) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(sent) == report["summary"]["actual_requests"] == 3
    assert report["cases"][0]["outcome"] == "rejected"
    assert report["cases"][0]["format_retries"] == 2


def test_request_budget_stops_correction_before_send(
    corpus: Path,
    responses: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """最多一次实际调用时，第二个格式纠正请求被阻止且不丢失首次计数。"""
    invalid = {"choices": [{"message": {"content": "{"}}], "usage": responses["usage"]}
    module = evaluator()
    sent = mock_http(monkeypatch, lambda request, number: httpx.Response(200, json=invalid))
    assert module.main(live_args(module, "budget", "--max-requests", "1")) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["error_code"] == "request_limit_exceeded"
    assert len(sent) == report["summary"]["actual_requests"] == 1


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"prompt_tokens": True, "completion_tokens": 1},
        {"prompt_tokens": -1, "completion_tokens": 2},
    ],
)
def test_unknown_usage_stops_next_case_and_never_means_zero_cost(
    usage: Any,
    corpus: Path,
    responses: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """缺失或无效 usage 不是免费调用；保留已接受分类但停止后续案例。"""
    payload = json.loads(corpus.read_text())
    payload["cases"].append({"id": "second", "request_file": "request.json"})
    corpus.write_text(json.dumps(payload))
    responses["usage"] = usage
    module = evaluator()
    sent = mock_http(monkeypatch, lambda request, number: httpx.Response(200, json=responses))
    assert module.main(live_args(module, "unknown")) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["actual_requests"] == len(sent) == 1
    assert report["error_code"] == "usage_unknown"
    assert report["summary"]["estimated_cost"] is None
    assert report["summary"]["known_prompt_tokens"] is None
    assert report["cases"][0]["outcome"] == "accepted"
    assert report["cases"][1]["outcome"] == "blocked"


@pytest.mark.parametrize("damage", ["empty", "traversal", "tools", "duplicate"])
def test_invalid_suite_fails_without_network_or_input_echo(
    damage: str, corpus: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """零案例、来源文件路径及工具字段不能成为新权限入口。"""
    payload = json.loads(corpus.read_text())
    if damage == "empty":
        payload["cases"] = []
    elif damage == "traversal":
        payload["cases"][0]["request_file"] = "../private-test-marker.json"
    elif damage == "duplicate":
        payload["cases"].append(payload["cases"][0])
    else:
        request = json.loads((corpus.parent / "request.json").read_text())
        request["tools"] = ["private-test-marker"]
        (corpus.parent / "request.json").write_text(json.dumps(request))
    corpus.write_text(json.dumps(payload))
    sent = mock_http(monkeypatch, lambda request, number: pytest.fail("network forbidden"))
    assert evaluator().main(live_args(evaluator())) == 1
    captured = capsys.readouterr()
    assert not sent
    assert "private-test-marker" not in captured.out + captured.err


@pytest.mark.parametrize(
    "kind",
    [
        "existing",
        "outside",
        "directory",
        "output_limit",
        "input_limit",
        "missing_key",
        "sidecar_existing",
    ],
)
def test_live_preflight_blocks_before_network(
    kind: str, corpus: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """产物与额度预检必须先于付费；已有结果、sidecar与密钥缺失都失败关闭。"""
    module = evaluator()
    sent = mock_http(monkeypatch, lambda request, number: pytest.fail("network forbidden"))
    args = live_args(module)
    target = module.REPORT_ROOT / "run.json"
    if kind == "existing":
        target.write_text("existing")
    elif kind == "outside":
        args.extend(["--output", str(corpus.parent / "bad.json")])
    elif kind == "directory":
        target.mkdir()
    elif kind == "output_limit":
        args.extend(["--max-output-tokens", "3999"])
    elif kind == "input_limit":
        args.extend(["--max-input-bytes", "1"])
    elif kind == "missing_key":
        monkeypatch.delenv("REAL_MODEL_EVAL_API_KEY")
    else:
        args.append("--save-accepted-proposals")
        (module.REPORT_ROOT / "run.review.json").write_text("existing")
    assert module.main(args) == 1
    assert not sent
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["actual_requests"] == 0
    if kind == "existing":
        assert target.read_text() == "existing"


def test_transport_error_stops_and_redacts_everything(
    corpus: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """底层异常可能携带凭证或响应，工具只输出固定码并保留已发起次数。"""

    def failure(request: httpx.Request, number: int) -> httpx.Response:
        raise httpx.ConnectError("private-test-marker", request=request)

    module = evaluator()
    sent = mock_http(monkeypatch, failure)
    assert module.main(live_args(module)) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["error_code"] == "model_transport_error"
    assert report["summary"]["actual_requests"] == len(sent) == 1
    assert "private-test-marker" not in captured.out + captured.err


def test_report_write_failure_retains_request_count(
    corpus: Path,
    responses: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """预检后磁盘仍可能故障；stdout必须报告失败且保留已付费请求统计。"""
    module = evaluator()
    mock_http(monkeypatch, lambda request, number: httpx.Response(200, json=responses))

    def fail(*args: object) -> None:
        raise OSError("private-test-marker")

    monkeypatch.setattr(module, "_write_report", fail)
    assert module.main(live_args(module)) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["error_code"] == "report_write_failed"
    assert report["summary"]["actual_requests"] == 1
    assert "private-test-marker" not in captured.out + captured.err


def test_accepted_review_sidecar_is_explicit_and_separate(
    corpus: Path,
    responses: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """本地人工复核只保存已校验提案，安全报告只放指纹，不含模型正文。"""
    module = evaluator()
    mock_http(monkeypatch, lambda request, number: httpx.Response(200, json=responses))
    assert module.main(live_args(module, "review", "--save-accepted-proposals")) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    sidecar = json.loads((module.REPORT_ROOT / "review.review.json").read_text())
    assert sidecar["proposals"]["baseline"]["market_overview"]
    assert sidecar["versions"] == report["versions"]
    assert len(report["review_artifact_sha256"]) == 64
    assert "market_overview" not in captured.out


def test_governed_transport_rejects_tools_and_wrong_endpoint() -> None:
    """直接测试最终HTTP门，防止未来适配器漂移增加工具权限或更换域名。"""
    module = evaluator()
    state = module.RunState()
    limits = module.Limits(
        max_requests=1,
        max_input_bytes=10000,
        max_output_tokens=7000,
        request_timeout_seconds=1,
        total_timeout_seconds=10,
    )

    async def exercise() -> None:
        inner = httpx.MockTransport(lambda request: pytest.fail("transport must not send"))
        transport = module.GovernedTransport(inner=inner, limits=limits, state=state)
        with pytest.raises(module.EvaluationStop, match="endpoint_forbidden"):
            await transport.handle_async_request(httpx.Request("POST", "https://example.com"))
        with pytest.raises(module.EvaluationStop, match="request_shape_forbidden"):
            await transport.handle_async_request(
                httpx.Request("POST", module.ENDPOINT, json={"tools": []})
            )

    asyncio.run(exercise())
    assert state.actual_requests == 0


@pytest.mark.parametrize("damage", ["missing", "json", "history_hash"])
def test_metadata_is_required_and_integrity_checked(
    damage: str, corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """历史样本、来源记录与人工规则均需可读且哈希一致，不能静默缺失。"""
    if damage == "missing":
        (corpus.parent / "rubric.json").unlink()
    elif damage == "json":
        (corpus.parent / "rubric.json").write_text("{private-test-marker")
    else:
        (corpus.parent / "historical-market.json").write_text('{"candles":[{}]}')
    assert evaluator().main([]) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["error_code"] == "metadata_invalid"
    assert report["summary"]["actual_requests"] == 0
    assert "private-test-marker" not in captured.out + captured.err


def test_redirect_is_never_followed(
    corpus: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """即使服务返回带其他域名的Location，凭证也不能被客户端重定向转发。"""
    module = evaluator()
    sent = mock_http(
        monkeypatch,
        lambda request, number: httpx.Response(
            302, headers={"Location": "https://example.com/private-test-marker"}
        ),
    )
    assert module.main(live_args(module)) == 1
    report = json.loads(capsys.readouterr().out)
    assert len(sent) == report["summary"]["actual_requests"] == 1
    assert report["error_code"] == "model_upstream_error"


def test_response_cannot_request_tools(
    corpus: Path,
    responses: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """无工具研究即使收到合法正文与工具调用并列响应，也必须拒绝工具侧信道。"""
    responses["choices"][0]["message"]["tool_calls"] = [{"name": "private-test-marker"}]
    module = evaluator()
    mock_http(monkeypatch, lambda request, number: httpx.Response(200, json=responses))
    assert module.main(live_args(module)) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error_code"] == "response_tools_forbidden"
    assert "private-test-marker" not in captured.out + captured.err


def test_news_boundary_checked_on_actual_adapter_request(
    corpus: Path,
    responses: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """注入样本只确认真实请求保留转义边界；不能据此把语义复核标成通过。"""
    source = Path(__file__).resolve().parents[2] / "evaluation" / "request-injection.json"
    (corpus.parent / "request.json").write_bytes(source.read_bytes())
    suite = json.loads(corpus.read_text())
    suite["cases"][0]["check_news_boundary"] = True
    corpus.write_text(json.dumps(suite))
    module = evaluator()
    sent = mock_http(monkeypatch, lambda request, number: httpx.Response(200, json=responses))
    assert module.main(live_args(module)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["cases"][0]["news_boundary_checked"] is True
    assert report["cases"][0]["semantic_review"] == "pending"
    assert b"UNTRUSTED_NEWS" in sent[0].content


def test_time_limits_cover_actual_send_and_expired_total() -> None:
    """请求超时保留已发送次数；总时间已耗尽则在实际HTTP前拒绝。"""
    module = evaluator()
    limits = module.Limits(
        max_requests=3,
        max_input_bytes=10000,
        max_output_tokens=7000,
        request_timeout_seconds=1,
        total_timeout_seconds=10,
    )
    payload: dict[str, Any] = {
        "model": "deepseek-v4-flash",
        "messages": [],
        "response_format": {},
        "thinking": {},
        "max_tokens": 4000,
    }

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2)
        raise AssertionError("timeout must interrupt")

    async def exercise() -> None:
        state = module.RunState()
        transport = module.GovernedTransport(
            inner=httpx.MockTransport(slow), limits=limits, state=state
        )
        with pytest.raises(module.EvaluationStop, match="request_timeout"):
            await transport.handle_async_request(
                httpx.Request("POST", module.ENDPOINT, json=payload)
            )
        assert state.actual_requests == 1
        expired = module.RunState(started=state.started - 20)
        transport = module.GovernedTransport(
            inner=httpx.MockTransport(slow), limits=limits, state=expired
        )
        with pytest.raises(module.EvaluationStop, match="total_timeout"):
            await transport.handle_async_request(
                httpx.Request("POST", module.ENDPOINT, json=payload)
            )
        assert expired.actual_requests == 0

    asyncio.run(exercise())


def test_gzip_response_is_decoded_once(
    corpus: Path,
    responses: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """真实HTTP压缩响应在边界层有界解码后，不能带旧压缩头交给httpx再次解压。"""
    module = evaluator()
    compressed = gzip.compress(json.dumps(responses).encode("utf-8"))
    mock_http(
        monkeypatch,
        lambda request, number: httpx.Response(
            200,
            headers={"Content-Encoding": "gzip", "Content-Length": str(len(compressed))},
            stream=httpx.ByteStream(compressed),
        ),
    )
    assert module.main(live_args(module)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["cases"][0]["outcome"] == "accepted"
    assert report["summary"]["known_usage_requests"] == 1


@pytest.mark.parametrize("price", ["1e999999999", "NaN", "Infinity", "-1", "1e-999999999"])
def test_invalid_prices_fail_before_http(
    price: str, corpus: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """有界显式Decimal单价防止估算溢出或零精度下溢破坏已发送请求报告。"""
    module = evaluator()
    sent = mock_http(monkeypatch, lambda request, number: pytest.fail("network forbidden"))
    assert (
        module.main(
            live_args(
                module,
                "price",
                "--input-price-per-million",
                price,
                "--output-price-per-million",
                "1",
            )
        )
        == 1
    )
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["actual_requests"] == len(sent) == 0


def test_preflight_flush_failure_never_sends(
    corpus: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """创建路径仍不等于可持久写入；付费前fsync失败必须阻止实际HTTP。"""
    module = evaluator()
    sent = mock_http(monkeypatch, lambda request, number: pytest.fail("network forbidden"))

    def fail_sync(descriptor: int) -> None:
        raise OSError("private-test-marker")

    monkeypatch.setattr(module.os, "fsync", fail_sync)
    assert module.main(live_args(module)) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error_code"] == "report_preflight_failed"
    assert not sent
    assert "private-test-marker" not in captured.out + captured.err


def test_reserved_artifact_does_not_reopen_replaced_path(corpus: Path) -> None:
    """Windows保持句柄阻止改名；允许改名的平台也只写原文件，不能改写替代路径。"""
    module = evaluator()
    target = module.REPORT_ROOT / "reserved.json"
    artifact = module._reserve_output(target)
    try:
        try:
            target.rename(target.with_suffix(".original"))
        except PermissionError:
            module._write_report(artifact, {"safe": True})
        else:
            target.write_text("replacement-must-remain")
            module._write_report(artifact, {"safe": True})
            assert target.read_text() == "replacement-must-remain"
    finally:
        artifact.handle.close()


def test_close_failure_preserves_stdout_counts(
    corpus: Path,
    responses: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """磁盘故障可在close再次触发；每个句柄都需独立收敛异常并打印安全统计。"""
    module = evaluator()
    original = module._reserve_output
    mock_http(monkeypatch, lambda request, number: httpx.Response(200, json=responses))

    class CloseFailure:
        """仅注入关闭阶段故障，其他方法仍访问真实独占临时文件。"""

        def __init__(self, inner: Any) -> None:
            self.inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

        def close(self) -> None:
            self.inner.close()
            raise OSError("private-test-marker")

    def reserve(path: Path) -> Any:
        artifact = original(path)
        return module.ReservedArtifact(artifact.path, CloseFailure(artifact.handle))

    monkeypatch.setattr(module, "_reserve_output", reserve)
    assert module.main(live_args(module)) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["error_code"] == "report_write_failed"
    assert report["summary"]["actual_requests"] == 1
    assert "private-test-marker" not in captured.out + captured.err
