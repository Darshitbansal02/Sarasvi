"""
SQLAlchemy declarative base and cross-database type helpers for Sarasvi.
Supports both PostgreSQL (production) and SQLite (local dev).
"""

import uuid
import json
import numpy as np

from sqlalchemy import TypeDecorator, String, Text, LargeBinary
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import CHAR


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class GUID(TypeDecorator):
    """Platform-independent GUID type. Uses CHAR(36) for SQLite, UUID for PG."""
    impl = CHAR(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, uuid.UUID):
                return str(value)
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            if isinstance(value, uuid.UUID):
                return value
            return uuid.UUID(value)
        return value

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))


class JSONType(TypeDecorator):
    """Platform-independent JSON type. Uses Text+JSON for SQLite, JSONB for PG."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value, sort_keys=True, separators=(",", ":"))
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            if isinstance(value, str):
                return json.loads(value)
            return value
        return value

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB
            return dialect.type_descriptor(JSONB)
        return dialect.type_descriptor(Text)


class VectorType(TypeDecorator):
    """
    Platform-independent Vector type.
    Uses LargeBinary (numpy serialization) for SQLite, pgvector for PG.
    """
    impl = LargeBinary
    cache_ok = True

    def __init__(self, dimensions: int):
        super().__init__()
        self.dimensions = dimensions

    def process_bind_param(self, value, dialect):
        if value is not None:
            if dialect.name == "postgresql":
                return value
            # For SQLite, store as raw bytes from numpy
            return np.array(value, dtype=np.float32).tobytes()
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            if dialect.name == "postgresql":
                return value
            # For SQLite, convert bytes back to list
            return np.frombuffer(value, dtype=np.float32).tolist()
        return value

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector
            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(LargeBinary)
