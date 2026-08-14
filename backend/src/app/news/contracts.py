from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from app.market.contracts import ContractSymbol, UtcDateTime


class NewsSourceTier(StrEnum):
    PRIMARY = "primary"
    PROFESSIONAL_MEDIA = "professional_media"


_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


def parse_http_url(value: str) -> AnyHttpUrl:
    return _HTTP_URL_ADAPTER.validate_python(value)


class NewsEventCategory(StrEnum):
    MARKET = "market"
    REGULATION = "regulation"
    ETF = "etf"
    SECURITY = "security"
    PROTOCOL = "protocol"
    MACRO = "macro"


class _NewsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NewsSourceDefinition(_NewsModel):
    source_id: Literal[
        "sec_press_releases",
        "cftc_press_releases",
        "federal_reserve_press_releases",
        "us_treasury_press_releases",
        "coindesk",
        "decrypt",
        "blockworks",
        "the_block",
    ]
    source_name: str = Field(min_length=1, max_length=120)
    tier: NewsSourceTier
    feed_url: AnyHttpUrl
    max_items_per_run: int = Field(ge=1, le=30)


COINDESK_SOURCE = NewsSourceDefinition(
    source_id="coindesk",
    source_name="CoinDesk",
    tier=NewsSourceTier.PROFESSIONAL_MEDIA,
    feed_url=parse_http_url("https://www.coindesk.com/arc/outboundfeeds/rss/"),
    max_items_per_run=20,
)
SEC_PRESS_RELEASES_SOURCE = NewsSourceDefinition(
    source_id="sec_press_releases",
    source_name="U.S. Securities and Exchange Commission",
    tier=NewsSourceTier.PRIMARY,
    feed_url=parse_http_url("https://www.sec.gov/news/pressreleases.rss"),
    max_items_per_run=20,
)
CFTC_PRESS_RELEASES_SOURCE = NewsSourceDefinition(
    source_id="cftc_press_releases",
    source_name="U.S. Commodity Futures Trading Commission",
    tier=NewsSourceTier.PRIMARY,
    feed_url=parse_http_url("https://www.cftc.gov/RSS/RSSGP/rssgp.xml"),
    max_items_per_run=20,
)
FEDERAL_RESERVE_PRESS_RELEASES_SOURCE = NewsSourceDefinition(
    source_id="federal_reserve_press_releases",
    source_name="Federal Reserve Press Releases",
    tier=NewsSourceTier.PRIMARY,
    feed_url=parse_http_url("https://www.federalreserve.gov/feeds/press_all.xml"),
    max_items_per_run=20,
)
US_TREASURY_PRESS_RELEASES_SOURCE = NewsSourceDefinition(
    source_id="us_treasury_press_releases",
    source_name="U.S. Treasury Press Releases",
    tier=NewsSourceTier.PRIMARY,
    feed_url=parse_http_url("https://home.treasury.gov/rss/press-releases.xml"),
    max_items_per_run=20,
)
DECRYPT_SOURCE = NewsSourceDefinition(
    source_id="decrypt",
    source_name="Decrypt",
    tier=NewsSourceTier.PROFESSIONAL_MEDIA,
    feed_url=parse_http_url("https://decrypt.co/feed"),
    max_items_per_run=20,
)
BLOCKWORKS_SOURCE = NewsSourceDefinition(
    source_id="blockworks",
    source_name="Blockworks",
    tier=NewsSourceTier.PROFESSIONAL_MEDIA,
    feed_url=parse_http_url("https://blockworks.com/feed"),
    max_items_per_run=20,
)
THE_BLOCK_SOURCE = NewsSourceDefinition(
    source_id="the_block",
    source_name="The Block",
    tier=NewsSourceTier.PROFESSIONAL_MEDIA,
    feed_url=parse_http_url("https://www.theblock.co/rss.xml"),
    max_items_per_run=20,
)
ALLOWED_NEWS_SOURCES: dict[str, NewsSourceDefinition] = {
    source.source_id: source
    for source in (
        SEC_PRESS_RELEASES_SOURCE,
        CFTC_PRESS_RELEASES_SOURCE,
        FEDERAL_RESERVE_PRESS_RELEASES_SOURCE,
        US_TREASURY_PRESS_RELEASES_SOURCE,
        COINDESK_SOURCE,
        DECRYPT_SOURCE,
        BLOCKWORKS_SOURCE,
        THE_BLOCK_SOURCE,
    )
}


class ExternalNewsItem(_NewsModel):
    source_item_id: str | None = Field(default=None, max_length=300)
    title: str = Field(min_length=1, max_length=4_000)
    summary: str = Field(min_length=1, max_length=20_000)
    url: AnyHttpUrl | None = None
    published_at: UtcDateTime
    language: Literal["en"] = "en"

    @field_validator("source_item_id", mode="before")
    @classmethod
    def normalize_source_item_id(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("来源条目 ID 必须是字符串")
        normalized = value.strip()
        return normalized or None

    @field_validator("published_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("新闻时间必须是 UTC 且带时区")
        return value.astimezone(UTC)


class NewsItemDraft(_NewsModel):
    source_id: str
    source_tier: NewsSourceTier
    source_item_id: str | None
    canonical_url: AnyHttpUrl | None
    published_at: UtcDateTime
    fetched_at: UtcDateTime
    language: Literal["en"]
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=1_600)
    related_symbols: tuple[ContractSymbol, ...]
    event_category: NewsEventCategory
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    deduplication_key: str = Field(min_length=1, max_length=2_000)

    @field_validator("published_at", "fetched_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("新闻时间必须是 UTC 且带时区")
        return value.astimezone(UTC)
