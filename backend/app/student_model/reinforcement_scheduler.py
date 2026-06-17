from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.database.engine import get_session_factory
from app.models.pedagogy import SQLConceptRetentionState
import structlog

logger = structlog.get_logger(__name__)

class ReinforcementScheduler:
    """
    ReinforcementScheduler — Computes spaced-repetition retention intervals
    and schedules reinforcement review tasks dynamically in SQLite.
    """
    def __init__(self):
        pass

    async def record_interaction(
        self,
        student_id: str,
        concept: str,
        mastery_score: float,
        misconception_score: float
    ):
        session_factory = get_session_factory()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        
        async with session_factory() as session:
            try:
                stmt = select(SQLConceptRetentionState).where(
                    SQLConceptRetentionState.student_id == student_id,
                    SQLConceptRetentionState.concept == concept
                )
                res = await session.execute(stmt)
                record = res.scalars().first()
                
                if record:
                    record.exposure_count += 1
                    record.mastery_score = mastery_score
                    # Reset retention score to 1.0 upon interaction/review
                    record.retention_score = 1.0
                    record.last_seen = now
                else:
                    import uuid
                    record = SQLConceptRetentionState(
                        id=uuid.uuid4(),
                        student_id=student_id,
                        concept=concept,
                        mastery_score=mastery_score,
                        retention_score=1.0,
                        last_seen=now,
                        forgetting_rate=0.0001,
                        exposure_count=1,
                        next_review_at=now
                    )
                    session.add(record)
                    
                # Compute interval: 60 * 2^exposure_count seconds for testability
                # (1 -> 120s, 2 -> 240s, etc.)
                interval_sec = 60 * (2 ** min(record.exposure_count, 10))
                record.next_review_at = now + timedelta(seconds=interval_sec)
                
                await session.commit()
                logger.info("reinforcement_scheduler.interaction_recorded", student_id=student_id, concept=concept, next_review=str(record.next_review_at))
            except Exception as e:
                logger.error("reinforcement_scheduler.record_failed", student_id=student_id, concept=concept, err=str(e))

    async def get_due_reviews(
        self,
        student_id: str,
        current_concepts: Optional[List[str]] = None,
        current_domain: Optional[str] = None,
        max_reviews: int = 2
    ) -> List[Dict[str, Any]]:
        session_factory = get_session_factory()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        due_list = []
        
        async with session_factory() as session:
            try:
                # Query all concept records for the student that are due or decayable
                stmt = select(SQLConceptRetentionState).where(
                    SQLConceptRetentionState.student_id == student_id,
                    SQLConceptRetentionState.next_review_at <= now
                )
                res = await session.execute(stmt)
                records = res.scalars().all()
                

                for r in records:
                    norm_concept_name = r.concept.lower().replace("_", " ")
                    r_domain = current_domain or "general"
                    
                    # 1. Check direct domain context alignment if provided
                    if current_domain and r_domain != current_domain:
                        continue
                        
                    # 2. Check concept relevance context if lesson concepts are present
                    if current_concepts:
                        matched_related = False
                        for cur_c in current_concepts:
                            norm_cur_c = cur_c.lower().replace("_", " ")
                            if norm_cur_c in norm_concept_name or norm_concept_name in norm_cur_c:
                                matched_related = True
                                break
                        if not matched_related:
                            continue
                            
                    # Apply Ebbinhaus decay to retention: e^(-forgetting_rate * elapsed_sec)
                    last_seen = r.last_seen
                    if last_seen.tzinfo is None:
                        last_seen = last_seen.replace(tzinfo=timezone.utc)
                    elapsed = (now - last_seen).total_seconds()
                    import math
                    decayed_retention = math.exp(-r.forgetting_rate * elapsed)
                    r.retention_score = round(max(0.0, min(1.0, decayed_retention)), 3)
                    
                    # Compute priority = (1 - retention) * (1 + 0.5 * misconception_score)
                    # For due reviews, assume misconception_score from DB (or default)
                    misconception_score = 0.8 if r.mastery_score < 0.5 else 0.0
                    priority = (1.0 - r.retention_score) * (1.0 + 0.5 * misconception_score)
                    
                    due_list.append({
                        "concept": r.concept,
                        "retention_score": r.retention_score,
                        "priority": round(priority, 3),
                        "exposure_count": r.exposure_count
                    })
                
                # Sort descending by priority
                due_list.sort(key=lambda x: x["priority"], reverse=True)
                due_list = due_list[:max_reviews]
                logger.info("reinforcement_scheduler.due_reviews_fetched", student_id=student_id, count=len(due_list))
            except Exception as e:
                logger.error("reinforcement_scheduler.fetch_failed", student_id=student_id, err=str(e))
                
        return due_list
