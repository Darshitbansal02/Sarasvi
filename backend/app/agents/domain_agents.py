"""
Domain-Aware Agents
"""

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class DomainAwareExplainer:
    """Generates pedagogical narration via the unified teaching pipeline."""

    async def generate_explanation(
        self,
        user: Optional[User],
        concept_id: str,
        snapshot_context: dict = None,
        strategy_modifier: str = "",
        confusion_level: float = 0.0,
        cognitive_load: float = 0.0,
        *,
        student_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        adaptation_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        resolved_student_id = student_id or (str(user.id) if user else "anonymous")
        from app.services.unified_teaching_pipeline import unified_teaching_pipeline

        return await unified_teaching_pipeline.generate_lesson(
            student_id=resolved_student_id,
            query=concept_id,
            user=user,
            snapshot_context=snapshot_context,
            strategy_modifier=strategy_modifier,
            confusion_level=confusion_level,
            cognitive_load=cognitive_load,
            db=db,
            adaptation_context=adaptation_context,
        )
