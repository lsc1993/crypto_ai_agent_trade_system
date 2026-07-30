from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

import pytest
from pydantic import JsonValue
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.reports import (
    AnalysisEvidenceRecord,
    AnalysisReportRecord,
)
from app.infrastructure.persistence.report_repository import (
    SqlAlchemyAnalysisReportRepository,
)
from app.market.contracts import ContractSymbol
from app.reports.contracts import (
    AnalysisEvidenceDraft,
    AnalysisReportCreation,
    AnalysisReportDraft,
    AnalysisReportStatus,
    report_payload_sha256,
)

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


class MigratedDatabase(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


@pytest.mark.asyncio
async def test_repository_persists_a_report_and_frozen_evidence(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyAnalysisReportRepository(migrated_database.session_factory)
    creation = _completed_creation("00000000-0000-0000-0000-000000000001")

    persisted = await repository.persist(creation)
    loaded = await repository.get_by_id(persisted.id)

    assert loaded is not None
    assert loaded == persisted
    assert loaded.analysis_id == creation.report.analysis_id
    assert loaded.evidence[0].payload == creation.evidences[0].payload
    assert loaded.evidence[0].report_id == persisted.id


@pytest.mark.asyncio
async def test_repository_filters_persisted_report_summaries(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyAnalysisReportRepository(migrated_database.session_factory)
    btc = await repository.persist(
        _completed_creation("00000000-0000-0000-0000-000000000011"),
    )
    await repository.persist(
        _degraded_creation("00000000-0000-0000-0000-000000000012"),
    )

    page = await repository.list(
        page=1,
        page_size=20,
        symbol=ContractSymbol.BTCUSDT,
        status=AnalysisReportStatus.COMPLETED,
    )

    assert page.total == 1
    assert page.items[0].id == btc.id
    assert page.items[0].status is AnalysisReportStatus.COMPLETED


@pytest.mark.asyncio
async def test_database_rejects_report_and_evidence_mutation(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyAnalysisReportRepository(migrated_database.session_factory)
    persisted = await repository.persist(
        _completed_creation("00000000-0000-0000-0000-000000000021"),
    )

    async with migrated_database.session_factory() as session:
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(
                update(AnalysisReportRecord)
                .where(AnalysisReportRecord.id == persisted.id)
                .values(title="changed"),
            )
            await session.commit()
        await session.rollback()

        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(
                delete(AnalysisEvidenceRecord).where(
                    AnalysisEvidenceRecord.id == persisted.evidence[0].id,
                )
            )
            await session.commit()


def _completed_creation(analysis_id: str) -> AnalysisReportCreation:
    report_id = UUID(analysis_id)
    report = AnalysisReportDraft(
        id=report_id,
        analysis_id=UUID(analysis_id),
        symbol=ContractSymbol.BTCUSDT,
        status=AnalysisReportStatus.COMPLETED,
        title="BTCUSDT 持久化市场研究",
        summary="本报告只陈述已冻结的公开市场观察。",
        facts=("价格来自已持久化的公开市场快照。",),
        inferences=("这些观察不构成方向或交易结论。",),
        risks=("市场数据可能随时间过期。",),
        limitations=("报告未访问账户、模型或实时市场。",),
        generated_at=NOW,
        data_cutoff_at=NOW - timedelta(minutes=1),
    )
    payload: dict[str, JsonValue] = {"summary": {"symbol": "BTCUSDT"}}
    evidence = AnalysisEvidenceDraft(
        report_id=report.id,
        symbol=ContractSymbol.BTCUSDT,
        source="binance_usdm_public_rest",
        source_url="https://www.binance.com/en/futures/BTCUSDT",
        observed_at=NOW - timedelta(minutes=1),
        fetched_at=NOW,
        summary="BTCUSDT 持久化市场快照",
        payload=payload,
        payload_sha256=report_payload_sha256(payload),
    )
    return AnalysisReportCreation(report=report, evidences=(evidence,))


def _degraded_creation(analysis_id: str) -> AnalysisReportCreation:
    report = AnalysisReportDraft(
        id=UUID(analysis_id),
        analysis_id=UUID(analysis_id),
        symbol=ContractSymbol.ETHUSDT,
        status=AnalysisReportStatus.DEGRADED,
        title="ETHUSDT 持久化市场研究已降级",
        summary="无法形成市场研究结论。",
        facts=(),
        inferences=(),
        risks=("持久化市场数据缺失。",),
        limitations=("本报告未形成市场结论。",),
        generated_at=NOW,
        data_cutoff_at=None,
    )
    return AnalysisReportCreation(report=report, evidences=())
