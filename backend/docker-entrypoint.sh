#!/bin/sh
# Keep this script LF-only: Docker executes it directly in a Linux container.
# 容器启动入口：先应用前向迁移，再将主进程交给 API。
# 任一步失败即退出，避免在数据库结构不匹配时继续提供服务。
set -eu

uv run alembic upgrade head
# exec 替换 shell，使服务直接接收容器停止信号并执行资源清理。
exec uv run python -m app
