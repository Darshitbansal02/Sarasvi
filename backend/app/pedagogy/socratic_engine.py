"""
Socratic Engine: The logic layer for pedagogical strategy shifts.
"""

from enum import Enum
from typing import Any

class TeachingStrategy(Enum):
    Socratic = "socratic"     # Asking questions, scaffolding
    Didactic = "didactic"     # Direct explanation
    Discovery = "discovery"   # Guided exploration
    Remedial = "remedial"     # Switching metaphors/simplifying

class SocraticEngine:
    def __init__(self):
        self.current_strategy = TeachingStrategy.Discovery

    def select_strategy(self, failure_mode: str, spatial_intent: dict, user_efficacy: float) -> TeachingStrategy:
        """
        Choose the best teaching strategy based on the current context.
        """
        # If user is failing an analogy, pivot to remedial (metaphor shift)
        if failure_mode == "analogy_failure":
            return TeachingStrategy.Remedial

        # If it's a specific spatial focus request and efficacy is high, use Socratic scaffolding
        if spatial_intent.get("intent") == "FOCUS_REQUEST":
            if user_efficacy > 0.6:
                return TeachingStrategy.Socratic
            else:
                return TeachingStrategy.Didactic # Direct explain if they are struggling

        # Default to Discovery for new concepts
        return TeachingStrategy.Discovery

    def generate_prompt_modifier(self, strategy: TeachingStrategy) -> str:
        """
        Returns a prompt snippet to influence the LLM's narration and visual intent.
        """
        modifiers = {
            TeachingStrategy.Socratic: "Use the Socratic method. Ask a leading question about the circled object. Do not give the answer yet.",
            TeachingStrategy.Didactic: "Provide a clear, direct explanation of the highlighted part. Use a formal technical breakdown.",
            TeachingStrategy.Remedial: "The previous metaphor failed. Switch to a completely different analogy (e.g. from trees to minecraft) and explain the concept simply.",
            TeachingStrategy.Discovery: "Guide the student to notice the patterns. Use 'what if' scenarios."
        }
        return modifiers.get(strategy, "")

socratic_engine = SocraticEngine()
