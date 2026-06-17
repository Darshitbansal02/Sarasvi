from typing import Dict, List, Optional
from dataclasses import dataclass, field
import math
import time


@dataclass
class MisconceptionRecord:
    misconception_id: str
    confidence: float
    evidence: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConceptKnowledgeProfile:
    """
    Per-concept knowledge profile with personalised Ebbinghaus decay.

    forgetting_rate is no longer a global constant (0.0001).  It is computed
    from the student's mastery and exposure count for that concept:

        rate = BASE_RATE / (1 + exposure_count * 0.3) * (1 - mastery * 0.5)

    Meaning:
      • High-mastery concepts are forgotten half as fast as low-mastery ones.
      • Each re-exposure reduces the forgetting rate by ~30 % of one step.
      • A student with mastery=0.9 and exposure=5 retains a concept ~4× longer
        than a student seeing it for the first time with mastery=0.5.
    """
    concept: str
    mastery_score: float = 0.5
    retention_score: float = 1.0
    confidence_score: float = 0.5
    misconception_score: float = 0.0
    last_seen: float = field(default_factory=time.time)
    # Personalised; recomputed after every update (see _recompute_forgetting_rate)
    forgetting_rate: float = 0.0001
    exposure_count: int = 0
    misconception_records: List[MisconceptionRecord] = field(default_factory=list)

    # Base Ebbinghaus rate — halves retention in ~2 h for a brand-new concept
    BASE_FORGETTING_RATE: float = field(default=0.0001, init=False, repr=False)

    def recompute_forgetting_rate(self) -> None:
        """Personalise the forgetting rate from mastery and exposure history."""
        exposure_factor = 1.0 + self.exposure_count * 0.30
        mastery_factor  = 1.0 - self.mastery_score * 0.50
        self.forgetting_rate = max(
            1e-6,
            self.BASE_FORGETTING_RATE / exposure_factor * mastery_factor,
        )

    def decay_retention(self, current_time: float) -> float:
        """Apply exponential Ebbinghaus decay to retention_score."""
        elapsed = max(0.0, current_time - self.last_seen)
        self.retention_score = round(math.exp(-self.forgetting_rate * elapsed), 3)
        return self.retention_score


@dataclass
class StudentKnowledgeState:
    """
    Multi-dimensional graph of the student's knowledge across all concepts
    they have encountered in any session.
    """
    concept_profiles: Dict[str, ConceptKnowledgeProfile] = field(default_factory=dict)
    # Legacy flat lists kept for backward compatibility with downstream consumers
    mastered: List[str] = field(default_factory=list)
    fragile: List[str] = field(default_factory=list)
    misconceptions: List[str] = field(default_factory=list)
    overload_level: float = 0.0


class KnowledgeStateEstimator:
    """
    Evaluates and updates StudentKnowledgeState after each interaction.
    """

    def estimate_state(
        self,
        understanding_score: float,
        confusion_index: float,
        fatigue_level: float,
        active_misconceptions: List[str],
        current_concept: str,
        existing_state: Optional[StudentKnowledgeState] = None,
    ) -> StudentKnowledgeState:
        now = time.time()
        concept_profiles: Dict[str, ConceptKnowledgeProfile] = (
            existing_state.concept_profiles if existing_state else {}
        )

        # Decay retention for all tracked concepts using their personalised rates
        for cp in concept_profiles.values():
            cp.decay_retention(now)

        # Get or create profile for the current concept
        if current_concept not in concept_profiles:
            concept_profiles[current_concept] = ConceptKnowledgeProfile(
                concept=current_concept
            )

        profile = concept_profiles[current_concept]
        profile.last_seen = now
        profile.exposure_count += 1

        # Update mastery and confidence
        profile.mastery_score = round(understanding_score, 3)
        profile.confidence_score = round(
            max(0.0, min(1.0, (1.0 - confusion_index) * 0.7 + understanding_score * 0.3)),
            3,
        )

        # Misconception score for this concept
        concept_mc_count = sum(
            1 for m in active_misconceptions
            if current_concept in m or m in current_concept
        )
        profile.misconception_score = round(min(1.0, concept_mc_count * 0.4), 3)

        # Append new misconception records (avoid duplicates)
        existing_ids = {r.misconception_id for r in profile.misconception_records}
        for mc in active_misconceptions:
            if mc not in existing_ids:
                profile.misconception_records.append(
                    MisconceptionRecord(
                        misconception_id=mc,
                        confidence=max(0.5, profile.misconception_score),
                        evidence=(
                            f"Active misconception during analysis of '{current_concept}'"
                        ),
                        timestamp=now,
                    )
                )

        # Personalise forgetting rate now that mastery and exposure are updated
        profile.recompute_forgetting_rate()

        # Rebuild legacy flat lists
        mastered = [
            c for c, p in concept_profiles.items()
            if p.mastery_score >= 0.82 and p.retention_score >= 0.50
        ]
        fragile = [
            c for c, p in concept_profiles.items()
            if p.mastery_score < 0.55 or p.retention_score < 0.50
        ]

        # Cognitive overload
        base_overload = confusion_index * 0.5 + fatigue_level * 0.4
        if active_misconceptions:
            base_overload += 0.15
        overload_level = round(min(1.0, max(0.0, base_overload)), 3)

        return StudentKnowledgeState(
            concept_profiles=concept_profiles,
            mastered=mastered,
            fragile=fragile,
            misconceptions=list(active_misconceptions),
            overload_level=overload_level,
        )
