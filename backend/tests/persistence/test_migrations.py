import asyncio
from importlib import import_module
from importlib.util import find_spec
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.shared.config import AppSettings


@pytest.mark.asyncio
async def test_database_engine_factory_uses_an_asyncpg_postgresql_url() -> None:
    assert find_spec("app.shared.database") is not None
    database = import_module("app.shared.database")
    factory = database.create_async_engine_from_secret
    engine = factory(
        SecretStr("postgresql+asyncpg://user:password@localhost/research"),
    )

    try:
        assert engine.url.get_backend_name() == "postgresql"
        assert engine.url.get_driver_name() == "asyncpg"
    finally:
        await engine.dispose()


def test_alembic_upgrade_creates_its_version_table_in_an_isolated_schema() -> None:
    database = import_module("app.shared.database")
    upgrade_database = getattr(database, "upgrade_database", None)

    assert callable(upgrade_database)
    test_database_url = AppSettings().test_database_url
    assert test_database_url is not None
    schema = f"market_test_{uuid4().hex[:16]}"

    asyncio.run(_create_schema(test_database_url, schema))
    try:
        upgrade_database(test_database_url, schema=schema)
        assert asyncio.run(_version_table_schemas(test_database_url)) == [schema]
    finally:
        asyncio.run(_drop_schema(test_database_url, schema))


def test_market_migration_creates_numeric_candle_columns_and_unique_key() -> None:
    test_database_url = AppSettings().test_database_url
    assert test_database_url is not None
    schema = f"market_test_{uuid4().hex[:16]}"

    asyncio.run(_create_schema(test_database_url, schema))
    try:
        database = import_module("app.shared.database")
        database.upgrade_database(test_database_url, schema=schema)
        columns = asyncio.run(_table_column_types(test_database_url, schema, "market_candles"))
        constraints = asyncio.run(
            _table_constraint_columns(test_database_url, schema, "market_candles")
        )

        assert columns["close_price"] == "numeric"
        assert columns["open_at"] == "timestamp with time zone"
        assert ("UNIQUE", ("symbol", "timeframe", "open_at")) in constraints
    finally:
        asyncio.run(_drop_schema(test_database_url, schema))


def test_backtest_migration_creates_immutable_numeric_snapshot_tables() -> None:
    test_database_url = AppSettings().test_database_url
    assert test_database_url is not None
    schema = f"market_test_{uuid4().hex[:16]}"

    asyncio.run(_create_schema(test_database_url, schema))
    try:
        database = import_module("app.shared.database")
        database.upgrade_database(test_database_url, schema=schema)
        runs = asyncio.run(_table_column_types(test_database_url, schema, "backtest_runs"))
        candles = asyncio.run(
            _table_column_types(test_database_url, schema, "backtest_candles")
        )
        events = asyncio.run(_table_column_types(test_database_url, schema, "backtest_events"))
        candle_constraints = asyncio.run(
            _table_constraint_columns(test_database_url, schema, "backtest_candles")
        )
        event_constraints = asyncio.run(
            _table_constraint_columns(test_database_url, schema, "backtest_events")
        )

        assert runs["initial_cash"] == "numeric"
        assert candles["close_price"] == "numeric"
        assert events["payload"] == "jsonb"
        assert ("PRIMARY KEY", ("run_id", "sequence")) in candle_constraints
        assert ("PRIMARY KEY", ("run_id", "sequence")) in event_constraints
    finally:
        asyncio.run(_drop_schema(test_database_url, schema))


async def _create_schema(database_url: SecretStr, schema: str) -> None:
    database = import_module("app.shared.database")
    engine = database.create_async_engine_from_secret(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        await engine.dispose()


async def _version_table_schemas(database_url: SecretStr) -> list[str]:
    database = import_module("app.shared.database")
    engine = database.create_async_engine_from_secret(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT table_schema FROM information_schema.tables "
                    "WHERE table_name = 'alembic_version' ORDER BY table_schema",
                ),
            )
            return list(result.scalars())
    finally:
        await engine.dispose()


async def _table_column_types(
    database_url: SecretStr,
    schema: str,
    table: str,
) -> dict[str, str]:
    database = import_module("app.shared.database")
    engine = database.create_async_engine_from_secret(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table",
                ),
                {"schema": schema, "table": table},
            )
            return dict(result.all())
    finally:
        await engine.dispose()


async def _table_constraint_columns(
    database_url: SecretStr,
    schema: str,
    table: str,
) -> set[tuple[str, tuple[str, ...]]]:
    database = import_module("app.shared.database")
    engine = database.create_async_engine_from_secret(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT constraint_type, constraint_name "
                    "FROM information_schema.table_constraints "
                    "WHERE table_schema = :schema AND table_name = :table",
                ),
                {"schema": schema, "table": table},
            )
            constraints: set[tuple[str, tuple[str, ...]]] = set()
            for constraint_type, constraint_name in result.tuples():
                column_result = await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.key_column_usage "
                        "WHERE table_schema = :schema AND table_name = :table "
                        "AND constraint_name = :constraint_name ORDER BY ordinal_position",
                    ),
                    {
                        "schema": schema,
                        "table": table,
                        "constraint_name": constraint_name,
                    },
                )
                constraints.add((constraint_type, tuple(column_result.scalars())))
            return constraints
    finally:
        await engine.dispose()


async def _drop_schema(database_url: SecretStr, schema: str) -> None:
    database = import_module("app.shared.database")
    engine = database.create_async_engine_from_secret(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        await engine.dispose()
