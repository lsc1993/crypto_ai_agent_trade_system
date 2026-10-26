# 新闻规范化：检查来源，清理标题摘要与跟踪参数，生成内容哈希、去重键及确定性类别；
# 文本仍是不可信证据。
# 研究新闻领域：登记的英文订阅源经规范化、归因和去重后成为证据；外部文本不具备执行权限。
"""不可信 RSS 文本的规范化与分类模块。

数据流：外部标题、摘要和 URL → 来源/语言/HTML/长度校验 → 稳定内容哈希与去重键 →
安全的 NewsItemDraft。此模块不执行网页内容，也不把原始 HTML 传入模型。
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AnyHttpUrl

from app.market.contracts import ContractSymbol
from app.market.symbols import ResearchSymbol
from app.news.contracts import (
    ALLOWED_NEWS_SOURCES,
    ExternalNewsItem,
    NewsEventCategory,
    NewsItemDraft,
    NewsSourceDefinition,
    parse_http_url,
)

_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_HTML_TAG = re.compile(r"<[^>]*>")
_WHITESPACE = re.compile(r"\s+")
_TRACKING_KEY = re.compile(r"^(utm_.+|fbclid)$", re.IGNORECASE)
_LATIN_WORD = re.compile(r"[a-z]+")
_ENGLISH_SIGNAL_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "with",
        "will",
        "after",
        "before",
        "during",
        "market",
        "update",
        "report",
        "reports",
        "context",
        "moves",
        "price",
        "prices",
        "rally",
        "falls",
        "rise",
        "drops",
        "demand",
        "policy",
        "sec",
        "digital",
        "asset",
        "enforcement",
        "action",
        "announces",
        "announced",
    }
)


# 将一个外部 RSS 项目规范化为可保存、可引用的英文新闻草稿。
def normalize_news_item(
    item: ExternalNewsItem,
    *,
    source: NewsSourceDefinition,
    fetched_at: datetime,
) -> NewsItemDraft:
    """将一个外部 RSS 项目规范化为可保存、可引用的英文新闻草稿。

    处理顺序先验证白名单来源和抓取时间，再清理文本、去除跟踪参数、计算哈希及
    分类；任一不可信输入不符合约束会被拒绝而不是静默修正。
    """
    # 规范化是进入持久化和模型上下文前的唯一入口；先检查来源再处理不可信 RSS 文本。
    approved_source = ALLOWED_NEWS_SOURCES.get(source.source_id)
    if approved_source != source:
        raise ValueError("未获准的新闻来源")
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("新闻抓取时间必须带时区")

    title = _normalize_text(item.title, maximum=300)
    summary = _normalize_text(item.summary, maximum=1_600)
    if not _is_english_text(f"{title} {summary}"):
        raise ValueError("仅支持英文新闻")

    canonical_url = _canonicalize_url(str(item.url)) if item.url is not None else None
    normalized_fetched_at = fetched_at.astimezone(UTC)
    content_hash = _sha256(
        "\x1f".join((source.source_id, title, summary, item.published_at.isoformat()))
    )
    deduplication_key = _deduplication_key(
        source_id=source.source_id,
        source_item_id=item.source_item_id,
        canonical_url=canonical_url,
        content_hash=content_hash,
    )
    return NewsItemDraft(
        source_id=source.source_id,
        source_tier=source.tier,
        source_item_id=item.source_item_id,
        canonical_url=canonical_url,
        published_at=item.published_at,
        fetched_at=normalized_fetched_at,
        language="en",
        title=title,
        summary=summary,
        related_symbols=_related_symbols(title, summary, source.source_id),
        event_category=_event_category(title, summary),
        content_hash=content_hash,
        deduplication_key=deduplication_key,
    )


# 去除脚本、样式和 HTML 标签，压缩空白并在语义字段上执行长度上限。
def _normalize_text(value: str, *, maximum: int) -> str:
    """去除脚本、样式和 HTML 标签，压缩空白并在语义字段上执行长度上限。"""
    without_scripts = _SCRIPT_OR_STYLE.sub(" ", value)
    plain_text = _WHITESPACE.sub(" ", _HTML_TAG.sub("", html.unescape(without_scripts))).strip()
    normalized = plain_text[:maximum].strip()
    if not normalized:
        raise ValueError("新闻文本不能为空")
    return normalized


# 检测非拉丁文字母，为英文来源提供保守的混合语言防护。
def _contains_non_latin_letter(value: str) -> bool:
    """检测非拉丁文字母，为英文来源提供保守的混合语言防护。"""
    return any(
        unicodedata.category(character).startswith("L")
        and "LATIN" not in unicodedata.name(character, "")
        for character in value
    )


# 用拉丁字符和常见英文信号词做保守筛选，不承担通用语言识别职责。
def _is_english_text(value: str) -> bool:
    """用拉丁字符和常见英文信号词做保守筛选，不承担通用语言识别职责。"""
    if _contains_non_latin_letter(value):
        return False
    words = _LATIN_WORD.findall(value.casefold())
    # 来源已是英文媒体白名单；这里仅做保守的混合语言防护，并非通用语言识别模型。
    english_signal_count = sum(word in _ENGLISH_SIGNAL_WORDS for word in words)
    return english_signal_count >= 2


# 移除跟踪参数、规范化主机与路径，再按 HTTP URL 契约校验新闻链接。
def _canonicalize_url(value: str):
    """移除跟踪参数、规范化主机与路径，再按 HTTP URL 契约校验新闻链接。"""
    parts = urlsplit(value)
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if not _TRACKING_KEY.match(key)
        ],
        doseq=True,
    )
    return parse_http_url(
        urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", query, ""))
    )


# 对 UTF-8 文本计算稳定摘要，用作内容身份或去重依据。
def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# 按来源项目 ID、规范链接或内容哈希依次生成稳定去重键。
def _deduplication_key(
    *,
    source_id: str,
    source_item_id: str | None,
    canonical_url: AnyHttpUrl | None,
    content_hash: str,
) -> str:
    """按来源项目 ID、规范链接或内容哈希依次生成稳定去重键。"""
    if source_item_id is not None:
        return f"{source_id}:source-item:{source_item_id}"
    if canonical_url is not None:
        return f"{source_id}:url:{canonical_url}"
    return f"{source_id}:content:{content_hash}"


# 根据获准来源和文本关键字标记新闻涉及的受支持合约标的。
def _related_symbols(
    title: str,
    summary: str,
    source_id: str,
) -> tuple[ResearchSymbol, ...]:
    """根据获准来源和文本关键字标记新闻涉及的受支持合约标的。"""
    content = f"{title} {summary}".casefold()
    symbols: list[ResearchSymbol] = []
    if re.search(r"\b(bitcoin|btc)\b", content):
        symbols.append(ContractSymbol.BTCUSDT)
    if re.search(r"\b(ethereum|ether|eth)\b", content):
        symbols.append(ContractSymbol.ETHUSDT)
    if (
        not symbols
        and source_id
        in {
            "federal_reserve_press_releases",
            "us_treasury_press_releases",
            "cftc_press_releases",
            "sec_press_releases",
        }
        and re.search(
            r"\b(fomc|federal funds|monetary policy|interest rates?|quantitative tightening|"
            r"quantitative easing|liquidity|stablecoins?|digital assets?|crypto(?:currency)?|"
            r"treasury (?:borrowing|refunding)|sanctions?)\b",
            content,
        )
    ):
        return (ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT)
    if (
        not symbols
        and source_id == "sec_press_releases"
        and re.search(r"\b(sec|regulation|enforcement|digital asset|crypto)\b", content)
    ):
        return (ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT)
    return tuple(symbols)


# 用确定性关键词将标题和摘要归入有限新闻事件类别。
def _event_category(title: str, summary: str) -> NewsEventCategory:
    """用确定性关键词将标题和摘要归入有限新闻事件类别。"""
    content = f"{title} {summary}".casefold()
    if re.search(
        r"\b(sec|regulat\w*|enforcement|lawsuit|approval|stablecoins?|sanctions?)\b",
        content,
    ):
        return NewsEventCategory.REGULATION
    if "etf" in content:
        return NewsEventCategory.ETF
    if re.search(r"\b(hack|exploit|breach|security)\b", content):
        return NewsEventCategory.SECURITY
    if re.search(r"\b(protocol|upgrade|fork|mainnet)\b", content):
        return NewsEventCategory.PROTOCOL
    if re.search(
        r"\b(fed|fomc|federal reserve|federal funds|inflation|interest rates?|macro|"
        r"monetary policy|quantitative tightening|quantitative easing|liquidity|"
        r"treasury (?:borrowing|refunding))\b",
        content,
    ):
        return NewsEventCategory.MACRO
    return NewsEventCategory.MARKET
