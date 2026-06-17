"""
Event Store — repository for persisting and querying TimelineEvents.

This is the persistence layer for the source of truth.
All queries support replay-safe ordering, generation filtering, and branch awareness.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from app.models.timeline_event import TimelineEvent
from app.events.event_protocol import TimelineEventData

logger = structlog.get_logger(__name__)


class EventStore:
    """Repository for TimelineEvent CRUD and replay queries."""

    def __init__(self, session: AsyncSession):
        self._session = session

    def _sanitize_payload(self, val: Any, seen: Optional[set] = None) -> Any:
        """Recursively sanitize the payload to prevent circular references and non-primitive objects."""
        if seen is None:
            seen = set()
        
        # Guard against circular reference recursion
        if id(val) in seen:
            return None
            
        if isinstance(val, dict):
            seen.add(id(val))
            res = {}
            for k, v in val.items():
                if k == "_layout_shapes":
                    continue
                res[k] = self._sanitize_payload(v, seen)
            seen.remove(id(val))
            return res
        elif isinstance(val, (list, tuple)):
            seen.add(id(val))
            res = [self._sanitize_payload(x, seen) for x in val]
            seen.remove(id(val))
            return res
        elif isinstance(val, (str, int, float, bool)) or val is None:
            return val
        else:
            try:
                # Handle pydantic models or enums
                if hasattr(val, "model_dump"):
                    return self._sanitize_payload(val.model_dump(), seen)
                elif hasattr(val, "value"):
                    return val.value
            except Exception:
                pass
            return str(val)

    async def persist_event(self, event: TimelineEventData, session_id: uuid.UUID) -> TimelineEvent:
        """Persist a single timeline event to the database."""
        db_event = TimelineEvent(
            id=uuid.UUID(event.event_id) if isinstance(event.event_id, str) else event.event_id,
            session_id=session_id,
            generation_id=event.generation_id,
            branch_id=event.branch_id,
            version_id=event.version_id,
            parent_event_id=(
                uuid.UUID(event.parent_event_id)
                if event.parent_event_id
                else None
            ),
            sequence_number=event.sequence_number,
            start_ms=event.start_ms,
            server_timestamp=event.server_timestamp,
            type=event.type,
            payload=self._sanitize_payload(event.payload),
        )
        self._session.add(db_event)
        await self._session.flush()
        logger.debug(
            "event_store.persisted",
            event_id=event.event_id,
            type=event.type,
            seq=event.sequence_number,
        )
        return db_event

    async def get_session_events(
        self,
        session_id: uuid.UUID,
        branch_id: str = "main",
        generation_id: Optional[str] = None,
        from_sequence: int = 0,
        limit: int = 10_000,
    ) -> Sequence[TimelineEvent]:
        """
        Get events for replay in deterministic order.
        Supports filtering by branch and generation.
        """
        conditions = [TimelineEvent.session_id == session_id]

        if branch_id:
            conditions.append(TimelineEvent.branch_id == branch_id)
        if generation_id:
            conditions.append(TimelineEvent.generation_id == generation_id)
        if from_sequence > 0:
            conditions.append(TimelineEvent.sequence_number >= from_sequence)

        stmt = (
            select(TimelineEvent)
            .where(and_(*conditions))
            .order_by(TimelineEvent.sequence_number)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_all_session_events(
        self,
        session_id: uuid.UUID,
    ) -> Sequence[TimelineEvent]:
        """Get ALL events for a session, across all branches, ordered by sequence."""
        stmt = (
            select(TimelineEvent)
            .where(TimelineEvent.session_id == session_id)
            .order_by(TimelineEvent.sequence_number)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_branches(self, session_id: uuid.UUID) -> list[str]:
        """Get all branch IDs for a session."""
        from sqlalchemy import distinct

        stmt = (
            select(distinct(TimelineEvent.branch_id))
            .where(TimelineEvent.session_id == session_id)
        )
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]

    async def get_latest_sequence(
        self, session_id: uuid.UUID, generation_id: str
    ) -> int:
        """Get the latest sequence number for a generation."""
        from sqlalchemy import func

        stmt = (
            select(func.max(TimelineEvent.sequence_number))
            .where(
                and_(
                    TimelineEvent.session_id == session_id,
                    TimelineEvent.generation_id == generation_id,
                )
            )
        )
        result = await self._session.execute(stmt)
        val = result.scalar()
        return val if val is not None else -1

    async def invalidate_generation(
        self, session_id: uuid.UUID, generation_id: str
    ) -> int:
        """
        Mark events from an invalidated generation.
        Does NOT delete — preserves for analytics and replay branch switching.
        Returns count of events in the invalidated generation.
        """
        stmt = (
            select(TimelineEvent)
            .where(
                and_(
                    TimelineEvent.session_id == session_id,
                    TimelineEvent.generation_id == generation_id,
                )
            )
        )
        result = await self._session.execute(stmt)
        events = result.scalars().all()
        count = len(events)

        logger.info(
            "event_store.generation_invalidated",
            session_id=str(session_id),
            generation_id=generation_id,
            event_count=count,
        )
        return count

    async def get_event_count(self, session_id: uuid.UUID) -> int:
        """Get total event count for a session."""
        from sqlalchemy import func

        stmt = (
            select(func.count(TimelineEvent.id))
            .where(TimelineEvent.session_id == session_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0
