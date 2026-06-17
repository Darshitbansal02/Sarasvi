"""
Session API routes — create sessions, retrieve events for replay, and stream lessons.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

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
    """
    try:
        await _run_llm_teaching_logic(session_id, *args, **kwargs)
    except Exception as exc:
        if _is_cancellation_or_shutdown(exc):
            logger.info("generation.cancelled_on_shutdown", session_id=str(session_id), error=str(exc))
        else:
            logger.error("generation.failed", session_id=str(session_id), error=str(exc), exc_info=True)
    finally:
        try:
            await session_state_store.set_page_complete(session_id, True)
        except Exception:
            pass


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

    # 1. Invalidate current generation
    gen_manager = await get_session_generation_manager(session_id)
    _, new_gen = gen_manager.invalidate_current()
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

    # 6. Page context: if the student was on a past page when they asked,
    #    anchor the explanation to that page's content.
    viewed_page_context = (parsed_snapshot or {}).get("viewed_page_context") or {}
    if viewed_page_context:
        page_label = viewed_page_context.get("label", "")
        page_index = viewed_page_context.get("page_index", 0)
        if page_label:
            strategy_modifier = (
                f"{strategy_modifier}\n\n"
                f"CRITICAL PAGE CONTEXT: The student is looking at {page_label} "
                f"(page {page_index + 1}) when asking this doubt. "
                f"Reference the diagrams, equations, and concepts on that specific page "
                f"in your response. Do not jump ahead — the student needs help with what "
                f"was already shown, not new material."
            ).strip()

    # 6b. Canvas gesture context: if the student circled a specific element on
    #     the board, anchor the whole explanation to THAT element and its content
    #     so the answer is about what they pointed at — not generic material.
    if spatial_intent.get("intent") in ("FOCUS_REQUEST", "RELATIONSHIP_QUERY"):
        circled_type = spatial_intent.get("object_type") or "element"
        circled_content = spatial_intent.get("object_content") or ""
        content_str = f' which reads "{circled_content}"' if circled_content else ""
        relation = (
            "how the connected parts relate"
            if spatial_intent.get("intent") == "RELATIONSHIP_QUERY"
            else "this specific element"
        )
        strategy_modifier = (
            f"{strategy_modifier}\n\n"
            f"CRITICAL CANVAS CONTEXT: The student drew on the whiteboard to point at "
            f"a {circled_type}{content_str}. Their doubt is specifically about {relation}. "
            f"Refer to it directly, re-highlight or re-draw it, and resolve their confusion "
            f"about it. Do NOT introduce unrelated material or jump ahead."
        ).strip()

    # Integrate visual/mathematical context derived from the vision pipeline.
    # Instruction wording depends on diagrams_enabled: when drawing is off, the
    # model must explain visually through equations + annotated text, not shapes.
    from app.config.settings import get_settings as _get_settings
    _drawing_on = _get_settings().diagrams_enabled
    if math_entities:
        strategy_modifier = (
            f"{strategy_modifier}\n\n"
            f"CRITICAL: The student's question includes the following mathematical concepts and expressions: "
            f"{', '.join(math_entities)}. Write each expression clearly on the whiteboard as an equation "
            f"and explain it step by step."
        )
    if diagram_entities or diagram_description:
        desc_str = f" ({diagram_description})" if diagram_description else ""
        element_list = ', '.join(diagram_entities) if diagram_entities else "the illustrated elements"
        if _drawing_on:
            diagram_instruction = (
                f"Draw these elements and label them clearly on the whiteboard: {element_list}."
            )
        else:
            diagram_instruction = (
                f"You CANNOT draw shapes or diagrams. Instead, describe each element in "
                f"text annotations and write the governing equations for: {element_list}. "
                f"Walk through the diagram verbally step-by-step in the narration."
            )
        strategy_modifier = (
            f"{strategy_modifier}\n\n"
            f"CRITICAL: The student's question includes a diagram/visual illustration{desc_str}. "
            f"{diagram_instruction}"
        )

    pivot_prefix = spatial_intent.get("narrative_hint", "I see. Let's look at it this way.")
    
    # Cancel any in-flight generation, then mark the page incomplete.
    await generation_job_manager.cancel_and_wait(session_id)
    await session_state_store.set_page_complete(session_id, False)

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
            # Read cognitive_load from the snapshot directly, or fall back to
            # pedagogical_state.confusion_level, or the configured default.
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

    strategy_modifier = "The student is experiencing high cognitive load. Stop the current complex explanation, summarize what was just shown in 1 sentence, and use a much simpler analogy."

    generation_job_manager.submit(
        session_id,
        _guarded_teaching(
            session_id, user.id, new_gen, session.topic,
            snapshot=request.snapshot,
            strategy_modifier=strategy_modifier,
            pivot_prefix="Let's slow down for a second.",
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

    strategy_modifier = "The previous explanation has finished. Autonomously transition to the next logical sub-topic or advanced layer of the concept. Expand the concept graph. DO NOT repeat the previous explanation."

    generation_job_manager.submit(
        session_id,
        _guarded_teaching(
            session_id, user.id, new_gen, session.topic,
            snapshot=request.snapshot,
            strategy_modifier=strategy_modifier,
            pivot_prefix="Moving on,",
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
