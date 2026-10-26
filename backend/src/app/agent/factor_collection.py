# 为综合研究独立采集资金费率历史与现货 ETF 专题，返回专题事实及可选冻结证据。
# 每条公开采集有独立超时；故障明确标为缺失或失败，不使用旧值补齐本次研究。
"""Independent, bounded public factor reads; failures do not invalidate market research."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Protocol, cast
from uuid import uuid4

from pydantic import JsonValue

from app.agent.evidence import FrozenResearchEvidence
from app.agent.factors import etf_topic, funding_topic
from app.agent.model import ModelEvidenceKind
from app.market.etf_flows import EtfFlowSnapshot
from app.market.funding_history import FundingHistory
from app.market.symbols import ResearchSymbol
from app.reports.factors import FactorTopic, unavailable_topic


# 公开已结算资金费率的读取端口；窗口由研究运行固定，而非由模型选择。
class FundingHistoryReader(Protocol):
    async def get_funding_history(
        self,
        symbol: Any,
        *,
        since: datetime,
        until: datetime,
    ) -> FundingHistory: ...


# 公开 ETF 快照端口；按本次研究截止时间采集，支持范围由上层约束。
class EtfFlowReader(Protocol):
    async def collect(
        self,
        symbol: Any,
        *,
        as_of: datetime,
    ) -> EtfFlowSnapshot: ...


# 校验标的和完整请求窗口后生成证据；无样本时只返回限制说明，取消保持向上传播。
async def collect_funding(
    reader: FundingHistoryReader | None,
    *,
    symbol: ResearchSymbol,
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


# 仅支持预置的两类 ETF 标的；交易日期不能晚于研究日，缺失披露不得解释成零。
async def collect_etf(
    reader: EtfFlowReader | None,
    *,
    symbol: ResearchSymbol,
    as_of: datetime,
) -> tuple[FactorTopic, FrozenResearchEvidence | None]:
    if symbol not in {"BTCUSDT", "ETHUSDT"}:
        return unavailable_topic(as_of=as_of, reason="当前数据源不支持"), None
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


# 模型只接收确定性统计投影，剔除事件正文与解释，避免事实和模型观点互相污染。
def _topic_content(topic: FactorTopic) -> str:
    return json.dumps(
        topic.model_dump(mode="json", exclude={"events", "interpretation"}),
        ensure_ascii=False,
        separators=(",", ":"),
    )
