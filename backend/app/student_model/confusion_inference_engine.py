from __future__ import annotations
import math


class ConfusionInferenceEngine:
    """
    ConfusionInferenceEngine — Estimates confusion probability from raw
    interaction signals.

    Old formula used arbitrary additive constants (0.45, 0.35, 0.18, 0.12)
    that were never fitted to data.  The new formula:

      1. Normalises each input to [0, 1] before weighting so the weights
         have an interpretable meaning ("fraction of maximum confusion
         attributable to each signal source").

      2. Uses smooth exponential normalisation for latency instead of hard
         thresholds (> 10s / > 5s), which caused sudden step changes in
         the confusion index.

      3. Weights sum to 1.0:
           gesture   40 % — cursor hesitation patterns (strongest real-time signal)
           latency   35 % — response time (reliable but noisy)
           errors    25 % — consecutive wrong answers

    These weights are still heuristic but are at least self-consistent and
    can be tuned as a single vector once real labeled data is available.
    """

    # Weight vector — must sum to 1.0
    W_GESTURE = 0.40
    W_LATENCY = 0.35
    W_ERRORS  = 0.25

    # Latency normalisation: tau_sec s maps to ~63% of max latency signal.
    # At tau=8s: 5s → 0.46, 10s → 0.71, 20s → 0.92 (smooth, no hard cliff)
    LATENCY_TAU = 8.0

    # Error normalisation: 4 consecutive errors maps to ~98% of max error signal
    ERROR_SCALE = 4.0

    def infer_confusion(
        self,
        gesture_intensity: float,
        latency_sec: float,
        consecutive_errors: int,
    ) -> float:
        """
        Return a confusion probability in [0, 1].

        Args:
            gesture_intensity:  Normalised cursor/gesture hesitation [0, 1].
            latency_sec:        Seconds the student took to respond.
            consecutive_errors: Number of wrong answers in a row.
        """
        # Normalise each signal to [0, 1]
        norm_gesture = max(0.0, min(1.0, gesture_intensity))
        norm_latency = 1.0 - math.exp(-latency_sec / self.LATENCY_TAU)
        norm_errors  = 1.0 - math.exp(-consecutive_errors / self.ERROR_SCALE)

        score = (
            self.W_GESTURE * norm_gesture
            + self.W_LATENCY * norm_latency
            + self.W_ERRORS  * norm_errors
        )

        return round(min(1.0, max(0.0, score)), 3)
