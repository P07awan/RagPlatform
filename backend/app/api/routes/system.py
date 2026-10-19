"""Non-sensitive configuration status and dashboard statistics."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.core.container import AppContainer
from app.schemas.system import ConfigStatus, DashboardStats

router = APIRouter(tags=["system"])


@router.get(
    "/config", response_model=ConfigStatus, summary="Non-sensitive configuration (no secrets)"
)
async def config_status(c: AppContainer = Depends(get_container)) -> ConfigStatus:
    return c.config_status()


@router.get("/stats", response_model=DashboardStats, summary="Dashboard statistics from real data")
async def stats(c: AppContainer = Depends(get_container)) -> DashboardStats:
    return await c.dashboard_stats()
