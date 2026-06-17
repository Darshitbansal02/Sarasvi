"""
Sarasvi — Main FastAPI Application

Production-grade cognitive education engine.
This is the entry point for the backend runtime.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.formparsers import MultiPartParser

# Globally increase Starlette's default 1024KB (1MB) multipart limit to 10MB
# to handle large whiteboard session states and interrupts.
MultiPartParser.max_part_size = 10 * 1024 * 1024
MultiPartParser.max_file_size = 10 * 1024 * 1024

from app.config.settings import get_settings
from app.database.engine import get_engine, dispose_engine
from app.database.base import Base
from app.events.event_bus import get_event_bus

import logging
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)


def _log_level_to_int(level: str) -> int:
    return logging.getLevelName((level or "INFO").upper()) if isinstance(level, str) else 20


# Honor settings.log_level instead of emitting everything unconditionally.
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        _log_level_to_int(get_settings().log_level)
    ),
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown handlers."""
    settings = get_settings()

    # ── Startup ──────────────────────────────────────────────────
    logger.info(
        "Sarasvi.starting",
        version=settings.app_version,
        environment=settings.environment,
    )

    # Fail-safe: refuse to boot in production with the insecure default JWT secret.
    if not settings.is_development and settings.jwt_secret_key == "dev-insecure-change-me-in-production":
        raise RuntimeError(
            "JWT_SECRET_KEY must be set to a strong secret in non-development environments."
        )

    # Fail-safe: SQLite is dev/test-only. Production must use Postgres/Supabase.
    if not settings.is_development and settings.is_sqlite:
        raise RuntimeError(
            "SQLite is not permitted outside development. Set DATABASE_URL to a "
            "Postgres/Supabase connection string (postgresql+asyncpg://...)."
        )

    # Initialize database engine (validates connection)
    engine = get_engine()
    logger.info("database.connected", url=settings.database_url[:50] + "...")

    # Create tables automatically in development
    if settings.is_development:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("database.tables_created")

    # Validate the configured LLM model exists (fail fast in non-dev).
    if settings.validate_models_on_startup:
        from app.utils.llm_client import llm_client
        ok, detail = await llm_client.validate_configured_model()
        if ok:
            logger.info("model.validated", detail=detail)
        else:
            if settings.is_development:
                logger.warning("model.validation_failed", detail=detail)
            else:
                raise RuntimeError(f"Model validation failed: {detail}")

    # Optional distributed tracing
    if settings.otel_enabled:
        from app.utils.observability import setup_tracing
        setup_tracing(console_export=settings.otel_console_export)

    # Start event bus
    event_bus = get_event_bus()
    await event_bus.start()
    logger.info("event_bus.started")

    logger.info("Sarasvi.ready", message="Sarasvi is ready")

    yield

    # ── Shutdown ─────────────────────────────────────────────────
    logger.info("Sarasvi.shutting_down")
    await event_bus.shutdown()
    await dispose_engine()
    logger.info("Sarasvi.shutdown_complete")


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()

    app = FastAPI(
        title="Sarasvi",
        description="Production-Grade Cognitive Education Engine",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
    )

    # ── CORS ─────────────────────────────────────────────────────
    # Use explicit origins from settings so credentialed requests work.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception Handling Middleware ────────────────────────────
    from fastapi.responses import JSONResponse
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException
    
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        logger.warning(
            "http_exception",
            path=str(request.url.path),
            method=request.method,
            status_code=exc.status_code,
            detail=exc.detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning(
            "validation_exception",
            path=str(request.url.path),
            method=request.method,
            errors=exc.errors(),
        )
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors()}
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "unhandled_exception",
            path=str(request.url.path),
            method=request.method,
            error=str(exc),
            exc_info=True
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An unexpected error occurred. Please contact support.",
                "error_code": "INTERNAL_SERVER_ERROR"
            }
        )

    # ── Request-ID + audit + metrics middleware ──────────────────
    import time
    from app.utils import observability as obs

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        # Honor an inbound X-Request-ID (e.g. from a gateway) or mint one, and
        # bind it so every log line during this request carries it.
        request_id = request.headers.get("x-request-id") or obs.new_request_id()
        obs.clear_context()
        obs.bind_request_id(request_id)
        path = str(request.url.path)
        start_time = time.time()
        
        # Intercept multipart requests and parse form with a larger 10MB limit per part
        # (prevents Starlette's default 1024KB limit from throwing on large whiteboard snapshots)
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type:
            try:
                await request.form(max_part_size=10 * 1024 * 1024)
            except Exception:
                pass

        try:
            response = await call_next(request)
        finally:
            duration = time.time() - start_time
        obs.HTTP_REQUESTS.labels(
            method=request.method, path=path, status=str(response.status_code)
        ).inc()
        obs.HTTP_LATENCY.labels(method=request.method, path=path).observe(duration)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "api_request",
            path=path,
            method=request.method,
            status_code=response.status_code,
            duration_ms=round(duration * 1000, 2),
        )
        obs.clear_context()
        return response

    # ── Prometheus metrics endpoint ──────────────────────────────
    if settings.metrics_enabled:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
        from fastapi.responses import Response as _Response

        @app.get("/metrics", include_in_schema=False)
        async def metrics():
            return _Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # ── Register Routes ──────────────────────────────────────────
    from app.api.routes.health import router as health_router
    from app.api.routes.auth import router as auth_router
    from app.api.routes.users import router as users_router
    from app.api.routes.sessions import router as sessions_router
    from app.api.routes.scenes import router as scenes_router
    from app.websocket.gateway import router as ws_router

    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(users_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(scenes_router, prefix="/api")
    app.include_router(ws_router)

    return app


# Create the app instance
app = create_app()
