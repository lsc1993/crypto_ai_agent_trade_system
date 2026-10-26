# 验证新闻采集的来源准入、限量、去重与研究运行状态契约。
# 替身隔离各来源故障，区分官方公告不足与媒体成功，取消信号不能被吞掉。
# 状态只接受安全标识、计数及错误码，不能装入原始新闻或模型载荷。
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
from app.symbols.contracts import ResearchSymbolEntry

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)
ANALYSIS_ID = UUID("00000000-0000-0000-0000-000000000601")
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000602")
EVIDENCE_ID = UUID("00000000-0000-0000-0000-000000000603")


# 获准来源替身记录读取时刻，既可返回条目，也可抛普通失败或取消以区分两类语义。
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


# 记录进入仓储的候选，再按去重键保留首条，分别检查应用过滤和仓储去重边界。
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


# 只提供活动研究目录读取，断言调用没有扩大为归档条目范围。
class StubResearchSymbolDirectory:
    def __init__(self, entries: tuple[ResearchSymbolEntry, ...]) -> None:
        self.entries = entries

    async def list(self, *, include_archived: bool = False) -> tuple[ResearchSymbolEntry, ...]:
        assert not include_archived
        return self.entries


@pytest.mark.asyncio
async def test_news_tracks_official_source_failure_separately_from_media_success() -> None:
    service = NewsIngestionService(
        sources=(
            StubNewsSource(),
            StubNewsSource(error=TimeoutError(), source=SEC_PRESS_RELEASES_SOURCE),
        ),
        repository=RecordingNewsRepository(),
    )
    result = await service.collect(ContractSymbol.BTCUSDT, since=NOW - timedelta(days=7), until=NOW)
    assert result.successful_source_ids == ("coindesk",)
    assert result.failed_source_ids == ("sec_press_releases",)


# 混入错标的、过期和重复条目，仓储只收到时间窗与币种过滤后的候选。
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
        successful_source_ids=("coindesk", "sec_press_releases"),
    )
    assert repository.ingested == [(duplicate, sec_duplicate)]
    assert [source.fetch_times for source in sources] == [[NOW], [NOW]]


@pytest.mark.asyncio
async def test_news_collection_applies_registered_symbol_aliases() -> None:
    item = _news_item(key="sol", published_at=NOW - timedelta(hours=1)).model_copy(
        update={"title": "Solana protocol update", "summary": "SOL ecosystem market context."}
    )
    solana = ResearchSymbolEntry(
        symbol="SOLUSDT",
        base_asset="SOL",
        quote_asset="USDT",
        margin_asset="USDT",
        contract_type="PERPETUAL",
        enabled=True,
        keywords=("Solana",),
        version=1,
        created_at=NOW,
        can_research=True,
    )
    repository = RecordingNewsRepository()
    service = NewsIngestionService(
        sources=(StubNewsSource((item,)),),
        repository=repository,
        symbol_repository=StubResearchSymbolDirectory((solana,)),
    )

    result = await service.collect("SOLUSDT", since=NOW - timedelta(days=1), until=NOW)

    assert result.items[0].related_symbols == (ContractSymbol.BTCUSDT, "SOLUSDT")
    assert repository.ingested[0][0].related_symbols == (ContractSymbol.BTCUSDT, "SOLUSDT")


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
        failed_source_ids=("coindesk", "sec_press_releases"),
    )
    assert repository.ingested == []


# 构造后修改适配器的来源声明，返回条目仍需按注入时冻结定义核验。
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
    # 服务已冻结原来源，后续改动不能让适配器冒充另一个合法来源。
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


# 取消不能降级为某个新闻来源故障，否则关闭请求会继续运行或写库。
@pytest.mark.asyncio
async def test_news_collection_propagates_cancellation() -> None:
    repository = RecordingNewsRepository()
    service = NewsIngestionService(
        sources=(StubNewsSource(error=asyncio.CancelledError()),),
        repository=repository,
    )

    # 取消需要原样传播给请求生命周期，不能并入普通来源失败统计。
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


# 构造服务后追加来源，测试运行范围仍保持原来注入的序列。
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


# 图状态仅保存关联标识与计数，额外载荷字段必须在契约入口拒绝。
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
