# 验证单次初始同步记录行情能力及安全失败。
# 记录仓储与采集替身保留结束状态，不使用真实公开源。
# 行情成功与 ETF 不支持分别表达，核心采集失败不能伪装为可研究状态。
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import UUID, uuid4

import pytest

from app.market.contracts import MarketDataUnavailableError
from app.symbols.contracts import SyncRun, SyncSource
from app.symbols.sync import ResearchSymbolSyncWorker

NOW = datetime(2030, 1, 1, tzinfo=UTC)


class FinishedRun(TypedDict):
    status: str
    sources: tuple[SyncSource, ...]
    snapshot_id: UUID | None
    error: str | None
    now: datetime


class RecordingRepository:
    def __init__(self, run: SyncRun | None) -> None:
        self.run = run
        self.finished: list[FinishedRun] = []

    async def claim(self, *, now: datetime) -> SyncRun | None:
        assert now == NOW
        return self.run

    async def finish(
        self,
        run: SyncRun,
        *,
        status: str,
        sources: tuple[SyncSource, ...],
        snapshot_id: UUID | None,
        error: str | None,
        now: datetime,
    ) -> bool:
        assert run == self.run
        self.finished.append({
            "status": status,
            "sources": sources,
            "snapshot_id": snapshot_id,
            "error": error,
            "now": now,
        })
        return True


class Capture:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    async def capture_symbol(self, symbol: str, *, captured_at: datetime) -> UUID:
        assert symbol == "SOLUSDT"
        assert captured_at == NOW
        if self.unavailable:
            raise MarketDataUnavailableError("market_data_unavailable", "safe")
        return uuid4()


def _run() -> SyncRun:
    return SyncRun(
        id=uuid4(),
        symbol="SOLUSDT",
        version=1,
        status="running",
        stage="capturing",
        created_at=NOW,
        started_at=NOW,
        lease_token=uuid4(),
        lease_until=NOW + timedelta(seconds=30),
    )


@pytest.mark.asyncio
async def test_sync_marks_market_inputs_ready_and_etf_unsupported() -> None:
    repository = RecordingRepository(_run())
    worker = ResearchSymbolSyncWorker(
        repository=repository,  # type: ignore[arg-type]
        capture=Capture(),  # type: ignore[arg-type]
        funding=None,
        clock=lambda: NOW,
    )

    assert await worker.run_once()
    finished = repository.finished[0]
    assert finished["status"] == "partial"
    sources = finished["sources"]
    assert isinstance(sources, tuple)
    assert {source.name for source in sources} == {
        "market",
        "candles",
        "derivatives",
        "funding",
        "news",
        "sentiment",
        "etf",
    }
    etf = next(source for source in sources if source.name == "etf")
    assert etf.status == "unsupported"
    assert etf.message == "当前数据源不支持"


@pytest.mark.asyncio
async def test_sync_records_safe_core_failure() -> None:
    repository = RecordingRepository(_run())
    worker = ResearchSymbolSyncWorker(
        repository=repository,  # type: ignore[arg-type]
        capture=Capture(unavailable=True),  # type: ignore[arg-type]
        funding=None,
        clock=lambda: NOW,
    )

    assert await worker.run_once()
    finished = repository.finished[0]
    assert finished["status"] == "failed"
    assert finished["error"] == "market_sync_failed"
    sources = finished["sources"]
    assert isinstance(sources, tuple)
    assert sources[0].status == "failed"
    assert sources[0].message == "公开行情同步失败，请稍后重试。"
