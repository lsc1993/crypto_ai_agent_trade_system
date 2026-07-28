from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.routes.market import router as market_router

API_NAME = "AI 加密合约研究工作台"

router = APIRouter(prefix="/api/v1")


class VersionDocument(BaseModel):
    name: str
    version: Literal["v1"]


@router.get("", response_model=VersionDocument)
async def get_version_document() -> VersionDocument:
    return VersionDocument(name=API_NAME, version="v1")


router.include_router(market_router)
