"""
Unified Teaching Pipeline — single authority for lesson generation on all entry paths.

v2: Integrates with the 3-call ReasoningCore. The pipeline no longer makes its own
    LLM calls for semantic analysis or verification — those are handled inside
    ReasoningCore's 3-call architecture.

LLM Call Budget:
    ReasoningCore Call 1: Semantic + Pedagogical Planning
    ReasoningCore Call 2: Lesson Skeleton
    ReasoningCore Call 3: Procedural Expansion → TeachingAST
    (optional) Call 4: Repair pass if verification rejects a step
    Total: 3-4 LLM calls (down from 15-24)
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.pedagogy.generative_synthesizer import GenerativeSynthesizer
from app.pedagogy.plan import PedagogicalPlan
from app.pedagogy.strategy_engine import StrategyEngine
from app.verification.gateway import verification_gateway
from app.reasoning.reasoning_core import reasoning_core

from app.services.curriculum_graph_service import curriculum_graph_service
from app.services.domain_enrichment_service import domain_enrichment_service
from app.services.lesson_conversion import teaching_sequence_to_semantic_primitives
from app.services.plan_exceptions import PlanRejectedError
from app.student_model.cognitive_tracker import CognitiveTracker
from app.models.user import User

logger = structlog.get_logger(__name__)

MAX_PLAN_ATTEMPTS = 2  # Reduced from 3 — fewer retries = fewer LLM calls


class UnifiedTeachingPipeline:
    """The single authoritative teaching pipeline.

    Consumed by REST /teach (via _run_llm_teaching_logic) and by the WebSocket
    student_message handler, which routes to the same _run_llm_teaching_logic.
    There is no second brain — CognitiveOS/CognitiveConductor are quarantined.
    """

    def __init__(self) -> None:
        self.strategy = StrategyEngine()
        self.synthesizer = GenerativeSynthesizer()
        self.validator = verification_gateway
        self.cognitive_tracker = CognitiveTracker()


    async def _synthesize(
        self,
        query: str,
        *,
        attempt: int,
        mix: dict[str, float],
        interests: list[str],
        context: Optional[dict],
        modifier: str,
        confusion_level: float,
        cognitive_load: float,
        domain: str,
        semantic_profile: Optional[dict[str, Any]] = None,
        user: Optional[User] = None,
    ) -> dict[str, Any]:
        """
        Generation path: ReasoningCore (3-call architecture) when enabled,
        with single-shot synthesis as the availability fallback.

        A PlanRejectedError from the ReasoningCore means a formal verifier rejected
        a step after repair — that propagates (fail closed) and is NOT silently
        downgraded to the unverified single-shot path.
        """
        if get_settings().reasoning_core_enabled:
            try:
                sequence, meta = await reasoning_core.build_teaching_sequence(
                    query,
                    user=user,
                    snapshot=context,
                    domain=domain,
                    modifier=modifier,
                    confusion_level=confusion_level,
                    cognitive_load=cognitive_load,
                    semantic_profile=semantic_profile,
                )
                return {"teaching_sequence": sequence, "narration": "", **meta}
            except PlanRejectedError:
                raise
            except Exception as exc:
                logger.warning("pipeline.reasoning_core_fallback", error=str(exc))

        return await self.synthesizer.synthesize_lesson(
            query,
            mix if attempt == 1 else {"scientific": 1.0},
            interests,
            context=context,
            modifier=modifier,
            confusion_level=confusion_level,
            cognitive_load=cognitive_load,
            user=user,
        )


    async def generate_lesson(
        self,
        *,
        student_id: str,
        query: str,
        user: Optional[User] = None,
        snapshot_context: Optional[dict] = None,
        strategy_modifier: str = "",
        confusion_level: float = 0.0,
        cognitive_load: float = 0.0,
        db: Optional[AsyncSession] = None,
        adaptation_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        _settings = get_settings()
        profile = self.cognitive_tracker.get_or_create_profile(
            student_id,
            learning_profile=user.learning_profile if user else None
        )

        # Resolve user's preferred language and append specific system prompts
        language = "en-US"
        if user and user.learning_profile:
            language = user.learning_profile.get("language", "en-US")
        
        if language == "hinglish":
            language_instructions = (
                "\nCRITICAL: Write the spoken narration in Hinglish (Hindi vocabulary written in Latin script, e.g., 'Aaj hum gravity ke baare mein samjhenge'). "
                "All mathematical equations, LaTeX symbols, and whiteboard annotations/labels must remain in standard English/Latin text."
            )
            strategy_modifier = f"{strategy_modifier}\n{language_instructions}".strip()
        elif language == "hi-IN":
            language_instructions = (
                "\nCRITICAL: Write the spoken narration in Hindi (Devanagari script, e.g., 'आज हम गुरुत्वाकर्षण के बारे में समझेंगे।'). "
                "All mathematical equations, LaTeX symbols, and whiteboard annotations/labels must remain in standard English/Latin text (do NOT write Devanagari characters on the whiteboard)."
            )
            strategy_modifier = f"{strategy_modifier}\n{language_instructions}".strip()

        if adaptation_context:
            confusion_level = max(
                confusion_level,
                float(adaptation_context.get("confusion_level", profile.confusion_index)),
            )
            cognitive_load = max(
                cognitive_load,
                float(adaptation_context.get("cognitive_load", profile.fatigue_level)),
            )
            extra_modifier = adaptation_context.get("strategy_modifier", "")
            if extra_modifier:
                strategy_modifier = f"{strategy_modifier}\n{extra_modifier}".strip()

        effective_confusion = max(confusion_level, profile.confusion_index)
        effective_load = max(cognitive_load, profile.fatigue_level)

        # ── Universal Early Profile (No LLM Call) ──
        # Bypasses the redundant early LLM call. Call 1 inside ReasoningCore
        # will perform the authoritative semantic domain classification.
        cached_profile = {
            "primary_domain": "general",
            "secondary_domains": [],
            "subdomain": "general",
            "concepts": [query],
            "learning_goal": f"Understand and explain: {query}",
            "learning_objective": f"Understand and explain: {query}",
            "final_answer_type": "conceptual",
            "teaching_modalities": {"whiteboard_only": True, "equation": False, "graph": False, "diagram": False},
            "visual_goal": "none",
            "teaching_strategy": {
                "reasoning_depth": "moderate",
                "explanation_style": "conceptual",
                "interaction_mode": "lecture",
                "construction_mode": "incremental",
                "cognitive_capabilities": []
            },
            "pedagogical_mode": "scaffold_first",
            "ambiguity_score": 0.5,
            "candidate_domains": ["general"],
            "prerequisites": [],
            "curriculum_level": (
                "advanced" if profile.understanding_score >= _settings.curriculum_band_advanced
                else "intermediate" if profile.understanding_score >= _settings.curriculum_band_intermediate
                else "beginner"
            ),
            "learning_mode": "visual",
            "constraints": [],
            "student_intent": "explanation",
            "conceptual_transitions": [
                {
                    "from_state": "basic or intuitive understanding",
                    "to_state": f"rigorous understanding of {query}"
                }
            ]
        }

        teaching_profile = cached_profile
        domain = "general"
        concepts = [query]

        # ── Prerequisite check (no LLM, graph-based) ────────────────
        missing_prereqs: list[str] = []
        prereq_preamble: list[dict[str, Any]] = []
        if db is not None:
            try:
                prereqs = await curriculum_graph_service.get_prerequisites(db, concepts)
                knowledge_scores = {
                    c: p.mastery_score
                    for c, p in profile.knowledge_state.concept_profiles.items()
                }
                missing_prereqs = curriculum_graph_service.filter_missing_prerequisites(
                    prereqs,
                    [],
                    knowledge_state=knowledge_scores,
                )
                if missing_prereqs:
                    prereq_preamble = curriculum_graph_service.build_prerequisite_preamble(missing_prereqs)
            except Exception as exc:
                logger.warning("pipeline.prereq_check_skipped", error=str(exc))

        # ── Retrieve similar past pedagogical episodes via vector search ────
        similar_episodes_str = ""
        if db is not None:
            try:
                from app.services.vector_service import vector_service
                similar_episodes = await vector_service.search_similar(query, db, limit=3)
                if similar_episodes:
                    parts = []
                    for row in similar_episodes:
                        summary = getattr(row, "summary", "") or (row[1] if len(row) > 1 else "")
                        strategy = getattr(row, "pedagogical_strategy", "") or (row[2] if len(row) > 2 else "")
                        score = getattr(row, "success_score", 1.0) or (row[3] if len(row) > 3 else 1.0)
                        parts.append(f"- Strategy: {strategy} (Efficacy Score: {score:.2f}). Summary: {summary}")
                    similar_episodes_str = "\n".join(parts)
            except Exception as e:
                logger.error("pipeline.similar_episodes_search_failed", error=str(e))

        if similar_episodes_str:
            similar_episodes_modifier = (
                f"\nHere are reference teaching episodes from past sessions to learn from:\n"
                f"{similar_episodes_str}\n"
                f"Analyze which strategies worked well (high efficacy score) or poorly, and adapt your teaching flow accordingly."
            )
            strategy_modifier = f"{strategy_modifier}\n{similar_episodes_modifier}".strip()

        # ── Build pedagogical plan from cached domain profile ────────
        semantic_for_plan = {
            "teaching_profile": teaching_profile,
            "learning_objective": teaching_profile.get("learning_objective", query),
            "concepts": concepts,
        }
        pedagogical_plan = PedagogicalPlan.from_semantic(
            query=query,
            semantic=semantic_for_plan,
            prerequisites=missing_prereqs,
        )
        plan_modifier = pedagogical_plan.to_synthesis_modifier()
        full_modifier = f"{strategy_modifier}\n{plan_modifier}".strip()

        # ── Generate lesson (3-call architecture inside ReasoningCore) ─
        all_rejections: list[str] = []
        last_lesson: dict[str, Any] = {}
        last_verification: dict[str, Any] = {}
        last_unverified: list[dict[str, Any]] = []

        for attempt in range(1, MAX_PLAN_ATTEMPTS + 1):
            rejections: list[str] = []

            mix = (
                self.strategy.calculate_pedagogical_mix(user, query)
                if user
                else {
                    "scientific": _settings.pedagogy_mix_scientific,
                    "metaphorical": _settings.pedagogy_mix_metaphorical,
                }
            )
            interests = (user.learning_profile.get("hobbies", []) if user else []) or ["general"]
            retry_note = ""
            if attempt > 1:
                retry_note = (
                    f"\nCRITICAL RETRY {attempt}: Previous plan failed: "
                    f"{'; '.join(all_rejections)}. Fix the issues."
                )

            lesson = await self._synthesize(
                query,
                attempt=attempt,
                mix=mix,
                interests=interests,
                context=snapshot_context,
                modifier=f"{full_modifier}{retry_note}",
                confusion_level=effective_confusion,
                cognitive_load=effective_load,
                domain=pedagogical_plan.objective.domain,
                semantic_profile=cached_profile if cached_profile else None,
                user=user,
            )

            if "prescriptive_plan" in lesson:
                pedagogical_plan.teaching_segments = lesson["prescriptive_plan"].get("teaching_segments", [])

            if not self.validator.validate_synthesis(lesson):
                rejections.append("synthesis_validation_failed")
                # Single-shot fallback (1 extra LLM call)
                lesson = await self.synthesizer.synthesize_lesson(
                    query,
                    {"scientific": 1.0},
                    interests,
                    modifier=f"{full_modifier}{retry_note}",
                    confusion_level=effective_confusion,
                    cognitive_load=effective_load,
                    user=user,
                )

            teaching_sequence = list(lesson.get("teaching_sequence") or [])
            if prereq_preamble and attempt == 1:
                teaching_sequence = prereq_preamble + teaching_sequence

            # ── Domain enrichment (no LLM — rule-based engine) ──────
            teaching_sequence, domain_rejections = await domain_enrichment_service.apply_domain_authority(
                teaching_sequence,
                query=query,
                semantic_profile={
                    "teaching_profile": teaching_profile,
                    "cognitive_structure": cached_profile.get("cognitive_structure") if cached_profile else {},
                    "learning_objective": pedagogical_plan.objective.text,
                    "semantic_understanding": lesson.get("semantic_understanding"),
                    "reasoning_requirements": lesson.get("reasoning_requirements"),
                    "teaching_strategy_plan": lesson.get("teaching_strategy"),
                },
            )
            if domain_rejections:
                rejections.extend(domain_rejections)

            # ── Verification is already done inside ReasoningCore ────
            # The ReasoningCore runs formal verifiers (math, physics, etc.) and
            # returns the results in lesson metadata. We extract them here.
            # NO additional LLM call for verification.
            last_verification = lesson.get("verification") or {}
            if isinstance(last_verification, dict) and last_verification.get("rejected", 0) > 0:
                rejection_results = last_verification.get("results", [])
                for r in rejection_results:
                    if r.get("status") == "rejected":
                        rejections.append(f"{r.get('verifier', 'unknown')}:{r.get('reason', 'unknown')}")
            last_unverified = [
                r for r in last_verification.get("results", [])
                if r.get("status") == "unverified"
            ]

            math_claims: list[dict[str, Any]] = []

            if not teaching_sequence:
                rejections.append("empty_sequence_after_verification")

            if not self.validator.validate_teaching_sequence(teaching_sequence, query=query):
                rejections.append("completeness_validation_failed")

            if rejections:
                all_rejections = list(set(all_rejections + rejections))
                logger.warning(
                    "pipeline.plan_rejected",
                    attempt=attempt,
                    rejections=rejections,
                    query=query,
                )
                if attempt >= MAX_PLAN_ATTEMPTS:
                    raise PlanRejectedError(
                        f"Plan rejected after {MAX_PLAN_ATTEMPTS} attempts",
                        rejections=all_rejections,
                        attempts=attempt,
                    )
                continue

            pedagogical_plan.merge_teaching_sequence(
                teaching_sequence,
                math_claims=math_claims,
                verification_passed=True,
                rejections=[],
                attempts=attempt,
            )

            # Update pedagogical plan with actual classified domain/concepts from AST
            ast_data = lesson.get("teaching_ast")
            if isinstance(ast_data, dict):
                ast_domain = ast_data.get("domain")
                ast_concepts = ast_data.get("concepts")
                if ast_domain:
                    pedagogical_plan.objective.domain = ast_domain
                if ast_concepts:
                    pedagogical_plan.concepts = ast_concepts

            semantic_primitives, narration_parts = teaching_sequence_to_semantic_primitives(
                teaching_sequence
            )

            last_lesson = {
                **lesson,
                "teaching_sequence": teaching_sequence,
                "math_claims": math_claims,
                "semantic_primitives": semantic_primitives,
                "narration": " ".join(narration_parts) or lesson.get("narration", ""),
                "pedagogical_plan": pedagogical_plan.model_dump(),
                "semantic_profile": cached_profile,
                "learning_objective": pedagogical_plan.objective.text,
                "primary_domain": pedagogical_plan.objective.domain,
                "concepts": pedagogical_plan.concepts,
                "student_profile": {
                    "understanding_score": profile.understanding_score,
                    "confusion_index": profile.confusion_index,
                    "fatigue_level": profile.fatigue_level,
                    "active_misconceptions": profile.active_misconceptions,
                },
                "adaptation": {
                    "confusion_level": effective_confusion,
                    "cognitive_load": effective_load,
                },
                "verification": last_verification,
                "unverified_claims": last_unverified,
            }
            break

        logger.info(
            "pipeline.lesson_generated",
            query=query,
            steps=len(last_lesson.get("teaching_sequence", [])),
            domain=last_lesson.get("primary_domain"),
            attempts=pedagogical_plan.verification.attempts,
        )
        return last_lesson


unified_teaching_pipeline = UnifiedTeachingPipeline()
