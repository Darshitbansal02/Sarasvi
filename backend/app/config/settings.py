"""
Sarasvi Configuration — Pydantic Settings with environment variable support.
All configuration is centralized here for deterministic behavior.
"""

from __future__ import annotations

import json
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────────
    environment: str = "development"
    log_level: str = "INFO"
    app_name: str = "Sarasvi"
    app_version: str = "0.1.0"

    # ── Database ─────────────────────────────────────────────────
    # SQLite is the LOCAL DEV / TEST default. Production sets DATABASE_URL to a
    # Postgres/Supabase URL (see .env.example). In non-development environments
    # the app refuses to start on SQLite (see app.main lifespan).
    database_url: str = "sqlite+aiosqlite:///./Sarasvi.db"
    database_url_sync: str = "sqlite:///./Sarasvi.db"
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    # Supabase's pooled endpoint (port 6543) runs pgbouncer in transaction mode,
    # which is incompatible with asyncpg prepared-statement caching. When true we
    # disable the statement cache so the pooled connection string works.
    db_pgbouncer_mode: bool = True
    # Require TLS for Postgres connections (Supabase mandates SSL).
    db_require_ssl: bool = True
    # Verify the server's TLS certificate chain. Keep TRUE in production (clean
    # trust store). Set DB_SSL_VERIFY=false on a dev machine whose antivirus /
    # corporate proxy injects a self-signed root into the chain — that breaks CA
    # verification ("self-signed certificate in certificate chain") even though
    # the connection is still encrypted. With it false, TLS still encrypts; only
    # the CA check is skipped.
    db_ssl_verify: bool = True

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.database_url

    # ── CORS ─────────────────────────────────────────────────────
    # Allow both localhost and 127.0.0.1 variants for the dev frontend
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

    # ── WebSocket ────────────────────────────────────────────────
    ws_heartbeat_interval: int = 30  # seconds
    ws_max_message_size: int = 1_048_576  # 1MB

    # ── Auth / Security ──────────────────────────────────────────
    # IMPORTANT: override jwt_secret_key in production via the JWT_SECRET_KEY env var.
    jwt_secret_key: str = "dev-insecure-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    # ── LLM concurrency / rate limiting ──────────────────────────
    # Number of concurrent LLM calls allowed process-wide. 1 = fully serialized
    # (safe for low free-tier quotas). Raise for higher-quota keys / more users.
    llm_max_concurrent: int = 1
    llm_min_interval_sec: float = 0.1

    # ── AI / Groq / Gemini (stubbed for now) ─────────────────────
    groq_api_key: str = "stub"
    groq_model_strong: str = "llama-3.3-70b-versatile"
    groq_model_fast: str = "llama-3.1-8b-instant"

    gemini_api_key: str = "stub"
    # Use real, currently-available model IDs as defaults so the app boots
    # out-of-the-box when a real key is set (validate_models_on_startup will
    # otherwise refuse to start in non-dev on an unknown model).
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-2"

    # ── TTS ──────────────────────────────────────────────────────
    tts_voice: str = "en-US-AriaNeural"
    tts_rate: str = "+0%"

    # ── Event System ─────────────────────────────────────────────
    event_bus_max_size: int = 10_000
    event_compression_threshold: int = 100

    # ── Reasoning core (Phases 4–6) ──────────────────────────────
    # When true, lessons are generated via plan → per-step verify → repair
    # (ReasoningCore). Falls back to single-shot synthesis on any failure.
    reasoning_core_enabled: bool = True
    enable_llm_factual_verification: bool = False

    # ── Drawing / diagram generation toggle ──────────────────────
    # When False, the LLM is instructed (prompt-only — no logic removed) to emit
    # NO diagram/geometry primitives (procedural_sketch, graph, physics_diagram,
    # data-structure diagrams, etc.). Text visuals (equation, annotation,
    # code_block) and verbal explanation of diagrams still work. Set
    # DIAGRAMS_ENABLED=false in .env to disable drawing temporarily.
    diagrams_enabled: bool = True

    # ── Scalability (Phase 9) ────────────────────────────────────
    # "memory" (in-process, single instance) or "redis" (multi-instance).
    pubsub_backend: str = "memory"
    redis_url: str = "redis://localhost:6379/0"

    # ── Observability ────────────────────────────────────────────
    metrics_enabled: bool = True            # expose Prometheus /metrics
    otel_enabled: bool = False              # set up an OpenTelemetry tracer
    otel_console_export: bool = False       # dump spans to stdout (debug)

    # ── Model validation ─────────────────────────────────────────
    # On startup, verify the configured Gemini model exists (when a real key is
    # set). Fails fast in non-development; warns in development.
    validate_models_on_startup: bool = True

    # ── Tunable pedagogy / heuristics (formerly hardcoded) ───────
    pedagogy_mix_scientific: float = 0.7
    pedagogy_mix_metaphorical: float = 0.3
    curriculum_band_advanced: float = 0.75      # understanding_score >= → advanced
    curriculum_band_intermediate: float = 0.45  # >= → intermediate, else beginner
    vision_confidence_high: float = 0.90        # skip verification above this
    vision_confidence_review: float = 0.75      # below this → needs_user_review
    interrupt_confusion_default: float = 0.8
    interrupt_cognitive_load_default: float = 0.7

    # ── TTS pacing (audio_planner) ───────────────────────────────
    tts_word_onset_ms: float = 130.0    # base onset per word
    tts_per_char_ms: float = 40.0       # additional ms per character

    # ── Verification (math claim checking) ───────────────────────
    # CPU-bound sympy can stall generation on pathological trig/radical
    # identities. Bound each equality check and the whole math pass; over-budget
    # claims degrade to UNVERIFIED (safe, non-fatal). Tunable without a redeploy.
    verify_eq_timeout_sec: float = 2.0      # max wall-time for ONE equality check
    verify_budget_sec: float = 15.0         # max wall-time for the whole math pass

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


# Singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
