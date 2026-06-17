"""
Session state models — durable, externalized session/student state.

Replaces the in-process module-global dicts (`_session_whiteboards`,
`_session_page_locks`) and the in-memory `session_registry` profile slot. State
lives in the database so it survives restarts and is a single source of truth.

Two tables, both keyed 1:1 by session_id:
  • SessionState        — page-progression lock, whiteboard snapshot, generation
                          + branch manager snapshots.
  • StudentProfileState — the CognitiveTracker StudentProfile (JSON).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, GUID, JSONType


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionState(Base):
    __tablename__ = "session_state"

    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True,
    )
    # {"current_page": int, "page_complete": bool, "total_pages_completed": int}
    page_lock: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)
    # WhiteboardManager.to_state() snapshot (scene cursor + pending transitions)
    whiteboard_state: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)
    # GenerationManager.to_state()
    generation_state: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)
    # BranchManager.to_state()
    branch_state: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow,
    )


class StudentProfileState(Base):
    __tablename__ = "student_profile_state"

    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True,
    )
    profile: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow,
    )
