from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.shared.config import AppSettings
from app.shared.database import (
    create_async_engine_from_secret,
    create_session_factory,
    upgrade_database,
)


@dataclass(frozen=True)
class MigratedDatabase:
    session_factory: async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture
async def migrated_database() -> AsyncIterator[MigratedDatabase]:
    """提供迁移后的临时 schema，避免测试接触开发数据库。"""
    database_url = AppSettings().test_database_url
    assert database_url is not None
    schema = f"market_test_{uuid4().hex[:16]}"
    engine = create_async_engine_from_secret(database_url).execution_options(
        schema_translate_map={None: schema},
    )

    await _create_schema(database_url, schema)
    try:
        await asyncio.to_thread(upgrade_database, database_url, schema=schema)
        yield MigratedDatabase(session_factory=create_session_factory(engine))
    finally:
        await engine.dispose()
        await _drop_schema(database_url, schema)


async def _create_schema(database_url: SecretStr, schema: str) -> None:
    engine = create_async_engine_from_secret(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        await engine.dispose()


async def _drop_schema(database_url: SecretStr, schema: str) -> None:
    engine = create_async_engine_from_secret(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        await engine.dispose()
