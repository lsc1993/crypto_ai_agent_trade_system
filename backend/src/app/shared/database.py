# 集中建立异步数据库引擎、会话工厂和迁移入口。
# 仅在驱动连接或 Alembic 配置需要时展开 SecretStr；checkpoint 使用兼容 Psycopg 的 URL。
# 会话不自动提交业务事务；调用仓储决定事务范围，迁移调用方决定目标库和 schema。
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


# 只在驱动连接边界展开连接串，开启连接健康检查；返回引擎但不执行建表。
def create_async_engine_from_secret(database_url: SecretStr) -> AsyncEngine:
    """创建仅供持久化用例使用的异步数据库引擎。"""
    return create_async_engine(
        database_url.get_secret_value(),
        pool_pre_ping=True,
    )


# 共享引擎创建入口，委托 SecretStr 版本并返回 AsyncEngine，调用者负责 dispose。
def create_database_engine(database_url: SecretStr) -> AsyncEngine:
    """创建数据库引擎，同时保持连接串只在共享配置层展开。"""
    return create_async_engine_from_secret(database_url)


# 把 asyncpg URL 转成 Psycopg 可用 PostgreSQL URL；仅返回内存字符串，不记录连接值。
def checkpoint_connection_string(database_url: SecretStr) -> str:
    """Return an in-memory psycopg-compatible URL without logging the secret value."""
    value = database_url.get_secret_value()
    asyncpg_prefix = "postgresql+asyncpg://"
    if value.startswith(asyncpg_prefix):
        return f"postgresql://{value.removeprefix(asyncpg_prefix)}"
    if value.startswith("postgresql://"):
        return value
    raise ValueError("LangGraph checkpoint 仅支持 PostgreSQL 数据库连接")


# 返回绑定引擎且提交后不过期的会话工厂，使事务外的已加载记录可以继续映射。
def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """为仓储提供不自动过期的异步会话工厂。"""
    return async_sessionmaker(engine, expire_on_commit=False)


# 用指定密钥连接执行 Alembic head；可指定测试 schema，调用方必须确认目标数据库。
def upgrade_database(database_url: SecretStr, *, schema: str | None = None) -> None:
    """在指定数据库中执行 Alembic 迁移，不记录连接串。"""
    configuration = Config(str(_BACKEND_DIRECTORY / "alembic.ini"))
    configuration.set_main_option("sqlalchemy.url", database_url.get_secret_value())
    if schema is not None:
        configuration.cmd_opts = Namespace(x=[f"schema={schema}"])
    command.upgrade(configuration, "head")
