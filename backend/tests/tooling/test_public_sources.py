# 公开源诊断离线回归：通过只读协议替身验证隔离、时效和安全输出，
# 并通过真实生产适配器与 MockTransport 验证固定 GET 请求和解析，不连接网络或数据库。
from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from scripts import check_public_sources as diagnostics

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["fresh", "stale", "future", "gap", "empty"])
async def test_real_sentiment_context_history(case: str) -> None:
    # 真实情绪适配器负责固定请求与解析；诊断检查全部返回时间、每日覆盖和48小时裕量。
    newest = NOW - timedelta(days=3 if case == "stale" else 0)
    if case == "future":
        newest = NOW + timedelta(seconds=1)

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "https://api.alternative.me/fng/?limit=8&format=json"
        return httpx.Response(
            200,
            json={
                "data": []
                if case == "empty"
                else [
                    {
                        "value": "42",
                        "value_classification": "UNTRUSTED",
                        "timestamp": str(
                            int(
                                (
                                    newest - timedelta(days=index * (2 if case == "gap" else 1))
                                ).timestamp()
                            )
                        ),
                    }
                    for index in range(8)
                ]
            },
        )

    async with (
        httpx.AsyncClient(
            base_url="https://api.alternative.me", transport=httpx.MockTransport(respond)
        ) as sentiment,
        httpx.AsyncClient(
            base_url="https://farside.co.uk", transport=httpx.MockTransport(respond)
        ) as etf,
    ):
        specs = diagnostics.build_context_checks(sentiment, etf, clock=lambda: NOW)
        report = await diagnostics.run_checks((specs[0],), clock=lambda: NOW)
    result = report.checks[0]
    assert (
        result.reason
        == {
            "fresh": "fresh",
            "stale": "stale_data",
            "future": "future_data",
            "gap": "incomplete_history",
            "empty": "unavailable",
        }[case]
    )
    assert result.threshold_seconds == 172800
    assert result.count == (0 if case == "empty" else 8)
    assert "UNTRUSTED" not in report.to_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["fresh", "incomplete", "stale", "utc_boundary", "empty"])
async def test_real_etf_context_dates_and_disclosure(case: str) -> None:
    # 纽约交易日必须原样保留；UTC已跨天时仍按纽约日期计算七日calendar时效。
    now = datetime(2026, 11, 3, 1, tzinfo=UTC) if case == "utc_boundary" else NOW
    day = "26 Oct 2026" if case in {"stale", "utc_boundary"} else "30 Oct 2026"
    if case == "stale":
        day = "23 Oct 2026"
    html = (
        "<table><tr><th></th><th>IBIT</th><th>FBTC</th></tr>"
        f"<tr><td>{day}</td><td>1.0</td><td>{'-' if case == 'incomplete' else '2.0'}</td>"
        f"<td>{'1.0' if case == 'incomplete' else '3.0'}</td></tr></table>"
    )

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "farside.co.uk"
        assert request.url.path in {"/btc/", "/eth/"}
        assert not request.url.query
        return httpx.Response(200, text="<table></table>" if case == "empty" else html)

    async with (
        httpx.AsyncClient(
            base_url="https://api.alternative.me", transport=httpx.MockTransport(respond)
        ) as sentiment,
        httpx.AsyncClient(
            base_url="https://farside.co.uk", transport=httpx.MockTransport(respond)
        ) as etf,
    ):
        specs = diagnostics.build_context_checks(sentiment, etf, clock=lambda: now)
        assert len(specs) == 3
        report = await diagnostics.run_checks(specs[1:], clock=lambda: now)
    for result in report.checks:
        assert (
            result.reason
            == {
                "fresh": "fresh",
                "incomplete": "incomplete_disclosure",
                "stale": "stale_data",
                "utc_boundary": "fresh",
                "empty": "invalid_response",
            }[case]
        )
        assert result.observed_at is None
        assert result.threshold_calendar_days == 7
        assert result.trading_date_timezone == "America/New_York"
        if case != "empty":
            assert result.latest_trading_date == date(2026, 10, int(day[:2]))
            assert result.disclosure_complete == (case != "incomplete")
        assert "IBIT" not in report.to_json()


def test_context_cli_is_explicit_and_default_inventory_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 默认调用仍是原24项，显式选项才传入扩展标志；CLI不增加任意URL选项。
    calls: list[bool] = []

    async def fake_run(*, include_context: bool = False) -> diagnostics.DiagnosticReport:
        calls.append(include_context)
        return diagnostics.DiagnosticReport("passed", "checks_complete", NOW, NOW, ())

    monkeypatch.setattr(diagnostics, "run_diagnostics", fake_run)
    assert diagnostics.main([]) == 0
    assert diagnostics.main(["--include-context"]) == 0
    assert calls == [False, True]
    assert "UNTRUSTED" not in capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize("include_context", [False, True])
async def test_diagnostics_inventory_and_client_boundary(
    monkeypatch: pytest.MonkeyPatch, include_context: bool
) -> None:
    # 调度入口创建真实客户端但不发请求：默认24项，显式扩展27项；所有客户端禁用重定向，
    # 不覆盖 trust_env，因此维持生产 httpx 的默认进程网络方式。
    original_client = httpx.AsyncClient
    clients: list[dict[str, object]] = []

    def client(**kwargs: object) -> httpx.AsyncClient:
        clients.append(kwargs)
        # 原始参数由检查入口固定构造；测试保留真实客户端初始化与关闭生命周期。
        return original_client(**kwargs)  # type: ignore[arg-type]

    async def inspect(
        specs: tuple[diagnostics.CheckSpec, ...], *, clock: object
    ) -> diagnostics.DiagnosticReport:
        assert len(specs) == (27 if include_context else 24)
        assert {spec.check_id for spec in specs} == (
            diagnostics.CHECK_IDS | diagnostics.CONTEXT_CHECK_IDS
            if include_context
            else diagnostics.CHECK_IDS
        )
        return diagnostics.DiagnosticReport("passed", "checks_complete", NOW, NOW, ())

    monkeypatch.setattr(diagnostics.httpx, "AsyncClient", client)
    monkeypatch.setattr(diagnostics, "run_checks", inspect)
    await diagnostics.run_diagnostics(include_context=include_context)
    assert len(clients) == (4 if include_context else 2)
    assert all(c["follow_redirects"] is False and "trust_env" not in c for c in clients)
    if include_context:
        assert [c.get("base_url") for c in clients[2:]] == [
            "https://api.alternative.me",
            "https://farside.co.uk",
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["timeout", "429", "redirect", "invalid"])
async def test_context_real_adapter_failures_are_safe_and_isolated(case: str) -> None:
    # 情绪适配器的合并领域错误不虚构HTTP状态；ETF保留自身安全码，两项失败均不阻断同行。
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host in {"api.alternative.me", "farside.co.uk"}
        if case == "timeout":
            raise httpx.ReadTimeout("UNTRUSTED-secret", request=request)
        return httpx.Response(
            {"429": 429, "redirect": 302, "invalid": 200}[case],
            content=b"UNTRUSTED-secret",
            headers={"Location": "https://unsafe.invalid/?token=hidden"},
        )

    async with (
        httpx.AsyncClient(
            base_url="https://api.alternative.me", transport=httpx.MockTransport(respond)
        ) as sentiment,
        httpx.AsyncClient(
            base_url="https://farside.co.uk", transport=httpx.MockTransport(respond)
        ) as etf,
    ):
        specs = diagnostics.build_context_checks(sentiment, etf, clock=lambda: NOW)
        report = await diagnostics.run_checks(specs, clock=lambda: NOW)
    assert len(report.checks) == 3
    assert report.checks[0].reason == ("timeout" if case == "timeout" else "unavailable")
    expected = {
        "timeout": "timeout",
        "429": "rate_limited",
        "redirect": "upstream_rejected",
        "invalid": "invalid_response",
    }[case]
    assert [result.reason for result in report.checks[1:]] == [expected, expected]
    assert "UNTRUSTED" not in report.to_json()
    assert "unsafe" not in report.to_json()


@pytest.mark.asyncio
async def test_etf_returned_future_date_is_rejected() -> None:
    # 生产网关已过滤网页未来日期；这个替身只验证诊断对返回契约中未来字段的独立防线。
    async def future() -> diagnostics.Observation:
        return diagnostics.Observation(
            1, latest_trading_date=date(2026, 11, 3), disclosure_complete=True
        )

    report = await diagnostics.run_checks(
        (diagnostics.CheckSpec("BTCUSDT.etf_flows", future, None, etf=True),), clock=lambda: NOW
    )
    assert (report.checks[0].status, report.checks[0].reason) == ("failed", "future_data")


@pytest.mark.asyncio
async def test_failure_isolation_and_safe_unknown_error() -> None:
    # 第一项包含不可信异常文本，第二项仍必须执行；安全投影不能携带原始消息。
    async def broken() -> diagnostics.Observation:
        raise RuntimeError("secret-response https://unsafe/?token=hidden")

    async def healthy() -> diagnostics.Observation:
        return diagnostics.Observation(count=1, observed_times=(NOW,))

    report = await diagnostics.run_checks(
        (
            diagnostics.CheckSpec("BTCUSDT.summary", broken, 300),
            diagnostics.CheckSpec("coindesk.rss", healthy, 604800, news=True),
        ),
        clock=lambda: NOW,
    )
    assert [item.reason for item in report.checks] == ["unexpected_error", "fresh"]
    assert report.status == "partial"
    assert "secret" not in report.to_json()
    assert "unsafe" not in report.to_json()


@pytest.mark.asyncio
async def test_total_timeout_does_not_block_other_source(monkeypatch: pytest.MonkeyPatch) -> None:
    # 无响应的协议替身模拟请求/重试等待，总时限取消该分项后其他来源仍完成。
    monkeypatch.setattr(diagnostics, "CHECK_TIMEOUT_SECONDS", 0.01)

    async def hanging() -> diagnostics.Observation:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def healthy() -> diagnostics.Observation:
        return diagnostics.Observation(count=1, observed_times=(NOW,))

    report = await diagnostics.run_checks(
        (
            diagnostics.CheckSpec("BTCUSDT.summary", hanging, 300),
            diagnostics.CheckSpec("coindesk.rss", healthy, 604800, news=True),
        ),
        clock=lambda: NOW,
    )
    assert [result.reason for result in report.checks] == ["timeout", "fresh"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("times", "count", "news", "reason", "status"),
    [
        ((), 0, False, "empty_data", "failed"),
        ((NOW - timedelta(hours=2),), 1, False, "stale_data", "partial"),
        ((NOW + timedelta(seconds=1),), 1, False, "future_data", "failed"),
        ((NOW - timedelta(days=10),), 1, True, "no_recent_news", "partial"),
        ((), 0, True, "empty_data", "partial"),
        ((NOW - timedelta(days=1),), 1, True, "fresh", "passed"),
    ],
)
async def test_freshness_and_news_coverage(
    times: tuple[datetime, ...], count: int, news: bool, reason: str, status: str
) -> None:
    # 低频新闻仍可访问，但零条或七日无内容不能冒充完整通过；未来时间明确失败。
    async def observe() -> diagnostics.Observation:
        return diagnostics.Observation(count=count, observed_times=times)

    report = await diagnostics.run_checks(
        (
            diagnostics.CheckSpec(
                "coindesk.rss" if news else "BTCUSDT.summary",
                observe,
                604800 if news else 300,
                news=news,
            ),
        ),
        clock=lambda: NOW,
    )
    item = report.checks[0]
    assert (item.reason, item.status) == (reason, status)
    if news:
        assert item.availability == "available"
        assert item.recent_news_count == (1 if reason == "fresh" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["timeout", "429", "redirect", "invalid"])
async def test_real_adapter_safe_failures(case: str) -> None:
    # 生产适配器确实执行请求、解析与既有有限重试；不修改适配器使诊断变绿。
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "fapi.binance.com"
        assert request.url.path == "/fapi/v1/exchangeInfo"
        if case == "timeout":
            raise httpx.ReadTimeout("unsafe-secret", request=request)
        if case == "429":
            return httpx.Response(429)
        if case == "redirect":
            return httpx.Response(302, headers={"Location": "https://unsafe.invalid/"})
        return httpx.Response(200, content=b"not-json-secret")

    async with httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=httpx.MockTransport(respond)
    ) as client:
        specs = diagnostics.build_checks(client, client, clock=lambda: NOW)
        report = await diagnostics.run_checks((specs[0],), clock=lambda: NOW)
    expected = {
        "timeout": "timeout",
        "429": "rate_limited",
        "redirect": "upstream_rejected",
        "invalid": "invalid_response",
    }
    assert report.checks[0].reason == expected[case]
    assert len(requests) == (2 if case in {"timeout", "429"} else 1)
    assert "secret" not in report.to_json()
    assert "unsafe" not in report.to_json()


@pytest.mark.asyncio
async def test_real_metadata_adapter_and_fixed_inventory() -> None:
    # 固定样本验证生产解析结果仅投影成条数，不把完整元数据或价格输出。
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/fapi/v1/exchangeInfo"
        return httpx.Response(
            200,
            json={
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "baseAsset": "BTC",
                        "quoteAsset": "USDT",
                        "marginAsset": "USDT",
                        "contractType": "PERPETUAL",
                        "status": "TRADING",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=httpx.MockTransport(respond)
    ) as client:
        specs = diagnostics.build_checks(client, client, clock=lambda: NOW)
        assert len(specs) == 24
        assert len({spec.check_id for spec in specs}) == 24
        report = await diagnostics.run_checks((specs[0],), clock=lambda: NOW)
    assert report.status == "passed"
    assert report.checks[0].reason == "metadata_available"
    assert report.checks[0].observed_at is None
    assert "TRADING" not in report.to_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 302, 429])
async def test_real_rss_adapter_and_safe_http_status(status: int) -> None:
    # 实际 RSS 适配器使用流式响应；正文仅在内存规范化，最终 JSON 不含标题、摘要或链接。
    class FeedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (
                b"<rss><channel><item><title>The market update UNTRUSTED-HEADLINE</title>"
                b"<description>The report on digital asset policy UNTRUSTED-SUMMARY</description>"
                b"<link>https://www.coindesk.com/example?private=UNTRUSTED</link>"
                b"<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate>"
                b"</item></channel></rss>"
            )

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == str(diagnostics.ALLOWED_NEWS_SOURCES["coindesk"].feed_url)
        return httpx.Response(
            status,
            stream=FeedStream(),
            headers={"Location": "https://unsafe.invalid/?token=hidden"},
        )

    async with httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=httpx.MockTransport(respond)
    ) as client:
        specs = diagnostics.build_checks(client, client, clock=lambda: NOW)
        spec = next(spec for spec in specs if spec.check_id == "coindesk.rss")
        report = await diagnostics.run_checks((spec,), clock=lambda: NOW)
    item = report.checks[0]
    assert item.status == ("passed" if status == 200 else "failed")
    assert item.recent_news_count == (1 if status == 200 else None)
    assert item.http_status == (None if status == 200 else status)
    assert "UNTRUSTED" not in report.to_json()
    assert "unsafe" not in report.to_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("include_good", [False, True])
async def test_real_rss_filtered_entries_are_partial_and_counted(include_good: bool) -> None:
    # 全拒绝和部分拒绝均保持可连接但覆盖不完整；输出只能有计数和固定原因。
    good = (
        "<item><title>The market update UNTRUSTED</title>"
        "<description>The report on market demand.</description>"
        "<link>https://example.com/UNTRUSTED</link>"
        "<pubDate>2026-11-02T10:00:00Z</pubDate></item>"
    )
    payload = (
        "<rss><channel>"
        + (good if include_good else "")
        + good.replace("The market update UNTRUSTED", "中文拒绝")
        + "</channel></rss>"
    ).encode()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield payload

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=Stream())

    async with httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=httpx.MockTransport(respond)
    ) as client:
        specs = diagnostics.build_checks(client, client, clock=lambda: NOW)
        spec = next(spec for spec in specs if spec.check_id == "coindesk.rss")
        report = await diagnostics.run_checks((spec,), clock=lambda: NOW)
    result = report.checks[0]
    assert (result.status, result.reason, result.availability) == (
        "partial",
        "filtered_entries",
        "available",
    )
    assert result.count == int(include_good)
    assert result.rejected_entry_count == 1
    assert result.recent_news_count == int(include_good)
    assert "UNTRUSTED" not in report.to_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [False, True])
async def test_real_funding_adapter_requires_seven_day_coverage(complete: bool) -> None:
    # 单条最新费率不代表七日历史完整；完整固定样本覆盖21个八小时结算点。
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/fapi/v1/fundingRate"
        assert request.url.params["symbol"] == "BTCUSDT"
        assert request.url.params["limit"] == "1000"
        assert request.url.params["startTime"] == str(
            int((NOW - timedelta(days=7)).timestamp() * 1000)
        )
        points = [NOW - timedelta(hours=8 * index) for index in range(21 if complete else 1)]
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "BTCUSDT",
                    "fundingTime": int(point.timestamp() * 1000),
                    "fundingRate": "0.0001",
                }
                for point in reversed(points)
            ],
        )

    async with httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=httpx.MockTransport(respond)
    ) as client:
        specs = diagnostics.build_checks(client, client, clock=lambda: NOW)
        spec = next(spec for spec in specs if spec.check_id == "BTCUSDT.funding_7d")
        report = await diagnostics.run_checks((spec,), clock=lambda: NOW)
    assert report.checks[0].reason == ("fresh" if complete else "incomplete_history")
    assert "0.0001" not in report.to_json()


@pytest.mark.parametrize("count", [0, 1])
def test_cli_safe_output_and_report_write_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path, count: int
) -> None:
    # CLI 的退出码、stdout JSON、可选磁盘 JSON 必须一致；落盘失败输出固定安全码。
    async def fake_run() -> diagnostics.DiagnosticReport:
        async def observe() -> diagnostics.Observation:
            return diagnostics.Observation(count=count, observed_times=(NOW,) if count else ())

        return await diagnostics.run_checks(
            (diagnostics.CheckSpec("BTCUSDT.summary", observe, 300),), clock=lambda: NOW
        )

    monkeypatch.setattr(diagnostics, "run_diagnostics", fake_run)
    target = tmp_path / "report.json"
    assert diagnostics.main(["--report", str(target)]) == (0 if count else 1)
    output = capsys.readouterr().out
    assert json.loads(output) == json.loads(target.read_text(encoding="utf-8"))
    assert json.loads(output)["schema_version"] == 1
    assert diagnostics.main(["--report", str(tmp_path)]) == 2
    output = capsys.readouterr().out
    assert json.loads(output)["reason"] == "report_write_failed"
    assert str(tmp_path) not in output
