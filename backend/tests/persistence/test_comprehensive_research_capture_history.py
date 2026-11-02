# 综合研究真实 SQL 验收：固定行情采集和混合 RSS 元数据进入生产研究图，
# 缺配置的真实模型适配器安全降级，报告、证据、输入快照及 Harness 审计持久化后重新读取。
# 网络边界只使用合成网关与 MockTransport；不预制报告，不读取环境密钥或连接真实上游。
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, cast
from uuid import uuid4

import httpx
import pytest
from pydantic import JsonValue
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.model import DeepSeekResearchLanguageModel
from app.agent.service import (
    AgentResearchDependencies,
    AgentResearchService,
    PersistedAgentMarketCapture,
)
from app.harness.market_research import (
    HarnessedMarketResearchService,
    MarketResearchWorkflow,
)
from app.harness.policy import MARKET_RESEARCH_POLICY
from app.harness.runtime import HarnessRuntime
from app.infrastructure.persistence.harness_audit_repository import SqlAlchemyHarnessAuditRepository
from app.infrastructure.persistence.models.agent_research import AgentAnalysisRunRecord
from app.infrastructure.persistence.models.market import (
    MarketSnapshotInputRecord,
    MarketSnapshotRecord,
)
from app.infrastructure.persistence.models.news import NewsItemRecord
from app.infrastructure.persistence.models.reports import (
    AnalysisEvidenceRecord,
    AnalysisReportRecord,
)
from app.infrastructure.persistence.news_repository import SqlAlchemyNewsRepository
from app.infrastructure.persistence.report_repository import SqlAlchemyAnalysisReportRepository
from app.infrastructure.persistence.repository import SqlAlchemyMarketRepository
from app.infrastructure.persistence.research_reader import SqlAlchemyPersistedMarketReader
from app.market.capture import CAPTURE_TIMEFRAMES, MarketCaptureService
from app.market.contracts import (
    Candle,
    CandleSeries,
    ContractSymbol,
    DataFreshness,
    FreshnessStatus,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.repository import snapshot_payload_sha256
from app.news.contracts import COINDESK_SOURCE
from app.news.rss import RssNewsSourceAdapter
from app.news.service import NewsCollection, NewsIngestionService
from app.reports.contracts import AnalysisReportStatus, MarketOutlook, report_payload_sha256

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)


class Database(Protocol):
    """只依赖 migrated_database 随机 schema 的会话工厂，不接触连接配置。"""

    session_factory: async_sessionmaker[AsyncSession]


@pytest.mark.asyncio
async def test_full_capture_freezes_partial_news_and_rereads_degraded_history(
    migrated_database: Database,
) -> None:
    """真实采集保存后，无模型请求的降级历史与不可变冻结输入保持同一关联链。"""
    factory = migrated_database.session_factory
    requests: list[httpx.Request] = []
    model_requests: list[httpx.Request] = []
    gateway = SyntheticPublicGateway()
    analysis_id = uuid4()

    def feed(request: httpx.Request) -> httpx.Response:
        # 只允许登记 feed 的一次读取；任何文章正文或其他 URL 请求均使验收失败。
        requests.append(request)
        assert request.method == "GET"
        assert str(request.url) == str(COINDESK_SOURCE.feed_url)
        return httpx.Response(200, stream=FeedBytes(_mixed_rss()))

    def reject_model_request(request: httpx.Request) -> httpx.Response:
        # 即使研究图误吞异常，最后的零调用断言也会揭示越过缺配置检查的行为。
        model_requests.append(request)
        pytest.fail("缺配置 DeepSeek 不得发出 HTTP 请求")

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(feed), trust_env=False) as news_client,
        httpx.AsyncClient(
            transport=httpx.MockTransport(reject_model_request), trust_env=False
        ) as model_client,
    ):
        news = ObservedNewsCollector(
            NewsIngestionService(
                sources=(
                    RssNewsSourceAdapter(
                        source=COINDESK_SOURCE, client=news_client, timeout_seconds=5
                    ),
                ),
                repository=SqlAlchemyNewsRepository(factory),
            )
        )
        service = AgentResearchService(
            dependencies=AgentResearchDependencies(
                market=PersistedAgentMarketCapture(
                    capture_service=MarketCaptureService(
                        gateway=gateway, repository=SqlAlchemyMarketRepository(factory)
                    ),
                    reader=SqlAlchemyPersistedMarketReader(factory),
                ),
                news=news,
                model=DeepSeekResearchLanguageModel(
                    client=model_client, api_key=None, model="deepseek-v4-flash"
                ),
                repository=SqlAlchemyAnalysisReportRepository(factory),
                clock=lambda: NOW,
            )
        )
        harness = HarnessedMarketResearchService(
            HarnessRuntime(
                policies=(MARKET_RESEARCH_POLICY,),
                workflows=(MarketResearchWorkflow(service),),
                audit_repository=SqlAlchemyHarnessAuditRepository(factory),
            ),
            clock=lambda: NOW,
            new_run_id=lambda: analysis_id,
        )
        saved = await harness.generate(ContractSymbol.BTCUSDT)

    assert gateway.calls == [(ContractSymbol.BTCUSDT, CAPTURE_TIMEFRAMES)]
    assert len(requests) == 1
    assert model_requests == []
    assert len(news.collections) == 1
    collection = news.collections[0]
    assert collection.successful_source_ids == ("coindesk",)
    assert collection.failed_source_count == 0
    assert len(collection.items) == 1
    diagnostic = collection.source_diagnostics[0]
    assert diagnostic.outcome == "partial"
    assert (diagnostic.entry_count, diagnostic.accepted_count, diagnostic.recent_count) == (5, 1, 1)
    assert {item.code: item.count for item in diagnostic.rejections} == {
        "missing_metadata": 1,
        "invalid_url": 1,
        "invalid_published_at": 1,
        "non_english": 1,
    }
    assert diagnostic.omitted_count == 0

    # 必须真正走到缺配置模型适配器；行情不足等其他降级原因不能替代本场景。
    assert saved.analysis_id == analysis_id
    assert saved.status is AnalysisReportStatus.DEGRADED
    assert saved.agent_analysis is not None
    assert saved.agent_analysis.data_quality.source_coverage == "partial"
    assert saved.agent_analysis.data_quality.missing_inputs == ("model_not_configured",)
    assert saved.agent_analysis.outlook is MarketOutlook.NEUTRAL
    assert saved.agent_analysis.confidence == "low"
    assert saved.agent_analysis.narrative is None
    assert saved.facts == saved.inferences == ()
    rejection_limit = "英文新闻条目过滤：拒绝 4 条，来源 coindesk；覆盖不完整。"
    assert rejection_limit in saved.limitations
    assert rejection_limit in saved.agent_analysis.limitations
    assert any("model_not_configured" in item for item in saved.limitations)
    # 拒绝项目只冻结安全计数，非法地址、原始时间和被拒绝正文不能混入报告或证据。
    serialized = saved.model_dump_json()
    assert "file:///rejected" not in serialized
    assert "not-a-date" not in serialized
    assert "不符合英文新闻准入规则" not in serialized

    # 新仓储、新会话按报告身份和运行身份重读；持久化比较覆盖完整安全报告契约。
    reader = SqlAlchemyAnalysisReportRepository(factory)
    assert await reader.get_by_id(saved.id) == saved
    assert await reader.get_by_analysis_id(analysis_id) == saved
    page = await reader.list(page=1, page_size=10, symbol=ContractSymbol.BTCUSDT, status=None)
    assert page.total == 1
    assert page.items[0].id == saved.id

    async with factory() as session:
        snapshot = (await session.execute(select(MarketSnapshotRecord))).scalar_one()
        frozen_input = (await session.execute(select(MarketSnapshotInputRecord))).scalar_one()
        news_record = (await session.execute(select(NewsItemRecord))).scalar_one()
        run = (await session.execute(select(AgentAnalysisRunRecord))).scalar_one()
        evidence_records = tuple((await session.execute(select(AnalysisEvidenceRecord))).scalars())
    assert run.analysis_id == analysis_id
    assert run.error_code == "model_not_configured"
    assert run.status == "degraded"
    assert frozen_input.snapshot_id == snapshot.id
    assert snapshot.symbol == frozen_input.symbol == saved.symbol
    assert snapshot.captured_at == NOW
    assert frozen_input.candle_count == 200
    assert frozen_input.payload_sha256 == snapshot_payload_sha256(
        cast(dict[str, JsonValue], frozen_input.payload)
    )
    assert snapshot.payload_sha256 == snapshot_payload_sha256(
        cast(dict[str, JsonValue], snapshot.payload)
    )
    market_evidence = next(
        item for item in saved.evidence if item.source == "binance_usdm_public_rest"
    )
    news_evidence = next(item for item in saved.evidence if item.source == "coindesk")
    assert len(saved.evidence) == len(evidence_records) == 2
    assert {item.analysis_report_id for item in evidence_records} == {saved.id}
    assert {item.id for item in evidence_records} == {item.id for item in saved.evidence}
    assert market_evidence.payload["snapshotInputSha256"] == frozen_input.payload_sha256
    assert market_evidence.payload["summary"] == snapshot.payload["summary"]
    assert news_evidence.observed_at == news_record.published_at
    assert news_evidence.fetched_at == news_record.fetched_at == NOW
    assert news_evidence.source_url == news_record.canonical_url
    news_payload = cast(dict[str, JsonValue], news_evidence.payload["news"])
    assert news_payload["title"] == news_record.title == collection.items[0].title
    assert news_payload["summary"] == news_record.summary == collection.items[0].summary
    assert news_record.content_hash == collection.items[0].content_hash
    for evidence in saved.evidence:
        assert evidence.report_id == saved.id
        assert evidence.symbol == saved.symbol
        assert evidence.payload_sha256 == report_payload_sha256(evidence.payload)

    fresh_market = SqlAlchemyPersistedMarketReader(factory)
    reread_input = await fresh_market.load_snapshot_input(snapshot.id)
    assert reread_input is not None
    assert reread_input.payload_sha256 == frozen_input.payload_sha256
    assert len(reread_input.candles) == 200
    assert {item.timeframe for item in reread_input.candles} == set(CAPTURE_TIMEFRAMES)
    assert all(item.close_at <= NOW for item in reread_input.candles)
    assert all(item.close_price != Decimal("99999") for item in reread_input.candles)

    trace = await SqlAlchemyHarnessAuditRepository(factory).get_trace(analysis_id)
    assert trace is not None
    assert trace.run.run_id == saved.analysis_id
    assert [item.kind.value for item in trace.events] == [
        "requested",
        "policy_authorized",
        "workflow_started",
        "workflow_degraded",
    ]
    assert trace.events[-1].error_code == "model_not_configured"

    # 在刚生成的真实记录上验证数据库拒绝覆盖；每次失败均回滚，随后重读证明历史未变。
    for statement in (
        update(AnalysisReportRecord)
        .where(AnalysisReportRecord.id == saved.id)
        .values(summary="改写"),
        update(AnalysisEvidenceRecord)
        .where(AnalysisEvidenceRecord.id == news_evidence.id)
        .values(summary="改写"),
        update(MarketSnapshotInputRecord)
        .where(MarketSnapshotInputRecord.snapshot_id == snapshot.id)
        .values(candle_count=0),
        update(NewsItemRecord).where(NewsItemRecord.id == news_record.id).values(title="改写"),
    ):
        async with factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(statement)
                await session.commit()
            await session.rollback()
    assert await SqlAlchemyAnalysisReportRepository(factory).get_by_id(saved.id) == saved
    assert (
        await SqlAlchemyPersistedMarketReader(factory).load_snapshot_input(snapshot.id)
        == reread_input
    )


class SyntheticPublicGateway:
    """仅替换最外层公开行情读取；返回足够的已收盘样本及必须排除的未来样本。"""

    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[MarketTimeframe, ...]]] = []

    async def get_summaries(self, symbols: tuple[Any, ...]) -> tuple[MarketSummary, ...]:
        """此研究入口应只请求完整行情，意外摘要读取立即失败。"""
        pytest.fail("综合研究采集不得绕过固定 get_market 路径")

    async def get_market(
        self, symbol: Any, timeframes: tuple[MarketTimeframe, ...]
    ) -> MarketDetail:
        """提供确定性 Decimal/UTC 行情，生产采集负责过滤、哈希和保存。"""
        self.calls.append((symbol, timeframes))
        assert symbol == ContractSymbol.BTCUSDT
        summary = MarketSummary(
            symbol=ContractSymbol.BTCUSDT,
            price=Decimal("68000.12"),
            change_24h=Decimal("1.5"),
            volume_24h=Decimal("1000000"),
            funding_rate=Decimal("0.0001"),
            open_interest=Decimal("500000"),
            freshness=DataFreshness(
                status=FreshnessStatus.FRESH,
                source="binance_usdm_public_rest",
                observed_at=NOW,
                fetched_at=NOW,
            ),
        )
        return MarketDetail(summary=summary, series=tuple(_series(item) for item in timeframes))


class ObservedNewsCollector:
    """旁路记录真实采集结果供断言使用，不改变条目、统计或生产写入路径。"""

    def __init__(self, service: NewsIngestionService) -> None:
        self.service = service
        self.collections: list[NewsCollection] = []

    async def collect(self, symbol: Any, *, since: datetime, until: datetime) -> NewsCollection:
        """委托一次实际服务收集，并原样返回不可变结果。"""
        result = await self.service.collect(symbol, since=since, until=until)
        self.collections.append(result)
        return result


class FeedBytes(httpx.AsyncByteStream):
    """以原始异步流模拟 RSS HTTP 响应，生产资源限制和 XML 解析保持生效。"""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.payload


def _series(timeframe: MarketTimeframe) -> CandleSeries:
    """每周期给出五十根已收盘 K 线及一根未来 K 线，验证冻结输入没有前视数据。"""
    duration = {
        MarketTimeframe.M15: timedelta(minutes=15),
        MarketTimeframe.H1: timedelta(hours=1),
        MarketTimeframe.H4: timedelta(hours=4),
        MarketTimeframe.D1: timedelta(days=1),
    }[timeframe]
    candles = tuple(
        Candle(
            symbol=ContractSymbol.BTCUSDT,
            timeframe=timeframe,
            open_at=NOW - duration * (50 - index),
            close_at=NOW - duration * (49 - index),
            open_price=Decimal("68000"),
            high_price=Decimal("100000"),
            low_price=Decimal("67900"),
            close_price=Decimal("99999") if index == 50 else Decimal("68000") + Decimal(index),
            volume=Decimal("10"),
            observed_at=NOW,
            fetched_at=NOW,
        )
        for index in range(51)
    )
    return CandleSeries(timeframe=timeframe, candles=candles)


def _mixed_rss() -> bytes:
    """一条合法英文 BTC 新闻与四种条目拒绝；来源应成功但覆盖只能为 partial。"""
    base = """<item><guid>{key}</guid><title>{title}</title><description>{summary}</description>
    <link>{link}</link><pubDate>{published}</pubDate></item>"""
    good = dict(
        key="accepted",
        title="Bitcoin market update after the public report",
        summary=(
            "The Bitcoin market is stable as traders review the public report and price context."
        ),
        link="https://www.coindesk.com/markets/frozen-capture",
        published="2026-08-10T11:00:00Z",
    )
    entries = [base.format(**good)]
    for overrides in (
        {"key": "missing", "summary": ""},
        {"key": "url", "link": "file:///rejected"},
        {"key": "date", "published": "not-a-date"},
        {
            "key": "language",
            "title": "中文标题",
            "summary": "这是一段不符合英文新闻准入规则的中文摘要。",
        },
    ):
        entries.append(base.format(**{**good, **overrides}))
    return ("<rss><channel>" + "".join(entries) + "</channel></rss>").encode("utf-8")
