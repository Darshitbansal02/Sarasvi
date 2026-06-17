from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Dict, Any, List

from app.student_model.knowledge_state_estimator import KnowledgeStateEstimator, StudentKnowledgeState
from app.student_model.confusion_inference_engine import ConfusionInferenceEngine
from app.student_model.learning_velocity_tracker import LearningVelocityTracker


@dataclass
class StudentProfile:
    """
    StudentProfile — Real-time state metrics tracking understanding,
    active fatigue, local confusion index, and predicted misconceptions.
    """
    student_id: str
    understanding_score: float = 0.5   # 0.0 (lost) → 1.0 (mastery)
    confusion_index: float = 0.1       # 0.0 (clear) → 1.0 (highly confused)
    fatigue_level: float = 0.0         # 0.0 (fresh) → 1.0 (exhausted)
    active_misconceptions: List[str] = field(default_factory=list)

    # Rich performance history: (score, difficulty) tuples so velocity and
    # understanding can be weighted by question difficulty, not just raw score.
    performance_history: List[float] = field(default_factory=list)
    difficulty_history: List[float] = field(default_factory=list)

    learning_velocity: float = 0.0
    knowledge_state: StudentKnowledgeState = field(default_factory=StudentKnowledgeState)

    # Cumulative interaction counts used for adaptive decay of signal weights
    total_interactions: int = 0
    consecutive_errors: int = 0

    # Real-time sensor metrics for ConfusionInferenceEngine calibration
    latest_gesture_intensity: float = 0.0
    latest_latency_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize scalar metrics. knowledge_state is recomputed on load from
        these scalars via the estimator, so it is intentionally not persisted."""
        return {
            "student_id": self.student_id,
            "understanding_score": self.understanding_score,
            "confusion_index": self.confusion_index,
            "fatigue_level": self.fatigue_level,
            "active_misconceptions": list(self.active_misconceptions),
            "performance_history": list(self.performance_history),
            "difficulty_history": list(self.difficulty_history),
            "learning_velocity": self.learning_velocity,
            "total_interactions": self.total_interactions,
            "consecutive_errors": self.consecutive_errors,
            "latest_gesture_intensity": self.latest_gesture_intensity,
            "latest_latency_sec": self.latest_latency_sec,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StudentProfile":
        return cls(
            student_id=data["student_id"],
            understanding_score=float(data.get("understanding_score", 0.5)),
            confusion_index=float(data.get("confusion_index", 0.1)),
            fatigue_level=float(data.get("fatigue_level", 0.0)),
            active_misconceptions=list(data.get("active_misconceptions", [])),
            performance_history=list(data.get("performance_history", [])),
            difficulty_history=list(data.get("difficulty_history", [])),
            learning_velocity=float(data.get("learning_velocity", 0.0)),
            total_interactions=int(data.get("total_interactions", 0)),
            consecutive_errors=int(data.get("consecutive_errors", 0)),
            latest_gesture_intensity=float(data.get("latest_gesture_intensity", 0.0)),
            latest_latency_sec=float(data.get("latest_latency_sec", 0.0)),
        )


class CognitiveTracker:
    """
    CognitiveTracker — Evaluates student interactive indicators to update
    cognitive metrics.

    Signal calibration rationale
    ────────────────────────────
    All adjustments are bounded and use smooth functions rather than hard
    threshold steps.  The magnitudes were chosen so that:
      • A single wrong answer moves confusion by ~0.20–0.35 (not 0.35 always)
      • A 15-second latency is the ceiling for confusion contribution (not 8s)
      • Correct streaks visibly reduce confusion (positive reinforcement)
      • draw_pause / replay_scrub / session_interrupt are first-class signals
        wired directly from the frontend rather than synthesised fakes
    """

    def __init__(self):
        self.estimator = KnowledgeStateEstimator()
        self.inference_engine = ConfusionInferenceEngine()
        self.velocity_tracker = LearningVelocityTracker()

    def get_or_create_profile(
        self, student_id: str, learning_profile: dict | None = None
    ) -> StudentProfile:
        from app.services.session_state_store import session_state_store
        managers = session_state_store.profile_slot(student_id)

        if not managers.get("profile"):
            lp = learning_profile or {}
            profile = StudentProfile(
                student_id=student_id,
                understanding_score=float(lp.get("understanding_score", 0.5)),
                confusion_index=float(lp.get("confusion_index", 0.1)),
                fatigue_level=float(lp.get("fatigue_level", 0.0)),
                active_misconceptions=list(lp.get("active_misconceptions", [])),
                learning_velocity=float(lp.get("learning_velocity", 0.0)),
            )
            profile.knowledge_state = self.estimator.estimate_state(
                profile.understanding_score,
                profile.confusion_index,
                profile.fatigue_level,
                profile.active_misconceptions,
                "general",
                existing_state=None,
            )
            managers["profile"] = profile
        return managers["profile"]

    def reset_profile(self, student_id: str) -> None:
        from app.services.session_state_store import session_state_store
        session_state_store.profile_slot(student_id)["profile"] = None

    # ── Durable hydration / persistence (async, called at request boundaries) ──
    async def hydrate(self, student_id: str, learning_profile: dict | None = None) -> StudentProfile:
        """Warm the in-process profile cache from the DB (rebuilding the knowledge
        graph from persisted scalars). Falls back to a fresh profile."""
        from app.services.session_state_store import session_state_store
        slot = session_state_store.profile_slot(student_id)
        if slot.get("profile") is None:
            data = await session_state_store.load_profile(student_id)
            if data:
                profile = StudentProfile.from_dict(data)
                profile.knowledge_state = self.estimator.estimate_state(
                    profile.understanding_score,
                    profile.confusion_index,
                    profile.fatigue_level,
                    profile.active_misconceptions,
                    "general",
                    existing_state=None,
                )
                slot["profile"] = profile
        return self.get_or_create_profile(student_id, learning_profile)

    async def persist(self, student_id: str) -> None:
        """Persist the cached profile to the DB."""
        from app.services.session_state_store import session_state_store
        profile = session_state_store.profile_slot(student_id).get("profile")
        if profile is not None:
            await session_state_store.save_profile(student_id, profile.to_dict())

    async def reset_profile_durable(self, student_id: str) -> None:
        from app.services.session_state_store import session_state_store
        await session_state_store.clear_profile(student_id)


    def record_interaction(
        self, student_id: str, event_type: str, payload: Dict[str, Any]
    ) -> StudentProfile:
        """
        Process a student interaction event and update the cognitive profile.

        Supported event types
        ─────────────────────
        response_latency    — how long the student took to respond (seconds)
        quiz_outcome        — result of a checkpoint question
        hesitation_indicator— cursor/gesture hesitation intensity (0–1)
        draw_pause          — student stopped drawing mid-stroke (frontend signal)
        replay_scrub        — student seeked backward in replay (strong confusion)
        session_interrupt   — student clicked "Interrupt & Ask" button
        concept_mastered    — explicit mastery event from evaluation layer
        """
        profile = self.get_or_create_profile(student_id)
        profile.total_interactions += 1

        # ── response_latency ─────────────────────────────────────────
        if event_type == "response_latency":
            delay = float(payload.get("delay_seconds", 1.0))
            profile.latest_latency_sec = delay
            # Smooth sigmoid-like ramp: 0 at 0s, ~0.15 at 5s, ~0.28 at 10s, caps at 0.35 at 15s+
            latency_signal = 0.35 * (1 - math.exp(-delay / 8.0))
            profile.confusion_index = min(1.0, profile.confusion_index + latency_signal)
            # Fatigue grows slowly with long response times
            if delay > 10.0:
                profile.fatigue_level = min(1.0, profile.fatigue_level + 0.04)

        # ── quiz_outcome ─────────────────────────────────────────────
        elif event_type == "quiz_outcome":
            is_correct = bool(payload.get("is_correct", False))
            difficulty = float(payload.get("difficulty", 0.5))  # 0=easy, 1=hard

            profile.performance_history.append(1.0 if is_correct else 0.0)
            profile.difficulty_history.append(difficulty)

            if is_correct:
                profile.consecutive_errors = 0
                # Confusion drops more when the question was hard
                relief = 0.15 + difficulty * 0.12
                profile.confusion_index = max(0.0, profile.confusion_index - relief)
                trigger = payload.get("misconception_trigger")
                if trigger and trigger in profile.active_misconceptions:
                    profile.active_misconceptions.remove(trigger)
            else:
                profile.consecutive_errors += 1
                # Confusion rises more on hard questions; caps at a streak of 3
                penalty = (0.15 + difficulty * 0.20) * min(1.0, profile.consecutive_errors / 3.0 + 0.5)
                profile.confusion_index = min(1.0, profile.confusion_index + penalty)
                trigger = payload.get("misconception_trigger")
                if trigger and trigger not in profile.active_misconceptions:
                    profile.active_misconceptions.append(trigger)

            # Understanding = difficulty-weighted rolling average (last 8)
            recent_s = profile.performance_history[-8:]
            recent_d = profile.difficulty_history[-8:]
            weights = [0.5 + d * 0.5 for d in recent_d]
            total_w = sum(weights) or 1.0
            profile.understanding_score = sum(s * w for s, w in zip(recent_s, weights)) / total_w

            # Fatigue creeps up with every question attempt
            profile.fatigue_level = min(1.0, profile.fatigue_level + 0.015)

        # ── hesitation_indicator ─────────────────────────────────────
        elif event_type == "hesitation_indicator":
            intensity = float(payload.get("intensity", 0.5))
            profile.latest_gesture_intensity = intensity
            # Scale proportionally; a full-intensity hesitation adds ~0.20
            profile.confusion_index = min(1.0, profile.confusion_index + intensity * 0.20)

        # ── draw_pause (frontend: student stopped drawing mid-stroke) ─
        elif event_type == "draw_pause":
            pause_ms = float(payload.get("duration_ms", 0))
            # Pauses > 2s during active drawing are a mild confusion signal
            if pause_ms > 2000:
                signal = 0.08 * min(1.0, (pause_ms - 2000) / 8000.0)
                profile.confusion_index = min(1.0, profile.confusion_index + signal)

        # ── replay_scrub (strong confusion: student went backward) ────
        elif event_type == "replay_scrub":
            # Any backward seek in replay is a strong indicator of confusion
            scrub_delta_ms = float(payload.get("delta_ms", 0))
            if scrub_delta_ms < 0:  # backward seek
                profile.confusion_index = min(1.0, profile.confusion_index + 0.18)

        # ── session_interrupt (student clicked "Interrupt & Ask") ─────
        elif event_type == "session_interrupt":
            # Interruptions are a direct confusion signal (student couldn't follow)
            profile.confusion_index = min(1.0, profile.confusion_index + 0.22)
            profile.fatigue_level = min(1.0, profile.fatigue_level + 0.05)

        # ── concept_mastered (from evaluation layer) ──────────────────
        elif event_type == "concept_mastered":
            profile.understanding_score = min(1.0, profile.understanding_score + 0.12)
            profile.confusion_index = max(0.0, profile.confusion_index - 0.10)

        elif event_type == "cognitive_load":
            # Client-sensed presentation load (scene density/complexity) reported by
            # the frontend as a SENSOR reading. The backend is the authority: we fold
            # it into fatigue via an EMA (bounded, smooth) so the next generation's
            # effective load reflects it, but it never hard-overrides. This is a
            # lightweight sensor update — skip the heavy confusion/velocity/graph
            # recompute below (which keys off interaction sensors, not visual load).
            load = max(0.0, min(1.0, float(payload.get("load", 0.0))))
            profile.fatigue_level = min(1.0, 0.85 * profile.fatigue_level + 0.15 * load)
            return profile

        # ── Centralized Confusion Calibration ────────────────────────
        inferred_index = self.inference_engine.infer_confusion(
            profile.latest_gesture_intensity,
            profile.latest_latency_sec,
            profile.consecutive_errors,
        )
        profile.confusion_index = max(profile.confusion_index, inferred_index)

        # ── Confidence calibration (runs after every event) ──────────
        # Underconfidence: high mastery but high confusion → gently reduce confusion
        if profile.understanding_score >= 0.75 and profile.confusion_index > 0.40:
            profile.confusion_index = max(0.10, profile.confusion_index - 0.12)
        # Overconfidence: low mastery but very low confusion → raise slightly so
        # the Socratic engine gets triggered appropriately
        elif profile.understanding_score < 0.40 and profile.confusion_index < 0.15:
            profile.confusion_index = min(0.55, profile.confusion_index + 0.15)

        # ── Learning velocity ─────────────────────────────────────────
        profile.learning_velocity = self.velocity_tracker.compute_velocity(
            profile.performance_history,
            profile.difficulty_history,
        )

        # ── Knowledge state graph ─────────────────────────────────────
        current_concept = payload.get("concept", "general")
        profile.knowledge_state = self.estimator.estimate_state(
            profile.understanding_score,
            profile.confusion_index,
            profile.fatigue_level,
            profile.active_misconceptions,
            current_concept,
            existing_state=profile.knowledge_state,
        )

        return profile
