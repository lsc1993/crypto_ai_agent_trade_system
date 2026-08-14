from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.agent.contracts import AgentErrorCode, AgentRunState
from app.market.contracts import ContractSymbol
from app.news.contracts import (
    COINDESK_SOURCE,
    SEC_PRESS_RELEASES_SOURCE,
    NewsEventCategory,
    NewsItemDraft,
    NewsSourceDefinition,
    NewsSourceTier,
    parse_http_url,
)
from app.news.service import NewsCollection, NewsIngestionService

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)
ANALYSIS_ID = UUID("00000000-0000-0000-0000-000000000601")
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000602")
EVIDENCE_ID = UUID("00000000-0000-0000-0000-000000000603")


class StubNewsSource:
    def __init__(
        self,
        items: tuple[NewsItemDraft, ...] = (),
        error: BaseException | None = None,
        *,
        source: NewsSourceDefinition = COINDESK_SOURCE,
    ) -> None:
        self.items = items
        self.error = error
        self.source = source
        self.fetch_times: list[datetime] = []

    async def fetch_items(self, *, fetched_at: datetime) -> tuple[NewsItemDraft, ...]:
        self.fetch_times.append(fetched_at)
        if self.error is not None:
            raise self.error
        return self.items


class RecordingNewsRepository:
    def __init__(self) -> None:
        self.ingested: list[tuple[NewsItemDraft, ...]] = []

    async def ingest_many(
        self,
        items: tuple[NewsItemDraft, ...],
    ) -> tuple[NewsItemDraft, ...]:
        self.ingested.append(items)
        unique: dict[str, NewsItemDraft] = {}
        for item in items:
            unique.setdefault(item.deduplication_key, item)
        return tuple(unique.values())


@pytest.mark.asyncio
async def test_news_collection_is_bounded_filtered_and_deduplicated() -> None:
    duplicate = _news_item(key="same", published_at=NOW - timedelta(hours=1))
    wrong_symbol = _news_item(
        key="eth",
        symbol=ContractSymbol.ETHUSDT,
        published_at=NOW - timedelta(hours=1),
    )
    too_old = _news_item(key="old", published_at=NOW - timedelta(days=4))
    repository = RecordingNewsRepository()
    sec_duplicate = _news_item(
        key="same",
        published_at=NOW - timedelta(hours=1),
        source=SEC_PRESS_RELEASES_SOURCE,
    )
    sources = (
        StubNewsSource((duplicate, wrong_symbol, too_old)),
        StubNewsSource((sec_duplicate,), source=SEC_PRESS_RELEASES_SOURCE),
    )
    service = NewsIngestionService(sources=sources, repository=repository)

    result = await service.collect(
        ContractSymbol.BTCUSDT,
        since=NOW - timedelta(days=3),
        until=NOW,
    )

    assert result == NewsCollection(
        items=(duplicate,),
        source_count=2,
        successful_source_count=2,
        failed_source_count=0,
        error_codes=(),
    )
    assert repository.ingested == [(duplicate, sec_duplicate)]
    assert [source.fetch_times for source in sources] == [[NOW], [NOW]]


@pytest.mark.asyncio
async def test_news_collection_isolates_a_source_failure() -> None:
    item = _news_item(
        key="ok",
        published_at=NOW - timedelta(hours=1),
        source=SEC_PRESS_RELEASES_SOURCE,
    )
    repository = RecordingNewsRepository()
    service = NewsIngestionService(
        sources=(
            StubNewsSource(error=RuntimeError("secret upstream detail")),
            StubNewsSource((item,), source=SEC_PRESS_RELEASES_SOURCE),
        ),
        repository=repository,
    )

    result = await service.collect(
        ContractSymbol.BTCUSDT,
        since=NOW - timedelta(days=3),
        until=NOW,
    )

    assert result.items == (item,)
    assert result.successful_source_count == 1
    assert result.failed_source_count == 1
    assert result.error_codes == ("news_source_failed",)


@pytest.mark.asyncio
async def test_news_collection_reports_all_source_failures_without_persisting() -> None:
    repository = RecordingNewsRepository()
    service = NewsIngestionService(
        sources=(
            StubNewsSource(error=RuntimeError("sensitive one")),
            StubNewsSource(
                error=ValueError("sensitive two"),
                source=SEC_PRESS_RELEASES_SOURCE,
            ),
        ),
        repository=repository,
    )

    result = await service.collect(
        ContractSymbol.BTCUSDT,
        since=NOW - timedelta(days=3),
        until=NOW,
    )

    assert result == NewsCollection(
        items=(),
        source_count=2,
        successful_source_count=0,
        failed_source_count=2,
        error_codes=("news_source_failed", "news_source_failed"),
    )
    assert repository.ingested == []


@pytest.mark.asyncio
async def test_news_collection_rejects_items_not_attributed_to_the_frozen_source() -> None:
    repository = RecordingNewsRepository()
    item = _news_item(key="wrong-source", published_at=NOW).model_copy(
        update={
            "source_id": "sec_press_releases",
            "source_tier": NewsSourceTier.PRIMARY,
        }
    )
    source = StubNewsSource((item,))
    service = NewsIngestionService(sources=(source,), repository=repository)
    source.source = SEC_PRESS_RELEASES_SOURCE

    result = await service.collect(
        ContractSymbol.BTCUSDT,
        since=NOW - timedelta(days=1),
        until=NOW,
    )

    assert result.items == ()
    assert result.failed_source_count == 1
    assert result.error_codes == ("news_source_failed",)
    assert repository.ingested == []


@pytest.mark.asyncio
async def test_news_collection_propagates_cancellation() -> None:
    repository = RecordingNewsRepository()
    service = NewsIngestionService(
        sources=(StubNewsSource(error=asyncio.CancelledError()),),
        repository=repository,
    )

    with pytest.raises(asyncio.CancelledError):
        await service.collect(
            ContractSymbol.BTCUSDT,
            since=NOW - timedelta(days=1),
            until=NOW,
        )


def test_news_ingestion_rejects_unapproved_or_duplicate_source_definitions() -> None:
    repository = RecordingNewsRepository()
    impostor = COINDESK_SOURCE.model_copy(update={"source_name": "Impostor"})

    with pytest.raises(ValueError, match="未获准"):
        NewsIngestionService(
            sources=(StubNewsSource(source=impostor),),
            repository=repository,
        )
    with pytest.raises(ValueError, match="重复"):
        NewsIngestionService(
            sources=(StubNewsSource(), StubNewsSource()),
            repository=repository,
        )


@pytest.mark.asyncio
async def test_news_ingestion_freezes_the_injected_source_sequence() -> None:
    repository = RecordingNewsRepository()
    sources = [StubNewsSource((_news_item(key="one", published_at=NOW),))]
    service = NewsIngestionService(sources=sources, repository=repository)
    sources.append(
        StubNewsSource(
            error=RuntimeError("must not be called"),
            source=SEC_PRESS_RELEASES_SOURCE,
        )
    )

    result = await service.collect(
        ContractSymbol.BTCUSDT,
        since=NOW - timedelta(days=1),
        until=NOW,
    )

    assert result.source_count == 1
    assert result.failed_source_count == 0


def test_agent_run_state_accepts_only_safe_identifiers_counts_and_error_codes() -> None:
    state = AgentRunState(
        analysis_id=ANALYSIS_ID,
        symbol=ContractSymbol.BTCUSDT,
        started_at=NOW,
        snapshot_id=SNAPSHOT_ID,
        evidence_ids=(EVIDENCE_ID,),
        news_source_count=2,
        news_success_count=1,
        news_failure_count=1,
        node_name="collect_news",
        error_codes=(AgentErrorCode.NEWS_SOURCE_FAILED,),
    )

    assert state.model_dump(mode="json") == {
        "analysis_id": str(ANALYSIS_ID),
        "symbol": "BTCUSDT",
        "started_at": "2026-08-10T12:00:00Z",
        "snapshot_id": str(SNAPSHOT_ID),
        "evidence_ids": [str(EVIDENCE_ID)],
        "news_source_count": 2,
        "news_success_count": 1,
        "news_failure_count": 1,
        "node_name": "collect_news",
        "error_codes": ["news_source_failed"],
    }


@pytest.mark.parametrize(
    "overrides",
    (
        {"source_count": 2, "successful_source_count": 1, "failed_source_count": 0},
        {
            "source_count": 1,
            "successful_source_count": 0,
            "failed_source_count": 1,
            "error_codes": ("api_key_supersecret",),
        },
    ),
)
def test_news_collection_rejects_inconsistent_counts_or_unsafe_errors(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "items": (),
        "source_count": 1,
        "successful_source_count": 1,
        "failed_source_count": 0,
        "error_codes": (),
        **overrides,
    }

    with pytest.raises(ValidationError):
        NewsCollection.model_validate(values)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("title", "Sensitive headline"),
        ("summary", "Sensitive summary"),
        ("prompt", "System prompt"),
        ("api_key", "test-key"),
        ("market_json", {"price": "68000"}),
        ("news_json", {"title": "Sensitive headline"}),
    ),
)
def test_agent_run_state_rejects_payload_fields(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentRunState.model_validate(
            {
                "analysis_id": ANALYSIS_ID,
                "symbol": ContractSymbol.BTCUSDT,
                "started_at": NOW,
                field: value,
            }
        )


@pytest.mark.parametrize(
    "error_code",
    ("contains secret", "UPPERCASE", "unsafe-url", "api_key_supersecret"),
)
def test_agent_run_state_rejects_unsafe_error_codes(error_code: str) -> None:
    with pytest.raises(ValidationError, match="安全错误码"):
        AgentRunState.model_validate(
            {
                "analysis_id": ANALYSIS_ID,
                "symbol": ContractSymbol.BTCUSDT,
                "started_at": NOW,
                "error_codes": (error_code,),
            }
        )


def _news_item(
    *,
    key: str,
    published_at: datetime,
    symbol: ContractSymbol = ContractSymbol.BTCUSDT,
    source: NewsSourceDefinition = COINDESK_SOURCE,
) -> NewsItemDraft:
    return NewsItemDraft(
        source_id=source.source_id,
        source_tier=source.tier,
        source_item_id=key,
        canonical_url=parse_http_url(f"https://example.com/markets/{key}"),
        published_at=published_at,
        fetched_at=NOW,
        language="en",
        title=f"Governed headline {key}",
        summary="A bounded public market report.",
        related_symbols=(symbol,),
        event_category=NewsEventCategory.MARKET,
        content_hash="a" * 64,
        deduplication_key=key,
    )
