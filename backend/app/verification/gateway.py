"""
VerificationGateway — single entry point for all lesson verification concerns.

Before this, four overlapping validators were imported ad-hoc across the pipeline
(plus one dead `ValidationEngine`, now removed). They have genuinely distinct jobs,
so this gateway unifies the *call surface* (one import, one object) while delegating
to the existing, unchanged implementations:

    validate_synthesis / validate_teaching_sequence → pedagogy.ValidationLayer
    validate_coverage                               → pedagogy.lesson_validator
    validate_timeline                               → services.timeline_validator
    formal (domain claim verification)              → verification.service

This is the place to add or swap verification rules in future, without threading
new imports through routes/services.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class VerificationGateway:
    def __init__(self) -> None:
        from app.pedagogy.validation_layer import ValidationLayer, lesson_validator
        self._synthesis = ValidationLayer()
        self._coverage = lesson_validator

    # ── Synthesis / teaching-sequence checks (pre-compile) ───────────
    def validate_synthesis(self, lesson: dict) -> bool:
        return self._synthesis.validate_synthesis(lesson)

    def validate_teaching_sequence(self, sequence: list, *, query: str) -> bool:
        return self._synthesis.validate_teaching_sequence(sequence, query=query)

    # ── Coverage check (post-compile, soft) ──────────────────────────
    def validate_coverage(
        self, events: list, instructions: Any, layout_assets: Optional[dict]
    ) -> tuple[bool, list]:
        return self._coverage.validate_timeline(events, instructions, layout_assets)

    # ── Strict timeline check (post-reconcile, raises on hard errors) ─
    def validate_timeline(self, events: list, *, layout_assets: Optional[dict] = None) -> None:
        from app.services.timeline_validator import validate_timeline as _validate_timeline
        _validate_timeline(events, layout_assets=layout_assets)

    # ── Formal domain-claim verification (math/physics/...) ──────────
    @property
    def formal(self):
        from app.verification.service import verification_service
        return verification_service


# Singleton — the canonical verification entry point.
verification_gateway = VerificationGateway()
