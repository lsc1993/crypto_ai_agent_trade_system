# 去重保存受治理新闻元数据并维护研究币种关联。
# 输入先取每个去重键的首项，数据库冲突不覆写旧新闻，再读取实际记录返回。
# 新增关联不等于改写新闻快照；这里只保存标题摘要，不抓取正文或解释外部指令。
from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.news import NewsItemRecord
from app.infrastructure.persistence.models.symbols import ResearchNewsLinkRecord
from app.news.contracts import (
    NewsEventCategory,
    NewsItemDraft,
    NewsSourceTier,
    parse_http_url,
)


# SqlAlchemyNewsRepository 将已校验领域契约连接到异步会话；数据库操作范围由各方法决定。
class SqlAlchemyNewsRepository:
    """追加保存去重后的受治理新闻，并返回数据库中的不可变快照。"""

    # 仅保存注入的会话工厂供后续操作使用；构造实例时不连接数据库或开启事务。
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # 以去重键保留首个输入，忽略数据库新闻冲突并追加关联；返回数据库实际保存的新闻。
    async def ingest_many(self, items: tuple[NewsItemDraft, ...]) -> tuple[NewsItemDraft, ...]:
        unique_items = _first_items_by_key(items)
        if not unique_items:
            return ()
        keys = tuple(unique_items)
        statement = insert(NewsItemRecord).values(
            [_to_values(item) for item in unique_items.values()]
        )
        statement = statement.on_conflict_do_nothing(
            constraint="uq_news_items_deduplication_key"
        )
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(statement)
                records = tuple(
                    (
                        await session.execute(
                            select(NewsItemRecord).where(
                                NewsItemRecord.deduplication_key.in_(keys)
                            )
                        )
                    ).scalars()
                )
                # 冲突忽略后必须读取实际落库记录，使后续关联引用旧新闻的真实 UUID，而非新候选 ID。
                records_by_key = {record.deduplication_key: record for record in records}
                links = [
                    {
                        "news_id": records_by_key[key].id,
                        "symbol": symbol,
                        "scope": _link_scope(unique_items[key]),
                        "created_at": unique_items[key].fetched_at,
                    }
                    for key in keys
                    for symbol in unique_items[key].related_symbols
                ]
                if links:
                    await session.execute(
                        insert(ResearchNewsLinkRecord)
                        .values(links)
                        .on_conflict_do_nothing()
                    )
                links_by_news_id = _links_by_news_id(
                    tuple(
                        (
                            await session.execute(
                                select(ResearchNewsLinkRecord).where(
                                    ResearchNewsLinkRecord.news_id.in_(
                                        tuple(record.id for record in records)
                                    )
                                )
                            )
                        ).scalars()
                    )
                )
        records_by_key = {record.deduplication_key: record for record in records}
        return tuple(
            _to_draft(
                records_by_key[key],
                links_by_news_id.get(records_by_key[key].id, ()),
            )
            for key in keys
        )


def _first_items_by_key(items: tuple[NewsItemDraft, ...]) -> dict[str, NewsItemDraft]:
    unique: dict[str, NewsItemDraft] = {}
    for item in items:
        unique.setdefault(item.deduplication_key, item)
    return unique


# 按下面的显式字段映射还原 dict[str, object]，保留可选值与已有顺序；不重新执行业务计算。
def _to_values(item: NewsItemDraft) -> dict[str, object]:
    return {
        "id": uuid4(),
        "deduplication_key": item.deduplication_key,
        "source_id": item.source_id,
        "source_tier": item.source_tier.value,
        "source_item_id": item.source_item_id,
        "canonical_url": None if item.canonical_url is None else str(item.canonical_url),
        "published_at": item.published_at,
        "fetched_at": item.fetched_at,
        "language": item.language,
        "title": item.title,
        "summary": item.summary,
        "related_symbols": list(item.related_symbols),
        "event_category": item.event_category.value,
        "content_hash": item.content_hash,
    }


# 按下面的显式字段映射还原 NewsItemDraft，保留可选值与已有顺序；不重新执行业务计算。
def _to_draft(record: NewsItemRecord, linked_symbols: tuple[str, ...] = ()) -> NewsItemDraft:
    return NewsItemDraft(
        source_id=record.source_id,
        source_tier=NewsSourceTier(record.source_tier),
        source_item_id=record.source_item_id,
        canonical_url=(
            None if record.canonical_url is None else parse_http_url(record.canonical_url)
        ),
        published_at=record.published_at,
        fetched_at=record.fetched_at,
        language="en",
        title=record.title,
        summary=record.summary,
        related_symbols=tuple(dict.fromkeys((*record.related_symbols, *linked_symbols))),
        event_category=NewsEventCategory(record.event_category),
        content_hash=record.content_hash,
        deduplication_key=record.deduplication_key,
    )


def _link_scope(item: NewsItemDraft) -> str:
    return "market_context" if item.event_category in {
        NewsEventCategory.MACRO,
        NewsEventCategory.REGULATION,
    } else "asset"


def _links_by_news_id(
    links: tuple[ResearchNewsLinkRecord, ...],
) -> dict[UUID, tuple[str, ...]]:
    grouped: dict[UUID, list[str]] = {}
    for link in links:
        grouped.setdefault(link.news_id, []).append(link.symbol)
    return {news_id: tuple(symbols) for news_id, symbols in grouped.items()}
