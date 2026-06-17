"""
GenerationJobManager — in-process, cancellable background jobs (single instance).

Replaces fire-and-forget `BackgroundTasks` / bare `asyncio.create_task` for lesson
generation. A real distributed queue (Celery/ARQ/Dramatiq) needs Redis, which this
deployment intentionally avoids; this gives the parts that actually matter for a
single instance:

  • cancellation — starting a new generation for a session cancels the in-flight one
    (interrupt / adapt / continue semantics), instead of leaking a wasted task whose
    events are merely filtered out downstream;
  • failure surfacing — exceptions are captured into queryable per-session status;
  • clean teardown — `cancel_and_wait` awaits the old task's finalizers (so the page
    lock can't be left in a racy state) before a new generation starts.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Optional

import structlog

logger = structlog.get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GenerationJobManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._status: dict[str, dict[str, Any]] = {}

    async def cancel_and_wait(self, session_id: str) -> None:
        """Cancel any in-flight generation for the session and await its teardown."""
        sid = str(session_id)
        task = self._tasks.get(sid)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 — teardown only
                pass

    def submit(self, session_id: str, coro: Awaitable[None], *, generation_id: Optional[str] = None) -> asyncio.Task:
        """Start a generation coroutine as a tracked task (does not cancel prior;
        call cancel_and_wait first if replace semantics are desired)."""
        sid = str(session_id)
        task = asyncio.create_task(self._run(sid, coro, generation_id), name=f"gen_{sid}")
        self._tasks[sid] = task
        return task

    async def _run(self, sid: str, coro: Awaitable[None], generation_id: Optional[str]) -> None:
        self._status[sid] = {"state": "running", "generation_id": generation_id, "started_at": _now_iso()}
        try:
            await coro
            self._status[sid] = {**self._status.get(sid, {}), "state": "completed", "ended_at": _now_iso()}
        except asyncio.CancelledError:
            self._status[sid] = {**self._status.get(sid, {}), "state": "cancelled", "ended_at": _now_iso()}
            raise
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the loop
            logger.error("generation_job.failed", session_id=sid, error=str(exc), exc_info=True)
            self._status[sid] = {**self._status.get(sid, {}), "state": "failed", "error": str(exc), "ended_at": _now_iso()}
        finally:
            # Only clear the slot if it's still us (a newer submit may have replaced it).
            cur = self._tasks.get(sid)
            if cur is asyncio.current_task():
                self._tasks.pop(sid, None)

    def status(self, session_id: str) -> dict[str, Any]:
        return self._status.get(str(session_id), {"state": "idle"})


# Singleton
generation_job_manager = GenerationJobManager()
