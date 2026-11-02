# 验证浏览器联验服务的数据库准入顺序、随机 schema 生命周期与清理认证。
# 数据库替身仅用于工具层离线回归；真实浏览器测试仍使用 PostgreSQL 和生产仓储。
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import SecretStr

from scripts import http_e2e_server as server
from scripts.check_test_database import DatabaseGuardError


@pytest.mark.asyncio
async def test_research_stops_before_engine_and_schema_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # worker 必须先释放写入能力，不能在连接或 schema 被删后继续保存研究。
    events: list[str] = []
    engine = MagicMock()

    async def stop() -> None:
        events.append("stop")

    async def dispose() -> None:
        events.append("dispose")

    async def drop(*args: object, **kwargs: object) -> None:
        events.append("drop")

    engine.dispose = dispose
    monkeypatch.setattr(server, "_schema_command", drop)
    database = server.HttpE2EDatabase(
        SecretStr("hidden"), "http_e2e_" + "a" * 32, engine, MagicMock(), before_cleanup=stop
    )
    await database.cleanup()
    assert events == ["stop", "dispose", "drop"]


@pytest.mark.asyncio
@pytest.mark.parametrize("sync_close_fails", [False, True])
async def test_all_consumers_close_before_schema_cleanup(sync_close_fails: bool) -> None:
    # 两个消费者共用 schema；同步回收异常也要回收研究 worker，且向清理调用方保留异常。
    events: list[str] = []
    database = MagicMock()
    research = MagicMock()
    symbols = MagicMock()

    async def close_sync() -> None:
        events.append("sync")
        if sync_close_fails:
            raise RuntimeError("synthetic close failure")

    async def close_research() -> None:
        events.append("research")

    symbols.close = close_sync
    research.close = close_research
    app = server.create_http_e2e_app(
        database, token="synthetic-run-token", research=research, symbols=symbols
    )
    research.install.assert_called_once_with(app, include_symbols=False)
    symbols.install.assert_called_once_with(app, token="synthetic-run-token")
    if sync_close_fails:
        with pytest.raises(RuntimeError, match="synthetic close failure"):
            await database.before_cleanup()
    else:
        await database.before_cleanup()
    assert events == ["sync", "research"]


@pytest.mark.asyncio
async def test_failed_preflight_never_creates_schema_or_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 缺少显式授权时不能先创建引擎，更不能发出写 SQL。
    preflight = AsyncMock(side_effect=DatabaseGuardError("explicit TEST_DATABASE_URL is required"))
    engine = MagicMock()
    monkeypatch.setattr(server, "check_test_database", preflight)
    monkeypatch.setattr(server, "create_async_engine_from_secret", engine)
    with pytest.raises(DatabaseGuardError):
        async with server.test_database_scope():
            pytest.fail("未通过预检不应进入服务运行阶段")
    engine.assert_not_called()


@pytest.mark.asyncio
async def test_random_schema_migration_and_cleanup_are_owned_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 迁移与 ORM 必须共享同一随机 schema；主动清理后 finally 不重复删除。
    events: list[tuple[str, str]] = []
    engine = MagicMock()
    engine.dispose = AsyncMock()
    engine.execution_options.return_value = engine
    monkeypatch.setattr(server, "check_test_database", AsyncMock(return_value=SecretStr("hidden")))
    monkeypatch.setattr(server, "create_async_engine_from_secret", MagicMock(return_value=engine))

    async def schema_command(_url: SecretStr, schema: str, *, create: bool) -> None:
        events.append(("create" if create else "drop", schema))

    def migrate(_url: SecretStr, *, schema: str) -> None:
        events.append(("migrate", schema))

    monkeypatch.setattr(server, "_schema_command", schema_command)
    monkeypatch.setattr(server, "upgrade_database", migrate)
    async with server.test_database_scope() as database:
        assert database.schema.startswith("http_e2e_")
        assert len(database.schema) == len("http_e2e_") + 32
        schema = database.schema
        assert events == [("create", schema), ("migrate", schema)]
        await database.cleanup()
        await database.cleanup()
        assert database.closed
    assert events == [("create", schema), ("migrate", schema), ("drop", schema)]


@pytest.mark.asyncio
async def test_migration_failure_cleans_only_the_new_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 启动中途失败也回收本次 schema，不能遗留写入区域或清理其他对象。
    commands = AsyncMock()
    engine = MagicMock()
    engine.dispose = AsyncMock()
    engine.execution_options.return_value = engine
    monkeypatch.setattr(server, "check_test_database", AsyncMock(return_value=SecretStr("hidden")))
    monkeypatch.setattr(server, "create_async_engine_from_secret", MagicMock(return_value=engine))
    monkeypatch.setattr(server, "_schema_command", commands)
    monkeypatch.setattr(
        server, "upgrade_database", MagicMock(side_effect=RuntimeError("synthetic"))
    )
    with pytest.raises(RuntimeError, match="synthetic"):
        async with server.test_database_scope():
            pytest.fail("迁移失败不应启动 HTTP 服务")
    assert commands.await_count == 2
    assert commands.await_args_list[0].args == commands.await_args_list[1].args
    assert commands.await_args_list[0].kwargs == {"create": True}
    assert commands.await_args_list[1].kwargs == {"create": False}


@pytest.mark.asyncio
async def test_schema_command_rejects_non_owned_names_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 防御性名称校验应在创建连接前拒绝业务 schema 和 SQL 片段。
    engine = MagicMock()
    monkeypatch.setattr(server, "create_async_engine_from_secret", engine)
    for name in ("public", "market_test_abcd", 'http_e2e_"; DROP DATABASE business;'):
        with pytest.raises(ValueError, match="invalid HTTP E2E schema"):
            await server._schema_command(  # pyright: ignore[reportPrivateUsage]
                SecretStr("hidden"), name, create=False
            )
    engine.assert_not_called()


@pytest.mark.asyncio
async def test_engine_setup_failure_still_cleans_created_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # schema 已创建但 ORM 引擎尚未就绪时也必须清理，不能把回收放在装配成功之后。
    commands = AsyncMock()
    monkeypatch.setattr(server, "check_test_database", AsyncMock(return_value=SecretStr("hidden")))
    monkeypatch.setattr(server, "_schema_command", commands)
    monkeypatch.setattr(
        server, "create_async_engine_from_secret", MagicMock(side_effect=RuntimeError("synthetic"))
    )
    with pytest.raises(RuntimeError, match="synthetic"):
        async with server.test_database_scope():
            pytest.fail("引擎装配失败不应启动 HTTP 服务")
    assert commands.await_count == 2
    assert commands.await_args_list[0].args == commands.await_args_list[1].args
    assert commands.await_args_list[1].kwargs == {"create": False}


@pytest.mark.asyncio
async def test_minimal_app_uses_production_repository_and_authenticated_cleanup() -> None:
    # 不启动生产 lifespan、模型或公开源；真实 trades 路由使用 SQLAlchemy 仓储。
    database = MagicMock()
    database.closed = False
    database.cleanup = AsyncMock()
    app = server.create_http_e2e_app(database, token="test-run-token")
    assert isinstance(app.state.trade_repository, server.SqlAlchemyTradeRepository)
    assert isinstance(app.state.trade_service, server.TradeService)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/__http_e2e__/ready")).status_code == 200
        assert (await client.get("/api/v1/market/snapshot")).status_code == 404
        denied = await client.post("/__http_e2e__/cleanup")
        assert denied.status_code == 403
        database.cleanup.assert_not_awaited()
        accepted = await client.post(
            "/__http_e2e__/cleanup", headers={"x-http-e2e-token": "test-run-token"}
        )
        assert accepted.status_code == 204
        database.cleanup.assert_awaited_once()
        database.closed = True
        assert (await client.get("/__http_e2e__/ready")).status_code == 503


def test_main_has_safe_blocked_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 驱动异常可能含敏感地址，CLI 只输出固定阻塞原因，不输出异常正文。
    @asynccontextmanager
    async def unavailable() -> AsyncGenerator[server.HttpE2EDatabase]:
        raise DatabaseGuardError("synthetic secret must stay hidden")
        yield  # pragma: no cover

    monkeypatch.setattr(server, "test_database_scope", unavailable)
    monkeypatch.setenv("HTTP_E2E_TOKEN", "test-run-token")
    assert server.main([]) == 2
    output = capsys.readouterr().out
    assert "blocked" in output
    assert "synthetic secret" not in output
