from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

import httpx

from app.infrastructure.persistence.repository import SqlAlchemyMarketRepository
from app.market.binance_usdm import BINANCE_USDM_BASE_URL, BinanceUsdmPublicMarketGateway
from app.market.capture import MarketCaptureService
from app.market.contracts import MarketDataUnavailableError
from app.shared.config import AppSettings
from app.shared.database import create_database_engine, create_session_factory


def run_capture(settings: AppSettings | None = None) -> int:
    """运行固定范围的公开市场快照采集。"""
    return asyncio.run(_run_capture(settings or AppSettings()))


async def _run_capture(settings: AppSettings) -> int:
    database_url = settings.database_url
    if database_url is None:
        print("数据库未配置，无法执行市场快照采集", file=sys.stderr)
        return 2

    engine = create_database_engine(database_url)
    try:
        async with httpx.AsyncClient(
            base_url=BINANCE_USDM_BASE_URL,
            headers={"Accept": "application/json"},
        ) as client:
            gateway = BinanceUsdmPublicMarketGateway(
                client=client,
                clock=lambda: datetime.now(UTC),
            )
            repository = SqlAlchemyMarketRepository(create_session_factory(engine))
            snapshot_ids = await MarketCaptureService(gateway, repository).capture(
                captured_at=datetime.now(UTC),
            )
    except MarketDataUnavailableError as error:
        print(f"市场快照采集失败：{error.code}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print(f"市场快照采集完成，已写入 {len(snapshot_ids)} 个快照")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_capture())
