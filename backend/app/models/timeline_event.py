"""
TimelineEvent model — the SOURCE OF TRUTH for all educational events.
Supports branching timelines for interruption-driven cognitive branches.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, BigInteger, DateTime, Boolean, Index, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, GUID, JSONType


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True,
    )

    generation_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    branch_id: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    version_id: Mapped[str] = mapped_column(String(100), nullable=False, default="v1")
    parent_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    interruption_trigger: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    server_timestamp: Mapped[int] = mapped_column(
        BigInteger, nullable=False,
        default=lambda: int(datetime.now(timezone.utc).timestamp() * 1000),
    )

    type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    session = relationship("Session", back_populates="timeline_events",
                          foreign_keys=[session_id],
                          primaryjoin="TimelineEvent.session_id == Session.id")

    __table_args__ = (
        Index("ix_timeline_session_seq", "session_id", "sequence_number"),
        Index("ix_timeline_session_gen", "session_id", "generation_id"),
        Index("ix_timeline_session_branch", "session_id", "branch_id"),
    )

    def __repr__(self) -> str:
        return f"<TimelineEvent seq={self.sequence_number} type={self.type} gen={self.generation_id}>"
