from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.market.contracts import ContractSymbol
from app.news.contracts import COINDESK_SOURCE, SEC_PRESS_RELEASES_SOURCE, NewsSourceDefinition
from app.news.rss import RssNewsSourceAdapter

FIXTURES = Path(__file__).parents[1] / "fixtures" / "news"
FETCHED_AT = datetime(2026, 8, 10, 9, tzinfo=UTC)


@pytest.mark.asyncio
async def test_rss_adapter_parses_only_registered_coindesk_feed_from_fixture() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=(FIXTURES / "coindesk.xml").read_bytes())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RssNewsSourceAdapter(source=COINDESK_SOURCE, client=client, timeout_seconds=8)
        items = await adapter.fetch_items(fetched_at=FETCHED_AT)

    assert len(requests) == 1
    assert str(requests[0].url) == str(COINDESK_SOURCE.feed_url)
    assert (
        requests[0].headers["accept"]
        == "application/atom+xml, application/rss+xml, application/xml"
    )
    assert len(items) == 1
    assert items[0].source_id == "coindesk"
    assert items[0].related_symbols == (ContractSymbol.BTCUSDT,)
    assert "<" not in items[0].summary


@pytest.mark.asyncio
async def test_rss_adapter_parses_sec_atom_fixture_and_rejects_unknown_source() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=(FIXTURES / "sec_press_releases.xml").read_bytes())

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
        return httpx.Response(200, content=b"x" * (RssNewsSourceAdapter.MAX_RESPONSE_BYTES + 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RssNewsSourceAdapter(source=COINDESK_SOURCE, client=client, timeout_seconds=8)
        with pytest.raises(ValueError, match="新闻响应超过大小限制"):
            await adapter.fetch_items(fetched_at=FETCHED_AT)
