from __future__ import annotations

import asyncio
import re
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.infrastructure.persistence.models import market
from app.shared.config import AppSettings

config = context.config

if config.config_file_name is not None:
    config_path = Path(config.config_file_name)
    if config_path.read_text(encoding="utf-8").find("[loggers]") >= 0:
        fileConfig(config.config_file_name)

target_metadata = market.Base.metadata
_SCHEMA_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


def _database_url() -> str:
    configured_url = config.get_main_option("sqlalchemy.url")
    if configured_url:
        return configured_url
    database_url = AppSettings().database_url
    if database_url is None:
        raise RuntimeError("DATABASE_URL 未配置，无法执行数据库迁移")
    return database_url.get_secret_value()


def _schema() -> str | None:
    schema = context.get_x_argument(as_dictionary=True).get("schema")
    if schema is None:
        return None
    if _SCHEMA_PATTERN.fullmatch(schema) is None:
        raise RuntimeError("迁移 schema 名称不合法")
    return schema


def _configure_migrations(connection: Connection) -> None:
    schema = _schema()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=schema,
    )
    with context.begin_transaction():
        if schema is not None:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        context.run_migrations()


async def _run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(_configure_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


run_migrations_online()
