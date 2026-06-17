from __future__ import annotations
from typing import List


class LearningVelocityTracker:
    """
    LearningVelocityTracker — Tracks the rate of knowledge absorption.

    Old implementation: plain average of raw score deltas over the last 3
    attempts.  Problems:
      • Getting 1.0 on an easy question and 0.0 on a hard one looked the
        same as the opposite, even though they signal very different things.
      • Window of 3 was too narrow — a single fluke dominated the velocity.

    New implementation: difficulty-weighted trend over the last 6 attempts.
      • Each delta is scaled by the difficulty of the harder of the two
        adjacent questions so that improving on hard material counts more
        than coasting on easy material.
      • A 6-item window smooths noise while still reacting to recent change.
      • Returns a value in [-1.0, +1.0]:
          +1  = rapid, consistent improvement on hard content
           0  = stable (no net change)
          -1  = rapid decline
    """

    WINDOW = 6

    def compute_velocity(
        self,
        performance_history: List[float],
        difficulty_history: List[float] | None = None,
    ) -> float:
        """
        Args:
            performance_history: List of raw scores (0.0 or 1.0 per quiz).
            difficulty_history:  Corresponding question difficulties [0, 1].
                                 If None or shorter than performance_history,
                                 uniform difficulty 0.5 is assumed.

        Returns:
            Velocity in [-1.0, +1.0].
        """
        if len(performance_history) < 2:
            return 0.0

        scores = performance_history[-self.WINDOW:]
        diffs  = (difficulty_history or [])[-self.WINDOW:] if difficulty_history else []

        # Pad difficulty with neutral 0.5 if shorter than scores
        while len(diffs) < len(scores):
            diffs = [0.5] + diffs

        weighted_deltas: List[float] = []
        for i in range(1, len(scores)):
            delta = scores[i] - scores[i - 1]
            # Weight by the difficulty of the harder adjacent question
            weight = 0.5 + max(diffs[i - 1], diffs[i]) * 0.5
            weighted_deltas.append(delta * weight)

        if not weighted_deltas:
            return 0.0

        # Normalise to [-1, +1]: max possible weighted delta is +1.0 (easy→hard correct)
        raw_velocity = sum(weighted_deltas) / len(weighted_deltas)
        return round(max(-1.0, min(1.0, raw_velocity)), 3)
