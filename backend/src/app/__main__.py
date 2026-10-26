# 支持 python -m app 启动 API 进程。
# 仅在直接作为模块入口执行时调用 server.run_api；普通导入不启动监听。
from __future__ import annotations

from app.server import run_api

if __name__ == "__main__":
    run_api()
