# 提供轻量进程存活探针 /healthz。
# 返回固定 ok 契约，不访问数据库、模型或交易所。
# 成功只说明请求已到达 API，不能据此判定外部依赖已就绪。
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


# HealthStatus 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：status；完整契约以下方声明为准。
class HealthStatus(BaseModel):
    status: Literal["ok"]


# 接收路由声明的请求参数，委托 下方契约映射，返回 HealthStatus。
@router.get("/healthz", response_model=HealthStatus)
async def get_health() -> HealthStatus:
    return HealthStatus(status="ok")
