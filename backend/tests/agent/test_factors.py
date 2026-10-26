# 验证政策、资金费率与 ETF 专题的证据选择和确定性统计。
# 结算缺口、未披露与零值具有不同含义，不能用不完整窗口冒充完整统计。
# 专题引用必须属于当前主题，模型缺失时仍保留事实与可见限制。
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.agent.factors import (
    apply_interpretations,
    etf_topic,
    funding_topic,
    policy_topic,
    select_news,
)
from app.market.contracts import ContractSymbol
from app.market.etf_flows import EtfFlowDay, EtfFlowSnapshot
from app.market.funding_history import FundingHistory, FundingPoint
from app.news.contracts import ALLOWED_NEWS_SOURCES, ExternalNewsItem
from app.news.normalization import normalize_news_item
from app.reports.factors import FactorAnalysis, FactorInterpretation, FactorTopic

NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)
POLICY_ID = UUID("00000000-0000-0000-0000-000000000811")
FUNDING_ID = UUID("00000000-0000-0000-0000-000000000812")


# 三个样本只能证明已获取窗口的均值与累计，不能把它们描述成完整七天结算历史。
def test_funding_statistics_use_exact_settled_samples_and_report_partial_coverage() -> None:
    history = FundingHistory(
        symbol=ContractSymbol.BTCUSDT,
        since=NOW - timedelta(days=7),
        until=NOW,
        fetched_at=NOW,
        points=tuple(
            FundingPoint(
                funding_time=NOW - timedelta(hours=8 * (2 - i)), funding_rate=Decimal(rate)
            )
            for i, rate in enumerate(("0.0001", "-0.0002", "-0.0002"))
        ),
    )
    topic = funding_topic(history, evidence_id=FUNDING_ID)
    facts = {item.label: item.value for item in topic.facts}
    assert facts["最新已结算费率"] == "-0.0002"
    assert facts["已获取样本平均费率"] == "-0.0001"
    assert facts["已获取样本累计费率"] == "-0.0003"
    assert facts["末尾已获取样本连续同号数"] == "2"
    assert topic.status == "partial"
    assert topic.observed_at == NOW


# 同号样本之间刻意留出结算缺口，验证同号样本数不能升级为真实连续结算次数。
def test_funding_gap_does_not_claim_continuous_settlement_direction() -> None:
    history = FundingHistory(
        symbol=ContractSymbol.BTCUSDT,
        since=NOW - timedelta(days=7),
        until=NOW,
        fetched_at=NOW,
        points=tuple(
            FundingPoint(funding_time=NOW - timedelta(hours=hours), funding_rate=Decimal("0.0001"))
            for hours in (24, 0)
        ),
    )
    topic = funding_topic(history, evidence_id=FUNDING_ID)
    facts = {item.label: item.value for item in topic.facts}
    assert topic.status == "partial"
    assert "连续同方向结算次数" not in facts
    assert facts["末尾已获取样本连续同号数"] == "2"
    assert any("不能证明真实结算连续性" in limit for limit in topic.limitations)


# 完整披露日用于五日统计，最新部分披露日单独展示；真实零流量与未披露空值必须同时保留。
def test_etf_five_disclosed_sessions_exclude_partial_latest_and_preserve_zero() -> None:
    dates = [
        date(2026, 8, 28),
        date(2026, 8, 31),
        date(2026, 9, 1),
        date(2026, 9, 2),
        date(2026, 9, 3),
    ]
    values = ["1000000", "-2000000", "0", "3000000", "4000000"]
    days = tuple(
        EtfFlowDay(
            trading_date=day,
            funds={"IBIT": Decimal(value)},
            total_net_flow_usd=Decimal(value),
            complete=True,
        )
        for day, value in zip(dates, values, strict=True)
    )
    snapshot = EtfFlowSnapshot(
        symbol=ContractSymbol.BTCUSDT,
        fetched_at=NOW,
        source_url="https://farside.co.uk/btc/",
        days=(
            *days,
            EtfFlowDay(
                trading_date=date(2026, 9, 4),
                funds={"IBIT": None, "FBTC": Decimal("0")},
                total_net_flow_usd=Decimal("0"),
                complete=False,
            ),
        ),
    )
    topic = etf_topic(snapshot, as_of=NOW, evidence_id=FUNDING_ID)
    facts = {item.label: item.value for item in topic.facts}
    assert facts["最近 5 个完整披露交易日累计净流量"] == "6000000"
    assert facts["最新交易日已披露净流量（部分）"] == "0"
    assert facts["累计起止交易日"] == "2026-08-28 至 2026-09-03"
    assert facts["IBIT · 2026-09-04"] is None
    assert facts["FBTC · 2026-09-04"] == "0"
    assert topic.status == "partial"


def test_etf_does_not_call_four_sessions_a_five_session_total() -> None:
    days = tuple(
        EtfFlowDay(
            trading_date=date(2026, 9, i),
            funds={"IBIT": Decimal("1")},
            total_net_flow_usd=Decimal("1"),
            complete=True,
        )
        for i in range(1, 5)
    )
    snapshot = EtfFlowSnapshot(
        symbol=ContractSymbol.BTCUSDT,
        fetched_at=NOW,
        source_url="https://farside.co.uk/btc/",
        days=days,
    )
    topic = etf_topic(snapshot, as_of=NOW, evidence_id=FUNDING_ID)
    facts = {item.label: item.value for item in topic.facts}
    assert facts["最近 5 个完整披露交易日累计净流量"] is None
    assert topic.status == "partial"


# UTC 已跨日而纽约仍在当日，数字齐全也不能将未结束交易日计入最终累计。
def test_etf_current_new_york_session_is_provisional_even_when_all_funds_are_numeric() -> None:
    as_of = datetime(2026, 9, 5, 1, tzinfo=UTC)  # Still September 4 in New York.
    dates = (date(2026, 8, 28), date(2026, 8, 31), *(date(2026, 9, i) for i in range(1, 5)))
    snapshot = EtfFlowSnapshot(
        symbol=ContractSymbol.BTCUSDT,
        fetched_at=as_of,
        source_url="https://farside.co.uk/btc/",
        days=tuple(
            EtfFlowDay(
                trading_date=day,
                funds={"IBIT": Decimal("1")},
                total_net_flow_usd=Decimal("1"),
                complete=True,
            )
            for day in dates
        ),
    )
    topic = etf_topic(snapshot, as_of=as_of, evidence_id=FUNDING_ID)
    facts = {item.label: item.value for item in topic.facts}
    assert topic.status == "partial"
    assert facts["最新交易日已披露净流量（部分）"] == "1"
    assert facts["最近 5 个完整披露交易日累计净流量"] == "5"
    assert facts["累计起止交易日"] == "2026-08-28 至 2026-09-03"
    assert facts["连续同方向已披露交易日"] is None
    assert any("纽约当日" in limit for limit in topic.limitations)


# 七天窗口中的官方政策优先保留，避免近期大量市场新闻挤掉长期主题证据。
def test_selection_preserves_week_old_policy_ahead_of_recent_market_chatter() -> None:
    def item(source: str, title: str, age: int):
        return normalize_news_item(
            ExternalNewsItem(
                title=title,
                summary="Bitcoin markets react to this release.",
                published_at=NOW - timedelta(days=age),
            ),
            source=ALLOWED_NEWS_SOURCES[source],
            fetched_at=NOW,
        )

    policy = item("sec_press_releases", "SEC announces crypto regulation", 6)
    old = item("sec_press_releases", "SEC announces old regulation", 8)
    chatter = tuple(item("coindesk", f"Bitcoin market report number {i}", 0) for i in range(30))
    chosen = select_news(
        (*chatter, old, policy, policy), symbol=ContractSymbol.BTCUSDT, as_of=NOW, limit=26
    )
    assert chosen[0].deduplication_key == policy.deduplication_key
    assert len(chosen) == 26
    assert old not in chosen
    assert sum(row.deduplication_key == policy.deduplication_key for row in chosen) == 1


def test_no_policy_evidence_does_not_claim_no_policies_exist() -> None:
    topic = policy_topic((), as_of=NOW, source_coverage="complete")
    assert topic.status == "missing"
    assert topic.interpretation is None
    assert any("覆盖" in limit for limit in topic.limitations)


# 引用属于本次报告仍不够，专题解释还必须引用该专题自己的证据。
def test_interpretation_rejects_citation_from_another_topic() -> None:
    analysis = FactorAnalysis(
        policy=FactorTopic(status="available", window_end=NOW, evidence_ids=(POLICY_ID,)),
        funding=FactorTopic(status="available", window_end=NOW, evidence_ids=(FUNDING_ID,)),
        etf=FactorTopic(status="missing", window_end=NOW),
    )
    proposal = FactorInterpretation(
        topic="policy",
        outlook="neutral",
        summary="政策影响需要结合市场证据判断。",
        short_term="短期可能影响风险偏好。",
        long_term="长期取决于政策执行。",
        invalidation="若政策撤回则需要重新评估。",
        evidence_ids=(FUNDING_ID,),
    )
    with pytest.raises(ValueError, match="专题证据"):
        apply_interpretations(analysis, (proposal,))


def test_missing_model_topic_retains_facts_with_explicit_limitation() -> None:
    topic = FactorTopic(status="available", window_end=NOW, evidence_ids=(POLICY_ID,))
    result = apply_interpretations(FactorAnalysis(policy=topic, funding=topic, etf=topic), ())
    assert result.policy.evidence_ids == (POLICY_ID,)
    assert result.policy.interpretation is None
    assert any("解释" in limit for limit in result.policy.limitations)


def test_topic_rejects_naive_dates_before_serialization_can_assume_a_timezone() -> None:
    with pytest.raises(ValueError, match="UTC"):
        FactorTopic(status="missing", window_end=datetime(2026, 9, 6))
