"""
Visual Goal Planner — maps high-level visual goals to representation specifications.
"""

from typing import Any, Dict
import structlog
from pydantic import BaseModel, Field
from app.utils.llm_client import llm_client
from app.semantic.semantic_understanding import SemanticUnderstanding
from app.reasoning.requirement_planner import ReasoningRequirementPlan
from app.pedagogy.strategy_engine import TeachingStrategy

logger = structlog.get_logger(__name__)

class RepresentationSpecification(BaseModel):
    representation_id: str = Field(default_factory=lambda: f"rep_{__import__('uuid').uuid4().hex[:6]}")
    representation_type: str = Field(description="Dynamic presentation model: e.g., relationship_network, process_flow, state_evolution, comparative_matrix")
    representation_details: dict = Field(default_factory=dict, description="Metadata describing components and structures")
    justification: str = Field(description="Pedagogical rationale for this representation")
    metadata: dict = Field(default_factory=dict, description="Operational metadata like strategy constraints")

_VISUAL_PLANNING_SYSTEM = """You are Sarasvi's Visual Goal Planner for an interactive teaching whiteboard.
Given a visual goal, semantic query understanding, reasoning requirements, and teaching strategy, determine the most effective representation specification.

Do NOT map directly to fixed whiteboard primitives (like graph or equation).
Instead, specify the cognitive layout representation model (e.g., relationship_network, process_flow, state_evolution, comparative_matrix, structural_sketch).

Return STRICT JSON matching this schema:
{
  "representation_type": "dynamic_representation_name",
  "representation_details": {
    "key_details_relevant_for_rendering": "details_here"
  },
  "justification": "why this representation was chosen"
}
"""

class VisualGoalPlanner:
    async def plan_visual_specification(
        self,
        visual_goal: str,
        semantic: SemanticUnderstanding,
        requirements: ReasoningRequirementPlan,
        strategy: TeachingStrategy,
        context: Dict[str, Any] = None
    ) -> RepresentationSpecification:
        """
        Generative visual planning mapping high-level goals and strategies to dynamic representation specifications.
        """
        strat_dict = strategy.model_dump() if (strategy and hasattr(strategy, "model_dump")) else (strategy or {})
        if not visual_goal or visual_goal == "none":
            return RepresentationSpecification(
                representation_type="none",
                representation_details={},
                justification="No visual representation requested.",
                metadata={"strategy": strat_dict}
            )

        user_prompt = (
            f"Visual Goal: {visual_goal}\n"
            f"Semantic Understanding Goal: {semantic.learning_goal}\n"
            f"Reasoning Requirements: {[r.model_dump() for r in requirements.requirements]}\n"
            f"Teaching Strategy Parameters: {[p.model_dump() for p in strategy.parameters]}\n"
        )
        if context:
            user_prompt += f"\nContext: {context}"

        try:
            logger.info("visual_goal_planner.calling_llm", goal=visual_goal)
            result = await llm_client.generate_json(_VISUAL_PLANNING_SYSTEM, user_prompt)
            spec = RepresentationSpecification.model_validate(result)
            spec.metadata["strategy"] = strat_dict
            logger.info("visual_goal_planner.success", representation=spec.representation_type)
            return spec
        except Exception as exc:
            logger.warning("visual_goal_planner.failed", error=str(exc))
            # Safe default fallback
            return RepresentationSpecification(
                representation_type="procedural_sketch",
                representation_details={"fallback": True},
                justification="Fallback due to LLM error.",
                metadata={"strategy": strat_dict}
            )

visual_goal_planner = VisualGoalPlanner()
