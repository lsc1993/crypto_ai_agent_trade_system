# 装配异步 Alembic 迁移环境，读取现有模型元数据和受保护数据库配置。
# 可选 schema 参数经白名单格式验证，用于隔离测试迁移及版本表。
# 使用无连接池引擎并在 finally 关闭；本文件执行时直接运行在线迁移。
from __future__ import annotations

import asyncio
import re
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.infrastructure.persistence.models import market, reports, symbols  # noqa: F401
from app.shared.config import AppSettings

config = context.config

if config.config_file_name is not None:
    config_path = Path(config.config_file_name)
    if config_path.read_text(encoding="utf-8").find("[loggers]") >= 0:
        fileConfig(config.config_file_name)

target_metadata = market.Base.metadata
_SCHEMA_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


# 优先读取迁移配置，否则使用应用秘密配置；缺失时明确失败，不输出连接值。
def _database_url() -> str:
    configured_url = config.get_main_option("sqlalchemy.url")
    if configured_url:
        return configured_url
    database_url = AppSettings().database_url
    if database_url is None:
        raise RuntimeError("DATABASE_URL 未配置，无法执行数据库迁移")
    return database_url.get_secret_value()


# 仅允许受限标识符，避免动态搜索路径包含任意 SQL；未提供时使用默认 schema。
def _schema() -> str | None:
    schema = context.get_x_argument(as_dictionary=True).get("schema")
    if schema is None:
        return None
    if _SCHEMA_PATTERN.fullmatch(schema) is None:
        raise RuntimeError("迁移 schema 名称不合法")
    return schema


# 版本表与业务表使用同一 schema；SET LOCAL 仅影响当前迁移事务。
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


# 异步建立连接，通过同步桥执行迁移；无论失败或成功均释放引擎。
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


# 同步入口负责创建本次迁移所需事件循环，不复用服务运行循环。
def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


run_migrations_online()
