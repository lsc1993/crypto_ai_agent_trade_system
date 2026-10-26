# 从固定版本镜像取 uv，运行时 Python 版本与后端项目要求一致。
FROM ghcr.io/astral-sh/uv:0.10.6 AS uv

FROM python:3.12-slim

COPY --from=uv /uv /usr/local/bin/uv

# 构建时编译字节码并复制依赖；运行时复用锁定环境，源码通过 src 路径导入。
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_SYNC=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# 先仅复制依赖声明，源码改动可复用依赖安装层；生产镜像不安装开发工具。
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 创建无交互登录的普通用户，将工作目录权限交给服务用户。
RUN useradd --create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app

# 同时打包服务、历史迁移和入口脚本，启动迁移使用与服务相同的版本。
COPY --chown=app:app src/ ./src/
COPY --chown=app:app alembic/ ./alembic/
COPY --chown=app:app alembic.ini docker-entrypoint.sh ./
RUN chmod +x /app/docker-entrypoint.sh

# API 与迁移均以普通用户运行，容器端口由 Compose 映射到本地。
USER app
EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
