"""
User model — stores learner profiles, emotional state, and mastery scores.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, GUID, JSONType, VectorType


def default_learning_profile() -> dict:
    return {
        "pace": "normal",
        "confused_topics": [],
        "pedagogical_preferences": {
            "scientific": 0.5,
            "metaphorical": 0.5,
            "visual": 0.8,
            "storytelling": 0.5,
            "minimalist": 0.2
        }
    }


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Nullable so pre-auth/legacy rows remain valid; new accounts always set it.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    learning_profile: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=default_learning_profile)
    learning_profile_embedding: Mapped[list[float]] = mapped_column(VectorType(768), nullable=True)
    emotional_profile: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)
    mastery_scores: Mapped[dict] = mapped_column(JSONType(), nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    sessions = relationship("Session", back_populates="user", lazy="selectin")

    def __repr__(self) -> str:
        return f"<User {self.name} ({self.email})>"
