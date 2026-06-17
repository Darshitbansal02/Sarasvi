"""
Reasoning Requirement Planner — dynamically plans the required cognitive operations and dependency graphs.
"""

from typing import List, Dict, Any
from pydantic import BaseModel, Field
import structlog
from app.utils.llm_client import llm_client
from app.semantic.semantic_understanding import SemanticUnderstanding

logger = structlog.get_logger(__name__)

class ReasoningRequirement(BaseModel):
    objective: str = Field(description="Cognitive objective of this requirement")
    operations: List[str] = Field(default_factory=list, description="Emergent reasoning operations to execute")
    dependencies: List[str] = Field(default_factory=list, description="Objectives of other requirements this depends on")

class ReasoningRequirementPlan(BaseModel):
    requirements_id: str = Field(default_factory=lambda: f"req_{__import__('uuid').uuid4().hex[:6]}")
    requirements: List[ReasoningRequirement] = Field(default_factory=list, description="List of reasoning requirements")
    success_criteria: List[str] = Field(default_factory=list, description="Granular, progressive items student must master")
    pedagogical_justification: str = Field(default="No justification provided", description="Justification for selecting this reasoning trajectory")

_REQUIREMENT_SYSTEM_PROMPT = """You are Sarasvi's Reasoning Requirement Planner.
Given the student's semantic query analysis, identify the cognitive reasoning requirements, operations, and granular success criteria needed to explain the concept.

You must dynamically invent emergent, open-ended operations (e.g., stack_unrolling, counterfactual_projection, network_effect_analysis) matching the query.
Produce an extremely comprehensive, progressive, and deep list of at least 15 to 25 highly granular requirements and corresponding success criteria (objectives) for deep topics (like recursion, Bayes' theorem, TCP handshake). Do NOT aggregate milestones; split them into highly atomic logical blocks. You must explicitly include success criteria and objectives covering:
1. Motivation/Real-world analogy
2. Core definition / Mathematical setup (explicitly using the terms "conditional probability" and "joint probability")
3. Structural mental model (explicitly using the term "symmetry" of set intersection / commutative property)
4. Step-by-step trace / Worked derivation (explicitly using the terms "bayes formula" and "derivation" / isolating terms)
5. Component interpretation & labeling (explicitly using the term "interpretation" for prior, likelihood, evidence)
6. Worked example / numerical application
7. Edge cases / Failure states (e.g., P(B) = 0 division by zero)
8. Common student mistakes/misconceptions
9. Real-world applications
10. Synthesis & Summary (explicitly using the term "summary" / belief updating)

For mathematical derivations (like Bayes' Theorem) or systems explanations (like TCP), do NOT aggregate multiple algebraic moves or state changes into one. Split them into highly atomic logical blocks (e.g., define joint probability, define conditional probability, equate symmetric intersections, isolate term, worked example scenario, etc.). Use the exact terminology specified above to maintain pedagogical completeness.

Return STRICT JSON matching this schema:
{
  "requirements": [
    {
      "objective": "The cognitive objective (e.g. 'Define the conditional probability equation')",
      "operations": ["emergent_snake_case_operation_name"],
      "dependencies": ["objectives of requirements this step depends on"]
    }
  ],
  "success_criteria": [
    "Granular, concrete item the student must be able to do or explain (e.g., 'Understand and write down the symmetry equation P(A and B) = P(B and A)')"
  ],
  "pedagogical_justification": "Why this reasoning trajectory was chosen"
}
"""

class ReasoningRequirementPlanner:
    async def plan_requirements(self, semantic: SemanticUnderstanding) -> ReasoningRequirementPlan:
        """Plan emergent reasoning requirements based on semantic profile."""
        logger.info("requirement_planner.start", goal=semantic.learning_goal)
        
        user_prompt = (
            f"Learning Goal: {semantic.learning_goal}\n"
            f"Concepts: {semantic.concepts}\n"
            f"Constraints: {semantic.constraints}\n"
            f"Intent: {semantic.student_intent}\n"
            f"Prior Assumptions: {semantic.prior_knowledge_assumptions}\n"
            f"Transitions: {[t.model_dump() for t in semantic.conceptual_transitions]}\n"
        )
        
        try:
            raw = await llm_client.generate_json(_REQUIREMENT_SYSTEM_PROMPT, user_prompt)
            plan = ReasoningRequirementPlan.model_validate(raw)
            logger.info("requirement_planner.success", requirements_count=len(plan.requirements))
            return plan
        except Exception as exc:
            logger.warning("requirement_planner.failed", error=str(exc))
            # Safe domain-agnostic fallback
            return ReasoningRequirementPlan(
                requirements=[
                    ReasoningRequirement(
                        objective=semantic.learning_goal,
                        operations=["procedural_exposition"],
                        dependencies=[]
                    )
                ],
                pedagogical_justification="Fallback due to LLM request failure."
            )

reasoning_requirement_planner = ReasoningRequirementPlanner()
