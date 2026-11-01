# 提供后端数据库回归共用的已迁移临时 schema 夹具。
# 每次使用独立随机名称，连接映射与迁移搜索路径指向同一测试 schema。
# 仅在专用测试 PostgreSQL 上运行；finally 释放引擎并清理本次临时 schema。
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.shared.database import (
    create_async_engine_from_secret,
    create_session_factory,
    upgrade_database,
)
from scripts.check_test_database import DatabaseGuardError, check_test_database


@dataclass(frozen=True)
class MigratedDatabase:
    session_factory: async_sessionmaker[AsyncSession]


# fixture 闭包包含间接依赖，因此 API、仓储与独立迁移测试均可按能力选择。
# tryfirst 确保内置 -m 过滤之前加标记，不依靠目录名猜测数据库需求。
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if isinstance(item, pytest.Function) and "checked_test_database_url" in item.fixturenames:
            item.add_marker(pytest.mark.database)


# 每次 pytest 进程自行预检，不信任先前 doctor 的结果；失败不会创建引擎或 schema。
# session 缓存只保留本次运行核验的 SecretStr，避免每个用例重复连接只读预检。
@pytest.fixture(scope="session")
def checked_test_database_url() -> SecretStr:
    try:
        return asyncio.run(check_test_database())
    except DatabaseGuardError as error:
        pytest.fail(f"test database preflight blocked: {error}", pytrace=False)


# 唯一 schema 既用于 ORM 表映射也用于迁移版本表隔离，防止并行测试互相覆盖。
# yield 后无论测试成功还是失败都释放连接并清理本次 schema。
@pytest_asyncio.fixture
async def migrated_database(
    checked_test_database_url: SecretStr,
) -> AsyncIterator[MigratedDatabase]:
    """提供迁移后的临时 schema，避免测试接触开发数据库。"""
    database_url = checked_test_database_url
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


# 名称由本夹具生成而非外部输入；使用独立引擎保证建库连接及时释放。
async def _create_schema(database_url: SecretStr, schema: str) -> None:
    engine = create_async_engine_from_secret(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        await engine.dispose()


# 级联范围仅为本次随机测试 schema，不清理业务 schema 或数据库。
async def _drop_schema(database_url: SecretStr, schema: str) -> None:
    engine = create_async_engine_from_secret(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        await engine.dispose()
