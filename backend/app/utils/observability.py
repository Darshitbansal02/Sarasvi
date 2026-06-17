"""
Observability — request IDs, contextvars, Prometheus metrics, optional OTel tracing.

- `request_id` / `generation_id` are bound into structlog's contextvars so every
  log line emitted during a request/generation carries them automatically
  (main.py already configures structlog.contextvars.merge_contextvars).
- Prometheus metrics are exposed at GET /metrics (see main.py).
- OpenTelemetry tracing is set up lazily and only when settings.otel_enabled.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from typing import Optional

import structlog
from prometheus_client import Counter, Histogram

logger = structlog.get_logger(__name__)

# ── Prometheus metrics ───────────────────────────────────────────────
HTTP_REQUESTS = Counter(
    "Sarasvi_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
HTTP_LATENCY = Histogram(
    "Sarasvi_http_request_duration_seconds", "HTTP request latency", ["method", "path"]
)
GENERATIONS = Counter(
    "Sarasvi_generations_total", "Lesson generations", ["outcome"]  # completed|failed|cancelled
)
GENERATION_LATENCY = Histogram(
    "Sarasvi_generation_duration_seconds", "Lesson generation wall time"
)
LLM_CALLS = Counter(
    "Sarasvi_llm_calls_total", "LLM API calls", ["provider", "outcome"]  # success|error
)


def new_request_id() -> str:
    return uuid.uuid4().hex


def bind_request_id(request_id: str) -> None:
    structlog.contextvars.bind_contextvars(request_id=request_id)


def bind_generation_id(generation_id: str) -> None:
    structlog.contextvars.bind_contextvars(generation_id=generation_id)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()


@contextmanager
def track_generation(generation_id: str):
    """Bind generation_id, time the generation, and record its outcome metric."""
    bind_generation_id(generation_id)
    start = time.perf_counter()
    outcome = "completed"
    try:
        yield
    except BaseException as exc:  # noqa: BLE001 — classify then re-raise
        import asyncio
        outcome = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
        raise
    finally:
        GENERATION_LATENCY.observe(time.perf_counter() - start)
        GENERATIONS.labels(outcome=outcome).inc()


def setup_tracing(*, console_export: bool = False) -> None:
    """Initialize a basic OpenTelemetry tracer provider (no-op if already set)."""
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        if isinstance(trace.get_tracer_provider(), TracerProvider):
            return  # already configured
        provider = TracerProvider(resource=Resource.create({"service.name": "Sarasvi-backend"}))
        if console_export:
            from opentelemetry.sdk.trace.export import (
                BatchSpanProcessor,
                ConsoleSpanExporter,
            )
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        logger.info("otel.tracer_initialized", console_export=console_export)
    except Exception as e:  # pragma: no cover — tracing must never break startup
        logger.warning("otel.setup_failed", error=str(e))


def record_llm_call(provider: str, ok: bool) -> None:
    LLM_CALLS.labels(provider=provider, outcome="success" if ok else "error").inc()
