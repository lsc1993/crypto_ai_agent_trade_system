# 新闻采集协调：并发读取批准来源、隔离失败，补充目录币种归因，过滤时间窗与标的后去重保存，
# 返回覆盖统计。
# 研究新闻领域：登记的英文订阅源经规范化、归因和去重后成为证据；外部文本不具备执行权限。
"""白名单 RSS 新闻采集服务。

数据流：启动时注入的获准适配器 → 并发抓取和按来源隔离失败 → 去重后的仓储写入 →
包含成功/失败计数与最小错误码的 NewsCollection。
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, TypeGuard, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.news.contracts import (
    ALLOWED_NEWS_SOURCES,
    NewsEventCategory,
    NewsItemDraft,
    NewsSourceDefinition,
)
from app.symbols.contracts import ResearchSymbolEntry


# NewsSourceAdapter 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class NewsSourceAdapter(Protocol):
    # 提供适配器声明的来源定义，供采集服务与固定白名单核对。
    @property
    def source(self) -> NewsSourceDefinition: ...

    # 从登记的订阅源读取有界响应，解析条目并规范化为新闻草稿；最多返回来源限定数量。
    async def fetch_items(self, *, fetched_at: datetime) -> tuple[NewsItemDraft, ...]: ...


# NewsRepository 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class NewsRepository(Protocol):
    # 将候选新闻交给仓储去重保存，返回已持久化的规范化条目。
    async def ingest_many(
        self,
        items: tuple[NewsItemDraft, ...],
    ) -> tuple[NewsItemDraft, ...]: ...


# ResearchSymbolDirectory 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class ResearchSymbolDirectory(Protocol):
    # 按筛选或归档选项读取领域记录集合/分页结果。
    async def list(self, *, include_archived: bool = False) -> tuple[ResearchSymbolEntry, ...]: ...


# 将已核验的适配器与获准来源绑定，供收集过程核对归因。
@dataclass(frozen=True)
class _ApprovedSourceAdapter:
    adapter: NewsSourceAdapter
    source: NewsSourceDefinition


# 一次新闻收集的项目、来源覆盖计数和不含上游细节的安全错误码。
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

    # 校验error_codes 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：新闻采集结果只能包含最小安全错误码。
    @field_validator("error_codes", mode="before")
    @classmethod
    def require_safe_error_codes(cls, value: object) -> object:
        if not isinstance(value, (tuple, list)):
            raise ValueError("新闻采集结果只能包含最小安全错误码")
        values = cast(tuple[object, ...] | list[object], value)
        if any(item != "news_source_failed" for item in values):
            raise ValueError("新闻采集结果只能包含最小安全错误码")
        return values

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：新闻来源计数不一致；新闻错误码数量与失败来源数量不一致；
    # 新闻来源明细与覆盖计数不一致。
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


# 只从启动时注入、且经白名单批准的 RSS 适配器收集新闻。
class NewsIngestionService:
    """只从启动时注入、且经白名单批准的 RSS 适配器收集新闻。"""

    # 验证所有适配器与静态来源白名单匹配，并冻结其运行时顺序。
    def __init__(
        self,
        *,
        sources: Iterable[NewsSourceAdapter],
        repository: NewsRepository,
        symbol_repository: ResearchSymbolDirectory | None = None,
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
        self._symbol_repository = symbol_repository

    # 在指定 UTC 时间窗内收集新闻并按来源隔离异常。
    async def collect(
        self,
        symbol: Any,
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
            # 取消属于任务生命周期信号，必须继续传播；不能当作某个来源失败后继续写入。
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
        attributed = await self._attribute_research_symbols(
            tuple(item for items in successful for item in items)
        )
        candidates = tuple(
            item
            for item in attributed
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

    # 依据已启用目录记录给新闻补充研究币种归因，无目录或条目时保持原输入。
    async def _attribute_research_symbols(
        self,
        items: tuple[NewsItemDraft, ...],
    ) -> tuple[NewsItemDraft, ...]:
        if self._symbol_repository is None or not items:
            return items
        # 只给已启用目录记录补充归因，归档币种不参与新的研究关联。
        entries = tuple(entry for entry in await self._symbol_repository.list() if entry.enabled)
        if not entries:
            return items
        return tuple(_with_research_symbols(item, entries) for item in items)


# 验证并标准化新闻窗口边界为 UTC，确保跨来源时间过滤可比较。
def _require_utc(value: datetime) -> datetime:
    """验证并标准化新闻窗口边界为 UTC，确保跨来源时间过滤可比较。"""
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("新闻采集窗口必须是 UTC 且带时区")
    return value.astimezone(UTC)


# 确认适配器返回的每条新闻都归属于其声明的获准来源。
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


_BROAD_POLICY_SOURCES = frozenset(
    {
        "federal_reserve_press_releases",
        "us_treasury_press_releases",
        "cftc_press_releases",
        "sec_press_releases",
    }
)


# 根据已启用目录的受限别名或官方宏观监管范围，补充去重后的研究币种关联。
def _with_research_symbols(
    item: NewsItemDraft,
    entries: tuple[ResearchSymbolEntry, ...],
) -> NewsItemDraft:
    """Add registered symbols only when a bounded alias or policy scope matches."""
    related = list(item.related_symbols)
    content = f"{item.title} {item.summary}".casefold()
    if item.source_id in _BROAD_POLICY_SOURCES and item.event_category in {
        NewsEventCategory.MACRO,
        NewsEventCategory.REGULATION,
    }:
        related.extend(entry.symbol for entry in entries)
    else:
        for entry in entries:
            aliases = (entry.base_asset, *entry.keywords)
            if any(_contains_alias(content, alias) for alias in aliases):
                related.append(entry.symbol)
    return item.model_copy(update={"related_symbols": tuple(dict.fromkeys(related))})


# 按不区分大小写且带词边界的字面别名匹配，避免短代码误命中更长单词。
def _contains_alias(content: str, alias: str) -> bool:
    normalized = alias.casefold()
    return bool(re.search(rf"(?<![\w]){re.escape(normalized)}(?![\w])", content))
