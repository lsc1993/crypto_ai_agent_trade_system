# 验证官方政策的市场上下文相关性，而非仅匹配币名。
# 相关政策即使没有币名也可覆盖两个预置币种。
# 无关官方发布不能因为来源权威就自动成为加密政策证据。
from datetime import UTC, datetime

import pytest

from app.market.contracts import ContractSymbol
from app.news.contracts import ALLOWED_NEWS_SOURCES, ExternalNewsItem, NewsEventCategory
from app.news.normalization import normalize_news_item


@pytest.mark.parametrize(
    "source_id,title,summary,category",
    [
        (
            "federal_reserve_press_releases",
            "Federal Reserve issues FOMC statement",
            "The Committee decided to maintain the target range for the federal funds rate.",
            NewsEventCategory.MACRO,
        ),
        (
            "us_treasury_press_releases",
            "Treasury announces stablecoin rules",
            "The Treasury proposed new rules for digital asset issuers.",
            NewsEventCategory.REGULATION,
        ),
        (
            "cftc_press_releases",
            "CFTC proposes digital asset regulation",
            "The Commission announced a proposed rule for crypto derivatives.",
            NewsEventCategory.REGULATION,
        ),
    ],
)
def test_official_policy_without_coin_name_reaches_both_reports(
    source_id: str,
    title: str,
    summary: str,
    category: NewsEventCategory,
) -> None:
    item = normalize_news_item(
        ExternalNewsItem(
            title=title, summary=summary, published_at=datetime(2026, 9, 1, tzinfo=UTC)
        ),
        source=ALLOWED_NEWS_SOURCES[source_id],
        fetched_at=datetime(2026, 9, 6, tzinfo=UTC),
    )
    assert item.related_symbols == (ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT)
    assert item.event_category == category


def test_unrelated_official_release_is_not_a_crypto_policy() -> None:
    item = normalize_news_item(
        ExternalNewsItem(
            title="Treasury announces museum visitor schedule",
            summary="The building will welcome visitors for an exhibition.",
            published_at=datetime(2026, 9, 1, tzinfo=UTC),
        ),
        source=ALLOWED_NEWS_SOURCES["us_treasury_press_releases"],
        fetched_at=datetime(2026, 9, 6, tzinfo=UTC),
    )
    assert item.related_symbols == ()
