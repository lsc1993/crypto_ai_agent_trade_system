"""白名单 RSS 新闻采集服务。

数据流：启动时注入的获准适配器 → 并发抓取和按来源隔离失败 → 去重后的仓储写入 →
包含成功/失败计数与最小错误码的 NewsCollection。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, TypeGuard, cast

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


@dataclass(frozen=True)
class _ApprovedSourceAdapter:
    adapter: NewsSourceAdapter
    source: NewsSourceDefinition


class NewsCollection(BaseModel):
    """一次新闻收集的项目、来源覆盖计数和不含上游细节的安全错误码。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[NewsItemDraft, ...]
    source_count: int = Field(ge=0, le=30)
    successful_source_count: int = Field(ge=0, le=30)
    failed_source_count: int = Field(ge=0, le=30)
    error_codes: tuple[Literal["news_source_failed"], ...] = Field(max_length=30)
    successful_source_ids: tuple[str, ...] = Field(default=(), max_length=30)
    failed_source_ids: tuple[str, ...] = Field(default=(), max_length=30)

    @field_validator("error_codes", mode="before")
    @classmethod
    def require_safe_error_codes(cls, value: object) -> object:
        if not isinstance(value, (tuple, list)):
            raise ValueError("新闻采集结果只能包含最小安全错误码")
        values = cast(tuple[object, ...] | list[object], value)
        if any(item != "news_source_failed" for item in values):
            raise ValueError("新闻采集结果只能包含最小安全错误码")
        return values

    @model_validator(mode="after")
    def require_consistent_counts(self) -> NewsCollection:
        if self.successful_source_count + self.failed_source_count != self.source_count:
            raise ValueError("新闻来源计数不一致")
        if len(self.error_codes) != self.failed_source_count:
            raise ValueError("新闻错误码数量与失败来源数量不一致")
        ids = (*self.successful_source_ids, *self.failed_source_ids)
        if ids and (
            len(set(ids)) != len(ids)
            or any(source not in ALLOWED_NEWS_SOURCES for source in ids)
            or len(self.successful_source_ids) != self.successful_source_count
            or len(self.failed_source_ids) != self.failed_source_count
        ):
            raise ValueError("新闻来源明细与覆盖计数不一致")
        return self


class NewsIngestionService:
    """只从启动时注入、且经白名单批准的 RSS 适配器收集新闻。"""

    def __init__(
        self,
        *,
        sources: Iterable[NewsSourceAdapter],
        repository: NewsRepository,
    ) -> None:
        """验证所有适配器与静态来源白名单匹配，并冻结其运行时顺序。"""
        bounded_sources = tuple(sources)
        if not bounded_sources:
            raise ValueError("至少需要一个获准新闻来源")
        if len(bounded_sources) > 30:
            raise ValueError("新闻来源数量不能超过 30")
        # 适配器自报的来源定义必须与静态白名单完全一致，避免运行时替换为未知来源。
        approved_sources: list[_ApprovedSourceAdapter] = []
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
            approved_sources.append(_ApprovedSourceAdapter(adapter=adapter, source=definition))
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("新闻来源不能重复")
        self._sources = tuple(approved_sources)
        self._repository = repository

    async def collect(
        self,
        symbol: ContractSymbol,
        *,
        since: datetime,
        until: datetime,
    ) -> NewsCollection:
        """在指定 UTC 时间窗内收集新闻并按来源隔离异常。

        单一 RSS 来源失败不会中断其余来源；错误详情不进入返回值，调用方只会看到
        受控错误码和来源覆盖计数。
        """
        normalized_since = _require_utc(since)
        normalized_until = _require_utc(until)
        if normalized_since > normalized_until:
            raise ValueError("新闻采集开始时间不能晚于结束时间")

        results = await asyncio.gather(
            *(source.adapter.fetch_items(fetched_at=normalized_until) for source in self._sources),
            return_exceptions=True,
        )
        successful: list[tuple[NewsItemDraft, ...]] = []
        success_ids: list[str] = []
        failure_ids: list[str] = []
        failed_count = 0
        for source, result in zip(self._sources, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException) or not _has_expected_attribution(
                result,
                source.source,
            ):
                failed_count += 1
                failure_ids.append(source.source.source_id)
                continue
            successful.append(result)
            success_ids.append(source.source.source_id)
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
            successful_source_ids=tuple(success_ids),
            failed_source_ids=tuple(failure_ids),
        )


def _require_utc(value: datetime) -> datetime:
    """验证并标准化新闻窗口边界为 UTC，确保跨来源时间过滤可比较。"""
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("新闻采集窗口必须是 UTC 且带时区")
    return value.astimezone(UTC)


def _has_expected_attribution(
    value: object,
    source: NewsSourceDefinition,
) -> TypeGuard[tuple[NewsItemDraft, ...]]:
    """确认适配器返回的每条新闻都归属于其声明的获准来源。"""
    if not isinstance(value, tuple):
        return False
    values = cast(tuple[object, ...], value)
    return all(
        isinstance(item, NewsItemDraft)
        and item.source_id == source.source_id
        and item.source_tier is source.tier
        for item in values
    )
