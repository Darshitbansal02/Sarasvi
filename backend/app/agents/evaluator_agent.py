"""
Evaluator Agent

Analyzes student interruptions to detect pedagogical failure modes.
"""

from typing import Literal

class EvaluatorAgent:
    def analyze_spatial_intent(self, gesture_data: dict, scene_objects: dict) -> dict:
        """
        Interprets a student's spatial gesture relative to the current whiteboard state.
        Returns a pedagogical intent object.
        """
        g_type = gesture_data.get("type", "unknown")
        target_id = gesture_data.get("target_id")
        
        target_obj = scene_objects.get(target_id) if target_id else None

        if g_type == "circle" and target_obj:
            return {
                "intent": "FOCUS_REQUEST",
                "object_type": target_obj.get("type"),
                "concept_id": target_obj.get("data", {}).get("concept"),
                # The actual content of the circled element (equation latex,
                # annotation text, code, label) so the lesson can anchor the
                # explanation to exactly what the student pointed at.
                "object_content": self._extract_object_content(target_obj),
                "narrative_hint": f"I see you're asking about this {target_obj.get('type')}..."
            }

        if g_type == "line" and target_obj:
            return {
                "intent": "RELATIONSHIP_QUERY",
                "object_type": target_obj.get("type"),
                "object_content": self._extract_object_content(target_obj),
                "narrative_hint": "Let's explore how these parts connect."
            }

        return {"intent": "GENERAL_INTERRUPTION", "narrative_hint": "I noticed you pointing something out."}

    @staticmethod
    def _extract_object_content(target_obj: dict) -> str:
        """Best-effort human-readable content of a circled whiteboard object."""
        data = target_obj.get("data", {}) or {}
        for key in ("latex", "text", "label", "code", "title", "content"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""

    def analyze_interruption(self, text: str) -> Literal["analogy_failure", "too_formal", "too_fast", "unknown"]:
        # Existing logic...
        text_lower = text.lower()
        if "minecraft" in text_lower or "analogy" in text_lower:
            return "analogy_failure"
        if "math" in text_lower or "equation" in text_lower:
            return "too_formal"
        if "fast" in text_lower:
            return "too_fast"
        return "unknown"
