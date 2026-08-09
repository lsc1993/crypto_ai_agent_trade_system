from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.dashboard.service import DashboardService, DashboardSnapshot

router = APIRouter(tags=["dashboard"])


def get_dashboard_service(request: Request) -> DashboardService:
    return cast(DashboardService, request.app.state.dashboard_service)


@router.get("/dashboard", response_model=DashboardSnapshot)
async def get_dashboard(
    service: Annotated[DashboardService, Depends(get_dashboard_service)],
) -> DashboardSnapshot:
    return await service.get_snapshot()
