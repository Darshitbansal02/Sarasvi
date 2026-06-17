"""
Health check endpoint.
"""

from fastapi import APIRouter

from app.config.settings import get_settings
from app.schemas.api_schemas import HealthResponse
from app.websocket.connection_manager import get_connection_manager

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """System health check endpoint."""
    settings = get_settings()
    conn_manager = get_connection_manager()

    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        environment=settings.environment,
        active_ws_connections=conn_manager.total_connections,
        active_sessions=len(conn_manager.active_sessions),
    )
