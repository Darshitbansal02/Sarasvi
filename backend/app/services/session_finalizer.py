"""
SessionFinalizer — end-of-session reflection into long-term memory.

Phase 1 salvage: the reflection/pgvector logic previously lived inside the now-dead
CognitiveConductor.finalize_session, which was a no-op because it read from an
in-memory `active_transcript` that nothing on the live path ever populated.

This service reconstructs the transcript from the persisted timeline events
(written by the WebSocket persistence subscriber) and stores a PedagogicalEpisode.
It is intentionally best-effort and fail-safe: it never raises, so a session
disconnect can never be broken by reflection failures.

NOTE (later phase): SummaryAgent is currently a scaffold (no real LLM summary,
zero-vector embedding). Upgrading it to a real summariser is a separate task.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.agents.summary_agent import summary_agent
from app.events.event_store import EventStore

logger = structlog.get_logger(__name__)


class SessionFinalizer:
    """Summarise a finished session and persist it as a PedagogicalEpisode."""

    async def finalize(self, session_id: str, db: AsyncSession | None = None) -> None:
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id

        if db is None:
            from app.database.engine import get_session_factory
            factory = get_session_factory()
            logger.info("session_finalizer.starting_with_factory", session_id=session_id)
            async with factory() as fresh_db:
                try:
                    await self._finalize_with_db(sid, fresh_db)
                    await fresh_db.commit()
                except Exception as exc:
                    await fresh_db.rollback()
                    logger.error("session_finalizer.failed", session_id=session_id, error=str(exc))
            return

        try:
            await self._finalize_with_db(sid, db)
        except Exception as exc:
            logger.error("session_finalizer.failed", session_id=session_id, error=str(exc))

    async def _finalize_with_db(self, sid: uuid.UUID, db: AsyncSession) -> None:
        session_id = str(sid)
        store = EventStore(db)
        events = await store.get_session_events(session_id=sid, branch_id="main")

        transcript: list[dict[str, Any]] = []
        for event in events:
            payload = getattr(event, "payload", None) or {}
            transcript.append(
                {
                    "type": str(getattr(event, "type", "")),
                    "content": payload.get("text", "") if isinstance(payload, dict) else "",
                }
            )

        if not transcript:
            logger.info("session_finalizer.skipped", reason="empty_transcript", session_id=session_id)
            return

        reflection = await summary_agent.summarize_session(session_id, transcript)

        # --- Batch-commit CognitiveTracker state to User model ---
        from app.models.session import Session as SessionModel
        from app.models.user import User as UserModel
        
        sess_stmt = select(SessionModel).where(SessionModel.id == sid)
        sess_res = await db.execute(sess_stmt)
        session_obj = sess_res.scalar_one_or_none()
        
        if session_obj:
            session_obj.status = "completed"
            session_obj.ended_at = datetime.now(timezone.utc)
            db.add(session_obj)
            
            user_stmt = select(UserModel).where(UserModel.id == session_obj.user_id)
            user_res = await db.execute(user_stmt)
            user_obj = user_res.scalar_one_or_none()
            if user_obj:
                from app.student_model.cognitive_tracker import CognitiveTracker
                tracker = CognitiveTracker()
                profile = tracker.get_or_create_profile(session_id)
                
                lp = dict(user_obj.learning_profile or {})
                lp["understanding_score"] = profile.understanding_score
                lp["confusion_index"] = profile.confusion_index
                lp["fatigue_level"] = profile.fatigue_level
                lp["active_misconceptions"] = list(profile.active_misconceptions)
                lp["learning_velocity"] = profile.learning_velocity
                
                user_obj.learning_profile = lp
                db.add(user_obj)
                logger.info("session_finalizer.cognitive_state_persisted", session_id=session_id, user_id=str(user_obj.id))

        # Persist a DB-agnostic ORM episode (no raw pgvector SQL, so this works
        # regardless of whether the deployment has the pgvector extension).
        from app.models.pedagogy import SQLPedagogicalEpisode
        from app.models.pedagogical_episode import PedagogicalEpisode

        episode = SQLPedagogicalEpisode(
            id=uuid.uuid4(),
            student_id=str(session_obj.user_id) if session_obj else str(session_id),
            topic=session_obj.topic if session_obj else "General Lesson",
            concepts=[],
            misconceptions_triggered=[],
            teaching_strategy=reflection.get("pedagogical_strategy", "mixed"),
            outcome_score=reflection.get("success_score", 1.0),
        )
        db.add(episode)

        # Persist the vector-search-enabled PedagogicalEpisode
        ped_episode = PedagogicalEpisode(
            id=uuid.uuid4(),
            session_id=sid,
            summary=reflection.get("summary", ""),
            pedagogical_strategy=reflection.get("pedagogical_strategy", "mixed"),
            success_score=reflection.get("success_score", 1.0),
            embedding=reflection.get("embedding", []),
        )
        db.add(ped_episode)
        await db.commit()

        logger.info("session_finalizer.persisted", session_id=session_id)


session_finalizer = SessionFinalizer()

