# 仅供 HTTP/数据库浏览器验收使用的独立服务，不装配生产 AppSettings 或生产 lifespan。
# 显式测试库准入通过后创建随机 schema、运行现有迁移，并使用生产交易日志服务和仓储。
# 研究使用固定模型传输，同步使用合成行情和事件门；均不访问公开源或订单执行。
# 清理先关闭两个消费者，再回收本次 schema，不触及业务数据。
from __future__ import annotations

import argparse
import asyncio
import hmac
import logging
import os
import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.errors import install_exception_handlers
from app.api.routes.trades import router as trades_router
from app.infrastructure.persistence.trade_repository import SqlAlchemyTradeRepository
from app.shared.database import (
    create_async_engine_from_secret,
    create_session_factory,
    upgrade_database,
)
from app.trades.service import TradeService
from scripts.check_test_database import DatabaseGuardError, check_test_database
from scripts.http_e2e_research import ResearchRuntime, research_runtime
from scripts.http_e2e_symbols import SymbolSyncRuntime, symbol_sync_runtime


@dataclass
class HttpE2EDatabase:
    # 生命周期持有者保存唯一的随机 schema 与秘密连接；不接受 CLI 指定清理目标。
    # cleanup 可由浏览器 teardown 或正常退出调用，锁避免两条路径重复删除。
    database_url: SecretStr
    schema: str
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    closed: bool = False
    before_cleanup: Callable[[], Awaitable[None]] | None = None
    _cleanup_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def cleanup(self) -> None:
        # 先释放 ORM 连接，再删除本次 schema；删除失败保持可重试，不能误报已清理。
        async with self._cleanup_lock:
            if self.closed:
                return
            if self.before_cleanup is not None:
                await self.before_cleanup()
            await self.engine.dispose()
            await _schema_command(self.database_url, self.schema, create=False)
            self.closed = True


async def _schema_command(database_url: SecretStr, schema: str, *, create: bool) -> None:
    # SQL 标识符不能使用值参数，因此先严格限定内部 UUID 名称，拒绝任意 schema 输入。
    # 级联删除范围始终是一条随机测试 schema，绝不清理数据库、角色或公共 schema。
    if re.fullmatch(r"http_e2e_[0-9a-f]{32}", schema) is None:
        raise ValueError("invalid HTTP E2E schema")
    engine = create_async_engine_from_secret(database_url)
    try:
        async with engine.begin() as connection:
            statement = f'CREATE SCHEMA "{schema}"' if create else f'DROP SCHEMA "{schema}" CASCADE'
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


@asynccontextmanager
async def test_database_scope() -> AsyncGenerator[HttpE2EDatabase]:
    # 预检必须早于所有写连接，复用既有专用测试库和受限角色契约。
    # 预检可读取业务配置作为拒绝依据，但服务从不使用业务配置连接或启动业务依赖。
    database_url = await check_test_database()
    schema = f"http_e2e_{uuid4().hex}"
    await _schema_command(database_url, schema, create=True)
    engine: AsyncEngine | None = None
    database: HttpE2EDatabase | None = None
    try:
        # schema 创建后立刻进入 finally 保护；引擎/会话装配失败也必须回收。
        engine = create_async_engine_from_secret(database_url).execution_options(
            schema_translate_map={None: schema},
        )
        database = HttpE2EDatabase(database_url, schema, engine, create_session_factory(engine))
        await asyncio.to_thread(upgrade_database, database_url, schema=schema)
        yield database
    finally:
        # 迁移失败也走同一回收路径，且仅清理已经成功创建的本次 schema。
        if database is not None:
            await database.cleanup()
        else:
            if engine is not None:
                await engine.dispose()
            await _schema_command(database_url, schema, create=False)


class ReadyResponse(BaseModel):
    # 就绪只声明验收服务的边界，不返回连接、schema 或认证 token。
    mode: str = "http-database-e2e"


def create_http_e2e_app(
    database: HttpE2EDatabase,
    *,
    token: str,
    research: ResearchRuntime | None = None,
    symbols: SymbolSyncRuntime | None = None,
) -> FastAPI:
    # 最小装配复用生产 HTTP 映射、确定性盈亏和 SQLAlchemy 事务/审计写入。
    # 提供交易日志、显式注入的研究/同步队列及验收生命周期路由，不冒充完整生产装配。
    if not token:
        raise ValueError("HTTP E2E run token is required")
    app = FastAPI(title="Isolated HTTP database E2E", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://127\.0\.0\.1:[0-9]+",
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["content-type"],
    )
    install_exception_handlers(app)
    repository = SqlAlchemyTradeRepository(database.session_factory)
    app.state.trade_repository = repository
    app.state.trade_service = TradeService(repository=repository)
    app.include_router(trades_router, prefix="/api/v1")
    if research is not None:
        research.install(app, include_symbols=symbols is None)
    if symbols is not None:
        symbols.install(app, token=token)

    async def close_workers() -> None:
        # 两个消费者都必须先退出；同步关闭异常也不能跳过研究 worker 的回收。
        try:
            if symbols is not None:
                await symbols.close()
        finally:
            if research is not None:
                await research.close()

    database.before_cleanup = close_workers

    async def ready() -> ReadyResponse:
        # 清理完成后不再向 Playwright 宣称数据库就绪。
        if database.closed:
            raise HTTPException(status_code=503, detail="HTTP E2E database is closed")
        return ReadyResponse()

    async def cleanup(x_http_e2e_token: str = Header(default="")) -> Response:
        # Windows 强制终止进程不保证 finally，因此 teardown 先显式回收。
        # 每次运行随机 token 防止失败启动的 teardown 操作同端口的其他验收服务。
        if not hmac.compare_digest(x_http_e2e_token, token):
            raise HTTPException(status_code=403, detail="HTTP E2E cleanup token rejected")
        await database.cleanup()
        return Response(status_code=204)

    app.add_api_route("/__http_e2e__/ready", ready, response_model=ReadyResponse)
    app.add_api_route("/__http_e2e__/cleanup", cleanup, methods=["POST"], status_code=204)
    return app


async def _serve(port: int, token: str) -> None:
    # 主进程拥有数据库作用域，uvicorn 正常退出或启动失败后都回收同一 schema。
    async with test_database_scope() as database:
        async with (
            research_runtime(database.session_factory) as research,
            symbol_sync_runtime(database.session_factory) as symbols,
        ):
            app = create_http_e2e_app(database, token=token, research=research, symbols=symbols)
            configuration = uvicorn.Config(
                app, host="127.0.0.1", port=port, log_level="critical", access_log=False
            )
            await uvicorn.Server(configuration).serve()


def main(argv: Sequence[str] | None = None) -> int:
    # 服务只绑定 loopback；不提供 URL/schema/生产配置覆盖参数。
    # 任意启动异常均转为固定摘要，避免迁移/驱动异常泄露实际测试连接信息。
    parser = argparse.ArgumentParser(description="Isolated HTTP/database browser E2E server")
    parser.add_argument("--port", type=int, default=8174)
    arguments = parser.parse_args(argv)
    token = os.environ.get("HTTP_E2E_TOKEN", "")
    if not token or not 1 <= arguments.port <= 65535:
        print("http database e2e: blocked (run token or port is invalid)")
        return 2
    # Alembic/SQLAlchemy 的异常原文不进入验收输出；诊断由只读准入命令单独提供。
    previous_logging_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(_serve(arguments.port, token))
    except DatabaseGuardError:
        print("http database e2e: blocked (dedicated test database preflight rejected)")
        return 2
    except Exception:
        print("http database e2e: failed (isolated service startup or cleanup failed)")
        return 1
    finally:
        logging.disable(previous_logging_disable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
