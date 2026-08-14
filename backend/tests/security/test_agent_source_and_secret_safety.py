from pathlib import Path

from app.news.contracts import ALLOWED_NEWS_SOURCES

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


def _application_source(directory: str) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((BACKEND_ROOT / "src" / "app" / directory).rglob("*.py"))
    )


def test_agent_sources_are_allowlisted_and_cannot_enable_social_or_full_page_fetch() -> None:
    source = (BACKEND_ROOT / "src" / "app" / "news" / "rss.py").read_text(
        encoding="utf-8"
    )
    news_source = _application_source("news")

    assert "ALLOWED_NEWS_SOURCES" in source
    assert set(ALLOWED_NEWS_SOURCES) == {
        "sec_press_releases",
        "cftc_press_releases",
        "federal_reserve_press_releases",
        "us_treasury_press_releases",
        "coindesk",
        "decrypt",
        "blockworks",
        "the_block",
    }
    assert all(str(item.feed_url).startswith("https://") for item in ALLOWED_NEWS_SOURCES.values())
    assert "telegram" not in news_source.lower()
    assert "discord" not in news_source.lower()
    assert "follow_redirects=True" not in source
    assert source.count("follow_redirects=") == 1
    assert "follow_redirects=False" in source
    assert "BeautifulSoup" not in news_source


def test_agent_and_news_source_contain_no_private_exchange_or_model_tool_surface() -> None:
    source = f"{_application_source('agent')}\n{_application_source('news')}"

    forbidden = (
        "create_order",
        "cancel_order",
        "fetch_balance",
        "fetch_positions",
        "tools=",
        "tool_choice",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "BeautifulSoup",
        "selenium",
        "playwright",
    )
    assert not {token for token in forbidden if token in source}


def test_operation_docs_keep_the_manual_research_and_secret_boundary() -> None:
    boundaries = (PROJECT_ROOT / "docs" / "operational-boundaries.md").read_text(
        encoding="utf-8"
    )
    deployment = (PROJECT_ROOT / "docs" / "local-deployment.md").read_text(
        encoding="utf-8"
    )
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "手动" in boundaries
    assert "DeepSeek" in boundaries
    assert "Alternative.me" in boundaries
    assert "非投资或交易指令" in boundaries
    assert "未跟踪" in deployment
    assert "缺失" in deployment and "降级" in deployment
    assert "抓取公开行情与英文新闻并分析" in readme
    for source_name in (
        "CFTC Press Releases",
        "Federal Reserve Press Releases",
        "U.S. Treasury Press Releases",
        "Decrypt",
        "Blockworks",
        "The Block",
    ):
        assert source_name in boundaries


def test_compose_passes_optional_deepseek_configuration_without_a_secret_value() -> None:
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:-}" in compose
    assert "DEEPSEEK_MODEL: ${DEEPSEEK_MODEL:-deepseek-v4-pro}" in compose
