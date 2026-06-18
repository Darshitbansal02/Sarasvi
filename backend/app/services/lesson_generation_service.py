"""
LessonGenerationService — the lesson generation pipeline, decomposed into phases.

Extracted verbatim from the former 410-line `_run_llm_teaching_logic` god-function
so each stage is named, isolated, and testable. The orchestration order and all
timing/reconciliation math are unchanged — this is a behavior-preserving refactor.

Phases (run in order by `run()`):
    _plan      → DomainAwareExplainer → lesson + DSL instructions + scene context
    _compile   → PresentationCompiler → timeline + per-stroke _charStates
    _synthesize_tts → real edge-tts audio per speech event (concurrent)
    _reconcile → shift events + _charStates onto the real audio timeline
    _publish   → emit every event + generation_end to the EventBus
    _finalize  → persist durable state (page lock, whiteboard, profile)
"""

from __future__ import annotations

import asyncio
import bisect
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from app.agents.domain_agents import DomainAwareExplainer
from app.config.settings import get_settings
from app.events.event_bus import get_event_bus
from app.events.event_protocol import TimelineEventData, EventType
from app.orchestration.live_cognitive_loop import LiveCognitiveLoop
from app.services.lesson_conversion import semantic_primitives_to_dsl_instructions
from app.services.plan_exceptions import PlanRejectedError
from app.services.session_state_store import session_state_store
from app.student_model.cognitive_tracker import CognitiveTracker

logger = structlog.get_logger(__name__)


# ── Narration sanitization for TTS ──────────────────────────────────
# Maps standalone LaTeX commands to the word a teacher would actually say. Order
# is irrelevant here (whole-token replacement); multi-arg structures (\frac,
# \sqrt) are handled separately below before this table runs.
_LATEX_WORD: dict[str, str] = {
    r"\int": "the integral of", r"\iint": "the double integral of",
    r"\oint": "the contour integral of",
    r"\sum": "the sum of", r"\prod": "the product of", r"\lim": "the limit of",
    r"\infty": "infinity", r"\partial": "partial", r"\nabla": "del",
    r"\cdot": "times", r"\times": "times", r"\div": "divided by",
    r"\pm": "plus or minus", r"\mp": "minus or plus",
    r"\leq": "less than or equal to", r"\le": "less than or equal to",
    r"\geq": "greater than or equal to", r"\ge": "greater than or equal to",
    r"\neq": "not equal to", r"\approx": "approximately",
    r"\equiv": "is equivalent to", r"\propto": "is proportional to",
    r"\rightarrow": "gives", r"\to": "to", r"\Rightarrow": "implies",
    r"\rightleftharpoons": "is in equilibrium with",
    r"\alpha": "alpha", r"\beta": "beta", r"\gamma": "gamma", r"\delta": "delta",
    r"\Delta": "delta", r"\epsilon": "epsilon", r"\varepsilon": "epsilon",
    r"\theta": "theta", r"\lambda": "lambda", r"\mu": "mu", r"\pi": "pi",
    r"\rho": "rho", r"\sigma": "sigma", r"\tau": "tau", r"\phi": "phi",
    r"\psi": "psi", r"\omega": "omega", r"\Omega": "omega", r"\hbar": "h bar",
    r"\sin": "sine", r"\cos": "cosine", r"\tan": "tangent", r"\log": "log",
    r"\ln": "natural log", r"\sqrt": "square root",
}


def _sanitize_narration_for_tts(text: str) -> str:
    """
    Convert narration that leaked LaTeX into something a TTS engine can speak
    naturally. The reasoning model is told to keep narration plain, but it
    routinely embeds `$...$`, `\\frac`, `^`, `_`, etc. Fed raw to edge-tts those
    become garbled noise ("dollar x caret 2") — heard as bad/duplicate-sounding
    audio on equations — and show up verbatim in the transcript. This runs only
    when math markup is actually present, so plain prose is untouched.
    """
    if not text:
        return text
    # Fast path: no math markup → leave prose exactly as written.
    if not any(tok in text for tok in ("\\", "$", "^", "_{", "{")):
        return text

    s = text
    # 1. Strip math-mode delimiters and spacing macros.
    s = re.sub(r"\\[()\[\]]", " ", s)              # \( \) \[ \]
    s = s.replace("$", " ")
    s = re.sub(r"\\(?:,|;|:|!|quad|qquad|left|right|displaystyle|text)\b", " ", s)
    s = re.sub(r"\\\\", " ", s)                     # row break

    # 2. Structured commands with arguments (run before the word table).
    for _ in range(3):  # resolve a few levels of nesting
        s = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1) over (\2)", s)
    s = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"square root of (\1)", s)

    # 3. Superscripts / subscripts → spoken form.
    s = re.sub(r"\^\s*\{([^{}]*)\}", r" to the power of (\1)", s)
    s = re.sub(r"\^\s*(\w)", r" to the power of \1", s)
    s = re.sub(r"_\s*\{([^{}]*)\}", r" sub (\1)", s)
    s = re.sub(r"_\s*(\w)", r" sub \1", s)

    # 4. Whole-word command substitutions.
    for cmd, word in _LATEX_WORD.items():
        s = re.sub(re.escape(cmd) + r"(?![a-zA-Z])", f" {word} ", s)

    # 5. Any remaining \command → its bare name; drop stray braces.
    s = re.sub(r"\\([a-zA-Z]+)", r" \1 ", s)
    s = s.replace("{", " ").replace("}", " ")

    # 6. Collapse whitespace and tidy spacing before punctuation.
    s = re.sub(r"\s+([,.;:?!])", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or text


# ── TTS synthesis (one speech event) ────────────────────────────────
async def _synthesize_speech_event(event: dict, voice: Optional[str] = None) -> int:
    """
    Phase 8 — streaming TTS. Synthesize audio + speech marks for ONE speech event
    (mutated in place) and return the (actual - estimated) duration delta in ms so
    the caller can shift later events. Doing this per-event in the emit loop means
    the first stroke reaches the student after one sentence's TTS instead of after
    the entire lesson's audio is precomputed.
    """
    if event.get("type") != "speech":
        return 0
    payload = event.get("payload", {})
    text = payload.get("text", "")
    if not text:
        return 0

    # Speak (and transcribe) natural language, never raw LaTeX. Mutating the
    # payload in place means the frontend transcript shows the clean form too,
    # and the edge-tts WordBoundary marks line up with what the student hears.
    text = _sanitize_narration_for_tts(text)
    payload["text"] = text

    import base64
    import edge_tts
    settings = get_settings()
    if not voice:
        voice = settings.tts_voice or "en-US-AriaNeural"
    # The compiler stores the ESTIMATED narration length under "duration_ms"
    # (audio_planner). Read it here so the (real − estimated) delta is non-zero
    # and the caller can shift later events onto the real audio timeline.
    orig_duration = payload.get("estimated_duration_ms") or payload.get("duration_ms", 0)

    try:
        communicate = edge_tts.Communicate(text, voice)
        audio_data = bytearray()
        speech_marks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                speech_marks.append({
                    "type": "word",
                    "value": chunk["text"],
                    "time": chunk["offset"] / 10000.0,
                    "duration": chunk["duration"] / 10000.0,
                    "word_index": len(speech_marks),
                })
        payload["audio_data"] = base64.b64encode(audio_data).decode("utf-8")
        payload["speech_marks"] = speech_marks
        payload["provider"] = "edge_tts"
        if speech_marks:
            actual = int(speech_marks[-1]["time"] + speech_marks[-1]["duration"])
        else:
            actual = int((len(text) / 12.0) * 1000)
        payload["estimated_duration_ms"] = actual
        # Publish the REAL audio length so the frontend narration timing and the
        # stroke-reveal pacing key off actual playback, not the estimate.
        payload["duration_ms"] = actual
        return (actual - orig_duration) if orig_duration > 0 else 0
    except Exception as e:
        logger.error("sessions.edge_tts_failed", error=str(e), text=text)
        # Local fallback (no audio bytes; synthetic word marks keep ink pacing).
        payload["audio_data"] = None
        payload["provider"] = "web_speech"
        marks = []
        curr = 0.0
        for i, w in enumerate(text.split()):
            marks.append({"type": "word", "value": w, "time": curr, "duration": 300.0, "word_index": i})
            curr += 350.0
        payload["speech_marks"] = marks
        actual = int(curr)
        payload["estimated_duration_ms"] = actual
        payload["duration_ms"] = actual
        return (actual - orig_duration) if orig_duration > 0 else 0


from app.config.symbol_word_map import SYMBOL_WORD_MAP


def align_char_states_to_speech(layout_asset, strokes, speech_marks, event_start_ms):
    if not layout_asset or not strokes or not speech_marks:
        return
    glyphs = layout_asset.get("glyphs", [])
    char_states = layout_asset.get("_charStates", [])
    if not glyphs or not char_states:
        return

    # Reset any stale wordBoundaryIndex first to prevent carry-over from other speech segments
    for c in char_states:
        if isinstance(c, dict):
            c.pop("wordBoundaryIndex", None)

    glyph_to_word: dict[int, int] = {}
    # Track only glyphs that matched via an exact or SYMBOL_WORD_MAP lookup.
    # Fallback assignments (min(current_word_idx, ...)) are intentionally excluded
    # because they map LaTeX symbols (∫, α, ½…) to arbitrary spoken words, which
    # overwrites the correct coarse-TTS-shifted absoluteStartMs with bad data.
    confident_glyphs: set[int] = set()
    current_word_idx = 0

    for g_idx, glyph in enumerate(glyphs):
        char = glyph.get("char", "").lower().strip()
        if not char:
            continue
        matched_idx = None
        for w_idx in range(current_word_idx, len(speech_marks)):
            word_val = speech_marks[w_idx].get("value", "").lower().strip(".,;:?!-()\"'")
            if word_val == char:
                matched_idx = w_idx
                break
            elif char in SYMBOL_WORD_MAP and word_val in SYMBOL_WORD_MAP[char]:
                matched_idx = w_idx
                break
        if matched_idx is not None:
            glyph_to_word[g_idx] = matched_idx
            confident_glyphs.add(g_idx)
            current_word_idx = matched_idx + 1
        # Unmatched glyphs are left out of glyph_to_word entirely — their
        # _charStates keep the coarse (real − estimated) shifted timestamps.

    for c in char_states:
        stroke_idx = c.get("strokeIndex")
        if stroke_idx is None or stroke_idx >= len(strokes):
            continue
        stroke = strokes[stroke_idx]
        char_idx = stroke.get("charIndex")
        # Only apply fine-grained word-boundary timing for confident matches.
        if char_idx is not None and char_idx in confident_glyphs:
            w_idx = glyph_to_word[char_idx]
            word_mark = speech_marks[w_idx]

            word_start = int(word_mark.get("time", 0))
            word_duration = max(
                120,
                int(word_mark.get("duration", 300))
            )

            glyph_indices = [
                g
                for g, mapped_word in glyph_to_word.items()
                if mapped_word == w_idx
            ]

            glyph_indices.sort()

            try:
                local_index = glyph_indices.index(char_idx)
            except ValueError:
                local_index = 0

            total_chars = max(1, len(glyph_indices))

            char_start = word_start + int(
                word_duration * (local_index / total_chars)
            )

            char_end = word_start + int(
                word_duration * ((local_index + 1) / total_chars)
            )

            c["startMs"] = event_start_ms + char_start
            c["endMs"] = event_start_ms + char_end
            c["absoluteStartMs"] = c["startMs"]
            c["absoluteEndMs"] = c["endMs"]
            c["wordBoundaryIndex"] = w_idx


async def _emit_plan_rejection(
    session_id: uuid.UUID,
    generation_id: str,
    error: PlanRejectedError,
) -> None:
    """Abort streaming when authoritative plan verification fails."""
    event_bus = get_event_bus()
    base_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    end_event = TimelineEventData(
        generation_id=generation_id,
        sequence_number=0,
        start_ms=0,
        server_timestamp=base_time,
        type=EventType.GENERATION_END,
        payload={
            "reason": "plan_rejected",
            "rejections": error.rejections,
            "attempts": error.attempts,
            "message": str(error),
            "total_events": 0,
            "page_complete": False,
        },
    )
    await event_bus.publish(f"session:{session_id}", end_event.model_dump())
    logger.error(
        "sessions.plan_rejected",
        session_id=str(session_id),
        generation_id=generation_id,
        rejections=error.rejections,
        attempts=error.attempts,
    )


class LessonGenerationService:
    """Generates one lesson (initial or Socratic pivot) and streams it to the bus."""

    def __init__(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        generation_id: str,
        topic: str,
        *,
        snapshot: Optional[dict] = None,
        strategy_modifier: str = "",
        pivot_prefix: str = "",
        confusion_level: float = 0.0,
        cognitive_load: float = 0.0,
        is_pivot: bool = False,
        student_question: Optional[str] = None,
    ) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.generation_id = generation_id
        self.topic = topic
        self.snapshot = snapshot
        self.strategy_modifier = strategy_modifier
        self.pivot_prefix = pivot_prefix
        self.confusion_level = confusion_level
        self.cognitive_load = cognitive_load
        self.is_pivot = is_pivot
        self.student_question = student_question

        self.tracker = CognitiveTracker()

        # Shared state populated across phases
        self.db = None
        self.user = None
        self.lesson: dict[str, Any] = {}
        self.semantic_instructions: list[Any] = []
        self.explanation_text: str = ""
        self.whiteboard = None
        self.scene_index: int = 0
        self.delete_events: list[Any] = []
        self.simulation_spec = None
        self.review_instructions: list[Any] = []
        self.strategy = None
        self.visual_spec: Any = {}
        self.lineage: dict[str, str] = {}
        self.compiled_artifact: dict[str, Any] = {}
        self.procedural_events: list[dict] = []
        self._layout_assets: dict[str, Any] = {}
        self._orig_durations: dict[int, int] = {}
        self._deltas: dict[int, int] = {}
        self.speech_timeline_shifts: list[tuple] = []

    # ── Orchestration ────────────────────────────────────────────────
    async def run(self) -> None:
        """Unifies generation + streaming for both initial lessons and pivots."""
        from app.database.engine import get_session_factory
        from sqlalchemy import select
        from app.models.user import User

        from app.utils.observability import track_generation

        session_factory = get_session_factory()
        with track_generation(self.generation_id):
            async with session_factory() as db:
                self.db = db
                result = await db.execute(select(User).where(User.id == self.user_id))
                user = result.scalar_one_or_none()
                if not user:
                    logger.error("teaching_logic.user_not_found", user_id=str(self.user_id))
                    return
                self.user = user

                try:
                    await self._plan()
                except PlanRejectedError as exc:
                    await _emit_plan_rejection(self.session_id, self.generation_id, exc)
                    return

                self._compile()
                await self._synthesize_tts()
                await self._reconcile()
                await self._publish()
                await self._finalize()

    # ── Phase: plan ──────────────────────────────────────────────────
    async def _plan(self) -> None:
        session_id, topic, user = self.session_id, self.topic, self.user

        explainer = DomainAwareExplainer()
        concept_id = topic

        # Warm the student profile from the durable store (survives restarts).
        profile = await self.tracker.hydrate(
            str(session_id),
            learning_profile=user.learning_profile if user else None,
        )
        if self.confusion_level <= 0.0:
            self.confusion_level = profile.confusion_index
        if self.cognitive_load <= 0.0:
            self.cognitive_load = profile.fatigue_level

        if self.student_question:
            self.strategy_modifier = (self.strategy_modifier or "") + f"\n\nCRITICAL: The student has asked the following doubt: \"{self.student_question}\". You MUST directly address and answer this doubt in your narration and visual primitives."

        live_loop = LiveCognitiveLoop(str(session_id))
        live_loop.current_concept = topic
        adaptation_context = live_loop.prepare_plan_context(topic, [])

        # 1. Unified pipeline: SemanticParse → Synthesize → Enrich → Verify
        lesson = await explainer.generate_explanation(
            user,
            concept_id,
            snapshot_context=self.snapshot,
            strategy_modifier=self.strategy_modifier,
            confusion_level=self.confusion_level,
            cognitive_load=self.cognitive_load,
            student_id=str(session_id),
            db=self.db,
            adaptation_context=adaptation_context,
        )

        # semantic_primitives already built by pipeline; ensure narration pivot prefix
        if self.pivot_prefix and lesson.get("narration"):
            lesson["narration"] = f"{self.pivot_prefix} {lesson['narration']}"

        semantic_primitives = lesson.get("semantic_primitives", [])

        # 2. Convert to DSL instructions (logs drops instead of silent skip)
        semantic_instructions = semantic_primitives_to_dsl_instructions(
            semantic_primitives,
            topic=topic,
        )

        explanation_text = f"{self.pivot_prefix} {lesson.get('narration', '')}".strip()

        # 3. Render Stream
        whiteboard = await session_state_store.get_whiteboard(session_id)

        # Resolve the active scene index from the student's snapshot if available
        scene_index = whiteboard.scene_index
        if self.snapshot:
            camera_state = self.snapshot.get("camera_state", {})
            if isinstance(camera_state, dict) and "x" in camera_state:
                try:
                    camera_x = float(camera_state["x"])
                    scene_index = int(round(camera_x / 1200.0))
                    # Align whiteboard's index for drawing coordinates positioning
                    whiteboard.scene_index = scene_index
                except (ValueError, TypeError):
                    pass

        # Advance to the next page for pivots so topic shifts always start cleanly.
        # But if is_pivot is True, we want to stay on the same page where the student asked their question/doubt
        # so the explanation happens in-place and preserves existing whiteboard context.
        delete_events = []
        if self.is_pivot:
            # Keep on the same page
            whiteboard.scene_index = scene_index

        # Check if any instruction requires simulation
        has_sim = any(instr.primitive_type.value == "simulation_start" for instr in semantic_instructions)
        simulation_spec = None

        from app.semantic.semantic_understanding import SemanticUnderstanding
        from app.reasoning.requirement_planner import ReasoningRequirementPlan
        from app.pedagogy.strategy_engine import TeachingStrategy

        sem_dict = lesson.get("semantic_understanding") or {}
        req_dict = lesson.get("reasoning_requirements") or {}
        strat_dict = lesson.get("teaching_strategy") or {}

        semantic = SemanticUnderstanding.model_validate(sem_dict) if sem_dict else None
        requirements = ReasoningRequirementPlan.model_validate(req_dict) if req_dict else None
        strategy = TeachingStrategy.model_validate(strat_dict) if strat_dict else None

        if has_sim and semantic and requirements and strategy:
            from app.semantic.simulation_planner import simulation_planner
            try:
                simulation_spec = await simulation_planner.plan_simulation(
                    query=topic,
                    requirements=requirements,
                    strategy=strategy
                )
            except Exception as exc:
                logger.warning("sessions.simulation_planning_failed", error=str(exc))

        # Retrieve context-aware reinforcement reviews from spaced-repetition scheduler (P0 Task 3)
        review_instructions = []
        try:
            from app.student_model.reinforcement_scheduler import ReinforcementScheduler
            scheduler = ReinforcementScheduler()
            topic_domain = lesson.get("primary_domain")

            due_reviews = await scheduler.get_due_reviews(
                student_id=str(session_id),
                current_concepts=[topic],
                current_domain=topic_domain,
                max_reviews=1
            )

            if due_reviews:
                review_concept = due_reviews[0]["concept"]
                review_text = f"Before we begin, let's quickly revisit: {review_concept}."
                review_duration_ms = int((len(review_text) / 12.0) * 1000) + 400

                from app.dsl.primitives import DSLInstruction, DSLPrimitiveType
                review_instructions.append(
                    DSLInstruction(
                        instruction_id=f"dsl_review_narr_{uuid.uuid4().hex[:6]}",
                        primitive_type=DSLPrimitiveType.NARRATION_SYNC,
                        data={
                            "_narration_sentence": review_text,
                            "is_review": True
                        },
                        duration_ms=review_duration_ms
                    )
                )
                review_instructions.append(
                    DSLInstruction(
                        instruction_id=f"dsl_review_ann_{uuid.uuid4().hex[:6]}",
                        primitive_type=DSLPrimitiveType.ANNOTATION,
                        data={
                            "annotation_id": f"review_{review_concept.replace(' ', '_')}",
                            "text": f"Review: {review_concept}",
                            "style": "emphasis",
                            "color": "amber",
                            "is_review": True
                        },
                        duration_ms=500
                    )
                )
                logger.info("sessions.review_prepared", concept=review_concept, session_id=str(session_id))
        except Exception as e:
            logger.warning("sessions.review_retrieval_failed", error=str(e))

        # Packaging Lineage IDs (P1 Task 6)
        semantic_id = semantic.semantic_id if semantic else ""
        requirements_id = requirements.requirements_id if requirements else ""
        strategy_id = strategy.strategy_id if strategy else ""

        visual_spec = lesson.get("visual_specification") or {}
        representation_id = ""
        if isinstance(visual_spec, dict):
            representation_id = visual_spec.get("representation_id", "")
        elif hasattr(visual_spec, "representation_id"):
            representation_id = visual_spec.representation_id

        lineage = {
            "semantic_id": semantic_id,
            "requirements_id": requirements_id,
            "strategy_id": strategy_id,
            "representation_id": representation_id
        }

        # Persist phase outputs for downstream phases
        self.lesson = lesson
        self.semantic_instructions = semantic_instructions
        self.explanation_text = explanation_text
        self.whiteboard = whiteboard
        self.scene_index = scene_index
        self.delete_events = delete_events
        self.simulation_spec = simulation_spec
        self.review_instructions = review_instructions
        self.strategy = strategy
        self.visual_spec = visual_spec
        self.lineage = lineage

    # ── Phase: compile ───────────────────────────────────────────────
    def _compile(self) -> None:
        from app.services.presentation_compiler import PresentationCompiler
        compiler = PresentationCompiler(self.whiteboard)

        from app.teaching_ast.ast_nodes import TeachingAST
        ast_dict = self.lesson.get("teaching_ast")
        ast = TeachingAST.model_validate(ast_dict) if ast_dict else None

        compiled_artifact = compiler.compile_presentation(
            self.semantic_instructions,
            self.explanation_text,
            scene_index=self.scene_index,
            student_confusion=self.confusion_level,
            simulation_spec=self.simulation_spec,
            review_instructions=self.review_instructions,
            strategy=self.strategy,
            lineage=self.lineage,
            visual_spec=self.visual_spec,
            ast=ast,
        )
        procedural_events = compiled_artifact["timeline"]

        # Soft coverage validator — checks equation/scene completeness.
        # Hard structural errors were already caught inside compile_presentation.
        # Use compiled_instructions (the actual instruction set used by the compiler)
        # instead of the teaching_sequence-derived semantic_instructions, so the
        # validator's expected set matches exactly what was compiled into layout_assets.
        from app.verification.gateway import verification_gateway
        _validation_instructions = compiled_artifact.get("compiled_instructions") or self.semantic_instructions
        _coverage_ok, _coverage_warnings = verification_gateway.validate_coverage(
            procedural_events, _validation_instructions, compiled_artifact.get("layout_assets")
        )
        if not _coverage_ok:
            logger.warning(
                "lesson.coverage_warnings",
                count=len(_coverage_warnings),
                warnings=_coverage_warnings,
            )

        # JSON round-trip the compiled_artifact to break any Python-level
        # object sharing (e.g. same list/tuple/dict referenced from multiple
        # positions) that causes json.dumps to report false circular-reference
        # errors when serializing the generation_start payload for WebSocket
        # streaming. After this step all nodes in the tree are unique objects.
        try:
            clean_artifact = json.loads(json.dumps(compiled_artifact, default=str))
        except Exception:
            clean_artifact = compiled_artifact  # fallback: let ndjson_stream handle it

        lesson_meta_event: dict = {
            "start_ms": 0,
            "type": "generation_start",
            "payload": {
                "learning_objective": self.lesson.get("learning_objective", self.topic),
                "primary_domain": self.lesson.get("primary_domain", "general"),
                "concepts": self.lesson.get("concepts", []),
                "unverified_claims": self.lesson.get("unverified_claims", []),
                "student_profile": self.lesson.get("student_profile", {}),
                "compiled_artifact": clean_artifact,
            },
        }
        procedural_events = [lesson_meta_event] + (self.delete_events or []) + procedural_events

        self.compiled_artifact = compiled_artifact
        self.procedural_events = procedural_events
        self._layout_assets = compiled_artifact.get("layout_assets", {}) if isinstance(compiled_artifact, dict) else {}

    # ── Phase: synthesize TTS ────────────────────────────────────────
    async def _synthesize_tts(self) -> None:
        # Reconcile the ESTIMATED timeline against REAL TTS audio. The compiler
        # timed every event — and the per-stroke _charStates inside the compiled
        # artifact — using audio_planner estimates. Here we synthesize the real
        # edge-tts audio per speech event and shift all LATER events (and their
        # stroke-reveal schedules) by the accumulated (real − estimated) delta, so
        # ink stays locked to the voice instead of drifting or overlapping.
        procedural_events = self.procedural_events

        # Save original estimated durations before synthesis mutates them in place
        self._orig_durations = {}
        for event in procedural_events:
            if event.get("type") == "speech":
                payload = event.get("payload", {})
                self._orig_durations[id(event)] = payload.get("estimated_duration_ms") or payload.get("duration_ms", 0)

        # Resolve voice based on user preference
        language = "en-US"
        if self.user and self.user.learning_profile:
            language = self.user.learning_profile.get("language", "en-US")
            
        voice_mapping = {
            "hi-IN": "hi-IN-SwaraNeural",
            "hinglish": "en-IN-NeerjaNeural",
            "en-US": "en-US-AriaNeural"
        }
        selected_voice = voice_mapping.get(language, "en-US-AriaNeural")

        # Synthesize ALL speech audio CONCURRENTLY (bounded). edge-tts is network
        # I/O, so this collapses N sequential ~1s syntheses into ~max(one call)
        # instead of their sum. Each call computes its own (real − estimated) delta
        # and mutates only its own payload, so the cumulative shift below is identical
        # to doing them one-by-one.
        _speech_events = [e for e in procedural_events if e.get("type") == "speech"]
        self._deltas = {}
        if _speech_events:
            _tts_sema = asyncio.Semaphore(8)

            async def _synth_bounded(ev):
                async with _tts_sema:
                    return id(ev), await _synthesize_speech_event(ev, voice=selected_voice)

            for _eid, _delta in await asyncio.gather(*[_synth_bounded(e) for e in _speech_events]):
                self._deltas[_eid] = _delta

        # Record original start, estimated end, and delta for each speech event
        self.speech_timeline_shifts = []
        for event in procedural_events:
            if event.get("type") == "speech":
                orig_start = event["start_ms"]
                orig_duration = self._orig_durations.get(id(event), 0)
                delta = self._deltas.get(id(event), 0)
                self.speech_timeline_shifts.append([orig_start, orig_start + orig_duration, delta])

    # ── Phase: reconcile ─────────────────────────────────────────────
    async def _reconcile(self) -> None:
        procedural_events = self.procedural_events
        speech_timeline_shifts = self.speech_timeline_shifts
        _layout_assets = self._layout_assets
        compiled_artifact = self.compiled_artifact

        # Reconcile the ESTIMATED timeline against the REAL TTS durations: shift
        # every event by the sum of deltas of speech events that originally end before the event starts.
        # Enforce sequential non-overlap constraints: if Event B originally started after Event A ended,
        # it must start at or after Event A ends in the reconstructed timeline.
        procedural_events.sort(key=lambda x: x["start_ms"])

        ended_events = []  # list of tuples: (prior_event, orig_end, shifted_end)
        last_speech_shifted_end = 0

        for event in procedural_events:
            orig_start = event["start_ms"]
            
            # Sum deltas dynamically to account for on-the-fly extra push adjustments
            cumulative_shift = sum(item[2] for item in speech_timeline_shifts if item[1] <= orig_start)

            # Initial shifted start candidate
            shifted_start = max(0, orig_start + cumulative_shift)

            # Enforce strict sequential ordering for speech events (no overlap)
            if event.get("type") == "speech" and last_speech_shifted_end > 0:
                if shifted_start < last_speech_shifted_end + 150:
                    extra_push = (last_speech_shifted_end + 150) - shifted_start
                    shifted_start = last_speech_shifted_end + 150
                    
                    # Update this speech event's delta in speech_timeline_shifts so that
                    # all subsequent events automatically get shifted by this extra push.
                    for item in speech_timeline_shifts:
                        if item[0] == orig_start:
                            item[2] += extra_push
                            break

            # Enforce sequential non-overlap constraint
            for prior_event, orig_end, shifted_end in ended_events:
                if orig_end <= orig_start:
                    shifted_start = max(shifted_start, shifted_end)

            event["start_ms"] = shifted_start

            # Calculate actual duration of this event
            actual_duration = event.get("payload", {}).get("duration_ms", 0)

            # Record original and shifted end times
            orig_dur = self._orig_durations.get(id(event), actual_duration)
            ended_events.append((event, orig_start + orig_dur, shifted_start + actual_duration))

            # Update last speech end tracking
            if event.get("type") == "speech":
                last_speech_shifted_end = shifted_start + actual_duration

            # Shift character states for reveals
            if event.get("type") == "stroke_reveal":
                shift = shifted_start - orig_start
                if shift:
                    _obj_id = (event.get("payload") or {}).get("object_id")
                    _asset = _layout_assets.get(_obj_id) if _obj_id else None
                    _char_states = _asset.get("_charStates") if isinstance(_asset, dict) else None
                    if _char_states:
                        for _c in _char_states:
                            _c["startMs"] = max(0, int(_c.get("startMs", 0)) + shift)
                            _c["endMs"] = max(0, int(_c.get("endMs", 0)) + shift)
                            _c["absoluteStartMs"] = _c["startMs"]
                            _c["absoluteEndMs"] = _c["endMs"]

        # Sort the final timeline by start_ms to maintain strict monotonic order
        procedural_events.sort(key=lambda x: x["start_ms"])

        # Precise Pass: Align _charStates directly to Edge-TTS WordBoundary markers using finalized start_ms times
        for event in procedural_events:
            if event.get("type") == "speech":
                reasoning_step_id = event.get("payload", {}).get("reasoning_step_id")
                if reasoning_step_id:
                    # Find the corresponding stroke_reveal event
                    stroke_reveal_event = next(
                        (e for e in procedural_events if e.get("type") == "stroke_reveal" and e.get("payload", {}).get("reasoning_step_id") == reasoning_step_id),
                        None
                    )
                    if stroke_reveal_event:
                        _obj_id = stroke_reveal_event.get("payload", {}).get("object_id")
                        _asset = _layout_assets.get(_obj_id) if _obj_id else None
                        _strokes = compiled_artifact.get("stroke_assets", {}).get(_obj_id) if _obj_id else None
                        _speech_marks = event.get("payload", {}).get("speech_marks", [])
                        if _asset and _strokes and _speech_marks:
                            speech_start_ms = event["start_ms"]
                            align_char_states_to_speech(_asset, _strokes, _speech_marks, speech_start_ms)
                            
                            # Re-anchor the event itself to the first reveal timestamp.
                            # This ensures the frontend starts the writing motor (which allocates the board
                            # and moves the cursor) exactly when the first synced stroke is due,
                            # rather than waiting for the original estimated event start.
                            _cs = _asset.get("_charStates")
                            if _cs:
                                earliest = min((c.get("startMs", float('inf')) for c in _cs), default=None)
                                if earliest is not None and earliest != float('inf'):
                                    stroke_reveal_event["start_ms"] = int(earliest)

        from app.verification.gateway import verification_gateway
        verification_gateway.validate_timeline(procedural_events, layout_assets=_layout_assets)

    # ── Phase: publish ───────────────────────────────────────────────
    async def _publish(self) -> None:
        procedural_events = self.procedural_events
        generation_id = self.generation_id
        session_id = self.session_id

        base_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        event_bus = get_event_bus()

        for i, event in enumerate(procedural_events):
            payload = event.get("payload", {})
            payload.pop("_narration_sentence", None)

            timeline_event = TimelineEventData(
                generation_id=generation_id,
                sequence_number=i,
                start_ms=event["start_ms"],
                server_timestamp=base_time + event["start_ms"],
                type=EventType(event["type"]),
                payload=payload,
            )
            published = timeline_event.model_dump()
            published.setdefault("event_id", f"{generation_id}:{i}")
            await event_bus.publish(f"session:{session_id}", published)

        final_start_ms = procedural_events[-1]["start_ms"] + 2000 if procedural_events else 0
        end_event = TimelineEventData(
            generation_id=generation_id,
            sequence_number=len(procedural_events),
            start_ms=final_start_ms,
            server_timestamp=base_time + final_start_ms,
            type=EventType.GENERATION_END,
            payload={
                "reason": "completed",
                "total_events": len(procedural_events),
                "page_index": self.scene_index,
                "page_complete": True,
            }
        )
        await event_bus.publish(
            f"session:{session_id}",
            end_event.model_dump(),
        )

    # ── Phase: finalize ──────────────────────────────────────────────
    async def _finalize(self) -> None:
        # Persist durable state at the generation boundary.
        await session_state_store.set_page_complete(self.session_id, True, page=self.scene_index, increment=True)
        await session_state_store.save_whiteboard(self.session_id)
        await self.tracker.persist(str(self.session_id))

        logger.info(
            "generation.completed",
            generation_id=self.generation_id,
            session_id=str(self.session_id),
            total_events=len(self.procedural_events),
            page_index=self.scene_index,
        )


async def run_lesson_generation(
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
) -> None:
    """Module-level entry point — preserves the original call signature."""
    await LessonGenerationService(
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
    ).run()
