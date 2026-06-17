"""
KnowledgeGraph model — symbolic concept graph for prerequisite tracking.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, GUID, JSONType


class KnowledgeGraphNode(Base):
    __tablename__ = "knowledge_graph"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    concept: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    dependencies: Mapped[list] = mapped_column(JSONType(), nullable=False, default=list)
    mastery_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    prerequisite_chain: Mapped[list] = mapped_column(JSONType(), nullable=False, default=list)

    def __repr__(self) -> str:
        return f"<KnowledgeGraphNode {self.concept}>"
