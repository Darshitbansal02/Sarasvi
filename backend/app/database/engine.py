"""
Async SQLAlchemy engine and session factory for Sarasvi.
Uses asyncpg driver with connection pooling.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get or create the async SQLAlchemy engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        is_sqlite = "sqlite" in settings.database_url

        kwargs = {
            "echo": False,
        }

        if is_sqlite:
            # SQLite doesn't support pool_size/max_overflow
            from sqlalchemy.pool import StaticPool
            kwargs["connect_args"] = {
                "check_same_thread": False,
                "timeout": 30 # Standard timeout for sqlite busy
            }
            kwargs["poolclass"] = StaticPool
        else:
            kwargs["pool_size"] = settings.db_pool_size
            kwargs["max_overflow"] = settings.db_max_overflow
            kwargs["pool_timeout"] = settings.db_pool_timeout
            kwargs["pool_pre_ping"] = True
            # Recycle connections before Supabase's idle cutoff.
            kwargs["pool_recycle"] = 1800

            # asyncpg-specific connect args (Supabase/pgbouncer compatibility).
            connect_args: dict = {}
            if "asyncpg" in settings.database_url:
                if settings.db_pgbouncer_mode:
                    # Transaction-mode pooler: disable prepared-statement caching
                    # and give statements unique names to avoid collisions.
                    connect_args["statement_cache_size"] = 0
                    connect_args["prepared_statement_cache_size"] = 0
                    import uuid as _uuid
                    connect_args["prepared_statement_name_func"] = (
                        lambda: f"__asyncpg_{_uuid.uuid4()}__"
                    )
                if settings.db_require_ssl and "sslmode" not in settings.database_url:
                    if settings.db_ssl_verify:
                        # Verify the server cert against the system trust store.
                        connect_args["ssl"] = True
                    else:
                        # Encrypt but do NOT verify the CA chain. Needed on dev
                        # machines where antivirus / a corporate proxy injects a
                        # self-signed root (CERTIFICATE_VERIFY_FAILED). Traffic is
                        # still encrypted; only chain verification is skipped.
                        import ssl as _ssl
                        _ctx = _ssl.create_default_context()
                        _ctx.check_hostname = False
                        _ctx.verify_mode = _ssl.CERT_NONE
                        connect_args["ssl"] = _ctx
            if connect_args:
                kwargs["connect_args"] = connect_args

        _engine = create_async_engine(settings.database_url, **kwargs)

        # Register SQLite pragmas
        if is_sqlite:
            from sqlalchemy import event
            @event.listens_for(_engine.sync_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                # Match the 30s driver-level connect timeout (was 5000ms, inconsistent).
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()

        # Register pgvector with asyncpg on every new connection (Postgres only)
        if not is_sqlite:
            from sqlalchemy import event
            @event.listens_for(_engine.sync_engine, "connect")
            def register_vector_on_connect(dbapi_connection, connection_record):
                # pgvector registration logic
                pass

    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db_session() -> AsyncSession:
    """Dependency: yield an async database session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the engine (called on shutdown)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
