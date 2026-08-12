from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.market.contracts import ContractSymbol
from app.news.contracts import COINDESK_SOURCE, SEC_PRESS_RELEASES_SOURCE, NewsSourceDefinition
from app.news.rss import RssNewsSourceAdapter

FIXTURES = Path(__file__).parents[1] / "fixtures" / "news"
FETCHED_AT = datetime(2026, 8, 10, 9, tzinfo=UTC)


class _TrackedAsyncByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.chunks_read = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.chunks_read += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_rss_adapter_parses_only_registered_coindesk_feed_from_fixture() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            stream=_TrackedAsyncByteStream(((FIXTURES / "coindesk.xml").read_bytes(),)),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RssNewsSourceAdapter(source=COINDESK_SOURCE, client=client, timeout_seconds=8)
        assert adapter.source is COINDESK_SOURCE
        items = await adapter.fetch_items(fetched_at=FETCHED_AT)

    assert len(requests) == 1
    assert str(requests[0].url) == str(COINDESK_SOURCE.feed_url)
    assert (
        requests[0].headers["accept"]
        == "application/atom+xml, application/rss+xml, application/xml"
    )
    assert requests[0].headers["accept-encoding"] == "identity"
    assert len(items) == 1
    assert items[0].source_id == "coindesk"
    assert items[0].related_symbols == (ContractSymbol.BTCUSDT,)
    assert "<" not in items[0].summary


@pytest.mark.asyncio
async def test_rss_adapter_parses_sec_atom_fixture_and_rejects_unknown_source() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=_TrackedAsyncByteStream(((FIXTURES / "sec_press_releases.xml").read_bytes(),)),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RssNewsSourceAdapter(
            source=SEC_PRESS_RELEASES_SOURCE,
            client=client,
            timeout_seconds=8,
        )
        items = await adapter.fetch_items(fetched_at=FETCHED_AT)

    assert len(items) == 1
    assert items[0].related_symbols == (ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT)

    unknown = NewsSourceDefinition.model_construct(
        source_id="unknown",
        source_name="Unknown",
        tier="primary",
        feed_url="https://example.com/rss",
        max_items_per_run=1,
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="未获准的新闻来源"):
            RssNewsSourceAdapter(source=unknown, client=client, timeout_seconds=8)


@pytest.mark.asyncio
async def test_rss_adapter_rejects_oversized_response_without_article_fetch() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=_TrackedAsyncByteStream((b"x" * (RssNewsSourceAdapter.MAX_RESPONSE_BYTES + 1),)),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RssNewsSourceAdapter(source=COINDESK_SOURCE, client=client, timeout_seconds=8)
        with pytest.raises(ValueError, match="新闻响应超过大小限制"):
            await adapter.fetch_items(fetched_at=FETCHED_AT)


@pytest.mark.asyncio
async def test_rss_adapter_stops_streaming_as_soon_as_response_exceeds_limit() -> None:
    stream = _TrackedAsyncByteStream(
        (
            b"x" * RssNewsSourceAdapter.MAX_RESPONSE_BYTES,
            b"y",
            b"must-not-be-read",
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RssNewsSourceAdapter(source=COINDESK_SOURCE, client=client, timeout_seconds=8)
        with pytest.raises(ValueError, match="新闻响应超过大小限制"):
            await adapter.fetch_items(fetched_at=FETCHED_AT)

    assert stream.chunks_read == 2
    assert stream.closed is True


@pytest.mark.asyncio
async def test_rss_adapter_rejects_compressed_response_before_reading_body() -> None:
    stream = _TrackedAsyncByteStream((b"compressed-response",))

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RssNewsSourceAdapter(source=COINDESK_SOURCE, client=client, timeout_seconds=8)
        with pytest.raises(ValueError, match="新闻响应不允许压缩编码"):
            await adapter.fetch_items(fetched_at=FETCHED_AT)

    assert stream.chunks_read == 0
    assert stream.closed is True


@pytest.mark.asyncio
async def test_rss_adapter_does_not_follow_redirects_from_registered_feed() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.host == "www.coindesk.com":
            return httpx.Response(302, headers={"Location": "https://unregistered.example/feed"})
        return httpx.Response(200, content=(FIXTURES / "coindesk.xml").read_bytes())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        adapter = RssNewsSourceAdapter(source=COINDESK_SOURCE, client=client, timeout_seconds=8)
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.fetch_items(fetched_at=FETCHED_AT)

    assert requested_urls == [str(COINDESK_SOURCE.feed_url)]


@pytest.mark.asyncio
async def test_rss_adapter_rejects_naive_fetched_at_before_fetching() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=(FIXTURES / "coindesk.xml").read_bytes())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RssNewsSourceAdapter(source=COINDESK_SOURCE, client=client, timeout_seconds=8)
        with pytest.raises(ValueError, match="新闻抓取时间必须带时区"):
            await adapter.fetch_items(fetched_at=datetime(2026, 8, 10, 9))

    assert requests == []
