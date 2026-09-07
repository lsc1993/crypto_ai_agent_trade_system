"""Independent, bounded public factor reads; failures do not invalidate market research."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Protocol, cast
from uuid import uuid4

from pydantic import JsonValue

from app.agent.evidence import FrozenResearchEvidence
from app.agent.factors import etf_topic, funding_topic
from app.agent.model import ModelEvidenceKind
from app.market.contracts import ContractSymbol
from app.market.etf_flows import EtfFlowSnapshot
from app.market.funding_history import FundingHistory
from app.reports.factors import FactorTopic, unavailable_topic


class FundingHistoryReader(Protocol):
    async def get_funding_history(
        self,
        symbol: ContractSymbol,
        *,
        since: datetime,
        until: datetime,
    ) -> FundingHistory: ...


class EtfFlowReader(Protocol):
    async def collect(self, symbol: ContractSymbol, *, as_of: datetime) -> EtfFlowSnapshot: ...


async def collect_funding(
    reader: FundingHistoryReader | None,
    *,
    symbol: ContractSymbol,
    as_of: datetime,
) -> tuple[FactorTopic, FrozenResearchEvidence | None]:
    if reader is None:
        return unavailable_topic(as_of=as_of, reason="尚未获取资金费率历史。"), None
    try:
        async with asyncio.timeout(12):
            history = await reader.get_funding_history(
                symbol,
                since=as_of - timedelta(days=7),
                until=as_of,
            )
        if (
            history.symbol != symbol
            or history.until != as_of
            or history.since != (as_of - timedelta(days=7))
        ):
            raise ValueError("资金费率来源窗口不一致")
        evidence_id = uuid4()
        topic = funding_topic(history, evidence_id=evidence_id)
        if not topic.evidence_ids:
            return topic, None
        return topic, FrozenResearchEvidence(
            id=evidence_id,
            kind=ModelEvidenceKind.FUNDING,
            source="binance_funding_history",
            source_url="https://fapi.binance.com/fapi/v1/fundingRate",
            observed_at=history.points[-1].funding_time,
            fetched_at=history.fetched_at,
            summary="冻结的近 7 天资金费率已结算历史与统计。",
            content=_topic_content(topic),
            payload=cast(dict[str, JsonValue], history.model_dump(mode="json")),
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        return unavailable_topic(
            as_of=as_of, failed=True, reason="资金费率历史采集失败，未生成基于历史的判断。"
        ), None


async def collect_etf(
    reader: EtfFlowReader | None,
    *,
    symbol: ContractSymbol,
    as_of: datetime,
) -> tuple[FactorTopic, FrozenResearchEvidence | None]:
    if reader is None:
        return unavailable_topic(as_of=as_of, reason="尚未获取 ETF 日度净流量。"), None
    try:
        async with asyncio.timeout(12):
            snapshot = await reader.collect(symbol, as_of=as_of)
        if snapshot.symbol != symbol or any(
            day.trading_date > as_of.date() for day in snapshot.days
        ):
            raise ValueError("ETF 来源标的或日期不一致")
        evidence_id = uuid4()
        topic = etf_topic(snapshot, as_of=as_of, evidence_id=evidence_id)
        return topic, FrozenResearchEvidence(
            id=evidence_id,
            kind=ModelEvidenceKind.ETF,
            source="farside_etf_flows",
            source_url=snapshot.source_url,
            # Trading dates have no intraday publication timestamp. Actual observation is the fetch.
            observed_at=snapshot.fetched_at,
            fetched_at=snapshot.fetched_at,
            summary="冻结的美国现货 ETF 日度净流量；观测时间为抓取时点，交易日期见载荷。",
            content=_topic_content(topic),
            payload=cast(dict[str, JsonValue], snapshot.model_dump(mode="json")),
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        return unavailable_topic(
            as_of=as_of, failed=True, reason="ETF 日度净流量采集失败，缺失数据不能作为零流量。"
        ), None


def _topic_content(topic: FactorTopic) -> str:
    return json.dumps(
        topic.model_dump(mode="json", exclude={"events", "interpretation"}),
        ensure_ascii=False,
        separators=(",", ":"),
    )
