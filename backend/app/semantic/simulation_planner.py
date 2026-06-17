"""
Simulation Planner — plans Executable Mental Models dynamically.
"""

from typing import List, Dict, Any
from pydantic import BaseModel, Field
import structlog
from app.utils.llm_client import llm_client
from app.reasoning.requirement_planner import ReasoningRequirementPlan
from app.pedagogy.strategy_engine import TeachingStrategy

logger = structlog.get_logger(__name__)

class SimulationEntity(BaseModel):
    id: str = Field(description="Unique ID of the entity")
    type: str = Field(description="Entity type (e.g., node, body, particle)")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Initial properties")

class SimulationRule(BaseModel):
    name: str = Field(description="Rule name")
    formula: str = Field(description="Dynamics formula (e.g., x = x + v*dt)")

class SimulationState(BaseModel):
    variables: Dict[str, Any] = Field(default_factory=dict, description="Variable values")

class SimulationTransition(BaseModel):
    trigger: str = Field(description="Event that triggers the state change")
    target_state: str = Field(description="Target state name")

class SimulationSpecification(BaseModel):
    simulation_type: str = Field(description="Dynamic model class (e.g. queue, particle_physics)")
    entities: List[SimulationEntity] = Field(default_factory=list)
    rules: List[SimulationRule] = Field(default_factory=list)
    initial_state: SimulationState = Field(default_factory=SimulationState)
    transitions: List[SimulationTransition] = Field(default_factory=list)
    justification: str = Field(description="Pedagogical justification for this model")

_SIMULATION_SYSTEM_PROMPT = """You are Sarasvi's Simulation Planning Engine.
Given a student query, reasoning requirements, and strategy parameters, generate a domain-agnostic Executable Mental Model specification representing the system dynamics.

Do NOT use subject-specific template classes. Specify the dynamics dynamically:
- entities: list of nodes, particles, variables, packets.
- rules: math equations or logical conditions mapping updates (e.g. force equations, packet routing rules).
- initial_state: starting variable values.
- transitions: state triggers.

Return STRICT JSON matching this schema:
{
  "simulation_type": "dynamic_type_name",
  "entities": [
    {
      "id": "entity_id",
      "type": "entity_type",
      "properties": {}
    }
  ],
  "rules": [
    {
      "name": "rule_name",
      "formula": "formula expression"
    }
  ],
  "initial_state": {
    "variables": {}
  },
  "transitions": [
    {
      "trigger": "event_trigger",
      "target_state": "state_name"
    }
  ],
  "justification": "Pedagogical rationale for this simulation setup"
}
"""

class SimulationPlanner:
    async def plan_simulation(
        self,
        query: str,
        requirements: ReasoningRequirementPlan,
        strategy: TeachingStrategy
    ) -> SimulationSpecification:
        """Plan dynamic simulation specification from core parameters."""
        logger.info("simulation_planner.start", query=query)
        
        user_prompt = (
            f"Query: {query}\n"
            f"Requirements: {[r.model_dump() for r in requirements.requirements]}\n"
            f"Strategy: {[p.model_dump() for p in strategy.parameters]}\n"
        )
        
        try:
            raw = await llm_client.generate_json(_SIMULATION_SYSTEM_PROMPT, user_prompt)
            spec = SimulationSpecification.model_validate(raw)
            logger.info("simulation_planner.success", sim_type=spec.simulation_type)
            return spec
        except Exception as exc:
            logger.warning("simulation_planner.failed", error=str(exc))
            # Safe domain-agnostic fallback
            return SimulationSpecification(
                simulation_type="conceptual_exposition",
                entities=[],
                rules=[],
                initial_state=SimulationState(variables={}),
                transitions=[],
                justification="Fallback due to LLM request error."
            )

simulation_planner = SimulationPlanner()
