from __future__ import annotations
from typing import Any
import structlog

from app.student_model.cognitive_tracker import CognitiveTracker
from app.pedagogy.misconception_predictor import MisconceptionPredictor

logger = structlog.get_logger(__name__)

class LiveCognitiveLoop:
    """
    LiveCognitiveLoop — Cognitive context provider for the teaching pipeline.

    Reads the current student cognitive model and predicted misconceptions,
    then returns synthesis constraints that the UnifiedTeachingPipeline uses
    to adapt the lesson before generation.
    """
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.cognitive_tracker = CognitiveTracker()
        self.misconception_predictor = MisconceptionPredictor()
        self.current_concept = "general"

    def prepare_plan_context(
        self,
        query: str,
        recent_interactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Pre-plan adaptation: update cognitive model and return synthesis constraints
        without mutating a finalized teaching sequence.
        """
        self.current_concept = query or self.current_concept

        profile = self.cognitive_tracker.get_or_create_profile(self.session_id)
        for evt in recent_interactions:
            self.cognitive_tracker.record_interaction(self.session_id, evt["type"], evt["payload"])

        predicted = self.misconception_predictor.predict_misconceptions(
            profile, recent_interactions, self.current_concept
        )
        modifier_parts: list[str] = []
        if predicted:
            modifier_parts.append(
                f"Watch for misconceptions: {', '.join(predicted)}. Address them explicitly."
            )
        if profile.confusion_index > 0.5:
            modifier_parts.append(
                "Student is confused — use simpler steps, fewer visuals, explicit conclusion."
            )

        return {
            "confusion_level": profile.confusion_index,
            "cognitive_load": profile.fatigue_level,
            "strategy_modifier": "\n".join(modifier_parts),
            "active_misconceptions": profile.active_misconceptions,
        }
