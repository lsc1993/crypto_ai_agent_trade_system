# 订阅源适配：只读取登记地址，限制响应字节且禁用重定向与压缩，安全解析条目元数据并规范化；
# 不读取正文页面。
# 研究新闻领域：登记的英文订阅源经规范化、归因和去重后成为证据；外部文本不具备执行权限。
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Final
from xml.etree.ElementTree import Element

import httpx
from defusedxml import ElementTree
from pydantic import ValidationError

from app.news.contracts import (
    ALLOWED_NEWS_SOURCES,
    ExternalNewsItem,
    NewsFetchResult,
    NewsItemDraft,
    NewsItemRejectedError,
    NewsRejectionCode,
    NewsRejectionCount,
    NewsSourceDefinition,
    parse_http_url,
)
from app.news.normalization import normalize_news_item

_ACCEPT_HEADER: Final = "application/atom+xml, application/rss+xml, application/xml"


# RssNewsSourceAdapter 汇集本模块的结构化数据，主要字段为 MAX_RESPONSE_BYTES。
class RssNewsSourceAdapter:
    MAX_RESPONSE_BYTES: Final = 512 * 1024

    # 初始化本实例依赖和配置；输入 source、client、timeout_seconds。
    def __init__(
        self,
        *,
        source: NewsSourceDefinition,
        client: httpx.AsyncClient,
        timeout_seconds: int,
    ) -> None:
        if ALLOWED_NEWS_SOURCES.get(source.source_id) != source:
            raise ValueError("未获准的新闻来源")
        self._source = source
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)

    # 提供适配器声明的来源定义，供采集服务与固定白名单核对。
    @property
    def source(self) -> NewsSourceDefinition:
        return self._source

    # 从登记的订阅源读取有界响应，解析条目并规范化为新闻草稿；最多返回来源限定数量。
    async def fetch_items(self, *, fetched_at: datetime) -> tuple[NewsItemDraft, ...]:
        # 保留已有适配器协议；生产协调器使用 fetch_result 取得同一次请求的局部诊断。
        return (await self.fetch_result(fetched_at=fetched_at)).items

    # 读取一次有界订阅并返回不可变结果；不保存实例计数，因此并发研究互不污染。
    async def fetch_result(self, *, fetched_at: datetime) -> NewsFetchResult:
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("新闻抓取时间必须带时区")
        normalized_fetched_at = fetched_at.astimezone(UTC)

        payload = bytearray()
        async with self._client.stream(
            "GET",
            str(self._source.feed_url),
            headers={"Accept": _ACCEPT_HEADER, "Accept-Encoding": "identity"},
            timeout=self._timeout,
            # 禁止跟随重定向，避免固定登记订阅源被替换为其他地址。
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            content_encoding = response.headers.get("Content-Encoding")
            if content_encoding is not None and content_encoding.strip().casefold() != "identity":
                raise ValueError("新闻响应不允许压缩编码")
            async for chunk in response.aiter_raw():
                if len(payload) + len(chunk) > self.MAX_RESPONSE_BYTES:
                    raise ValueError("新闻响应超过大小限制")
                payload.extend(chunk)

        # 使用安全 XML 解析器处理不可信订阅内容；标题和摘要进入后续规范化，而非直接作为可信指令。
        root = ElementTree.fromstring(payload)
        return self._parse_items(root, fetched_at=normalized_fetched_at)

    # 遍历订阅条目，仅接纳标题、摘要、链接与时间齐全的元数据。
    def _parse_items(self, root: Element, *, fetched_at: datetime) -> NewsFetchResult:
        entries = tuple(
            element for element in root.iter() if _local_name(element.tag) in {"item", "entry"}
        )
        parsed: list[NewsItemDraft] = []
        rejections: Counter[NewsRejectionCode] = Counter()
        omitted_count = 0
        for entry in entries:
            title = _child_text(entry, "title")
            summary = _child_text(entry, "description") or _child_text(entry, "summary")
            link = _child_url(entry)
            published = (
                _child_text(entry, "pubDate")
                or _child_text(entry, "published")
                or _child_text(entry, "updated")
            )
            if not title or not summary or not link or not published:
                rejections["missing_metadata"] += 1
                continue
            # 只捕获对应输入解析器的已知错误，不用宽泛 ValueError 隔离整段规范化逻辑。
            try:
                url = parse_http_url(link)
            except ValidationError:
                rejections["invalid_url"] += 1
                continue
            try:
                published_at = _parse_published_at(published)
            except (ValueError, OverflowError):
                rejections["invalid_published_at"] += 1
                continue
            try:
                external = ExternalNewsItem(
                    source_item_id=_child_text(entry, "guid") or _child_text(entry, "id"),
                    title=title,
                    summary=summary,
                    url=url,
                    published_at=published_at,
                )
            except ValidationError:
                rejections["invalid_metadata"] += 1
                continue
            try:
                item = normalize_news_item(external, source=self._source, fetched_at=fetched_at)
            except NewsItemRejectedError as error:
                rejections[error.code] += 1
                continue
            except ValidationError:
                rejections["invalid_metadata"] += 1
                continue
            if len(parsed) < self._source.max_items_per_run:
                parsed.append(item)
            else:
                omitted_count += 1
        return NewsFetchResult(
            items=tuple(parsed),
            entry_count=len(entries),
            rejections=tuple(
                NewsRejectionCount(code=code, count=count)
                for code, count in sorted(rejections.items())
            ),
            omitted_count=omitted_count,
        )


# 去除 XML 标签命名空间，兼容不同订阅格式的同名字段。
def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


# 查找指定直接子元素，清理安全文本后返回；空内容返回空值。
def _child_text(element: Element, name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == name:
            value = _safe_element_text(child).strip()
            return value or None
    return None


# 递归收集正文文本和尾部文字，跳过脚本与样式节点内容。
def _safe_element_text(element: Element) -> str:
    parts = [element.text or ""]
    for child in element:
        if _local_name(child.tag).casefold() not in {"script", "style"}:
            parts.append(_safe_element_text(child))
        else:
            parts.append(" ")
        parts.append(child.tail or "")
    return "".join(parts)


# 读取链接元素的地址属性或文本，空链接返回空值。
def _child_url(element: Element) -> str | None:
    for child in element:
        if _local_name(child.tag) == "link":
            value = child.attrib.get("href") or "".join(child.itertext()).strip()
            return value or None
    return None


# 兼容邮件日期和标准时间格式，拒绝无时区发布时间并统一转成 UTC。
def _parse_published_at(value: str) -> datetime:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("新闻发布时间必须带时区")
    return parsed.astimezone(UTC)
