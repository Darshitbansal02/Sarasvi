import uuid
from enum import Enum
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Float, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.database.base import Base, GUID


class PedagogicalFailure(str, Enum):
    """Typed failure modes for analytics and RLEF loops."""
    ANALOGY_FAILURE = "analogy_failure"
    PACING_OVERLOAD = "pacing_overload"
    VISUAL_CONFUSION = "visual_confusion"
    FORMALISM_REJECTION = "formalism_rejection"
    UNKNOWN = "unknown"


class PedagogicalFramework(Base):
    """
    Stores successful pedagogical heuristics and constraints for dynamic synthesis.
    This replaces hardcoded metaphors with a generative framework.
    """
    __tablename__ = "pedagogical_frameworks"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    concept_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    
    # e.g., "Physical chaining works well"
    heuristic_pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    
    # Domain specific demographic constraints
    target_age_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_age_max: Mapped[int] = mapped_column(Integer, nullable=False, default=99)
    
    # E.g., "visual", "storytelling", "scientific"
    cognitive_style: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Reinforcement Learning from Educational Feedback (RLEF) score
    efficacy_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )


class PedagogicalBlueprint(Base):
    """
    Layer 5: Pedagogical Memory.
    Stores 'compressed' episodes of teaching success/failure as vectors.
    """
    __tablename__ = "pedagogical_blueprints"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    
    # The compressed semantic summary of the teaching episode
    # e.g., "Student rejected metaphorical recursion explanation; formal stack visualization succeeded"
    compressed_episode: Mapped[str] = mapped_column(Text, nullable=False)
    
    # 768-dimensional embedding for Gemini text-embedding-004
    embedding: Mapped[Vector] = mapped_column(Vector(768), nullable=False)
    
    # Metadata for filtering (Pedagogical Fingerprint)
    concept_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    student_style_mix: Mapped[dict] = mapped_column(JSON, nullable=False)
    difficulty_level: Mapped[str] = mapped_column(String(20), nullable=False) # e.g., "High"
    
    # Outcome: positive (success) or failure mode
    outcome: Mapped[str] = mapped_column(String(50), nullable=False) 
    
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )


class SQLMisconceptionRecord(Base):
    __tablename__ = "sql_misconception_records"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    misconception_id: Mapped[str] = mapped_column(String(100), nullable=False)
    concept: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    first_seen: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    last_seen: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class SQLConceptRetentionState(Base):
    __tablename__ = "sql_concept_retention_states"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    concept: Mapped[str] = mapped_column(String(100), nullable=False)
    mastery_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    retention_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    last_seen: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    forgetting_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0001)
    exposure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_review_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True)


class SQLPedagogicalEpisode(Base):
    __tablename__ = "sql_pedagogical_episodes"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(3000), nullable=False)
    concepts: Mapped[dict] = mapped_column(JSON, nullable=False) # List of concepts
    misconceptions_triggered: Mapped[dict] = mapped_column(JSON, nullable=False) # List of misconceptions
    teaching_strategy: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
