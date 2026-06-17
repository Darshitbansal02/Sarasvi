"""Structured pedagogical plan models — single contract for all entry paths."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PlanObjective(BaseModel):
    text: str = ""
    domain: str = "general"
    final_answer_type: str = "conceptual"


class ReasoningStep(BaseModel):
    step_id: str = ""
    narration: str = ""
    rationale: str = ""
    depends_on: list[str] = Field(default_factory=list)


class VisualStep(BaseModel):
    step_id: str = ""
    primitive_type: str = ""
    narration: str = ""
    board_role: Optional[str] = None
    region: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


class PlanVerification(BaseModel):
    math_claims: list[dict[str, Any]] = Field(default_factory=list)
    passed: bool = True
    rejections: list[str] = Field(default_factory=list)
    attempts: int = 0


class PlanConclusion(BaseModel):
    narration: str = ""
    final_answer: str = ""
    latex: str = ""


class PedagogicalPlanStep(BaseModel):
    """Legacy flat step — retained for timeline compatibility."""
    step_id: str = ""
    intent: str = ""
    content_kind: str = ""
    depends_on: list[str] = Field(default_factory=list)
    board_role: Optional[str] = None
    region: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


class PedagogicalPlan(BaseModel):
    objective: PlanObjective = Field(default_factory=PlanObjective)
    concepts: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    reasoning_steps: list[ReasoningStep] = Field(default_factory=list)
    visual_steps: list[VisualStep] = Field(default_factory=list)
    verification: PlanVerification = Field(default_factory=PlanVerification)
    conclusion: PlanConclusion = Field(default_factory=PlanConclusion)
    steps: list[PedagogicalPlanStep] = Field(default_factory=list)
    teaching_segments: list[Any] = Field(default_factory=list)

    @classmethod
    def from_semantic(
        cls,
        *,
        query: str,
        semantic: dict[str, Any],
        prerequisites: list[str] | None = None,
    ) -> "PedagogicalPlan":
        teaching_profile = semantic.get("teaching_profile", {})
        concepts = teaching_profile.get("concepts") or semantic.get("concepts") or [query]
        
        # Populate teaching_segments if present in semantic
        teaching_segments = []
        if "teaching_segments" in teaching_profile:
            teaching_segments = teaching_profile["teaching_segments"]
        elif "teaching_segments" in semantic:
            teaching_segments = semantic["teaching_segments"]

        return cls(
            objective=PlanObjective(
                text=semantic.get("learning_objective") or teaching_profile.get("learning_objective") or query,
                domain=teaching_profile.get("primary_domain", "general"),
                final_answer_type=teaching_profile.get("final_answer_type", "conceptual"),
            ),
            concepts=list(concepts),
            prerequisites=list(prerequisites or []),
            teaching_segments=teaching_segments,
        )

    def merge_teaching_sequence(
        self,
        teaching_sequence: list[dict[str, Any]],
        *,
        math_claims: list[dict[str, Any]] | None = None,
        verification_passed: bool = True,
        rejections: list[str] | None = None,
        attempts: int = 0,
    ) -> "PedagogicalPlan":
        reasoning: list[ReasoningStep] = []
        visual: list[VisualStep] = []
        flat_steps: list[PedagogicalPlanStep] = []

        for index, step in enumerate(teaching_sequence):
            narration = step.get("narration_sentence", "") or ""
            prim = step.get("visual_primitive") or {}
            prim_type = prim.get("type", "speech") if isinstance(prim, dict) else "speech"
            payload = prim.get("data", {}) if isinstance(prim, dict) else {}
            step_id = str(
                payload.get("equation_id")
                or payload.get("annotation_id")
                or payload.get("step_id")
                or f"step_{index}"
            )

            if narration:
                reasoning.append(
                    ReasoningStep(
                        step_id=f"reason_{step_id}",
                        narration=narration,
                        rationale=str(payload.get("rule") or payload.get("annotation") or ""),
                        depends_on=[f"step_{index - 1}"] if index > 0 else [],
                    )
                )

            if isinstance(prim, dict) and prim.get("type"):
                visual.append(
                    VisualStep(
                        step_id=step_id,
                        primitive_type=str(prim_type),
                        narration=narration,
                        board_role=payload.get("board_role") or prim.get("board_role"),
                        region=prim.get("region") or payload.get("region"),
                        data=dict(payload),
                    )
                )

            flat_steps.append(
                PedagogicalPlanStep(
                    step_id=step_id,
                    intent=str(prim_type),
                    content_kind=str(prim_type),
                    depends_on=[f"step_{index - 1}"] if index > 0 else [],
                    board_role=payload.get("board_role"),
                    region=prim.get("region") if isinstance(prim, dict) else None,
                    data=dict(payload),
                )
            )

        conclusion_narration = ""
        conclusion_latex = ""
        final_answer = ""
        for step in reversed(teaching_sequence):
            text = step.get("narration_sentence", "").strip()
            if text and not conclusion_narration:
                conclusion_narration = text
            prim = step.get("visual_primitive") or {}
            if isinstance(prim, dict):
                data = prim.get("data") or {}
                latex = str(data.get("full_latex") or data.get("latex") or "").strip()
                if latex and not conclusion_latex:
                    conclusion_latex = latex
                    if "=" in latex:
                        final_answer = latex.split("=", 1)[1].strip()
            if conclusion_narration and conclusion_latex:
                break

        self.reasoning_steps = reasoning
        self.visual_steps = visual
        self.steps = flat_steps
        self.conclusion = PlanConclusion(
            narration=conclusion_narration,
            final_answer=final_answer,
            latex=conclusion_latex,
        )
        self.verification = PlanVerification(
            math_claims=list(math_claims or []),
            passed=verification_passed,
            rejections=list(rejections or []),
            attempts=attempts,
        )
        return self

    def to_synthesis_modifier(self) -> str:
        """Constraint text injected into LLM synthesis."""
        lines = [
            f"Learning objective: {self.objective.text}",
            f"Domain: {self.objective.domain}",
            f"Final answer type: {self.objective.final_answer_type}",
            f"Concepts: {', '.join(self.concepts)}",
        ]
        if self.prerequisites:
            lines.append(f"Prerequisites to acknowledge: {', '.join(self.prerequisites)}")
        if self.reasoning_steps:
            lines.append("Reasoning must follow: setup → derivation → verification → conclusion.")
        return "\n".join(lines)

    @classmethod
    def from_runtime_steps(cls, objective: str, runtime_steps: list[dict[str, Any]]) -> "PedagogicalPlan":
        plan = cls(objective=PlanObjective(text=objective))
        sequence = []
        for step in runtime_steps:
            payload = step.get("payload", {}) if isinstance(step, dict) else {}
            sequence.append(
                {
                    "narration_sentence": payload.get("narration", ""),
                    "visual_primitive": {"type": step.get("type", "speech"), "data": payload},
                }
            )
        return plan.merge_teaching_sequence(sequence)
