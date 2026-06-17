import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, DateTime, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, GUID, JSONType


class SceneSnapshot(Base):
    """
    Cognitive Semantic Scene Snapshot.
    Stores the pedagogical state, attention state, transition context, and semantic scene mutations.
    DO NOT store raw PixiJS instances or renderer-specific state here.
    """
    __tablename__ = "scene_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("sessions.id"), nullable=False, index=True)
    concept_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    schema_version: Mapped[str] = mapped_column(String(50), default="1.0.0")
    runtime_version: Mapped[str] = mapped_column(String(50), default="1.0.0")
    dsl_version: Mapped[str] = mapped_column(String(50), default="1.0.0")

    pedagogical_state: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)
    pedagogical_plan: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)
    attention_state: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)
    transition_context: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)
    scene_graph_state: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)
    visual_plan: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)
    camera_state: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)
    transcript_state: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)
    semantic_summary: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    replay_cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timeline_offset: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    session = relationship("Session", backref="scene_snapshots")

    def __repr__(self) -> str:
        return f"<SceneSnapshot(id={self.id}, session_id={self.session_id}, concept_id={self.concept_id})>"
