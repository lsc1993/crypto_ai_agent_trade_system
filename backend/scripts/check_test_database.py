# 提供测试专用 PostgreSQL 的集中准入和只读命令；不创建数据库、角色或 schema。
# 测试目标只来自显式进程环境，业务地址同时参考本地配置作为拒绝依据。
# 所有错误仅暴露固定摘要；禁止把 URL、密码、驱动异常带入日志或 pytest 错误。
from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource
from sqlalchemy import make_url, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

_BACKEND = Path(__file__).resolve().parents[1]
_ENV_FILES = (_BACKEND / ".env", _BACKEND.parent / ".env")
_DATABASE = "crypto_research_test"
_ROLE = "crypto_research_test_runner"


class DatabaseGuardError(RuntimeError):
    # 异常只承载由本模块生成的固定原因，不接受驱动错误作为公开消息。
    pass


@dataclass(frozen=True)
class DatabaseIdentity:
    # 只读服务端查询的最小契约；不包含地址、密码或业务数据。
    database: str
    user: str
    superuser: bool
    create_database: bool
    create_role: bool
    replication: bool
    bypass_rls: bool
    can_login: bool
    role_memberships: bool
    can_connect: bool
    can_create_schema: bool


class _BusinessSettings(BaseSettings):
    # 仅用于获取本地业务地址拒绝清单；不解析模型设置和测试连接。
    model_config = SettingsConfigDict(extra="ignore", env_file_encoding="utf-8")
    database_url: SecretStr | None = None


def _parse_url(value: str) -> URL:
    # SQLAlchemy 解析错误可能带上原始输入，必须在边界替换为固定异常。
    try:
        url = make_url(value)
        _ = url.port
        return url
    except Exception:
        raise DatabaseGuardError("invalid database configuration") from None


def _test_target(environment: Mapping[str, str], env_files: tuple[Path, ...]) -> SecretStr:
    # 空值、非 asyncpg、非固定专用身份或 query 覆盖 host/database 都应在联网前拒绝。
    value = environment.get("TEST_DATABASE_URL", "").strip()
    if not value:
        raise DatabaseGuardError("explicit TEST_DATABASE_URL is required")
    url = _parse_url(value)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.database != _DATABASE
        or url.username != _ROLE
        or not url.host
        or url.query
        or (url.port is not None and not 1 <= url.port <= 65535)
    ):
        raise DatabaseGuardError("dedicated test database and restricted role are required")

    business_urls = [environment.get("DATABASE_URL", "")]
    try:
        for path in env_files:
            if path.is_file():
                # 单独调用 dotenv 来源，避免进程配置遮盖文件中的业务目标。
                # 只提取业务字段；dotenv 的测试地址绝不会用于授权。
                values = DotEnvSettingsSource(_BusinessSettings, env_file=path)()
                business_value = values.get("database_url")
                if isinstance(business_value, str):
                    business_urls.append(business_value)
    except Exception:
        raise DatabaseGuardError("business database configuration cannot be checked") from None

    for business_value in business_urls:
        if not business_value:
            continue
        business = _parse_url(business_value)
        if "database" in business.query or "dbname" in business.query:
            raise DatabaseGuardError("ambiguous business database configuration")
        if business.database == url.database:
            # 故意保守：同库名即拒绝，不依赖驱动、凭证、端口或 DNS 名称相等。
            # 这也会拒绝不同集群上的同名业务库，避免主机别名/代理造成漏判。
            raise DatabaseGuardError("business and test database names must be distinct")
    return SecretStr(value)


async def read_database_identity(database_url: SecretStr) -> DatabaseIdentity:
    # 连接自启动即只读，事务再显式只读；超时限制连接与查询等待。
    # 只查当前数据库、角色标志和成员资格，不访问业务表、不修改数据库设置。
    engine = create_async_engine(
        database_url.get_secret_value(),
        connect_args={
            "timeout": 5,
            "command_timeout": 5,
            "server_settings": {"default_transaction_read_only": "on"},
        },
        echo=False,
        hide_parameters=True,
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            result = await connection.execute(
                text(
                    "SELECT current_database() AS database, current_user AS username, "
                    "r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolreplication, "
                    "r.rolbypassrls, r.rolcanlogin, "
                    "EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member = r.oid) "
                    "AS role_memberships, "
                    "has_database_privilege(current_user, current_database(), 'CONNECT') "
                    "AS can_connect, "
                    "has_database_privilege(current_user, current_database(), 'CREATE') "
                    "AS can_create_schema "
                    "FROM pg_roles r WHERE r.rolname = current_user"
                )
            )
            row = result.mappings().one()
            return DatabaseIdentity(
                database=str(row["database"]),
                user=str(row["username"]),
                superuser=bool(row["rolsuper"]),
                create_database=bool(row["rolcreatedb"]),
                create_role=bool(row["rolcreaterole"]),
                replication=bool(row["rolreplication"]),
                bypass_rls=bool(row["rolbypassrls"]),
                can_login=bool(row["rolcanlogin"]),
                role_memberships=bool(row["role_memberships"]),
                can_connect=bool(row["can_connect"]),
                can_create_schema=bool(row["can_create_schema"]),
            )
    finally:
        await engine.dispose()


async def check_test_database(
    environment: Mapping[str, str] | None = None,
    *,
    env_files: tuple[Path, ...] = _ENV_FILES,
    reader: Callable[[SecretStr], Awaitable[DatabaseIdentity]] = read_database_identity,
) -> SecretStr:
    # 返回经过配置和服务端双重核验的秘密地址，供测试随后建立自己的写入连接。
    # 替身协议只服务离线回归；普通 CLI/pytest 均使用真正的只读身份查询。
    database_url = _test_target(os.environ if environment is None else environment, env_files)
    try:
        identity = await reader(database_url)
    except Exception:
        raise DatabaseGuardError("test database connection or identity query failed") from None
    if identity.database != _DATABASE or identity.user != _ROLE:
        raise DatabaseGuardError("test database server identity does not match")
    if any(
        (
            identity.superuser,
            identity.create_database,
            identity.create_role,
            identity.replication,
            identity.bypass_rls,
            identity.role_memberships,
            not identity.can_login,
            not identity.can_connect,
            not identity.can_create_schema,
        )
    ):
        # 全部成员资格都拒绝，包括可 SET ROLE 的管理员/预定义角色，避免间接超权。
        raise DatabaseGuardError("test database role privileges are not restricted")
    return database_url


def main() -> int:
    # doctor 使用固定安全输出与退出码：缺配置/连接失败/拒绝均为 2，不执行修复。
    try:
        asyncio.run(check_test_database())
    except DatabaseGuardError as error:
        print(f"test database: blocked ({error})")
        return 2
    print("test database: passed (read-only identity and restricted role verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
