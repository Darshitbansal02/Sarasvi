"""
SessionStateStore — the single owner of per-session runtime state.

Consolidates what used to live in three places:
  • sessions.py module globals (_session_whiteboards, _session_page_locks)
  • orchestration.session_registry (generation / branch / profile)

State is durable in Postgres/SQLite (session_state + student_profile_state) so it
survives restarts and is a single source of truth, with a per-process write-through
cache so hot paths (WS sequence increments, the compiler's whiteboard mutations)
stay in-memory. DB writes happen at boundaries (generation end, interrupt, disconnect).

NOTE: This makes state *durable* and gives one ownership boundary. True active-active
multi-instance streaming additionally needs a cross-instance pub/sub bus
(Postgres LISTEN/NOTIFY or Redis); that is deliberately out of scope here.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Optional

import structlog
from sqlalchemy import select

from app.database.engine import get_session_factory
from app.events.branch_manager import BranchManager
from app.events.generation_manager import GenerationManager
from app.layouts.whiteboard_manager import WhiteboardManager
from app.models.session_state import SessionState, StudentProfileState

logger = structlog.get_logger(__name__)


def _default_page_lock() -> dict:
    # page_complete starts True so the first /continue (and first teach) can proceed.
    return {"current_page": 0, "page_complete": True, "total_pages_completed": 0}


class SessionStateStore:
    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        # _transient holds purely in-process state that must NOT be cleared by
        # evict() / _upsert().  pending_resume lives here so that a save_whiteboard
        # call during G2's _finalize doesn't silently wipe it before _auto_resume_lesson
        # can read it.
        self._transient: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ── in-process cache (sync) ──────────────────────────────────────
    def _slot(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            return self._cache.setdefault(str(session_id), {})

    def _tslot(self, session_id: str) -> dict[str, Any]:
        """Return the transient (non-evictable) slot for this session."""
        with self._lock:
            return self._transient.setdefault(str(session_id), {})

    def evict(self, session_id: str) -> None:
        """Evict DB-backed cache for this session. Transient state is preserved."""
        with self._lock:
            self._cache.pop(str(session_id), None)

    # ── DB helpers ───────────────────────────────────────────────────
    async def _load_row(self, session_id: str, force_refresh: bool = False) -> Optional[SessionState]:
        """Load session state from DB, optionally bypassing cache in the caller."""
        sid = uuid.UUID(str(session_id))
        factory = get_session_factory()
        async with factory() as db:
            return (
                await db.execute(select(SessionState).where(SessionState.session_id == sid))
            ).scalar_one_or_none()

    async def _upsert(self, session_id: str, **fields: Any) -> None:
        """Merge-update the session_state row (insert if missing)."""
        sid = uuid.UUID(str(session_id))
        factory = get_session_factory()
        async with factory() as db:
            row = (
                await db.execute(select(SessionState).where(SessionState.session_id == sid))
            ).scalar_one_or_none()
            if row is None:
                row = SessionState(
                    session_id=sid,
                    page_lock=_default_page_lock(),
                    whiteboard_state={},
                    generation_state={},
                    branch_state={},
                )
                db.add(row)
            for key, value in fields.items():
                setattr(row, key, value)
            await db.commit()
            
            # Gap 2 Fix: Clear local cache slot on write to ensure subsequent
            # reads (even on the same instance) reload the latest serialized DB state.
            # This is the "safe" middle-ground before implementing a full Pub/Sub bus.
            self.evict(session_id)

    # ── page lock (DB-authoritative; tiny, no cache) ─────────────────

    # ── page lock (DB-authoritative; tiny, no cache) ─────────────────
    async def get_page_lock(self, session_id: str) -> dict:
        row = await self._load_row(session_id)
        if row and row.page_lock:
            return dict(row.page_lock)
        return _default_page_lock()

    async def save_page_lock(self, session_id: str, lock: dict) -> None:
        await self._upsert(session_id, page_lock=dict(lock))

    async def set_page_complete(
        self, session_id: str, complete: bool, *, page: Optional[int] = None, increment: bool = False
    ) -> None:
        lock = await self.get_page_lock(session_id)
        lock["page_complete"] = complete
        if complete and increment:
            lock["total_pages_completed"] = int(lock.get("total_pages_completed", 0)) + 1
        if page is not None:
            lock["current_page"] = int(page)
        await self.save_page_lock(session_id, lock)

    # ── whiteboard ───────────────────────────────────────────────────
    async def get_whiteboard(self, session_id: str) -> WhiteboardManager:
        slot = self._slot(session_id)
        if "whiteboard" not in slot:
            row = await self._load_row(session_id)
            slot["whiteboard"] = WhiteboardManager.from_state(row.whiteboard_state if row else None)
        return slot["whiteboard"]

    async def reset_whiteboard(self, session_id: str) -> WhiteboardManager:
        slot = self._slot(session_id)
        slot["whiteboard"] = WhiteboardManager()
        await self._upsert(session_id, whiteboard_state={})
        return slot["whiteboard"]

    async def save_whiteboard(self, session_id: str) -> None:
        wb = self._slot(session_id).get("whiteboard")
        if wb is not None:
            await self._upsert(session_id, whiteboard_state=wb.to_state())

    async def save_whiteboard_obj(self, session_id: str, wb: "WhiteboardManager") -> None:
        """Save a whiteboard object directly, bypassing the cache lookup.

        Use this instead of save_whiteboard() whenever the caller holds the
        whiteboard reference directly — e.g. inside _finalize() where
        set_page_complete() may have already evicted the cache slot.
        """
        if wb is not None:
            await self._upsert(session_id, whiteboard_state=wb.to_state())

    # ── generation / branch managers ─────────────────────────────────
    async def get_managers(self, session_id: str) -> dict[str, Any]:
        """Return {'generation': GenerationManager, 'branch': BranchManager},
        rehydrating from the DB on a cold cache miss."""
        slot = self._slot(session_id)
        if "generation" not in slot:
            row = await self._load_row(session_id)
            slot["generation"] = GenerationManager.from_state(
                str(session_id), row.generation_state if row else None
            )
            slot["branch"] = BranchManager.from_state(
                str(session_id), row.branch_state if row else None
            )
        return slot

    def get_managers_cached(self, session_id: str) -> Optional[dict[str, Any]]:
        """Non-async peek at already-loaded managers (None if not warmed)."""
        slot = self._slot(session_id)
        return slot if "generation" in slot else None

    async def save_managers(self, session_id: str) -> None:
        slot = self._slot(session_id)
        gen: Optional[GenerationManager] = slot.get("generation")
        br: Optional[BranchManager] = slot.get("branch")
        fields: dict[str, Any] = {}
        if gen is not None:
            fields["generation_state"] = gen.to_state()
        if br is not None:
            fields["branch_state"] = br.to_state()
        if fields:
            await self._upsert(session_id, **fields)

    # ── pending lesson resume (in-memory; lives between /interrupt and doubt-end) ──
    # Stores the original generation's id + playback offset so that after the
    # doubt pivot completes, _auto_resume_lesson can replay the remaining events
    # without a second LLM call.
    def save_pending_resume(
        self,
        session_id: str,
        generation_id: str,
        interrupted_at_ms: float,
        branch_id: str = "main",
    ) -> None:
        self._tslot(session_id)["pending_resume"] = {
            "generation_id": generation_id,
            "interrupted_at_ms": float(interrupted_at_ms),
            "branch_id": branch_id,
        }

    def get_pending_resume(self, session_id: str) -> Optional[dict]:
        return self._tslot(session_id).get("pending_resume")

    def clear_pending_resume(self, session_id: str) -> None:
        self._tslot(session_id).pop("pending_resume", None)

    # ── pivot playback duration (in-memory; used to delay G3 until G2 is done) ──
    def save_pivot_playback_ms(self, session_id: str, ms: float) -> None:
        """Record how long the just-published pivot (G2) generation will play.
        Read by _guarded_teaching to delay G3 until G2's audio finishes."""
        self._tslot(session_id)["pivot_playback_ms"] = float(ms)

    def pop_pivot_playback_ms(self, session_id: str) -> float:
        """Return and clear the stored pivot playback duration (0.0 if not set)."""
        return float(self._tslot(session_id).pop("pivot_playback_ms", 0.0))

    # ── student profile cache (sync access for CognitiveTracker) ─────
    def profile_slot(self, session_id: str) -> dict[str, Any]:
        return self._slot(session_id)

    async def load_profile(self, session_id: str) -> Optional[dict]:
        """Warm the profile cache from DB; returns the stored profile dict or None."""
        sid = uuid.UUID(str(session_id))
        factory = get_session_factory()
        async with factory() as db:
            row = (
                await db.execute(
                    select(StudentProfileState).where(StudentProfileState.session_id == sid)
                )
            ).scalar_one_or_none()
            return dict(row.profile) if row and row.profile else None

    async def save_profile(self, session_id: str, profile_dict: dict) -> None:
        sid = uuid.UUID(str(session_id))
        factory = get_session_factory()
        async with factory() as db:
            row = (
                await db.execute(
                    select(StudentProfileState).where(StudentProfileState.session_id == sid)
                )
            ).scalar_one_or_none()
            if row is None:
                db.add(StudentProfileState(session_id=sid, profile=profile_dict))
            else:
                row.profile = profile_dict
            await db.commit()

    async def clear_profile(self, session_id: str) -> None:
        self._slot(session_id)["profile"] = None
        sid = uuid.UUID(str(session_id))
        factory = get_session_factory()
        async with factory() as db:
            row = (
                await db.execute(
                    select(StudentProfileState).where(StudentProfileState.session_id == sid)
                )
            ).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
                await db.commit()


# Singleton — single ownership boundary for all session runtime state.
session_state_store = SessionStateStore()
