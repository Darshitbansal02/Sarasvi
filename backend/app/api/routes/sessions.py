"""
Session API routes — create sessions, retrieve events for replay, and stream lessons.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Form, File, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
import structlog

from app.api.deps import get_current_user, resolve_session_owner
from app.database.engine import get_db_session
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.events.event_protocol import TimelineEventData, EventType
from app.events.event_store import EventStore
from app.events.event_bus import get_event_bus
from app.events.generation_manager import GenerationManager
from app.config.settings import get_settings
from app.student_model.cognitive_tracker import CognitiveTracker
from app.agents.evaluator_agent import EvaluatorAgent
from app.schemas.api_schemas import (
    SessionCreate,
    SessionResponse,
    SessionListResponse,
    SessionEventsResponse,
    TimelineEventResponse,
    ImageExtractionResponse,
)

class CognitiveAdaptRequest(BaseModel):
    cognitive_load: float
    confusion_level: float
    snapshot: Optional[dict] = None

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])

# All per-session runtime state (whiteboard, page lock, generation/branch managers,
# student profile) lives in the single, durable SessionStateStore. The previous
# in-process module-global dicts have been removed.
from app.services.session_state_store import session_state_store
from app.services.generation_job_manager import generation_job_manager
from app.services.doubt_resume_reflow import (
    reflow_remaining_assets,
    shift_stroke_points_in_list,
    shift_coordinates_in_payload_by_delta,
)
from app.layouts.document_flow import MARGIN_TOP as _MARGIN_TOP


def _infer_latex_from_empty_math(topic: str, narration_sentence: str = "") -> str:
    """
    Neutral repair helper — intentionally minimal and subject-agnostic.
    Do not perform subject-specific inference here; return provided context
    or empty string so downstream rendering remains driven by explicit
    semantic primitives.
    """
    return (narration_sentence or topic or "").strip()


async def get_session_generation_manager(session_id: uuid.UUID) -> GenerationManager:
    """Return the active GenerationManager for a session (rehydrated from the store)."""
    managers = await session_state_store.get_managers(str(session_id))
    return managers["generation"]


@router.get("/topics", response_model=List[dict])
async def get_available_topics():
    """Return starter topic suggestions. The platform can teach any subject — these are examples only."""
    return []


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """List the authenticated user's sessions."""
    query = (
        select(Session)
        .where(Session.user_id == current_user.id)
        .order_by(Session.started_at.desc())
    )
    
    result = await db.execute(query)
    sessions = result.scalars().all()
    
    return SessionListResponse(
        sessions=[SessionResponse.model_validate(s) for s in sessions],
        total=len(sessions)
    )


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    data: SessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new teaching session owned by the authenticated user."""
    session = Session(
        user_id=current_user.id,
        topic=data.topic,
        status=SessionStatus.CREATED,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)

    # Save selected language in the user's learning profile
    if data.language:
        profile = dict(current_user.learning_profile)
        profile["language"] = data.language
        current_user.learning_profile = profile
        db.add(current_user)
        await db.flush()

    logger.info("session.created", session_id=str(session.id), topic=data.topic, language=data.language)
    return session


class InteractionSignal(BaseModel):
    """
    A real-time student interaction signal sent from the frontend.

    event_type choices
    ──────────────────
    response_latency   — seconds student took to respond (payload: delay_seconds)
    quiz_outcome       — checkpoint result (payload: is_correct, difficulty, misconception_trigger)
    hesitation_indicator — cursor/gesture hesitation (payload: intensity 0–1)
    draw_pause         — student paused mid-stroke (payload: duration_ms)
    replay_scrub       — student scrubbed backward in replay (payload: delta_ms < 0)
    session_interrupt  — student clicked "Interrupt & Ask"
    concept_mastered   — explicit mastery signal from evaluation layer
    """
    event_type: str
    payload: dict = {}
    concept: str = "general"


@router.post("/{session_id}/interaction", status_code=status.HTTP_204_NO_CONTENT)
async def record_interaction(
    session_id: uuid.UUID,
    signal: InteractionSignal,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Receive a real-time student interaction signal from the frontend and
    feed it into the CognitiveTracker so the student model stays accurate.

    This replaces the previous approach where the backend synthesised fake
    signals (e.g. delay_seconds=2.0 for every non-confused student).
    """
    await resolve_session_owner(session_id, db, current_user)

    from app.student_model.cognitive_tracker import CognitiveTracker
    tracker = CognitiveTracker()
    await tracker.hydrate(str(session_id))
    payload = {**signal.payload, "concept": signal.concept}
    tracker.record_interaction(str(session_id), signal.event_type, payload)
    await tracker.persist(str(session_id))

    logger.info(
        "session.interaction_recorded",
        session_id=str(session_id),
        event_type=signal.event_type,
        concept=signal.concept,
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get session details (owner only)."""
    return await resolve_session_owner(session_id, db, current_user)


@router.get("/{session_id}/events", response_model=SessionEventsResponse)
async def get_session_events(
    session_id: uuid.UUID,
    branch_id: str = "main",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get all events for a session (owner only, for replay)."""
    await resolve_session_owner(session_id, db, current_user)
    event_store = EventStore(db)

    events = await event_store.get_session_events(
        session_id=session_id,
        branch_id=branch_id,
    )
    branches = await event_store.get_branches(session_id)

    return SessionEventsResponse(
        session_id=session_id,
        events=[TimelineEventResponse.model_validate(e) for e in events],
        total=len(events),
        branches=branches,
    )


async def _run_llm_teaching_logic(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    generation_id: str,
    topic: str,
    snapshot: Optional[dict] = None,
    strategy_modifier: str = "",
    pivot_prefix: str = "",
    confusion_level: float = 0.0,
    cognitive_load: float = 0.0,
    is_pivot: bool = False,
    student_question: Optional[str] = None,
):
    """
    Thin entry point retained for callers (the WS student_message handler and the
    REST teach/interrupt/adapt/continue routes). The implementation lives in
    LessonGenerationService, decomposed into Plan -> Compile -> SynthesizeTTS ->
    Reconcile -> Publish -> Finalize phases (behavior-preserving extraction).
    """
    from app.services.lesson_generation_service import run_lesson_generation
    await run_lesson_generation(
        session_id,
        user_id,
        generation_id,
        topic,
        snapshot=snapshot,
        strategy_modifier=strategy_modifier,
        pivot_prefix=pivot_prefix,
        confusion_level=confusion_level,
        cognitive_load=cognitive_load,
        is_pivot=is_pivot,
        student_question=student_question,
    )

def _is_cancellation_or_shutdown(exc: BaseException) -> bool:
    """Recursively check if the exception was caused by cancellation or server shutdown."""
    import asyncio
    curr = exc
    seen = set()
    while curr is not None:
        if id(curr) in seen:
            break
        seen.add(id(curr))
        if isinstance(curr, (asyncio.CancelledError, GeneratorExit, KeyboardInterrupt)):
            return True
        exc_str = str(curr)
        if "no active connection" in exc_str or "connection is closed" in exc_str:
            return True
        cause = getattr(curr, "__cause__", None)
        if cause is not None:
            curr = cause
        else:
            curr = getattr(curr, "__context__", None)
    return False


async def _guarded_teaching(session_id: uuid.UUID, *args, **kwargs) -> None:
    """
    Run a teaching generation as a background task, guaranteeing the page lock is
    released even if generation raises — otherwise /continue is wedged at 409.

    For pivot (doubt) generations: if the generation succeeds AND a pending_resume
    was registered by handle_interruption, automatically replay the remaining
    original-lesson events with shifted timestamps — no second LLM call.
    """
    is_pivot = kwargs.get("is_pivot", False)
    generation_succeeded = False
    try:
        await _run_llm_teaching_logic(session_id, *args, **kwargs)
        generation_succeeded = True
    except Exception as exc:
        if _is_cancellation_or_shutdown(exc):
            logger.info("generation.cancelled_on_shutdown", session_id=str(session_id), error=str(exc))
        else:
            logger.error("generation.failed", session_id=str(session_id), error=str(exc), exc_info=True)
        session_state_store.clear_pending_resume(str(session_id))
    finally:
        # Keep page_complete=False when auto-resume will immediately follow (G3 will
        # release the lock itself), so no /continue can sneak in between G2 and G3.
        pending_resume_exists = bool(session_state_store.get_pending_resume(str(session_id)))
        if not (is_pivot and generation_succeeded and pending_resume_exists):
            try:
                await session_state_store.set_page_complete(session_id, True)
            except Exception:
                pass

    if is_pivot and generation_succeeded:
        # Wait for G2's frontend playback to finish before publishing G3's
        # generation_start. Without this, ttsPlayer.stop() fires mid-sentence.
        # The duration was recorded by LessonGenerationService._publish.
        pivot_ms = session_state_store.pop_pivot_playback_ms(str(session_id))
        if pivot_ms > 0:
            # Extra 1.5 s so the frontend's audio drain + COMPLETED transition
            # settle before G3 arrives.
            wait_s = pivot_ms / 1000.0 + 1.5
            logger.info(
                "auto_resume.waiting_for_g2_playback",
                session_id=str(session_id),
                pivot_playback_ms=round(pivot_ms),
                wait_s=round(wait_s, 1),
            )
            await asyncio.sleep(wait_s)

        try:
            await _auto_resume_lesson(session_id)
            # G3 events are now published; mark the page complete so /continue
            # works after G3 finishes. (Mirrors what _guarded_teaching's finally
            # block does for non-pivot generations.)
            try:
                await session_state_store.set_page_complete(session_id, True)
            except Exception:
                pass
        except Exception as exc:
            logger.error("auto_resume.failed", session_id=str(session_id), error=str(exc), exc_info=True)
            # Release the lock even if auto-resume fails.
            try:
                await session_state_store.set_page_complete(session_id, True)
            except Exception:
                pass
        finally:
            session_state_store.clear_pending_resume(str(session_id))


def find_referenced_object_ids(payload: Any) -> set[str]:
    ids = set()
    if isinstance(payload, dict):
        for key in ("object_id", "board_id", "equation_id", "highlight_id", "ann_id", "annotation_id", "step_id", "shape_id"):
            val = payload.get(key)
            if isinstance(val, str) and val:
                ids.add(val)
    return ids


async def reconstruct_interrupted_whiteboard_cursors(
    session_id: uuid.UUID,
    generation_id: str,
    interrupted_at_ms: float,
    db: AsyncSession,
    branch_id: str = "main",
) -> tuple[dict[int, float], int, float]:
    """
    Reconstruct the whiteboard page cursors at the moment of interruption.
    Reads G1 events, determines which elements were actually rendered (start_ms <= interrupted_at_ms),
    and finds their positions/heights in the G1 compiled_artifact layout_assets.

    Returns (page_cursors, max_page, max_content_ms) where max_content_ms is the
    start_ms of the LAST content event of the generation — used by the caller to
    tell whether the student interrupted DURING playback (max_content_ms >
    interrupted_at_ms) even when the backend already finished generating.
    """
    from app.events.event_store import EventStore
    store = EventStore(db)
    all_g1 = await store.get_session_events(
        session_id,
        branch_id=branch_id,
        generation_id=generation_id,
    )
    if not all_g1:
        logger.warning(
            "reconstruct_cursors.no_events_in_db",
            session_id=str(session_id),
            generation_id=generation_id,
            branch_id=branch_id,
        )
        return {0: 50.0}, 0, 0.0

    gen_start = next((e for e in all_g1 if str(e.type) in ("generation_start", "EventType.generation_start")), None)
    if not gen_start or not gen_start.payload:
        logger.warning(
            "reconstruct_cursors.no_gen_start_found",
            session_id=str(session_id),
            generation_id=generation_id,
            branch_id=branch_id,
        )
        return {0: 50.0}, 0, 0.0

    _SKIP_END = {"generation_start", "generation_end", "session_init", "heartbeat"}
    max_content_ms = max(
        (float(e.start_ms or 0) for e in all_g1
         if str(e.type).split(".")[-1] not in _SKIP_END),
        default=0.0,
    )

    compiled_artifact = gen_start.payload.get("compiled_artifact") or {}
    layout_assets = compiled_artifact.get("layout_assets") or {}
    timeline = compiled_artifact.get("timeline")

    _SKIP = {"generation_start", "generation_end", "session_init", "heartbeat"}
    
    played_events = []
    use_dict_events = False

    if isinstance(timeline, list) and len(timeline) > 0:
        played_events = [
            e for e in timeline
            if isinstance(e, dict)
            and str(e.get("type", "")).split(".")[-1] not in _SKIP
            and (e.get("start_ms") or 0) <= interrupted_at_ms
        ]
        use_dict_events = True
        logger.info(
            "reconstruct_cursors.using_precompiled_timeline",
            session_id=str(session_id),
            generation_id=generation_id,
            timeline_len=len(timeline),
            played_len=len(played_events),
            interrupted_at_ms=interrupted_at_ms,
        )
    else:
        played_events = [
            e for e in all_g1
            if str(e.type).split(".")[-1] not in _SKIP
            and (e.start_ms or 0) <= interrupted_at_ms
        ]
        use_dict_events = False
        logger.info(
            "reconstruct_cursors.using_db_events_fallback",
            session_id=str(session_id),
            generation_id=generation_id,
            all_g1_len=len(all_g1),
            played_len=len(played_events),
            interrupted_at_ms=interrupted_at_ms,
        )

    page_cursors = {}
    max_page = 0

    for event in played_events:
        if use_dict_events:
            payload = event.get("payload") or {}
        else:
            payload = event.payload or {}

        obj_ids = find_referenced_object_ids(payload)
        for obj_id in obj_ids:
            asset = layout_assets.get(obj_id)
            if not asset:
                continue
            x = asset.get("x")
            y = asset.get("y")
            height = asset.get("height", 0)
            if x is not None and y is not None:
                page_idx = int(x // 1200)
                is_centered = asset.get("type") in ("equation", "annotation")
                bottom = (y + height / 2.0) if is_centered else (y + height)
                next_y = bottom + 24.0  # GAP_MEDIUM
                next_y = min(725.0, max(50.0, next_y))
                page_cursors[page_idx] = max(page_cursors.get(page_idx, 50.0), next_y)
                max_page = max(max_page, page_idx)

    if not page_cursors:
        page_cursors = {0: 50.0}

    logger.info(
        "reconstruct_cursors.completed",
        session_id=str(session_id),
        page_cursors=page_cursors,
        max_page=max_page,
        max_content_ms=max_content_ms,
    )
    return page_cursors, max_page, max_content_ms


async def _auto_resume_lesson(session_id: uuid.UUID) -> None:
    """
    Replay the remaining events from the original lesson generation (G1) as a new
    generation (G3), shifting timestamps so they start from t=0 relative to G3.
    Called after a doubt pivot completes — eliminates the need for a second LLM call.
    """
    pending = session_state_store.get_pending_resume(str(session_id))
    if not pending:
        logger.warning("auto_resume.no_pending", session_id=str(session_id))
        return

    original_gen_id: str = pending["generation_id"]
    interrupted_at_ms: float = pending["interrupted_at_ms"]
    branch_id: str = pending.get("branch_id", "main")

    managers = await session_state_store.get_managers(session_id)
    gen_manager: GenerationManager = managers["generation"]
    branch_manager = managers["branch"]
    _, resume_gen_id = gen_manager.invalidate_current()
    await session_state_store.save_managers(str(session_id))

    from app.events.event_store import EventStore
    from app.database.engine import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        store = EventStore(db)
        all_g1 = await store.get_session_events(
            session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id)),
            branch_id=branch_id,
            generation_id=original_gen_id,
        )

    if not all_g1:
        logger.info("auto_resume.no_events", session_id=str(session_id), gen_id=original_gen_id)
        return

    # Pull the generation_start so we can re-emit its compiled_artifact in G3.
    gen_start = next((e for e in all_g1 if str(e.type) in ("generation_start", "EventType.generation_start")), None)

    _SKIP = {"generation_start", "generation_end", "session_init", "heartbeat"}
    remaining = [
        e for e in all_g1
        if str(e.type).split(".")[-1] not in _SKIP
        and (e.start_ms or 0) > interrupted_at_ms
    ]

    logger.info(
        "auto_resume.resuming",
        session_id=str(session_id),
        original_gen=original_gen_id,
        resume_gen=resume_gen_id,
        interrupted_at_ms=interrupted_at_ms,
        remaining_events=len(remaining),
    )

    event_bus = get_event_bus()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    _LEAD_MS = 500  # gap before first content event so frontend processes generation_start first

    # ── Re-flow the remaining lesson content around the doubt answer ────
    # Reconstruct what G1's cursor was at the moment of interruption.
    async with factory() as db:
        g1_inter_cursors, interrupted_max_page, _g1_max_content_ms = await reconstruct_interrupted_whiteboard_cursors(
            session_id, original_gen_id, interrupted_at_ms, db, branch_id=branch_id
        )

    # Where the doubt answer (G2) left the cursor on each page.
    g2_wb = await session_state_store.get_whiteboard(str(session_id))
    g2_cursors = dict(g2_wb.flow._page_cursors)
    g2_cursors[g2_wb.flow.page] = g2_wb.flow.current_y

    # G1's compiled layout assets that we will re-position.
    g1_payload = dict(gen_start.payload or {}) if gen_start else {}
    compiled_artifact = g1_payload.get("compiled_artifact") or {}
    layout_assets = compiled_artifact.get("layout_assets") or {}
    stroke_assets = compiled_artifact.get("stroke_assets") or {}

    # Identify which assets belong to the not-yet-drawn (remaining) events.
    remaining_object_ids = set()
    for evt in remaining:
        remaining_object_ids.update(find_referenced_object_ids(evt.payload))

    remaining_assets = []
    for obj_id in remaining_object_ids:
        asset = layout_assets.get(obj_id)
        if asset is None:
            continue
        asset.setdefault("id", obj_id)
        remaining_assets.append(asset)

    # Single layout authority: route every remaining item through DocumentFlowLayout,
    # seeded at the doubt's end cursor. This mutates each asset's x/y in place and
    # returns per-object shift deltas + final per-page cursors. Replaces the previous
    # inline per-page delta/cascade math, which mishandled fragmentation, tall items
    # and multi-page cascades. See app/services/doubt_resume_reflow.py.
    resume_start_page = g2_wb.flow.page
    _reflow = reflow_remaining_assets(
        remaining_assets,
        post_doubt_cursors=g2_cursors,
        start_page=resume_start_page,
    )
    asset_final_shifts = _reflow.shifts
    current_cursors = _reflow.end_cursors
    # Calculate page_shifts based on starting cursors before reflow (i.e. g2_cursors vs g1_inter_cursors)
    # This prevents using the final cursor positions (which include all reflowed assets' heights)
    # as the baseline page shift.
    all_pages = set(g2_cursors.keys()) | set(g1_inter_cursors.keys()) | set(current_cursors.keys())
    page_shifts = {}
    for p in all_pages:
        page_shifts[p] = g2_cursors.get(p, _MARGIN_TOP) - g1_inter_cursors.get(p, _MARGIN_TOP)
    # Shift layout assets, strokes, and timestamps
    time_shift = - interrupted_at_ms + _LEAD_MS
    for obj_id, asset in layout_assets.items():
        # Shift _charStates timestamps for all assets
        _cs = asset.get("_charStates")
        if isinstance(_cs, list):
            for char_state in _cs:
                if isinstance(char_state, dict):
                    for key in ("startMs", "endMs", "absoluteStartMs", "absoluteEndMs"):
                        if key in char_state:
                            char_state[key] = max(0, int(round(char_state[key] + time_shift)))
        if "_revealStartMs" in asset:
            asset["_revealStartMs"] = max(0, int(round(asset["_revealStartMs"] + time_shift)))

    # Apply delta_x and delta_y shifts to remaining assets, shapes and strokes
    for obj_id in remaining_object_ids:
        asset = layout_assets.get(obj_id)
        if not asset or obj_id not in asset_final_shifts:
            continue

        delta_x, delta_y = asset_final_shifts[obj_id]

        if delta_x != 0.0:
            # _safeTextX is the ABSOLUTE x the frontend uses to position equation /
            # annotation glyphs (sceneRenderer reads obj._safeTextX). When an item
            # cascades onto a new page the page offset changes, so this must move with
            # it — otherwise the equation renders in the old page's column.
            if "_safeTextX" in asset:
                asset["_safeTextX"] = float(asset["_safeTextX"]) + delta_x
            for shape in asset.get("shapes", []):
                if "x" in shape:
                    shape["x"] = float(shape["x"]) + delta_x

        if delta_y != 0.0:
            if "_safeTextY" in asset:
                asset["_safeTextY"] = float(asset["_safeTextY"]) + delta_y
            for shape in asset.get("shapes", []):
                if "y" in shape:
                    shape["y"] = float(shape["y"]) + delta_y

        # Shift points in stroke_assets ONLY if they are absolute coordinates (i.e. not relative to centered objects)
        # Equation and annotation strokes are centered/relative to _safeTextX/_safeTextY and must not be shifted twice.
        is_centered_asset = asset.get("type") in ("equation", "annotation")
        if not is_centered_asset:
            if obj_id in stroke_assets:
                shift_stroke_points_in_list(stroke_assets[obj_id], delta_x, delta_y)

            # Shift points in asset["_strokesLayout"] if present
            _sl = asset.get("_strokesLayout")
            if isinstance(_sl, list):
                shift_stroke_points_in_list(_sl, delta_x, delta_y)
    # Rebuild the remaining events timeline with proper page transitions and coordinates
    new_remaining = []
    current_page = resume_start_page

    last_delta_x = (resume_start_page - interrupted_max_page) * 1200.0
    last_delta_y = page_shifts.get(resume_start_page, 0.0)

    for evt in remaining:
        evt_type = str(evt.type).split(".")[-1]
        evt_payload = dict(evt.payload or {})

        # Skip any existing scene_start events as we will dynamically re-generate them
        if evt_type == "scene_start":
            continue

        # 1. Resolve referencing object and target page
        obj_id = None
        obj_ids = find_referenced_object_ids(evt_payload)
        for oid in obj_ids:
            if oid in asset_final_shifts:
                obj_id = oid
                break

        obj_page = None
        if obj_id is not None:
            a = layout_assets.get(obj_id)
            if a is not None and a.get("x") is not None:
                obj_page = int(float(a["x"]) // 1200.0)

        # Determine original coordinates in payload BEFORE shifting to calculate correct target page
        x_orig = None
        if "x" in evt_payload:
            x_orig = evt_payload["x"]
        elif isinstance(evt_payload.get("position"), dict) and evt_payload["position"].get("x") is not None:
            x_orig = evt_payload["position"]["x"]
        elif isinstance(evt_payload.get("path"), list) and len(evt_payload["path"]) > 0:
            first = evt_payload["path"][0]
            if isinstance(first, dict) and first.get("x") is not None:
                x_orig = first["x"]
            elif isinstance(first, (list, tuple)) and len(first) >= 1:
                x_orig = first[0]

        # 2. Determine new page of this event. Prefer the referenced object's
        #    reflowed page (authoritative); fall back to any x in the payload.
        if obj_page is not None:
            evt_page = obj_page
        else:
            evt_page = int(float(x_orig) // 1200.0) if x_orig is not None else current_page

        if evt_page < resume_start_page:
            evt_page = current_page

        # 3. Resolve the exact delta_x and delta_y for this event
        if obj_id is not None:
            delta_x, delta_y = asset_final_shifts[obj_id]
        elif x_orig is not None:
            op = int(float(x_orig) // 1200.0)
            delta_x = (evt_page - op) * 1200.0
            delta_y = page_shifts.get(evt_page, 0.0)
        else:
            delta_x = last_delta_x
            delta_y = last_delta_y

        # Update running defaults
        last_delta_x = delta_x
        last_delta_y = delta_y

        # 4. Shift coordinates in this event's payload
        shift_coordinates_in_payload_by_delta(evt_payload, delta_x, delta_y)

        # 5. If we crossed a page boundary, insert scene_start events. Emit them 1ms
        #    BEFORE the content event so the frontend switches the active scene first
        #    and the object inherits the correct sceneId.
        if evt_page > current_page:
            for p_idx in range(current_page + 1, evt_page + 1):
                new_remaining.append({
                    "event_id": f"evt_scene_start_{uuid.uuid4().hex[:6]}",
                    "type": "scene_start",
                    "start_ms": max(0, (evt.start_ms or 0) - 1),
                    "payload": {
                        "scene_index": p_idx,
                        "scene_id": f"scene_{p_idx}",
                        "label": f"Page {p_idx + 1}",
                        "camera_x": p_idx * 1200.0,
                        "camera_y": 375,
                        "reason": "document_overflow",
                    }
                })
            current_page = evt_page

        evt_payload["scene_index"] = current_page
        new_remaining.append({
            "type": evt_type,
            "start_ms": evt.start_ms,
            "payload": evt_payload,
        })

    # ── generation_start with G1's compiled_artifact ──────────────────
    await event_bus.publish(f"session:{session_id}", {
        "type": "generation_start",
        "generation_id": resume_gen_id,
        "branch_id": branch_manager.active_branch_id,
        "sequence_number": gen_manager.next_sequence(),
        "start_ms": 0,
        "server_timestamp": now_ms,
        "payload": {
            **g1_payload,
            "resumed_from_generation": original_gen_id,
            "interrupted_at_ms": interrupted_at_ms,
        },
    })

    # ── remaining content events with timestamps shifted to start from 0 ──
    publish_tasks = []
    for evt in new_remaining:
        shifted_ms = int(round(max(0.0, (evt.get("start_ms") or 0) - interrupted_at_ms) + _LEAD_MS))
        payload = {
            "type": evt["type"],
            "generation_id": resume_gen_id,
            "branch_id": branch_manager.active_branch_id,
            "sequence_number": gen_manager.next_sequence(),
            "start_ms": shifted_ms,
            "server_timestamp": now_ms,
            "payload": evt["payload"],
        }
        publish_tasks.append(event_bus.publish(f"session:{session_id}", payload))
    if publish_tasks:
        await asyncio.gather(*publish_tasks)

    # ── generation_end ────────────────────────────────────────────────
    end_ms = int(round(
        max((e.get("start_ms") or 0) for e in new_remaining) - interrupted_at_ms + _LEAD_MS + 1000
        if new_remaining else _LEAD_MS + 1000
    ))
    await event_bus.publish(f"session:{session_id}", {
        "type": "generation_end",
        "generation_id": resume_gen_id,
        "branch_id": branch_manager.active_branch_id,
        "sequence_number": gen_manager.next_sequence(),
        "start_ms": end_ms,
        "server_timestamp": now_ms,
        "payload": {"reason": "completed", "resumed": True, "page_complete": True, "total_events": len(new_remaining)},
    })

    # Update the whiteboard cursors to reflect the shifted content end.
    resume_wb = await session_state_store.get_whiteboard(str(session_id))
    resume_wb._flow._page = max(current_cursors.keys(), default=0)
    resume_wb._flow._y = current_cursors.get(resume_wb._flow._page, 50.0)
    resume_wb._flow._y_left = resume_wb._flow._y
    resume_wb._flow._y_right = resume_wb._flow._y
    resume_wb._flow._page_cursors = current_cursors
    await session_state_store.save_whiteboard_obj(str(session_id), resume_wb)

    await session_state_store.save_managers(str(session_id))
    await session_state_store.set_page_complete(str(session_id), True)
    logger.info("auto_resume.complete", session_id=str(session_id), resume_gen=resume_gen_id, events_replayed=len(remaining))


@router.post("/{session_id}/teach")
async def teach_topic_stream(
    session_id: uuid.UUID,
    topic: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Main teaching endpoint. Streams lesson events via the unified LLM pipeline.
    Events are published to the event bus so WebSocket clients receive them.
    """
    await resolve_session_owner(session_id, db, current_user)
    user = current_user

    gen_id = f"gen_init_{uuid.uuid4().hex[:8]}"

    # Check if real LLM is available
    from app.config.settings import get_settings
    settings = get_settings()

    has_gemini = settings.gemini_api_key and settings.gemini_api_key.strip() not in ("stub", "your_gemini_key_here", "")
    has_groq = settings.groq_api_key and settings.groq_api_key.strip() not in ("stub", "your_key_here", "")

    if not has_gemini and not has_groq:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid LLM API key detected. Please configure GEMINI_API_KEY or GROQ_API_KEY in backend/.env to run the real AI whiteboard engine."
        )

    # Real LLM path
    # Cancel any in-flight generation for this session before starting a new one.
    await generation_job_manager.cancel_and_wait(session_id)
    # Lock the page so the student cannot advance until generation completes
    await session_state_store.set_page_complete(session_id, False, page=0)

    # Register gen_id with the GenerationManager so that /interrupt's
    # invalidate_current() returns this ID as old_gen (used by _auto_resume_lesson
    # to look up G1 events in the EventStore). Without this, the manager holds a
    # stale ID from a previous call and the lookup finds nothing.
    _teach_managers = await session_state_store.get_managers(session_id)
    _teach_managers["generation"].set_current(gen_id)
    await session_state_store.save_managers(session_id)

    # 1. Clear student cognitive state profile (durably)
    from app.student_model.cognitive_tracker import CognitiveTracker
    await CognitiveTracker().reset_profile_durable(str(session_id))

    # 2. Prior timeline events are intentionally PRESERVED (was: hard DELETE).
    #    Each generation is namespaced by generation_id, so live playback still
    #    forwards only the current generation while replay history is retained.

    async def run_real_generation():
        # Clear/Reset whiteboard for a new lesson topic
        await session_state_store.reset_whiteboard(session_id)
        try:
            await _run_llm_teaching_logic(session_id, user.id, gen_id, topic)
        except Exception as exc:
            # On any failure, release the page lock so the client isn't wedged
            # at a permanent 409 on /continue, and surface the failure.
            if _is_cancellation_or_shutdown(exc):
                logger.info("generation.cancelled_on_shutdown", session_id=str(session_id), error=str(exc))
            else:
                logger.error("generation.failed", session_id=str(session_id), error=str(exc), exc_info=True)
            try:
                await session_state_store.set_page_complete(session_id, True)
            except Exception:
                pass
            try:
                msg = "Generation failed" if not _is_cancellation_or_shutdown(exc) else "Cancelled on shutdown"
                end_event = TimelineEventData(
                    generation_id=gen_id,
                    sequence_number=0,
                    start_ms=0,
                    server_timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
                    type=EventType.GENERATION_END,
                    payload={"reason": "error", "message": msg, "page_complete": True, "total_events": 0},
                )
                await get_event_bus().publish(f"session:{session_id}", end_event.model_dump())
            except Exception:
                pass

    generation_job_manager.submit(session_id, run_real_generation(), generation_id=gen_id)

    return {"status": "started", "generation_id": gen_id, "mode": "llm"}


@router.post("/extract-image", response_model=ImageExtractionResponse)
async def extract_image_text(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Utility endpoint to run the full 3-stage vision pipeline on an uploaded image,
    returning the transcribed text, LaTeX math, and semantic structures.
    """
    try:
        from app.utils.llm_client import llm_client
        content = await file.read()
        mime_type = file.content_type or "image/png"
        semantic = await llm_client.run_vision_pipeline(content, mime_type)
        return ImageExtractionResponse(**semantic)
    except Exception as e:
        logger.error("api.extract_image_text_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Image extraction and verification pipeline failed: {str(e)}"
        )


@router.post("/{session_id}/interrupt")
async def handle_interruption(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    text: str = Form(...),
    gesture_data: Optional[str] = Form(None),
    snapshot: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    session = await resolve_session_owner(session_id, db, current_user)
    user = current_user

    # 1. Invalidate current generation; keep old_gen so we can resume it after the doubt.
    managers = await session_state_store.get_managers(session_id)
    gen_manager: GenerationManager = managers["generation"]
    branch_manager = managers["branch"]
    old_gen, new_gen = gen_manager.invalidate_current()
    await session_state_store.save_managers(session_id)

    # 2. Parse form metadata
    import json
    parsed_gesture = None
    if gesture_data:
        try:
            parsed_gesture = json.loads(gesture_data)
        except Exception as e:
            logger.warning("sessions.interrupt.parse_gesture_failed", error=str(e))
            
    parsed_snapshot = None
    if snapshot:
        try:
            parsed_snapshot = json.loads(snapshot)
        except Exception as e:
            logger.warning("sessions.interrupt.parse_snapshot_failed", error=str(e))

    # Register the original lesson (G1) for auto-resume after the doubt answer.
    # interrupted_at_ms comes from the frontend's current playback clock (timeline_offset
    # in the snapshot), so we know which G1 events were already played vs remaining.
    interrupted_at_ms = float((parsed_snapshot or {}).get("timeline_offset") or 0)
    session_state_store.save_pending_resume(
        str(session_id), old_gen, interrupted_at_ms, branch_manager.active_branch_id
    )

    # 3. Vision Extraction pipeline if file uploaded
    # Cap untrusted free-text before it reaches any LLM prompt — bounds the
    # prompt-injection surface and token/cost abuse from a pasted wall of text.
    _MAX_DOUBT_CHARS = 2000
    student_question = (text or "")[:_MAX_DOUBT_CHARS]
    math_entities = []
    diagram_entities = []
    diagram_description = ""
    
    if file and file.filename:
        try:
            from app.utils.llm_client import llm_client
            content = await file.read()
            mime_type = file.content_type or "image/png"

            semantic = await llm_client.run_vision_pipeline(content, mime_type)

            extracted_text = semantic.get("question_text", "")
            math_entities = semantic.get("math_entities", [])
            diagram_entities = semantic.get("diagram_entities", [])
            diagram_description = semantic.get("diagram_description", "")
            
            if student_question.strip():
                student_question = f"{student_question}\n\n[Extracted from Image]:\n{extracted_text}"
            else:
                student_question = extracted_text
                
            logger.info("sessions.interrupt.image_processed", question=student_question)
        except Exception as e:
            logger.error("sessions.interrupt.image_pipeline_failed", error=str(e))

    # 4. Evaluate Interruption
    evaluator = EvaluatorAgent()
    failure_mode = evaluator.analyze_interruption(student_question)
    
    spatial_intent = {}
    if parsed_gesture and parsed_snapshot:
        scene_objects = parsed_snapshot.get("scene_graph_state", {}).get("objects", {})
        spatial_intent = evaluator.analyze_spatial_intent(parsed_gesture, scene_objects)
    
    # 5. Strategy Selection
    from app.pedagogy.socratic_engine import socratic_engine
    strategy = socratic_engine.select_strategy(
        failure_mode=failure_mode,
        spatial_intent=spatial_intent,
        user_efficacy=user.learning_profile.get("efficacy_score", 0.5)
    )
    strategy_modifier = socratic_engine.generate_prompt_modifier(strategy)

    # Cancel any in-flight generation first so its cancellation handler has completed
    # and saved its whiteboard before we reconstruct the interrupted state.
    await generation_job_manager.cancel_and_wait(session_id)

    # Reconstruct G1's interrupted whiteboard state to place G2 accurately.
    interrupted_cursors, interrupted_max_page, g1_max_content_ms = await reconstruct_interrupted_whiteboard_cursors(
        session_id, old_gen, interrupted_at_ms, db, branch_id=branch_manager.active_branch_id
    )

    # 6. Page context: if the student was on a past page when they asked,
    #    anchor the explanation to that page's content.
    viewed_page_context = (parsed_snapshot or {}).get("viewed_page_context") or {}
    viewed_page_index = viewed_page_context.get("page_index", 0)

    # Override whiteboard cursors to match the exact interruption point ONLY if mid-lesson.
    whiteboard = await session_state_store.get_whiteboard(session_id)
    page_lock = await session_state_store.get_page_lock(str(session_id))
    # "mid-lesson" must mean the student interrupted DURING PLAYBACK — not merely
    # that the backend is still generating. The backend finishes generating a lesson
    # in ~20-30s, but the frontend keeps playing it for minutes; a doubt asked at
    # t=95s is mid-playback even though page_complete is already True. If we only
    # checked page_complete we'd skip the cursor override and leave G1's FULL-layout
    # phantom page cursors in the whiteboard — which makes the doubt cascade onto the
    # wrong page AND seeds the auto-resume reflow with bottom-of-page cursors, jamming
    # resumed content past the 750px page bottom. So treat it as mid-lesson whenever
    # unplayed content remains past the interruption point.
    has_unplayed = interrupted_at_ms < (g1_max_content_ms - 1.0)
    mid_lesson = (not page_lock.get("page_complete", False)) or has_unplayed
    if mid_lesson:
        whiteboard._flow._page = interrupted_max_page
        whiteboard._flow._y = interrupted_cursors.get(interrupted_max_page, 50.0)
        whiteboard._flow._y_left = whiteboard._flow._y
        whiteboard._flow._y_right = whiteboard._flow._y
        whiteboard._flow._page_cursors = interrupted_cursors

    # 6a. Spatial & page context for the doubt explanation.
    # Mid-lesson: the doubt must append where G1's pen actually stopped
    # (interrupted_max_page), NOT the student's live camera page. The frontend's
    # viewed_page_index frequently reports page 0 even when the pen is several
    # pages ahead; honouring it here would jump the doubt onto a wrong, already-
    # full page, force a spurious page break, and desync it from the auto-resume
    # shift baseline (causing the overlap/interleaving you saw). Only when the
    # lesson is COMPLETE (student scrolled back to an older page to ask about it)
    # do we honour viewed_page_index.
    if mid_lesson:
        anchor_page_index = interrupted_max_page
        whiteboard.scene_index = anchor_page_index
    else:
        whiteboard.scene_index = viewed_page_index
        if whiteboard.flow.space_state == "nearly_full":
            anchor_page_index = interrupted_max_page + 1
            whiteboard.scene_index = anchor_page_index
        else:
            anchor_page_index = viewed_page_index

    await session_state_store.save_whiteboard_obj(session_id, whiteboard)
    space_state = whiteboard.flow.space_state    # ample | limited | nearly_full

    _space_guidance = {
        "ample":       "There is room to answer in-place on this page.",
        "limited":     "Space is limited; keep the answer concise. The layout engine will open a new page if needed.",
        "nearly_full": "This page is nearly full; the layout engine will automatically continue on the next page — do NOT manually insert a page break.",
    }

    if viewed_page_context:
        page_label = viewed_page_context.get("label") or f"page {viewed_page_index + 1}"
        strategy_modifier = (
            f"{strategy_modifier}\n\n"
            f"DOUBT CONTEXT — BOARD PAGE: The student is viewing {page_label} and their "
            f"doubt is about content on that page. "
            f"Your answer MUST:\n"
            f"  1. Reference the specific equations, diagrams, or annotations already visible on that page "
            f"     (listed in WHITEBOARD CONTENTS below) — point to them by content, not by position.\n"
            f"  2. Append your explanation BELOW existing content — never erase or overwrite it.\n"
            f"  3. Be self-contained: fully resolve the doubt so the student is unblocked.\n"
            f"  4. End with a brief closing line that signals the doubt is resolved and the lesson will continue "
            f"     (e.g. 'With that clarified, let us pick up where we left off.').\n"
            f"  Space status: {_space_guidance.get(space_state, '')}"
        ).strip()

    # 6b. Canvas gesture context: student circled or pointed at a specific element.
    if spatial_intent.get("intent") in ("FOCUS_REQUEST", "RELATIONSHIP_QUERY"):
        circled_type = spatial_intent.get("object_type") or "element"
        circled_content = spatial_intent.get("object_content") or ""
        content_str = f' ("{circled_content}")' if circled_content else ""
        relation = (
            "how the connected parts relate"
            if spatial_intent.get("intent") == "RELATIONSHIP_QUERY"
            else "this specific element"
        )
        strategy_modifier = (
            f"{strategy_modifier}\n\n"
            f"GESTURE CONTEXT: The student drew on the board to indicate a "
            f"{circled_type}{content_str}. Their doubt is specifically about {relation}. "
            f"Address it directly in your narration — do NOT use a scripted opener; "
            f"derive a natural reference from the content itself."
        ).strip()

    # 7. Pivot Orchestration — cursor already restored above.

    # Mark the page incomplete.
    await session_state_store.set_page_complete(session_id, False)

    # Doubt answers don't need a transition phrase — the strategy modifier
    # already frames the response ("I see you're asking about…").
    pivot_prefix = ""

    # The interrupt was manual, so confusion is at least moderate (tunable defaults).
    _s = get_settings()
    generation_job_manager.submit(
        session_id,
        _guarded_teaching(
            session_id, user.id, new_gen, session.topic,
            snapshot=parsed_snapshot,
            strategy_modifier=strategy_modifier,
            pivot_prefix=pivot_prefix,
            confusion_level=_s.interrupt_confusion_default,
            cognitive_load=(
                parsed_snapshot.get("cognitive_load")
                or parsed_snapshot.get("pedagogical_state", {}).get("confusion_level")
                or _s.interrupt_cognitive_load_default
            ) if parsed_snapshot else _s.interrupt_cognitive_load_default,
            is_pivot=True,
            student_question=student_question,
        ),
        generation_id=new_gen,
    )

    return {"status": "interruption_processed", "generation_id": new_gen}

@router.post("/{session_id}/adapt")
async def handle_cognitive_adaptation(
    session_id: uuid.UUID,
    request: CognitiveAdaptRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Called implicitly by the frontend when cognitive load crosses a threshold.
    Triggers a Socratic pivot to simplify without explicit user interruption.
    """
    session = await resolve_session_owner(session_id, db, current_user)
    user = current_user

    gen_manager = await get_session_generation_manager(session_id)
    _, new_gen = gen_manager.invalidate_current()
    await session_state_store.save_managers(session_id)
    await generation_job_manager.cancel_and_wait(session_id)
    await session_state_store.set_page_complete(session_id, False)

    strategy_modifier = (
        "The student is experiencing high cognitive load. IMMEDIATELY shift approach: "
        "speak in shorter sentences, reduce the number of visual elements per step to at most two, "
        "and ground the concept in a single concrete everyday analogy before any formal notation. "
        "Begin your narration with a natural acknowledgement that you are slowing down — do NOT "
        "use a scripted phrase; let it arise from the context of what was just shown. "
        "Do NOT repeat content already on the board; continue forward from the current position."
    )

    generation_job_manager.submit(
        session_id,
        _guarded_teaching(
            session_id, user.id, new_gen, session.topic,
            snapshot=request.snapshot,
            strategy_modifier=strategy_modifier,
            confusion_level=request.confusion_level,
            cognitive_load=request.cognitive_load,
            is_pivot=True,
        ),
        generation_id=new_gen,
    )

    return {"status": "adaptation_processed", "generation_id": new_gen}

class ContinueRequest(BaseModel):
    snapshot: Optional[dict] = None

@router.post("/{session_id}/continue")
async def handle_continuous_teaching(
    session_id: uuid.UUID,
    request: ContinueRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Called by the frontend when the teacher goes idle.
    Autonomously generates the next logical concept in the lesson graph,
    ensuring continuous, non-stop pedagogical evolution.
    """
    session = await resolve_session_owner(session_id, db, current_user)
    user = current_user

    # Enforce page-progression lock: block if current page is still generating
    page_lock = await session_state_store.get_page_lock(session_id)
    if not page_lock["page_complete"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Current page is not yet complete. Wait for the teacher to finish.",
        )

    gen_manager = await get_session_generation_manager(session_id)
    _, new_gen = gen_manager.invalidate_current()
    await session_state_store.save_managers(session_id)

    # Sync the next page from layout transitions emitted by the WhiteboardManager.
    whiteboard = await session_state_store.get_whiteboard(session_id)
    pending_scene_transitions = whiteboard.consume_scene_transitions()
    if pending_scene_transitions:
        whiteboard.scene_index = max(int(t.get("scene_index", whiteboard.scene_index)) for t in pending_scene_transitions)
        await session_state_store.save_whiteboard(session_id)

    # Cancel any in-flight generation, then mark new page as not complete.
    await generation_job_manager.cancel_and_wait(session_id)
    await session_state_store.set_page_complete(session_id, False)

    strategy_modifier = (
        "The previous teaching unit has finished. "
        "IMPORTANT — look at WHITEBOARD CONTENTS in the context below: every item listed there "
        "is already visible to the student. Do NOT re-explain, re-draw, or re-narrate any of it. "
        "Advance to the NEXT logical sub-topic or deeper layer of the concept that has NOT yet "
        "appeared on the board. Begin your narration with a natural bridging phrase that connects "
        "to what was just covered — do NOT use a scripted filler like 'Moving on'; derive it from "
        "the actual content (e.g. 'Now that we understand X, let us see why Y follows…'). "
        "If a student doubt was recently resolved, treat that resolution as completed context "
        "and resume the original lesson plan from the next unaddressed concept."
    )

    generation_job_manager.submit(
        session_id,
        _guarded_teaching(
            session_id, user.id, new_gen, session.topic,
            snapshot=request.snapshot,
            strategy_modifier=strategy_modifier,
        ),
        generation_id=new_gen,
    )

    return {"status": "continue_processed", "generation_id": new_gen}


@router.get("/{session_id}/page-status")
async def get_page_status(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the current page-progression lock state for a session (owner only)."""
    await resolve_session_owner(session_id, db, current_user)
    return await session_state_store.get_page_lock(session_id)
