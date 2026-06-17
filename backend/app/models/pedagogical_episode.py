"""
PedagogicalEpisode model — represents a compressed, semantic memory of a 
learning interaction, enabled for vector search.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Float, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, GUID, VectorType

class PedagogicalEpisode(Base):
    __tablename__ = "pedagogical_episodes"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    
    # Semantic Content
    summary: Mapped[str] = mapped_column(Text(), nullable=False)
    pedagogical_strategy: Mapped[str] = mapped_column(String(200), nullable=False) # e.g. "Socratic", "Direct", "Analogical"
    
    # Mastery / Success Metrics
    success_score: Mapped[float] = mapped_column(Float(), default=1.0)
    cognitive_load_peak: Mapped[float] = mapped_column(Float(), nullable=True)
    
    # The Vector (768 dimensions for Gemini text-embedding-004)
    # This allows Sarasvi to find "similar breakthroughs" from past sessions.
    embedding: Mapped[list[float]] = mapped_column(VectorType(768), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    session = relationship("Session")

    def __repr__(self) -> str:
        return f"<PedagogicalEpisode {self.id} strategy='{self.pedagogical_strategy}' score={self.success_score}>"
