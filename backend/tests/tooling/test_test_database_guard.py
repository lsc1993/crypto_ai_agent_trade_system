# 验证测试库准入在写入前失败，并以只读身份替身覆盖真实数据库不可用的环境。
# 所有 URL 均为虚构测试值；拒绝路径不得连接网络或泄漏连接串和驱动异常。
from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

pytest_plugins = ["pytester"]

if TYPE_CHECKING:
    from scripts.check_test_database import DatabaseIdentity

SAFE_URL = (
    "postgresql+asyncpg://crypto_research_test_runner:synthetic-secret@"
    "127.0.0.1:55432/crypto_research_test"
)


def identity() -> DatabaseIdentity:
    # 固定返回受限角色和专用库，测试各危险权限时只改变待验证的一项。
    guard = import_module("scripts.check_test_database")
    return guard.DatabaseIdentity(
        database="crypto_research_test",
        user="crypto_research_test_runner",
        superuser=False,
        create_database=False,
        create_role=False,
        replication=False,
        bypass_rls=False,
        can_login=True,
        role_memberships=False,
        can_connect=True,
        can_create_schema=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"TEST_DATABASE_URL": "invalid-sensitive-url"},
        {"TEST_DATABASE_URL": SAFE_URL.replace("+asyncpg", "+psycopg")},
        {"TEST_DATABASE_URL": SAFE_URL.replace("/crypto_research_test", "/crypto_research")},
        {"TEST_DATABASE_URL": SAFE_URL.replace("crypto_research_test_runner:", "postgres:")},
        {"TEST_DATABASE_URL": SAFE_URL + "?host=business-server"},
        {
            "TEST_DATABASE_URL": SAFE_URL,
            "DATABASE_URL": "postgresql+psycopg://other:different@alias:5432/crypto_research_test",
        },
    ],
)
async def test_unsafe_configuration_rejected_before_connection(environment: dict[str, str]) -> None:
    # 删除配置门禁会触发替身中的断言，证明错误配置未进入连接或写入阶段。
    guard = import_module("scripts.check_test_database")
    connected = False

    async def forbidden(_: SecretStr) -> DatabaseIdentity:
        nonlocal connected
        connected = True
        return identity()

    with pytest.raises(guard.DatabaseGuardError):
        await guard.check_test_database(environment, env_files=(), reader=forbidden)
    assert not connected


@pytest.mark.asyncio
async def test_dotenv_test_url_never_authorizes_database_access(tmp_path: Path) -> None:
    guard = import_module("scripts.check_test_database")
    local_env = tmp_path / ".env"
    local_env.write_text(f"TEST_DATABASE_URL={SAFE_URL}\n", encoding="utf-8")
    with pytest.raises(guard.DatabaseGuardError):
        await guard.check_test_database({}, env_files=(local_env,))


@pytest.mark.asyncio
async def test_dotenv_business_target_still_blocks_test_connection(tmp_path: Path) -> None:
    guard = import_module("scripts.check_test_database")
    local_env = tmp_path / ".env"
    local_env.write_text(f"DATABASE_URL={SAFE_URL}\n", encoding="utf-8")

    async def read(_: SecretStr) -> DatabaseIdentity:
        return identity()

    with pytest.raises(guard.DatabaseGuardError):
        await guard.check_test_database(
            {"TEST_DATABASE_URL": SAFE_URL}, env_files=(local_env,), reader=read
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database", "crypto_research"),
        ("user", "postgres"),
        ("superuser", True),
        ("create_database", True),
        ("create_role", True),
        ("replication", True),
        ("bypass_rls", True),
        ("role_memberships", True),
        ("can_login", False),
        ("can_connect", False),
        ("can_create_schema", False),
    ],
)
async def test_server_identity_and_privileges_are_checked(field: str, value: object) -> None:
    guard = import_module("scripts.check_test_database")

    async def read(_: SecretStr) -> DatabaseIdentity:
        return replace(identity(), **{field: value})

    with pytest.raises(guard.DatabaseGuardError):
        await guard.check_test_database({"TEST_DATABASE_URL": SAFE_URL}, env_files=(), reader=read)


@pytest.mark.asyncio
async def test_independent_port_and_restricted_role_pass() -> None:
    guard = import_module("scripts.check_test_database")

    async def read(_: SecretStr) -> DatabaseIdentity:
        return identity()

    checked = await guard.check_test_database(
        {"TEST_DATABASE_URL": SAFE_URL, "DATABASE_URL": "postgresql://app@localhost/research"},
        env_files=(),
        reader=read,
    )
    assert checked.get_secret_value() == SAFE_URL
    assert "synthetic-secret" not in repr(checked)


@pytest.mark.asyncio
async def test_connection_error_is_sanitized() -> None:
    guard = import_module("scripts.check_test_database")

    async def read(_: SecretStr) -> DatabaseIdentity:
        raise RuntimeError(f"driver failed {SAFE_URL}")

    with pytest.raises(guard.DatabaseGuardError) as error:
        await guard.check_test_database({"TEST_DATABASE_URL": SAFE_URL}, env_files=(), reader=read)
    assert "synthetic-secret" not in str(error.value)
    assert SAFE_URL not in str(error.value)
    assert error.value.__suppress_context__


def test_cli_missing_configuration_returns_two_without_sensitive_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    guard = import_module("scripts.check_test_database")
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    assert guard.main() == 2
    output = capsys.readouterr()
    assert "blocked" in output.out
    assert "postgresql" not in output.out + output.err


@pytest.mark.asyncio
async def test_identity_reader_uses_read_only_transaction_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 数据库协议替身捕获真正查询入口；若删去只读设置或加入写 SQL，本测试失败。
    guard = import_module("scripts.check_test_database")
    statements: list[str] = []
    engine_options: dict[str, object] = {}
    disposed = False

    class Result:
        def mappings(self) -> Result:
            return self

        def one(self) -> dict[str, object]:
            return {
                "database": "crypto_research_test",
                "username": "crypto_research_test_runner",
                "rolsuper": False,
                "rolcreatedb": False,
                "rolcreaterole": False,
                "rolreplication": False,
                "rolbypassrls": False,
                "rolcanlogin": True,
                "role_memberships": False,
                "can_connect": True,
                "can_create_schema": True,
            }

    class Connection:
        async def execute(self, statement: object) -> Result:
            sql = str(statement)
            statements.append(sql)
            assert sql == "SET TRANSACTION READ ONLY" or sql.startswith("SELECT ")
            return Result()

    class Engine:
        @asynccontextmanager
        async def begin(self) -> AsyncGenerator[Connection]:
            yield Connection()

        async def dispose(self) -> None:
            nonlocal disposed
            disposed = True

    def create_engine(_: str, **kwargs: object) -> Engine:
        engine_options.update(kwargs)
        return Engine()

    monkeypatch.setattr(guard, "create_async_engine", create_engine)
    assert await guard.read_database_identity(SecretStr(SAFE_URL)) == identity()
    assert statements[0] == "SET TRANSACTION READ ONLY"
    assert len(statements) == 2
    assert engine_options["connect_args"] == {
        "timeout": 5,
        "command_timeout": 5,
        "server_settings": {"default_transaction_read_only": "on"},
    }
    assert disposed


def test_database_fixture_dependencies_are_marked_and_fail_before_write(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 在隔离 pytest 子进程中实际执行项目夹具。一个间接依赖和一个独立迁移依赖
    # 都必须带 database 标记；配置缺失应在任何引擎创建、迁移及测试体前失败。
    backend = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join((str(backend), str(backend / "src"))))
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    source = (backend / "tests" / "conftest.py").read_text(encoding="utf-8")
    pytester.makeconftest(
        source
        + """
def forbidden_engine(*args, **kwargs):
    raise AssertionError("WRITE CONNECTION REACHED")
create_async_engine_from_secret = forbidden_engine
"""
    )
    pytester.makeini("[pytest]\nmarkers = database: requires dedicated PostgreSQL\n")
    pytester.makepyfile("""
import pytest
@pytest.fixture
def repository(migrated_database):
    return migrated_database
def test_indirect(repository):
    raise AssertionError("WRITE BODY REACHED")
def test_independent_migration(checked_test_database_url):
    raise AssertionError("WRITE BODY REACHED")
def test_offline():
    pass
""")
    offline = pytester.runpytest_subprocess("-q", "-m", "not database")
    offline.assert_outcomes(passed=1, deselected=2)
    database = pytester.runpytest_subprocess("-q", "-m", "database")
    database.assert_outcomes(errors=2, deselected=1)
    output = database.stdout.str()
    assert "preflight blocked" in output
    assert "WRITE CONNECTION REACHED" not in output
    assert "WRITE BODY REACHED" not in output
