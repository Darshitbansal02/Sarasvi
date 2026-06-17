"""
Domain engine enrichment — validates and constrains LLM plans via domain authority.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.domains.engine_resolver import resolve_engine_for_domain
from app.dsl.primitives import DSLInstruction

logger = structlog.get_logger(__name__)


class DomainEnrichmentService:
    """Runs domain engines to validate and constrain teaching sequences."""

    async def apply_domain_authority(
        self,
        teaching_sequence: list[dict[str, Any]],
        *,
        query: str,
        semantic_profile: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """
        Returns (constrained_sequence, domain_rejections).
        """
        # Get teaching strategies and visual planning details
        teaching_profile = semantic_profile.get("teaching_profile") or {}
        domain = teaching_profile.get("primary_domain") or "general"
        concepts = teaching_profile.get("concepts") or [query]
        primary_concept = concepts[0] if concepts else query
        engine = resolve_engine_for_domain(domain)

        teaching_modalities = teaching_profile.get("teaching_modalities") or {}
        teaching_strategy = teaching_profile.get("teaching_strategy") or {}
        visual_goal = teaching_profile.get("visual_goal") or "none"
        
        # Load Cognitive Core structures if present, or create fallbacks
        from app.semantic.semantic_understanding import SemanticUnderstanding, ConceptualTransition
        from app.reasoning.requirement_planner import ReasoningRequirementPlan, ReasoningRequirement
        from app.pedagogy.strategy_engine import TeachingStrategy, StrategyParameter

        semantic_data = semantic_profile.get("semantic_understanding")
        if isinstance(semantic_data, dict):
            semantic = SemanticUnderstanding.model_validate(semantic_data)
        else:
            semantic = SemanticUnderstanding(
                learning_goal=query,
                concepts=concepts,
                constraints=[],
                student_intent="explanation",
                prior_knowledge_assumptions=[],
                conceptual_transitions=[ConceptualTransition(from_state="Intuitive", to_state="Rigorous")]
            )

        requirements_data = semantic_profile.get("reasoning_requirements")
        if isinstance(requirements_data, dict):
            requirements = ReasoningRequirementPlan.model_validate(requirements_data)
        else:
            requirements = ReasoningRequirementPlan(
                requirements=[
                    ReasoningRequirement(
                        objective=query,
                        operations=["procedural_exposition"]
                    )
                ],
                pedagogical_justification="Fallback logic"
            )

        strategy_data = semantic_profile.get("teaching_strategy_plan")
        if isinstance(strategy_data, dict):
            strategy = TeachingStrategy.model_validate(strategy_data)
        else:
            strategy = TeachingStrategy(
                parameters=[StrategyParameter(name="pace", value="normal")],
                rationale="Fallback logic"
            )

        # Generative Visual Goal mapping to visual representation specification
        from app.semantic.visual_goal_planner import visual_goal_planner
        try:
            visual_spec = await visual_goal_planner.plan_visual_specification(
                visual_goal=visual_goal,
                semantic=semantic,
                requirements=requirements,
                strategy=strategy
            )
        except Exception as exc:
            logger.warning("domain_enrichment.visual_planning_failed", error=str(exc))
            from app.semantic.visual_goal_planner import RepresentationSpecification
            visual_spec = RepresentationSpecification(
                representation_type="none",
                representation_details={},
                justification="Error fallback"
            )
            
        concept_payload = {
            "concept": primary_concept,
            "domain": domain,
            "title": primary_concept,
            "query": query,
            # Guard all optional fields: domain engines use `x in field` membership
            # checks that raise TypeError when the field is None.
            "cognitive_structure": semantic_profile.get("cognitive_structure") or {},
            "teaching_modalities": teaching_modalities,
            "teaching_strategy": teaching_strategy,
            "visual_goal": visual_goal,
            "visual_specification": visual_spec.model_dump() if hasattr(visual_spec, "model_dump") else visual_spec,
            "learning_objective": semantic_profile.get("learning_objective") or query,
            "key_points": concepts or [query],
            "latex": teaching_profile.get("latex") or "",
        }

        # --- Universal Primitive Realization Layer Bypassed ---
        # Realization of Visual Specifications has been moved downstream to the Compiler layer.
        dsl_instructions = []

        passed, rejections = engine.validate_plan(
            teaching_sequence,
            query=query,
            concept_payload=concept_payload,
        )
        if not passed:
            logger.warning("domain_enrichment.plan_rejected", rejections=rejections, domain=domain)
            return teaching_sequence, rejections

        constrained = engine.constrain_sequence(
            teaching_sequence,
            query=query,
            concept_payload=concept_payload,
            dsl_instructions=dsl_instructions,
        )

        logger.info(
            "domain_enrichment.constrained",
            domain=domain,
            engine=type(engine).__name__,
            steps=len(constrained),
        )
        return constrained, []


domain_enrichment_service = DomainEnrichmentService()
