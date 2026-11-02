# 新闻生产协调链的离线回归：真实 RSS 适配器配合固定流，验证请求局部覆盖诊断与报告限制。
# 不读网络、数据库或模型；拒绝、空订阅、窗口无内容与标的不相关分别验证。
# pyright: reportPrivateUsage=false
import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.agent.service import _limitations, _policy_source_coverage, _source_coverage
from app.market.contracts import ContractSymbol
from app.news.contracts import ALLOWED_NEWS_SOURCES, NewsItemDraft
from app.news.rss import RssNewsSourceAdapter
from app.news.service import NewsIngestionService

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


class _Repository:
    # 返回原候选，避免存储去重掩盖采集覆盖断言。
    async def ingest_many(self, items: tuple[NewsItemDraft, ...]) -> tuple[NewsItemDraft, ...]:
        return items


class _Stream(httpx.AsyncByteStream):
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def __aiter__(self):
        yield self.payload


def _entry(
    *, title: str = "The Bitcoin market update", published: str = "2026-11-02T10:00:00Z"
) -> str:
    return (
        f"<item><title>{title}</title><description>The report on market demand.</description>"
        f"<link>https://example.com/safe</link><pubDate>{published}</pubDate></item>"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["filtered", "all_filtered", "empty", "old", "unrelated"])
async def test_production_collection_distinguishes_content_coverage(case: str) -> None:
    # 不相关但近期的合法条目证明“无币种证据”不能冒充“来源无近期内容”。
    entry = {
        "filtered": _entry() + _entry(title="中文拒绝"),
        "all_filtered": _entry(title="中文拒绝"),
        "empty": "",
        "old": _entry(published="2026-10-01T10:00:00Z"),
        "unrelated": _entry(title="The museum market update"),
    }[case]
    payload = f"<rss><channel>{entry}</channel></rss>".encode()

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Stream(payload))

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = NewsIngestionService(
            sources=(
                RssNewsSourceAdapter(
                    source=ALLOWED_NEWS_SOURCES["coindesk"], client=client, timeout_seconds=5
                ),
            ),
            repository=_Repository(),
        )
        result = await service.collect(
            ContractSymbol.BTCUSDT, since=NOW - timedelta(days=7), until=NOW
        )
    diagnostic = result.source_diagnostics[0]
    assert (
        diagnostic.outcome
        == {
            "filtered": "partial",
            "all_filtered": "partial",
            "empty": "empty",
            "old": "no_recent",
            "unrelated": "complete",
        }[case]
    )
    assert diagnostic.recent_count == (1 if case in {"filtered", "unrelated"} else 0)
    assert diagnostic.rejected_count == (1 if "filtered" in case else 0)
    assert _source_coverage(result) == ("complete" if case == "unrelated" else "partial")
    assert result.failed_source_count == 0
    limitations = " ".join(_limitations(result, (), market=None))
    if "filtered" in case:
        assert "英文新闻条目过滤：拒绝 1 条，来源 coindesk；覆盖不完整。" in limitations
    elif case == "empty":
        assert "英文新闻空订阅：coindesk；本次未提供条目。" in limitations
    elif case == "old":
        assert (
            "本次保留的英文新闻条目在时间窗内无内容：coindesk；"
            "不能据此认定连接失败或整个来源无近期内容。"
        ) in limitations
    else:
        assert "时间窗内无内容" not in limitations


@pytest.mark.asyncio
async def test_filtered_official_source_prevents_complete_policy_coverage() -> None:
    # 四个官方来源均能读取，但一源过滤时政策来源覆盖仍只能 partial。
    def respond(request: httpx.Request) -> httpx.Response:
        entry = _entry()
        if request.url.host == "www.sec.gov":
            entry += _entry(title="中文拒绝")
        return httpx.Response(
            200, stream=_Stream(f"<rss><channel>{entry}</channel></rss>".encode())
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = NewsIngestionService(
            sources=tuple(
                RssNewsSourceAdapter(source=source, client=client, timeout_seconds=5)
                for source in tuple(ALLOWED_NEWS_SOURCES.values())[:4]
            ),
            repository=_Repository(),
        )
        result = await service.collect(
            ContractSymbol.BTCUSDT, since=NOW - timedelta(days=7), until=NOW
        )
    assert _policy_source_coverage(result) == "partial"


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_unknown_normalizer_error_is_source_failure_and_cancellation_propagates(
    monkeypatch: pytest.MonkeyPatch, cancelled: bool
) -> None:
    # 已知条目拒绝之外的异常必须在整源边界处理；取消不能写仓储或生成成功诊断。
    import app.news.rss as rss

    def broken(*args: object, **kwargs: object) -> NewsItemDraft:
        if cancelled:
            raise asyncio.CancelledError()
        raise RuntimeError("UNTRUSTED https://unsafe.invalid/")

    monkeypatch.setattr(rss, "normalize_news_item", broken)

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, stream=_Stream(f"<rss><channel>{_entry()}</channel></rss>".encode())
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = NewsIngestionService(
            sources=(
                RssNewsSourceAdapter(
                    source=ALLOWED_NEWS_SOURCES["coindesk"], client=client, timeout_seconds=5
                ),
            ),
            repository=_Repository(),
        )
        if cancelled:
            with pytest.raises(asyncio.CancelledError):
                await service.collect(
                    ContractSymbol.BTCUSDT, since=NOW - timedelta(days=7), until=NOW
                )
        else:
            result = await service.collect(
                ContractSymbol.BTCUSDT, since=NOW - timedelta(days=7), until=NOW
            )
            assert result.source_diagnostics[0].outcome == "failed"
            assert result.failed_source_count == 1
            assert "UNTRUSTED" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_budgeted_old_samples_do_not_claim_the_entire_feed_has_no_recent_news() -> None:
    # 前二十条过期而第二十一条近期：预算只保留旧样本，必须限定说明范围。
    payload = (
        "<rss><channel>"
        + _entry(published="2026-10-01T10:00:00Z") * 20
        + _entry()
        + "</channel></rss>"
    ).encode()

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Stream(payload))

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = NewsIngestionService(
            sources=(
                RssNewsSourceAdapter(
                    source=ALLOWED_NEWS_SOURCES["coindesk"], client=client, timeout_seconds=5
                ),
            ),
            repository=_Repository(),
        )
        result = await service.collect(
            ContractSymbol.BTCUSDT, since=NOW - timedelta(days=7), until=NOW
        )
    assert result.source_diagnostics[0].recent_count == 0
    assert result.source_diagnostics[0].omitted_count == 1
    assert result.source_diagnostics[0].outcome == "partial"
    limits = " ".join(_limitations(result, (), market=None))
    assert "本次保留的英文新闻条目在时间窗内无内容" in limits
    assert "不能据此认定连接失败或整个来源无近期内容" in limits
    assert "英文新闻来源在本次时间窗内无内容" not in limits
