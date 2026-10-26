# 验证模拟绩效迁移为旧账户补充不可变基线。
# 先迁移至旧版本并种入历史账户，再升级观察估值记录。
# 回填标记为部分历史，不能伪造当时不存在的完整估值序列。
from __future__ import annotations

import asyncio
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.sql.elements import TextClause

from alembic import command
from app.shared.config import AppSettings

NOW = datetime(2026, 8, 6, 12, tzinfo=UTC)
ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000909")
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000910")
BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]


def test_paper_performance_migration_backfills_an_immutable_partial_history() -> None:
    database_url = AppSettings().test_database_url
    assert database_url is not None
    schema = f"paper_performance_test_{uuid4().hex[:16]}"

    asyncio.run(_create_schema(database_url, schema))
    try:
        _upgrade(database_url, schema, "0006_create_paper_trading")
        asyncio.run(_seed_legacy_account(database_url, schema))
        _upgrade(database_url, schema, "head")

        valuations = asyncio.run(_valuations(database_url, schema))

        assert valuations == [
            (0, "initial", None, "10000.000000000000000000"),
            (1, "migration_baseline", SNAPSHOT_ID, "9750.000000000000000000"),
        ]
        with pytest.raises(DBAPIError, match="immutable"):
            asyncio.run(
                _execute_in_schema(
                    database_url,
                    schema,
                    text("UPDATE paper_account_valuations SET equity = equity"),
                    {},
                )
            )
    finally:
        asyncio.run(_drop_schema(database_url, schema))


def _upgrade(database_url: SecretStr, schema: str, revision: str) -> None:
    configuration = Config(str(BACKEND_DIRECTORY / "alembic.ini"))
    configuration.set_main_option("sqlalchemy.url", database_url.get_secret_value())
    configuration.cmd_opts = Namespace(x=[f"schema={schema}"])
    command.upgrade(configuration, revision)


# 名称由本夹具生成而非外部输入；使用独立引擎保证建库连接及时释放。
async def _create_schema(database_url: SecretStr, schema: str) -> None:
    engine = _database_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        await engine.dispose()


async def _seed_legacy_account(database_url: SecretStr, schema: str) -> None:
    engine = _database_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await connection.execute(
                text(
                    "INSERT INTO paper_accounts ("
                    "id, status, symbol, initial_cash, cash, equity, peak_equity, "
                    "daily_start_equity, daily_realized_loss, daily_day, cooldown_remaining, "
                    "risk_config, execution_config, created_at"
                    ") VALUES ("
                    ":id, 'active', 'BTCUSDT', 10000, 8000, 9750, 10000, "
                    "10000, 0, DATE '2026-08-06', 0, '{}'::jsonb, '{}'::jsonb, :created_at"
                    ")"
                ),
                {"id": ACCOUNT_ID, "created_at": NOW},
            )
            await connection.execute(
                text(
                    "INSERT INTO paper_positions ("
                    "account_id, quantity, average_entry_price, remaining_entry_cost, opened_at, "
                    "updated_at"
                    ") VALUES (:account_id, 10, 175, 1750, :opened_at, :updated_at)"
                ),
                {"account_id": ACCOUNT_ID, "opened_at": NOW, "updated_at": NOW},
            )
            await connection.execute(
                text(
                    "INSERT INTO paper_market_snapshots ("
                    "id, account_id, price, source, observed_at, fetched_at, payload_hash"
                    ") VALUES ("
                    ":id, :account_id, 175, 'binance_usdm_public', :observed_at, "
                    ":fetched_at, :payload_hash"
                    ")"
                ),
                {
                    "id": SNAPSHOT_ID,
                    "account_id": ACCOUNT_ID,
                    "observed_at": NOW,
                    "fetched_at": NOW,
                    "payload_hash": "b" * 64,
                },
            )
    finally:
        await engine.dispose()


async def _valuations(
    database_url: SecretStr,
    schema: str,
) -> list[tuple[int, str, UUID | None, str]]:
    engine = _database_engine(database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            result = await connection.execute(
                text(
                    "SELECT sequence, kind, snapshot_id, equity::text "
                    "FROM paper_account_valuations ORDER BY sequence"
                )
            )
            return list(result.tuples())
    finally:
        await engine.dispose()


async def _execute_in_schema(
    database_url: SecretStr,
    schema: str,
    statement: TextClause,
    parameters: dict[str, object],
) -> None:
    engine = _database_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await connection.execute(statement, parameters)
    finally:
        await engine.dispose()


# 级联范围仅为本次随机测试 schema，不清理业务 schema 或数据库。
async def _drop_schema(database_url: SecretStr, schema: str) -> None:
    engine = _database_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        await engine.dispose()


def _database_engine(database_url: SecretStr):
    from app.shared.database import create_async_engine_from_secret

    return create_async_engine_from_secret(database_url)
