from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthStatus(BaseModel):
    status: Literal["ok"]


@router.get("/healthz", response_model=HealthStatus)
async def get_health() -> HealthStatus:
    return HealthStatus(status="ok")
