"""
Teaching AST — Intermediate Representation for Sarasvi Lessons.

The Teaching AST is the single source of truth between LLM generation and
frontend rendering.  All renderers (board, narration, timeline, replay)
consume this AST — they never interpret raw LLM JSON directly.

Architecture:
    LLM Call 1 → SemanticPlan   (concepts, strategy, depth)
    LLM Call 2 → LessonSkeleton (segment structure)
    LLM Call 3 → TeachingAST    (full procedural expansion)
        ↓
    AST → Board Renderer     (stroke_reveal, equation_write)
    AST → Narration Renderer (speech events, TTS)
    AST → Timeline Renderer  (flat timeline with timing)
    AST → Replay Engine      (rewind, branch, checkpoint)
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LessonComplexity(str, Enum):
    """Adaptive complexity tier — controls lesson length and depth."""
    TRIVIAL = "trivial"        # 2-5 min  (e.g. "What is 2+2?")
    SIMPLE = "simple"          # 5-10 min (e.g. "What is gravity?")
    MODERATE = "moderate"      # 10-20 min (e.g. "Explain recursion")
    DEEP = "deep"              # 20-35 min (e.g. "Derive Bayes' Theorem")
    EXHAUSTIVE = "exhaustive"  # 35-50 min (e.g. "Full TCP/IP stack")


class VisualNodeType(str, Enum):
    """What the teacher draws / shows on the board."""
    EQUATION = "equation"
    EQUATION_WRITE = "equation_write"
    ANNOTATION = "annotation"
    CODE_BLOCK = "code_block"
    GRAPH = "graph"
    PROCEDURAL_SKETCH = "procedural_sketch"
    COMPLEXITY_LABEL = "complexity_label"
    ALGORITHM_STEP = "algorithm_step"
    EQUATION_HIGHLIGHT = "equation_highlight"
    TEACHER_GESTURE = "teacher_gesture"
    COGNITIVE_PAUSE = "cognitive_pause"
    CAMERA_MOVE = "camera_move"
    ATTENTION_FOCUS = "attention_focus"
    SIMULATION_START = "simulation_start"


class SegmentType(str, Enum):
    """Pedagogical role of a lesson segment."""
    MOTIVATION = "motivation"
    INTRODUCTION = "introduction"
    MENTAL_MODEL = "mental_model"
    DEFINITION = "definition"
    DERIVATION = "derivation"
    EXAMPLE = "example"
    APPLICATION = "application"
    MISCONCEPTION = "misconception"
    CHECKPOINT = "checkpoint"
    SUMMARY = "summary"


# ---------------------------------------------------------------------------
# AST Node Models
# ---------------------------------------------------------------------------

class VisualNode(BaseModel):
    """A single visual action on the board."""
    visual_type: VisualNodeType
    data: dict[str, Any] = Field(default_factory=dict)

    # Board-scoping metadata (for equations)
    board_id: str | None = None
    write_mode: str | None = None  # create, append, transform

    # Nib-on-word: the exact phrase, copied verbatim from THIS step's narration,
    # immediately after which the teacher should draw this visual. The
    # choreographer splits the narration here (say up to the phrase → draw →
    # continue). None / not-found → the visual is drawn after the full narration.
    reveal_anchor: str | None = None


class ReasoningStep(BaseModel):
    """
    One atomic teaching moment:
      • A factual claim (the truth)
      • A narration script (the teacher's words)
      • A visual node (what appears on the board)
    """
    step_id: str = Field(default_factory=lambda: f"rs_{uuid.uuid4().hex[:8]}")
    claim: str = Field(description="The factual/mathematical truth asserted")
    narration: str = Field(description="Teacher's spoken dialogue — 2-5 sentences")
    visual: VisualNode | None = None
    depends_on: list[str] = Field(default_factory=list)
    difficulty: float = 0.5


class TeachingSegment(BaseModel):
    """
    A coherent block of teaching — maps to a pedagogical phase.
    Contains multiple reasoning steps that form a logical unit.
    """
    segment_id: str = Field(default_factory=lambda: f"seg_{uuid.uuid4().hex[:6]}")
    segment_type: SegmentType = SegmentType.INTRODUCTION
    objective: str = ""
    reasoning_steps: list[ReasoningStep] = Field(default_factory=list)


class SemanticPlan(BaseModel):
    """
    Output of LLM Call 1 — semantic + pedagogical planning.
    Replaces: SemanticUnderstanding + ReasoningRequirementPlan + TeachingStrategy
    """
    plan_id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:6]}")
    learning_goal: str
    concepts: list[str] = Field(default_factory=list)
    domain: str = "general"
    subdomain: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    student_intent: str = "explanation"
    complexity: LessonComplexity = LessonComplexity.MODERATE
    predicted_misconceptions: list[str] = Field(default_factory=list)

    # Strategy parameters (open-ended)
    strategy_parameters: dict[str, Any] = Field(default_factory=dict)
    strategy_rationale: str = ""

    # Success criteria (what the student must be able to do)
    success_criteria: list[str] = Field(default_factory=list)

    # Constraints from the student's query
    constraints: list[str] = Field(default_factory=list)

    # Target step counts derived from complexity
    @property
    def target_segments(self) -> tuple[int, int]:
        """(min_segments, max_segments) for the skeleton call."""
        return {
            LessonComplexity.TRIVIAL: (2, 4),
            LessonComplexity.SIMPLE: (3, 6),
            LessonComplexity.MODERATE: (5, 10),
            LessonComplexity.DEEP: (8, 15),
            LessonComplexity.EXHAUSTIVE: (12, 20),
        }.get(self.complexity, (5, 10))

    @property
    def target_steps_per_segment(self) -> tuple[int, int]:
        """(min_steps, max_steps) per segment for the expansion call."""
        return {
            LessonComplexity.TRIVIAL: (2, 3),
            LessonComplexity.SIMPLE: (2, 4),
            LessonComplexity.MODERATE: (3, 6),
            LessonComplexity.DEEP: (4, 8),
            LessonComplexity.EXHAUSTIVE: (5, 10),
        }.get(self.complexity, (3, 6))


class LessonSkeleton(BaseModel):
    """
    Output of LLM Call 2 — structural skeleton of the lesson.
    Contains segment containers without detailed reasoning steps.
    """
    skeleton_id: str = Field(default_factory=lambda: f"skel_{uuid.uuid4().hex[:6]}")
    objective: str = ""
    domain: str = "general"
    final_answer_type: str = "conceptual"
    segments: list[SkeletonSegment] = Field(default_factory=list)


class SkeletonSegment(BaseModel):
    """A segment placeholder in the skeleton — no reasoning steps yet."""
    segment_id: str = Field(default_factory=lambda: f"seg_{uuid.uuid4().hex[:6]}")
    segment_type: str = "introduction"
    objective: str = ""
    narration_goals: list[str] = Field(default_factory=list)
    visual_goals: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)


# Fix forward reference — LessonSkeleton references SkeletonSegment
LessonSkeleton.model_rebuild()


class TeachingAST(BaseModel):
    """
    The complete Teaching AST — the single source of truth for a lesson.
    
    Produced by LLM Call 3 (Procedural Expansion) and consumed by all renderers.
    This is the architectural boundary: nothing downstream talks to the LLM.
    Everything downstream transforms the AST into rendering instructions.
    """
    ast_id: str = Field(default_factory=lambda: f"ast_{uuid.uuid4().hex[:8]}")

    # Lineage — which plan & skeleton produced this AST
    plan_id: str = ""
    skeleton_id: str = ""

    # Metadata
    learning_objective: str = ""
    domain: str = "general"
    complexity: LessonComplexity = LessonComplexity.MODERATE
    concepts: list[str] = Field(default_factory=list)

    # The tree
    segments: list[TeachingSegment] = Field(default_factory=list)

    # Student context at generation time
    student_profile: dict[str, Any] = Field(default_factory=dict)

    # Verification results
    verification: dict[str, Any] = Field(default_factory=dict)

    @property
    def total_steps(self) -> int:
        return sum(len(seg.reasoning_steps) for seg in self.segments)

    @property
    def all_narration(self) -> str:
        """Concatenated narration text for the entire lesson."""
        parts = []
        for seg in self.segments:
            for step in seg.reasoning_steps:
                if step.narration:
                    parts.append(step.narration)
        return " ".join(parts)

    def to_teaching_sequence(self) -> list[dict[str, Any]]:
        """
        Flatten the AST into the legacy teaching_sequence format
        for backward compatibility with existing pipeline stages
        (verification, lesson_conversion, etc.).
        """
        sequence = []
        for segment in self.segments:
            for step in segment.reasoning_steps:
                entry: dict[str, Any] = {
                    "step_id": step.step_id,
                    "narration_sentence": step.narration,
                    "claim": step.claim,
                    "depends_on": step.depends_on,
                    "difficulty": step.difficulty,
                }
                if step.visual:
                    vtype = step.visual.visual_type.value
                    vdata = dict(step.visual.data)
                    if step.visual.board_id:
                        vdata["board_id"] = step.visual.board_id
                    if step.visual.write_mode:
                        vdata["write_mode"] = step.visual.write_mode
                    if step.visual.reveal_anchor:
                        vdata["reveal_anchor"] = step.visual.reveal_anchor
                    entry["visual_primitive"] = {
                        "type": vtype,
                        "data": vdata,
                    }
                sequence.append(entry)
        return sequence
