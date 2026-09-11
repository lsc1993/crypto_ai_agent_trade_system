from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.news import NewsItemRecord
from app.infrastructure.persistence.models.symbols import (
    ResearchNewsLinkRecord,
    ResearchSymbolRecord,
)
from app.infrastructure.persistence.news_repository import SqlAlchemyNewsRepository
from app.market.contracts import ContractSymbol
from app.news.contracts import (
    NewsEventCategory,
    NewsItemDraft,
    NewsSourceTier,
    parse_http_url,
)

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)


class MigratedDatabase(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


@pytest.mark.asyncio
async def test_ingest_many_keeps_the_first_immutable_news_snapshot_on_conflict(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyNewsRepository(migrated_database.session_factory)
    original = _news_item(title="Original governed headline")
    changed = original.model_copy(update={"title": "Changed headline must not overwrite"})

    first = await repository.ingest_many((original,))
    second = await repository.ingest_many((changed, original))

    assert first == (original,)
    assert second == (original,)
    async with migrated_database.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(NewsItemRecord))
        assert count == 1


@pytest.mark.asyncio
async def test_database_rejects_news_snapshot_update_and_delete(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyNewsRepository(migrated_database.session_factory)
    await repository.ingest_many((_news_item(),))

    async with migrated_database.session_factory() as session:
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(update(NewsItemRecord).values(title="changed"))
            await session.commit()
        await session.rollback()

        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(delete(NewsItemRecord))
            await session.commit()


@pytest.mark.asyncio
async def test_ingest_many_adds_research_symbol_links_without_mutating_news_history(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyNewsRepository(migrated_database.session_factory)
    original = _news_item()
    async with migrated_database.session_factory() as session:
        async with session.begin():
            session.add(
                ResearchSymbolRecord(
                    symbol="SOLUSDT",
                    base_asset="SOL",
                    quote_asset="USDT",
                    margin_asset="USDT",
                    contract_type="PERPETUAL",
                    enabled=True,
                    keywords=["SOL", "Solana"],
                    capabilities=[],
                    version=1,
                    created_at=NOW,
                )
            )

    await repository.ingest_many((original,))
    attributed = original.model_copy(
        update={"related_symbols": (ContractSymbol.BTCUSDT, "SOLUSDT")}
    )
    persisted = await repository.ingest_many((attributed,))

    assert persisted[0].title == original.title
    assert persisted[0].related_symbols == (ContractSymbol.BTCUSDT, "SOLUSDT")
    async with migrated_database.session_factory() as session:
        links = tuple((await session.scalars(select(ResearchNewsLinkRecord))).all())
    assert {(link.symbol, link.scope) for link in links} >= {
        ("BTCUSDT", "asset"),
        ("SOLUSDT", "asset"),
    }


def _news_item(*, title: str = "Governed headline") -> NewsItemDraft:
    return NewsItemDraft(
        source_id="coindesk",
        source_tier=NewsSourceTier.PROFESSIONAL_MEDIA,
        source_item_id="item-1",
        canonical_url=parse_http_url("https://www.coindesk.com/markets/item-1"),
        published_at=NOW,
        fetched_at=NOW,
        language="en",
        title=title,
        summary="A normalized English summary without raw feed markup.",
        related_symbols=(ContractSymbol.BTCUSDT,),
        event_category=NewsEventCategory.MARKET,
        content_hash="a" * 64,
        deduplication_key="coindesk:item-1",
    )
