"""
CheckpointService — graph-free Socratic checkpoint evaluation.

Phase 1 salvage: the useful checkpoint logic previously lived inside the now-dead
CognitiveConductor.process_checkpoint_response, which was a no-op because it
required a TeachingActionGraph (`active_graph`) that the live REST pipeline never
builds. This service keeps the genuinely valuable behaviour — evaluate the
student's answer, update the CognitiveTracker student model, and record the
outcome to the spaced-repetition scheduler — without any dependency on the
dormant CognitiveOS / TeachingActionGraph subsystems.

NOTE (Phase 4 follow-up): StudentResponseEvaluator still contains domain-specific
keyword fallback tables. That is intentionally left untouched here; cleaning it is
a Phase 4 (pedagogy) task, not Phase 1 (consolidation).
"""

from __future__ import annotations

from typing import Any

import structlog

from app.student_model.cognitive_tracker import CognitiveTracker
from app.student_model.student_response_evaluator import StudentResponseEvaluator

logger = structlog.get_logger(__name__)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class CheckpointService:
    """Evaluate a checkpoint answer and update the student model (no graph required)."""

    def __init__(self) -> None:
        self._tracker = CognitiveTracker()
        self._evaluator = StudentResponseEvaluator()

    async def evaluate(
        self,
        session_id: str,
        answer_text: str,
        question_text: str = "",
    ) -> dict[str, Any]:
        """
        Returns:
            {
              "is_correct": bool,
              "detected_misconception": str | None,
              "events": [ <evaluation_result event>, ... ]
            }
        """
        profile = self._tracker.get_or_create_profile(session_id)

        eval_result = await self._evaluator.evaluate_response(
            answer_text,
            question_text or "",
            list(getattr(profile, "active_misconceptions", []) or []),
        )

        is_correct = bool(eval_result.get("is_correct", True))
        misconception = eval_result.get("detected_misconception")
        concept_hint = " ".join((question_text or answer_text).split()[:3]) or "general"

        # ── Route through CognitiveTracker to preserve single-writer updates ────
        payload = {
            "is_correct": is_correct,
            "difficulty": 0.5,
            "misconception_trigger": misconception,
            "concept": concept_hint,
        }
        profile = self._tracker.record_interaction(session_id, "quiz_outcome", payload)

        # ── Record to spaced-repetition scheduler (best effort) ──────
        try:
            from app.student_model.reinforcement_scheduler import ReinforcementScheduler

            scheduler = ReinforcementScheduler()
            concept_hint = " ".join((question_text or answer_text).split()[:3]) or "general"
            await scheduler.record_interaction(
                student_id=session_id,
                concept=concept_hint,
                mastery_score=profile.understanding_score,
                misconception_score=1.0 if misconception else 0.0,
            )
        except Exception as exc:  # never let scheduling break checkpoint handling
            logger.warning("checkpoint_service.scheduler_record_failed", error=str(exc))

        evaluation_event = {
            "type": "evaluation_result",
            "payload": {
                "is_correct": bool(eval_result.get("is_correct", True)),
                "detected_misconception": misconception,
                "understanding_score": profile.understanding_score,
                "confusion_index": profile.confusion_index,
            },
        }

        logger.info(
            "checkpoint_service.evaluated",
            session_id=session_id,
            is_correct=evaluation_event["payload"]["is_correct"],
            misconception=misconception,
        )

        return {
            "is_correct": evaluation_event["payload"]["is_correct"],
            "detected_misconception": misconception,
            "events": [evaluation_event],
        }


checkpoint_service = CheckpointService()
