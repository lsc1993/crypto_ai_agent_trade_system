from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AnyHttpUrl

from app.market.contracts import ContractSymbol
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


def normalize_news_item(
    item: ExternalNewsItem,
    *,
    source: NewsSourceDefinition,
    fetched_at: datetime,
) -> NewsItemDraft:
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


def _normalize_text(value: str, *, maximum: int) -> str:
    without_scripts = _SCRIPT_OR_STYLE.sub(" ", value)
    plain_text = _WHITESPACE.sub(" ", _HTML_TAG.sub("", html.unescape(without_scripts))).strip()
    normalized = plain_text[:maximum].strip()
    if not normalized:
        raise ValueError("新闻文本不能为空")
    return normalized


def _contains_non_latin_letter(value: str) -> bool:
    return any(
        unicodedata.category(character).startswith("L")
        and "LATIN" not in unicodedata.name(character, "")
        for character in value
    )


def _is_english_text(value: str) -> bool:
    if _contains_non_latin_letter(value):
        return False
    words = _LATIN_WORD.findall(value.casefold())
    # Sources are an allowlist of English publishers. This is an additional
    # conservative mixed-language guard, not a general-purpose language model.
    english_signal_count = sum(word in _ENGLISH_SIGNAL_WORDS for word in words)
    return english_signal_count >= 2


def _canonicalize_url(value: str):
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


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _deduplication_key(
    *,
    source_id: str,
    source_item_id: str | None,
    canonical_url: AnyHttpUrl | None,
    content_hash: str,
) -> str:
    if source_item_id is not None:
        return f"{source_id}:source-item:{source_item_id}"
    if canonical_url is not None:
        return f"{source_id}:url:{canonical_url}"
    return f"{source_id}:content:{content_hash}"


def _related_symbols(title: str, summary: str, source_id: str) -> tuple[ContractSymbol, ...]:
    content = f"{title} {summary}".casefold()
    symbols: list[ContractSymbol] = []
    if re.search(r"\b(bitcoin|btc)\b", content):
        symbols.append(ContractSymbol.BTCUSDT)
    if re.search(r"\b(ethereum|ether|eth)\b", content):
        symbols.append(ContractSymbol.ETHUSDT)
    if (
        not symbols
        and source_id == "sec_press_releases"
        and re.search(r"\b(sec|regulation|enforcement|digital asset|crypto)\b", content)
    ):
        return (ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT)
    return tuple(symbols)


def _event_category(title: str, summary: str) -> NewsEventCategory:
    content = f"{title} {summary}".casefold()
    if re.search(r"\b(sec|regulat|enforcement|lawsuit|approval)\b", content):
        return NewsEventCategory.REGULATION
    if "etf" in content:
        return NewsEventCategory.ETF
    if re.search(r"\b(hack|exploit|breach|security)\b", content):
        return NewsEventCategory.SECURITY
    if re.search(r"\b(protocol|upgrade|fork|mainnet)\b", content):
        return NewsEventCategory.PROTOCOL
    if re.search(r"\b(fed|inflation|interest rate|macro)\b", content):
        return NewsEventCategory.MACRO
    return NewsEventCategory.MARKET
