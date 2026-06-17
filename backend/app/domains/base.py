"""
Base interface for Domain Simulation Engines.
"""

from abc import ABC, abstractmethod
from typing import Any

from app.dsl.primitives import DSLInstruction


class BaseSimulationEngine(ABC):
    """
    Interface for domain-specific concept simulation engines.
    """

    domain_name: str = "general"
    required_primitive_types: list[str] = []
    forbidden_primitive_types: list[str] = []

    @abstractmethod
    def process_concept(self, concept_payload: dict[str, Any]) -> list[DSLInstruction]:
        """Convert a high-level concept into semantic DSL instructions."""
        pass

    def validate_plan(
        self,
        teaching_sequence: list[dict[str, Any]],
        *,
        query: str,
        concept_payload: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """
        Domain authority: reject plans that violate domain structure rules.
        Returns (passed, rejection_reasons).
        """
        rejections: list[str] = []
        visual_types = {
            str((step.get("visual_primitive") or {}).get("type", "")).lower()
            for step in teaching_sequence
            if step.get("visual_primitive")
        }
        for required in self.required_primitive_types:
            if required.lower() not in visual_types:
                rejections.append(f"missing_required_primitive:{required}")
        for forbidden in self.forbidden_primitive_types:
            if forbidden.lower() in visual_types:
                rejections.append(f"forbidden_primitive:{forbidden}")
        return len(rejections) == 0, rejections

    def constrain_sequence(
        self,
        teaching_sequence: list[dict[str, Any]],
        *,
        query: str,
        concept_payload: dict[str, Any],
        dsl_instructions: list[DSLInstruction],
    ) -> list[dict[str, Any]]:
        """
        Domain authority: reshape LLM sequence to match domain structure.
        Default merges engine skeleton before LLM steps when types are missing.
        """
        if not dsl_instructions:
            return teaching_sequence

        constrained = list(teaching_sequence)
        existing_types = {
            str((step.get("visual_primitive") or {}).get("type", "")).lower()
            for step in constrained
            if step.get("visual_primitive")
        }

        insert_at = 0
        for instr in dsl_instructions:
            prim_type = instr.primitive_type.value
            if prim_type.lower() in existing_types:
                continue
            constrained.insert(
                insert_at,
                {
                    "narration_sentence": f"Establish the {self.domain_name.replace('_', ' ')} structure for this concept.",
                    "visual_primitive": {
                        "type": prim_type,
                        "data": dict(instr.data),
                        "region": instr.region,
                        "duration_ms": instr.duration_ms or 1200,
                    },
                },
            )
            existing_types.add(prim_type.lower())
            insert_at += 1

        for step in constrained:
            prim = step.get("visual_primitive")
            if not isinstance(prim, dict):
                continue
            prim.setdefault("data", {})
            prim["data"].setdefault("domain", concept_payload.get("domain", self.domain_name))
            prim["data"].setdefault("concept", concept_payload.get("concept", query))

        return constrained
