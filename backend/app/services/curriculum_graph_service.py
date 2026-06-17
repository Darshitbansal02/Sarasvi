"""
Curriculum graph service — prerequisite lookup and mastery gating via KnowledgeGraphNode.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_graph import KnowledgeGraphNode

logger = structlog.get_logger(__name__)

# Seed concepts used when the DB table is empty (bootstrap for dev)
DEFAULT_GRAPH_SEED: list[dict[str, Any]] = [
    {
        "concept": "recursion",
        "dependencies": ["functions", "call_stack"],
        "prerequisite_chain": ["functions", "call_stack", "recursion"],
        "mastery_weight": 1.0,
    },
    {
        "concept": "derivatives",
        "dependencies": ["algebra", "functions", "limits"],
        "prerequisite_chain": ["algebra", "functions", "limits", "derivatives"],
        "mastery_weight": 1.0,
    },
    {
        "concept": "mutex",
        "dependencies": ["threads", "shared_memory"],
        "prerequisite_chain": ["processes", "threads", "shared_memory", "mutex"],
        "mastery_weight": 1.0,
    },
    {
        "concept": "tcp",
        "dependencies": ["ip", "packets"],
        "prerequisite_chain": ["networking", "ip", "packets", "tcp"],
        "mastery_weight": 1.0,
    },
    {
        "concept": "integration",
        "dependencies": ["derivatives", "algebra"],
        "prerequisite_chain": ["algebra", "functions", "derivatives", "integration"],
        "mastery_weight": 1.0,
    },
]


def _normalize_concept(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


class CurriculumGraphService:
    """Queries and maintains the knowledge graph for prerequisite ordering."""

    async def ensure_seeded(self, db: AsyncSession) -> None:
        result = await db.execute(select(KnowledgeGraphNode).limit(1))
        if result.scalar_one_or_none() is not None:
            return
        for entry in DEFAULT_GRAPH_SEED:
            db.add(
                KnowledgeGraphNode(
                    concept=entry["concept"],
                    dependencies=entry["dependencies"],
                    prerequisite_chain=entry["prerequisite_chain"],
                    mastery_weight=entry.get("mastery_weight", 1.0),
                )
            )
        await db.commit()
        logger.info("curriculum_graph.seeded", count=len(DEFAULT_GRAPH_SEED))

    async def get_prerequisites(
        self,
        db: AsyncSession,
        concepts: list[str],
    ) -> list[str]:
        await self.ensure_seeded(db)
        prereqs: list[str] = []
        for raw in concepts:
            key = _normalize_concept(raw)
            result = await db.execute(
                select(KnowledgeGraphNode).where(KnowledgeGraphNode.concept == key)
            )
            node = result.scalar_one_or_none()
            if not node:
                continue
            chain = node.prerequisite_chain or node.dependencies or []
            for item in chain:
                normalized = _normalize_concept(str(item))
                if normalized and normalized not in prereqs and normalized != key:
                    prereqs.append(normalized)
        return prereqs

    def filter_missing_prerequisites(
        self,
        prerequisites: list[str],
        mastered_concepts: list[str],
        *,
        mastery_threshold: float = 0.70,
        knowledge_state: dict[str, float] | None = None,
    ) -> list[str]:
        mastered = {_normalize_concept(c) for c in mastered_concepts}
        if knowledge_state:
            for concept, score in knowledge_state.items():
                if score >= mastery_threshold:
                    mastered.add(_normalize_concept(concept))
        missing: list[str] = []
        for prereq in prerequisites:
            key = _normalize_concept(prereq)
            if key not in mastered:
                missing.append(prereq)
        return missing

    def build_prerequisite_preamble(
        self,
        missing: list[str],
    ) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for prereq in missing[:3]:
            label = prereq.replace("_", " ")
            steps.append(
                {
                    "narration_sentence": f"Before we continue, let's briefly review: {label}.",
                    "visual_primitive": {
                        "type": "annotation",
                        "data": {
                            "annotation_id": f"prereq_{_normalize_concept(prereq)}",
                            "text": f"Prerequisite: {label}",
                            "style": "emphasis",
                        },
                    },
                }
            )
        return steps


curriculum_graph_service = CurriculumGraphService()
