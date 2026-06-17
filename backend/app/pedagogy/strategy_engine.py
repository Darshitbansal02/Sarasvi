"""
Pedagogical Strategy Engine — dynamically plans open-ended strategy parameters.
"""

from typing import List, Union, Dict, Any
from pydantic import BaseModel, Field
import structlog
from app.utils.llm_client import llm_client
from app.reasoning.requirement_planner import ReasoningRequirementPlan
from app.models.user import User

logger = structlog.get_logger(__name__)

class StrategyParameter(BaseModel):
    name: str = Field(description="Name of the strategy parameter (e.g., analogy_density, proof_rigor, pace)")
    value: Union[str, float, int] = Field(description="Parameter value (string, float, or integer)")

class TeachingStrategy(BaseModel):
    strategy_id: str = Field(default_factory=lambda: f"strat_{__import__('uuid').uuid4().hex[:6]}")
    parameters: List[StrategyParameter] = Field(default_factory=list, description="List of strategy parameters")
    rationale: str = Field(description="Pedagogical reasoning for this strategy configuration")

_STRATEGY_SYSTEM_PROMPT = """You are Sarasvi's Teaching Strategy Engine.
Given a list of reasoning requirements and the student's cognitive state (confusion level, cognitive load/fatigue), compute an open-ended teaching strategy.

You must dynamically decide and output key parameters tailored to the lesson and learner state, including:
- analogy_density: High (e.g. 0.8) for confused students, low for advanced.
- visualization_intensity: High if the visual requirements are spatial or complex.
- proof_rigor: High for formal math/physics derivations when student confusion is low, lower when student is fatigued.
- simulation_frequency: High for dynamic processes (physics, algorithms) to model behavior.
- question_frequency: Rate of Socratic checkpoints to verify understanding.
- pacing: slow, normal, or fast depending on cognitive load.
- abstraction_level: intuitive, standard, or rigorous.

Return STRICT JSON matching this schema:
{
  "parameters": [
    {
      "name": "strategy_parameter_name",
      "value": "value"
    }
  ],
  "rationale": "Pedagogical rationale explaining these strategy choices"
}
"""

class StrategyEngine:
    async def plan_strategy(
        self,
        requirements: ReasoningRequirementPlan,
        confusion_level: float,
        cognitive_load: float,
        user: Any = None
    ) -> TeachingStrategy:
        """Plan open-ended teaching strategy based on reasoning requirements and student state."""
        logger.info("strategy_engine.start", requirements_count=len(requirements.requirements))
        
        user_prompt = (
            f"Requirements: {[r.model_dump() for r in requirements.requirements]}\n"
            f"Student Confusion Level: {confusion_level:.2f}\n"
            f"Student Cognitive Load: {cognitive_load:.2f}\n"
        )
        if user:
            user_prompt += f"User Hobbies/Interests: {user.learning_profile.get('hobbies', [])}\n"
            
        try:
            raw = await llm_client.generate_json(_STRATEGY_SYSTEM_PROMPT, user_prompt)
            strategy = TeachingStrategy.model_validate(raw)
            logger.info("strategy_engine.success", parameters_count=len(strategy.parameters))
            return strategy
        except Exception as exc:
            logger.warning("strategy_engine.failed", error=str(exc))
            # Safe default fallback parameters
            return TeachingStrategy(
                parameters=[
                    StrategyParameter(name="pace", value="normal"),
                    StrategyParameter(name="depth", value="standard"),
                    StrategyParameter(name="example_density", value=0.5)
                ],
                rationale="Fallback parameters applied due to LLM call failure."
            )

    def calculate_pedagogical_mix(self, user: User, concept_id: str) -> dict[str, float]:
        """Keep backwards-compatibility for existing pipeline references."""
        base_preferences = user.learning_profile.get(
            "session_pedagogical_preferences", 
            user.learning_profile.get("pedagogical_preferences", {
                "scientific": 0.5,
                "metaphorical": 0.5,
                "visual": 0.5,
                "storytelling": 0.5
            })
        )
        mix = base_preferences.copy()
        total = sum(mix.values())
        if total > 0:
            for k in mix:
                mix[k] = round(mix[k] / total, 2)
        return mix

strategy_engine = StrategyEngine()
