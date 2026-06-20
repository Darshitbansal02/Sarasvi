"""
Generation Manager — controls generation lifecycle for interruption safety.

A "generation" represents a single uninterrupted AI explanation cycle.
When interrupted, the current generation is invalidated and a new one starts.
All events with stale generation_ids are rejected by the scheduler.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class GenerationManager:
    """
    Manages generation IDs for a session.
    Ensures interruption-safe event invalidation.
    """

    def __init__(self, session_id: str):
        self._session_id = session_id
        self._current_generation_id: str = self._new_id()
        self._sequence_counter: int = 0
        self._invalidated_generations: set[str] = set()
        self._generation_history: list[dict] = []
        self._start_time_ms: int = int(
            datetime.now(timezone.utc).timestamp() * 1000
        )

    @property
    def current_generation_id(self) -> str:
        return self._current_generation_id

    @property
    def current_sequence(self) -> int:
        return self._sequence_counter

    def next_sequence(self) -> int:
        """Get next sequence number and increment counter."""
        seq = self._sequence_counter
        self._sequence_counter += 1
        return seq

    def elapsed_ms(self) -> int:
        """Milliseconds since session start."""
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        return now - self._start_time_ms

    def invalidate_current(self) -> tuple[str, str]:
        """
        Invalidate current generation and create a new one.
        Returns (old_generation_id, new_generation_id).
        Used during STOP_AND_REPLAN.
        """
        old_id = self._current_generation_id
        self._invalidated_generations.add(old_id)

        # Record history
        self._generation_history.append(
            {
                "generation_id": old_id,
                "invalidated_at": datetime.now(timezone.utc).isoformat(),
                "final_sequence": self._sequence_counter,
            }
        )

        # Start new generation
        self._current_generation_id = self._new_id()
        # Don't reset sequence — it's monotonically increasing per session
        logger.info(
            "generation.invalidated",
            session_id=self._session_id,
            old_generation=old_id,
            new_generation=self._current_generation_id,
        )
        return old_id, self._current_generation_id

    def set_current(self, generation_id: str) -> None:
        """Register an externally-created generation_id as the active generation.
        Used by /teach which creates its own gen_id before submitting the background job,
        so that /interrupt's invalidate_current() returns the correct old ID."""
        self._current_generation_id = generation_id

    def is_valid_generation(self, generation_id: str) -> bool:
        """Check if a generation ID is still valid (not invalidated)."""
        return generation_id not in self._invalidated_generations

    def is_current_generation(self, generation_id: str) -> bool:
        """Check if a generation ID is the current active one."""
        return generation_id == self._current_generation_id

    def is_stale(self, generation_id: str) -> bool:
        """Check if an event's generation is stale (should be rejected)."""
        return generation_id in self._invalidated_generations

    @property
    def history(self) -> list[dict]:
        """Get generation history for analytics."""
        return list(self._generation_history)

    @property
    def invalidated_count(self) -> int:
        """Number of invalidated generations (≈ number of interruptions)."""
        return len(self._invalidated_generations)

    @staticmethod
    def _new_id() -> str:
        return f"gen_{uuid.uuid4().hex[:12]}"

    # ── Serialization (for durable, externalized session state) ──────
    def to_state(self) -> dict:
        return {
            "current_generation_id": self._current_generation_id,
            "sequence_counter": self._sequence_counter,
            "invalidated_generations": sorted(self._invalidated_generations),
            "generation_history": self._generation_history,
            "start_time_ms": self._start_time_ms,
        }

    @classmethod
    def from_state(cls, session_id: str, state: dict | None) -> "GenerationManager":
        mgr = cls(session_id)
        if state:
            mgr._current_generation_id = state.get("current_generation_id", mgr._current_generation_id)
            mgr._sequence_counter = int(state.get("sequence_counter", 0))
            mgr._invalidated_generations = set(state.get("invalidated_generations", []))
            mgr._generation_history = list(state.get("generation_history", []))
            mgr._start_time_ms = int(state.get("start_time_ms", mgr._start_time_ms))
        return mgr
