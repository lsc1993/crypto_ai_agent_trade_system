"""Deterministic topic selection, statistics and validation before model interpretation."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from app.market.etf_flows import EtfFlowSnapshot
from app.market.funding_history import FundingHistory
from app.market.symbols import ResearchSymbol
from app.news.contracts import ALLOWED_NEWS_SOURCES, NewsEventCategory, NewsItemDraft
from app.reports.factors import (
    FactorAnalysis,
    FactorFact,
    FactorInterpretation,
    FactorTopic,
    PolicyEvent,
    unavailable_topic,
)

POLICY_SOURCES = frozenset(
    {
        "sec_press_releases",
        "cftc_press_releases",
        "federal_reserve_press_releases",
        "us_treasury_press_releases",
    }
)


def is_policy(item: NewsItemDraft) -> bool:
    return item.source_id in POLICY_SOURCES and item.event_category in {
        NewsEventCategory.REGULATION,
        NewsEventCategory.MACRO,
    }


def select_news(
    items: tuple[NewsItemDraft, ...],
    *,
    symbol: ResearchSymbol,
    as_of: datetime,
    limit: int,
) -> tuple[NewsItemDraft, ...]:
    candidates = sorted(
        (
            item
            for item in items
            if symbol in item.related_symbols
            and as_of - timedelta(days=7) <= item.published_at <= as_of
        ),
        key=lambda item: (is_policy(item), item.published_at),
        reverse=True,
    )
    unique: dict[str, NewsItemDraft] = {}
    for item in candidates:
        unique.setdefault(item.deduplication_key, item)
    return tuple(unique.values())[:limit]


def policy_topic(
    items: tuple[tuple[NewsItemDraft, UUID], ...],
    *,
    as_of: datetime,
    source_coverage: Literal["none", "partial", "complete"],
) -> FactorTopic:
    selected = tuple((item, evidence_id) for item, evidence_id in items if is_policy(item))[:12]
    events = tuple(
        PolicyEvent(
            institution=ALLOWED_NEWS_SOURCES[item.source_id].source_name,
            title=item.title,
            summary=item.summary,
            published_at=item.published_at,
            evidence_id=evidence_id,
            source_url=str(item.canonical_url or ALLOWED_NEWS_SOURCES[item.source_id].feed_url),
        )
        for item, evidence_id in selected
    )
    return FactorTopic(
        status=("partial" if selected else "failed" if source_coverage == "none" else "missing"),
        window_start=as_of - timedelta(days=7),
        window_end=as_of,
        observed_at=max((item.published_at for item, _ in selected), default=None),
        fetched_at=max((item.fetched_at for item, _ in selected), default=None),
        facts=(
            FactorFact(
                label="近 7 天已获取的美国官方政策事件", value=str(len(events)), unit="count"
            ),
        ),
        events=events,
        evidence_ids=tuple(event.evidence_id for event in events),
        limitations=(
            "范围为 SEC、CFTC、美联储和美国财政部；"
            "RSS 条目与本次证据数量均有上限，覆盖可能不完整。",
            "未获取相关事件不代表过去一周没有政策；发布时间不等于政策生效时间。",
        ),
    )


def apply_interpretations(
    analysis: FactorAnalysis,
    interpretations: tuple[FactorInterpretation, ...],
) -> FactorAnalysis:
    by_kind = {item.topic: item for item in interpretations}
    if len(by_kind) != len(interpretations):
        raise ValueError("专题解释不能重复")
    topics: dict[str, FactorTopic] = {}
    for kind in ("policy", "funding", "etf"):
        topic: FactorTopic = getattr(analysis, kind)
        proposal = by_kind.get(kind)
        if proposal is not None:
            if topic.status in {"missing", "failed"} or not set(proposal.evidence_ids) <= set(
                topic.evidence_ids
            ):
                raise ValueError("模型解释必须引用本专题证据")
        limits = topic.limitations
        if proposal is None and topic.evidence_ids:
            limits = (*limits, "本次模型未形成可验证的专题解释，以下仅展示冻结事实。")
        topics[kind] = FactorTopic.model_validate(
            {
                **topic.model_dump(),
                "interpretation": proposal,
                "limitations": limits,
            }
        )
    return FactorAnalysis.model_validate(topics)


def funding_topic(history: FundingHistory, *, evidence_id: UUID) -> FactorTopic:
    points = history.points
    if not points:
        return unavailable_topic(as_of=history.until, reason="近 7 天未获取已结算资金费率。")
    rates = tuple(point.funding_rate for point in points)
    total = sum(rates, Decimal("0"))
    intervals = {b.funding_time - a.funding_time for a, b in zip(points, points[1:])}
    regular = len(intervals) == 1 and next(iter(intervals)) <= timedelta(hours=8)
    covered = (
        regular
        and points[0].funding_time - history.since <= next(iter(intervals))
        and history.until - points[-1].funding_time <= next(iter(intervals))
    )
    sign = _sign(rates[-1])
    streak = 0
    for rate in reversed(rates):
        if _sign(rate) != sign:
            break
        streak += 1
    limits = [
        "数据来自 Binance USD-M 单一交易所；费率为每次已结算口径，不是下一期预测。",
        "均值与累计值仅描述已获取样本；不推导年化，不将正负费率直接等同价格方向。",
    ]
    if not covered:
        limits.append("样本未完整覆盖近 7 天或结算间隔不一致；均值不能直接作为同周期费率比较。")
        limits.append("连续同号数仅描述已获取样本，存在数据缺口时不能证明真实结算连续性。")
    return FactorTopic(
        status="available" if covered else "partial",
        window_start=history.since,
        window_end=history.until,
        observed_at=points[-1].funding_time,
        fetched_at=history.fetched_at,
        evidence_ids=(evidence_id,),
        limitations=tuple(limits),
        facts=(
            _fact("最新已结算费率", rates[-1], "rate"),
            _fact("已获取样本平均费率", total / len(rates), "rate"),
            _fact("已获取样本累计费率", total, "rate"),
            _fact("已获取结算次数", len(rates), "count"),
            _fact("正费率次数", sum(rate > 0 for rate in rates), "count"),
            _fact("负费率次数", sum(rate < 0 for rate in rates), "count"),
            _fact("零费率次数", sum(rate == 0 for rate in rates), "count"),
            _fact("末尾已获取样本连续同号数", streak, "count"),
            _fact("最近结算方向", "正费率" if sign > 0 else "负费率" if sign < 0 else "零费率"),
            _fact("首个样本时间（UTC）", points[0].funding_time.isoformat()),
        ),
    )


def etf_topic(snapshot: EtfFlowSnapshot, *, as_of: datetime, evidence_id: UUID) -> FactorTopic:
    days = snapshot.days
    latest = days[-1]
    session_date = as_of.astimezone(ZoneInfo("America/New_York")).date()
    provisional = latest.trading_date == session_date
    latest_complete = latest.complete and not provisional
    complete = tuple(day for day in days if day.complete and day.trading_date < session_date)[-5:]
    has_five = len(complete) == 5
    incomplete_window = any(
        not day.complete or day.trading_date == session_date
        for day in days
        if day.trading_date >= (complete[0].trading_date if complete else days[0].trading_date)
    )
    gaps = any(_weekday_gap(a.trading_date, b.trading_date) for a, b in zip(days, days[1:]))
    stale = (session_date - latest.trading_date).days > 4
    status = "available" if has_five and not (incomplete_window or gaps or stale) else "partial"
    total = sum((day.total_net_flow_usd or Decimal("0") for day in complete), Decimal("0"))
    streak = 0
    sign = _sign(latest.total_net_flow_usd or Decimal("0"))
    previous: date | None = None
    if latest_complete:
        for day in reversed(days):
            if (
                not day.complete
                or _sign(day.total_net_flow_usd or Decimal("0")) != sign
                or (previous is not None and _weekday_gap(day.trading_date, previous))
            ):
                break
            streak += 1
            previous = day.trading_date
    facts = [
        _fact("最新已披露交易日", latest.trading_date.isoformat()),
        _fact(
            "最新交易日净流量" if latest_complete else "最新交易日已披露净流量（部分）",
            latest.total_net_flow_usd,
            "usd",
        ),
        _fact("最近 5 个完整披露交易日累计净流量", total if has_five else None, "usd"),
        _fact(
            "累计起止交易日",
            f"{complete[0].trading_date} 至 {complete[-1].trading_date}" if has_five else None,
        ),
        _fact("已获取完整披露交易日数", len(complete), "count"),
        _fact("连续同方向已披露交易日", streak if latest_complete else None, "count"),
        _fact(
            "最新资金方向",
            ("净流入" if sign > 0 else "净流出" if sign < 0 else "零净流量")
            if latest_complete
            else "部分披露，方向待确认",
        ),
    ]
    contributors = sorted(
        latest.funds.items(),
        key=lambda pair: (
            pair[1] is not None,
            abs(pair[1] or Decimal("0")),
        ),
        reverse=True,
    )
    # Show largest disclosed contributors and all currently missing funds within the UI budget.
    for ticker, flow in contributors[:20]:
        facts.append(_fact(f"{ticker} · {latest.trading_date}", flow, "usd"))
    limits = [
        "美国现货 ETF，按来源交易日期统计；单位为美元。来源为 Farside 汇总，可能发生后续修订。",
        "交易日期不等于发布时间；抓取时间记录本次可获知时点。休市不补零，资金流与价格不构成必然因果。",
    ]
    if not has_five:
        limits.append("不足 5 个完整披露交易日，未计算五日累计值。")
    if provisional:
        limits.append("纽约当日数据暂定，即使各基金均已显示数值，也不计入五日累计和连续方向统计。")
    if incomplete_window:
        limits.append("最新窗口包含未完整披露数据；五日累计仅取完整披露日，未把缺失资金当作零。")
    if gaps:
        limits.append("日期序列存在工作日空档，可能为休市或缺失披露；连续天数仅按可验证日期计算。")
    if stale:
        limits.append("最新交易日距本次研究超过 4 个自然日，数据可能滞后。")
    return FactorTopic(
        status=status,
        window_end=as_of,
        fetched_at=snapshot.fetched_at,
        facts=tuple(facts),
        evidence_ids=(evidence_id,),
        limitations=tuple(limits),
    )


def _fact(
    label: str,
    value: Decimal | int | str | None,
    unit: Literal["text", "rate", "usd", "count"] = "text",
) -> FactorFact:
    return FactorFact(label=label, value=None if value is None else str(value), unit=unit)


def _sign(value: Decimal) -> int:
    return (value > 0) - (value < 0)


def _weekday_gap(start: date, end: date) -> bool:
    return any(
        (start + timedelta(days=offset)).weekday() < 5 for offset in range(1, (end - start).days)
    )
