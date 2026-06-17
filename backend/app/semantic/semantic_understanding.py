"""
Semantic Understanding Engine — parses raw queries into structured learning objectives, intents, constraints, and transitions.
"""

from typing import List, Any, Dict
from pydantic import BaseModel, Field
import structlog
from app.utils.llm_client import llm_client

logger = structlog.get_logger(__name__)

class ConceptualTransition(BaseModel):
    from_state: str = Field(description="Initial/basic conceptual understanding state")
    to_state: str = Field(description="Target/rigorous conceptual understanding state")

class SemanticUnderstanding(BaseModel):
    semantic_id: str = Field(default_factory=lambda: f"sem_{__import__('uuid').uuid4().hex[:6]}")
    learning_goal: str = Field(description="Core learning goal the student wants to achieve")
    concepts: List[str] = Field(default_factory=list, description="Primary curriculum concepts involved")
    constraints: List[str] = Field(default_factory=list, description="Explicit constraints or constraints specified in the query")
    student_intent: str = Field(description="Intent class: explanation, derivation, proof, comparison, troubleshooting, etc.")
    prior_knowledge_assumptions: List[str] = Field(default_factory=list, description="Prerequisites or assumptions about prior knowledge")
    conceptual_transitions: List[ConceptualTransition] = Field(default_factory=list, description="Desired shift in mental models")

_SEMANTIC_SYSTEM_PROMPT = """You are Sarasvi's Semantic Understanding Engine.
Analyze the student's query and extract the underlying cognitive learning goals, concepts, constraints, intent, prior knowledge assumptions, and conceptual transitions.

Return STRICT JSON matching this schema:
{
  "learning_goal": "what the student is trying to achieve",
  "concepts": ["concept_1", "concept_2"],
  "constraints": ["any explicit constraints, metaphors requested, or limits"],
  "student_intent": "explanation|proof|derivation|comparison|troubleshooting",
  "prior_knowledge_assumptions": ["what the student is assumed to already know"],
  "conceptual_transitions": [
    {
      "from_state": "basic or intuitive understanding",
      "to_state": "target rigorous or shift in mental model"
    }
  ]
}
"""

class SemanticUnderstandingEngine:
    async def analyze_query(self, query: str) -> SemanticUnderstanding:
        """Analyze a raw student question and return structured semantic understanding."""
        logger.info("semantic_understanding.start", query=query)
        try:
            raw = await llm_client.generate_json(_SEMANTIC_SYSTEM_PROMPT, f"Query: {query}")
            understanding = SemanticUnderstanding.model_validate(raw)
            logger.info("semantic_understanding.success", goal=understanding.learning_goal)
            return understanding
        except Exception as exc:
            logger.warning("semantic_understanding.failed", error=str(exc))
            # Safe domain-agnostic fallback
            return SemanticUnderstanding(
                learning_goal=query,
                concepts=[query],
                constraints=[],
                student_intent="explanation",
                prior_knowledge_assumptions=[],
                conceptual_transitions=[
                    ConceptualTransition(
                        from_state="Unfamiliar with the topic",
                        to_state=f"Understand {query}"
                    )
                ]
            )

semantic_understanding_engine = SemanticUnderstandingEngine()
