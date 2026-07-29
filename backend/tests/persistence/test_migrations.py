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


async def _drop_schema(database_url: SecretStr, schema: str) -> None:
    database = import_module("app.shared.database")
    engine = database.create_async_engine_from_secret(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        await engine.dispose()
