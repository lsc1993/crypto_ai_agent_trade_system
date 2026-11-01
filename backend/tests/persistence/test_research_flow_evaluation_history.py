# 使用专用 migrated_database 的随机 schema 验证技术 v2 降级历史的真实 SQL 保存/读取。
# 固定 HTTP 外壳与独立测试正文仍走生产两阶段适配器、引用校验和 Harness 审计；
# 不复用开发评估语料、不导入测试私有 helper，也不连接真实模型或交易所。
from __future__ import annotations

import json
from typing import Protocol
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.technical.plan_service import TechnicalPlanResearchService
from app.harness.technical_research import HarnessedTechnicalPlanExecutor
from app.infrastructure.persistence.harness_audit_repository import SqlAlchemyHarnessAuditRepository
from app.infrastructure.persistence.technical_report_repository import (
    SqlAlchemyTechnicalReportRepository,
)
from app.reports.technical_plan import TechnicalPlanReport
from scripts.evaluate_research_flows import no_lease, no_progress, technical_model
from scripts.research_flow_fixtures import NOW, MarketRecipe, OfflineMarket, build_market


class Database(Protocol):
    """只要求随机 schema 的会话工厂，测试不访问夹具内部连接配置。"""

    session_factory: async_sessionmaker[AsyncSession]


async def admitted(symbol: str) -> bool:
    """仅准入合成场景使用的公开 BTC 标的。"""
    return symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_real_repository_reads_immutable_degraded_v2_history(
    migrated_database: Database,
) -> None:
    """分析格式拒绝、编排超时及数据不足保存后可由新仓储重读，且审计闭环。"""
    recipe = MarketRecipe(
        version="synthetic-breakout-v1",
        initial_price="80.0",
        step="0.3",
        plateau="105.0",
        last_close="106.2",
        swing_low="98.0",
        swing_high="125.0",
    )
    factory = migrated_database.session_factory
    repository = SqlAlchemyTechnicalReportRepository(factory)
    audit = SqlAlchemyHarnessAuditRepository(factory)
    reports: list[TechnicalPlanReport] = []
    for scenario, expected_quality, expected_calls in (
        ("analysis", "analysis_unavailable", ["analysis", "analysis"]),
        ("composition", "composition_fallback", ["analysis", "composition", "composition"]),
        ("insufficient", "data_insufficient", []),
    ):
        calls: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            stage = "analysis" if payload["thinking"]["type"] == "enabled" else "composition"
            calls.append(stage)
            if scenario == "composition" and stage == "composition":
                raise httpx.ReadTimeout("PRIVATE_PERSISTENCE_TIMEOUT", request=request)
            frozen = json.loads(payload["messages"][1]["content"])["frozenContext"]
            evidence_id = frozen["analysis"]["evidenceId"]

            def claim(ref: str) -> dict[str, object]:
                return {
                    "text": "持久化回归依据{{" + ref + "}}解释冻结结构，等待后续收盘复核相反证据。",
                    "evidenceId": evidence_id,
                    "factRefs": [ref],
                    "methodRefs": [],
                }

            general = claim("facts.volumeRatio")
            decision = {
                "stance": "long",
                "selectedPlanRef": "plans.0",
                **{
                    key: [general]
                    for key in (
                        "marketStructure",
                        "supportingEvidence",
                        "counterEvidence",
                        "invalidation",
                        "alternative",
                        "waitingConditions",
                        "risks",
                    )
                },
                "methodApplications": [{**general, "methodRefs": ["volume_price"]}],
                "entryConditions": [claim("plans.0.triggerLevel")],
                "stopRationale": [claim("plans.0.stopLoss")],
                "targetRationale": [claim("plans.0.target")],
            }
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": "PRIVATE_PERSISTENCE_BAD_JSON"
                                if scenario == "analysis"
                                else json.dumps(decision, ensure_ascii=False),
                                "reasoning_content": "PRIVATE_PERSISTENCE_REASONING",
                            },
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            service = TechnicalPlanResearchService(
                market=OfflineMarket(build_market(recipe), insufficient=scenario == "insufficient"),
                repository=repository,
                model=technical_model(client),
                clock=lambda: NOW,
            )
            executor = HarnessedTechnicalPlanExecutor(
                service,
                audit=audit,
                authorizer=admitted,
                clock=lambda: NOW,
            )
            report = await executor.generate(
                "BTCUSDT", analysis_id=uuid4(), progress=no_progress, before_save=no_lease
            )
        assert report.status == "degraded"
        assert report.generation.quality == expected_quality
        assert calls == expected_calls
        # 重新装配仓储和会话后按两种身份读取，证明结果不是内存服务对象的旁路回传。
        fresh_reader = SqlAlchemyTechnicalReportRepository(factory)
        assert await fresh_reader.get(report.id) == report
        assert await fresh_reader.get_by_analysis_id(report.analysis_id) == report
        assert "PRIVATE_PERSISTENCE" not in report.model_dump_json()
        trace = await audit.get_trace(report.analysis_id)
        assert trace is not None
        assert trace.events[-1].kind.value == "workflow_degraded"
        reports.append(report)
    page = await SqlAlchemyTechnicalReportRepository(factory).list(
        symbol="BTCUSDT", page=1, page_size=10
    )
    assert {item.id for item in page.items} == {report.id for report in reports}
    assert page.total == 3
