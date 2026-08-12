from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.market.contracts import ContractSymbol
from app.news.contracts import ALLOWED_NEWS_SOURCES, NewsItemDraft, NewsSourceDefinition


class NewsSourceAdapter(Protocol):
    @property
    def source(self) -> NewsSourceDefinition: ...

    async def fetch_items(self, *, fetched_at: datetime) -> tuple[NewsItemDraft, ...]: ...


class NewsRepository(Protocol):
    async def ingest_many(
        self,
        items: tuple[NewsItemDraft, ...],
    ) -> tuple[NewsItemDraft, ...]: ...


class NewsCollection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[NewsItemDraft, ...]
    source_count: int = Field(ge=0, le=30)
    successful_source_count: int = Field(ge=0, le=30)
    failed_source_count: int = Field(ge=0, le=30)
    error_codes: tuple[Literal["news_source_failed"], ...] = Field(max_length=30)

    @field_validator("error_codes", mode="before")
    @classmethod
    def require_safe_error_codes(cls, value: object) -> object:
        if not isinstance(value, (tuple, list)):
            raise ValueError("新闻采集结果只能包含最小安全错误码")
        values = cast(tuple[object, ...] | list[object], value)
        if any(
            item != "news_source_failed"
            for item in values
        ):
            raise ValueError("新闻采集结果只能包含最小安全错误码")
        return values

    @model_validator(mode="after")
    def require_consistent_counts(self) -> NewsCollection:
        if self.successful_source_count + self.failed_source_count != self.source_count:
            raise ValueError("新闻来源计数不一致")
        if len(self.error_codes) != self.failed_source_count:
            raise ValueError("新闻错误码数量与失败来源数量不一致")
        return self


class NewsIngestionService:
    """Collect only from the bounded, pre-approved RSS adapters supplied at startup."""

    def __init__(
        self,
        *,
        sources: Iterable[NewsSourceAdapter],
        repository: NewsRepository,
    ) -> None:
        bounded_sources = tuple(sources)
        if not bounded_sources:
            raise ValueError("至少需要一个获准新闻来源")
        if len(bounded_sources) > 30:
            raise ValueError("新闻来源数量不能超过 30")
        source_ids: list[str] = []
        for adapter in bounded_sources:
            try:
                definition = cast(object, adapter.source)
            except AttributeError as error:
                raise ValueError("新闻来源必须声明获准来源") from error
            if (
                not isinstance(definition, NewsSourceDefinition)
                or ALLOWED_NEWS_SOURCES.get(definition.source_id) != definition
            ):
                raise ValueError("未获准的新闻来源")
            source_ids.append(definition.source_id)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("新闻来源不能重复")
        self._sources = bounded_sources
        self._repository = repository

    async def collect(
        self,
        symbol: ContractSymbol,
        *,
        since: datetime,
        until: datetime,
    ) -> NewsCollection:
        normalized_since = _require_utc(since)
        normalized_until = _require_utc(until)
        if normalized_since > normalized_until:
            raise ValueError("新闻采集开始时间不能晚于结束时间")

        results = await asyncio.gather(
            *(
                source.fetch_items(fetched_at=normalized_until)
                for source in self._sources
            ),
            return_exceptions=True,
        )
        successful = tuple(result for result in results if not isinstance(result, BaseException))
        failed_count = len(results) - len(successful)
        candidates = tuple(
            item
            for items in successful
            for item in items
            if normalized_since <= item.published_at <= normalized_until
            and symbol in item.related_symbols
        )
        persisted = await self._repository.ingest_many(candidates) if candidates else ()
        return NewsCollection(
            items=persisted,
            source_count=len(self._sources),
            successful_source_count=len(successful),
            failed_source_count=failed_count,
            error_codes=("news_source_failed",) * failed_count,
        )


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("新闻采集窗口必须是 UTC 且带时区")
    return value.astimezone(UTC)
