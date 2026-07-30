from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.routes.analysis_reports import router as analysis_reports_router
from app.api.routes.market import router as market_router
from app.api.routes.research_market import router as research_market_router

API_NAME = "AI 加密合约研究工作台"

router = APIRouter(prefix="/api/v1")


class VersionDocument(BaseModel):
    name: str
    version: Literal["v1"]


@router.get("", response_model=VersionDocument)
async def get_version_document() -> VersionDocument:
    return VersionDocument(name=API_NAME, version="v1")


router.include_router(market_router)
router.include_router(research_market_router)
router.include_router(analysis_reports_router)
