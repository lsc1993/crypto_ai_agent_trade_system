from argparse import Namespace
from pathlib import Path

from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command

_BACKEND_DIRECTORY = Path(__file__).resolve().parents[3]


def create_async_engine_from_secret(database_url: SecretStr) -> AsyncEngine:
    """创建仅供持久化用例使用的异步数据库引擎。"""
    return create_async_engine(
        database_url.get_secret_value(),
        pool_pre_ping=True,
    )


def create_database_engine(database_url: SecretStr) -> AsyncEngine:
    """创建数据库引擎，同时保持连接串只在共享配置层展开。"""
    return create_async_engine_from_secret(database_url)


def checkpoint_connection_string(database_url: SecretStr) -> str:
    """Return an in-memory psycopg-compatible URL without logging the secret value."""
    value = database_url.get_secret_value()
    asyncpg_prefix = "postgresql+asyncpg://"
    if value.startswith(asyncpg_prefix):
        return f"postgresql://{value.removeprefix(asyncpg_prefix)}"
    if value.startswith("postgresql://"):
        return value
    raise ValueError("LangGraph checkpoint 仅支持 PostgreSQL 数据库连接")


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """为仓储提供不自动过期的异步会话工厂。"""
    return async_sessionmaker(engine, expire_on_commit=False)


def upgrade_database(database_url: SecretStr, *, schema: str | None = None) -> None:
    """在指定数据库中执行 Alembic 迁移，不记录连接串。"""
    configuration = Config(str(_BACKEND_DIRECTORY / "alembic.ini"))
    configuration.set_main_option("sqlalchemy.url", database_url.get_secret_value())
    if schema is not None:
        configuration.cmd_opts = Namespace(x=[f"schema={schema}"])
    command.upgrade(configuration, "head")
