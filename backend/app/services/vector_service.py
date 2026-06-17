"""
VectorService — Handles semantic embeddings for pedagogical memory.
Uses Google Gemini Embedding API (text-embedding-004).
"""

from typing import List
import structlog

logger = structlog.get_logger(__name__)

class VectorService:
    async def generate_embedding(self, text: str) -> List[float]:
        """Generates a 768-dimensional embedding via Google Gemini API (text-embedding-004 model)."""
        from app.config.settings import get_settings
        import httpx
        
        settings = get_settings()
        api_key = settings.gemini_api_key
        model_name = settings.gemini_embedding_model or "text-embedding-004"
        
        # Check if a valid API key is present
        if not api_key or api_key.strip() in ("stub", "your_key_here", "your_gemini_key_here", ""):
            logger.warn("vector_service.gemini_key_missing_fallback_empty")
            return []
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:embedContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }
        payload = {
            "model": f"models/{model_name}",
            "content": {
                "parts": [{"text": text}]
            },
            "outputDimensionality": 768
        }
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                embedding = data["embedding"]["values"]
                return embedding
        except Exception as e:
            # Strip the api key if it leaks anywhere in the exception details
            error_msg = str(e)
            if api_key in error_msg:
                error_msg = error_msg.replace(api_key, "REDACTED_API_KEY")
            logger.error("vector_service.gemini_embedding_error", error=error_msg)
            return []

    async def search_similar(self, query_text: str, db_session, limit: int = 3):
        """
        Executes a vector similarity search directly against the database, with a fallback for SQLite.
        """
        from app.models.pedagogical_episode import PedagogicalEpisode
        from sqlalchemy import select
        import numpy as np
        
        query_vector = await self.generate_embedding(query_text)
        if not query_vector:
            return []
            
        dialect_name = "postgresql"
        if hasattr(db_session, "bind") and db_session.bind is not None:
            dialect_name = db_session.bind.dialect.name
            
        if dialect_name == "postgresql":
            # Using raw SQL with explicit cast for pgvector
            from sqlalchemy import text
            vector_str = f"[{','.join(map(str, query_vector))}]"
            stmt = text(
                "SELECT id, summary, pedagogical_strategy, success_score "
                "FROM pedagogical_episodes "
                "ORDER BY embedding <-> CAST(:ov AS vector) "
                "LIMIT :limit"
            )
            try:
                result = await db_session.execute(stmt, {"ov": vector_str, "limit": limit})
                return result.all()
            except Exception as e:
                logger.error("vector_service.postgres_search_error", error=str(e))
                return []
        else:
            # SQLite fallback: read all pedagogical episodes and compute distances in-memory
            try:
                stmt = select(PedagogicalEpisode)
                result = await db_session.execute(stmt)
                episodes = result.scalars().all()
                if not episodes:
                    return []
                
                q_vec = np.array(query_vector, dtype=np.float32)
                distances = []
                for ep in episodes:
                    if ep.embedding:
                        ep_vec = np.array(ep.embedding, dtype=np.float32)
                        dist = np.linalg.norm(q_vec - ep_vec)
                        distances.append((dist, ep))
                
                # Sort by distance (ascending)
                distances.sort(key=lambda x: x[0])
                
                from collections import namedtuple
                ResultRow = namedtuple("ResultRow", ["id", "summary", "pedagogical_strategy", "success_score"])
                
                return [
                    ResultRow(
                        id=ep.id,
                        summary=ep.summary,
                        pedagogical_strategy=ep.pedagogical_strategy,
                        success_score=ep.success_score
                    )
                    for _, ep in distances[:limit]
                ]
            except Exception as e:
                logger.error("vector_service.sqlite_search_error", error=str(e))
                return []

# Global instance
vector_service = VectorService()
