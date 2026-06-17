"""
SummaryAgent — Compresses session experiences into long-term pedagogical memory.
"""

from typing import List, Dict, Any
import structlog
from app.services.vector_service import vector_service

logger = structlog.get_logger(__name__)

class SummaryAgent:
    def __init__(self):
        pass

    async def summarize_session(self, session_id: str, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Takes raw event logs and produces a structured summary with embeddings.
        """
        logger.info("summary_agent.summarizing", session_id=session_id, event_count=len(events))
        
        # In a real scenario, this would call an LLM (e.g. Groq) to describe the arc.
        # For now, we scaffold the logic.
        
        raw_text = self._extract_text_content(events)
        
        # Simulated LLM Summary
        summary_text = f"Session focused on {raw_text[:100]}... with positive student engagement."
        strategy = "Socratic" # Should be detected by LLM
        success_score = 0.85 # Should be calculated based on Analytics
        
        # Generate Vector Embedding
        embedding = await vector_service.generate_embedding(summary_text)
        
        return {
            "session_id": session_id,
            "summary": summary_text,
            "pedagogical_strategy": strategy,
            "success_score": success_score,
            "embedding": embedding
        }

    def _extract_text_content(self, events: List[Dict[str, Any]]) -> str:
        texts = []
        for e in events:
            if e.get("type") == "speech":
                texts.append(e.get("content", ""))
        return " ".join(texts)

# Global instance
summary_agent = SummaryAgent()
