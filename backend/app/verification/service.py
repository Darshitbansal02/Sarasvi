"""
VerificationService — runs verification over a teaching sequence and produces a
VerificationReport.

There is NO per-subject routing. Verifiers are selected purely from STRUCTURAL
signals present in the lesson (equations, reaction arrows, code), so any subject
is handled uniformly:
  • equations      → universal symbolic verifier (any operation, any subject)
  • reaction arrow → chemistry balancer (self-guards on valid element symbols)
  • code block     → algorithms verifier
A formal REJECTED claim fails the lesson closed; everything else is advisory.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.verification.algorithms_verifier import algorithms_verifier
from app.verification.base import VerificationReport
from app.verification.chemistry_verifier import chemistry_verifier
from app.verification.factual_verifier import factual_verifier
from app.verification.math_verifier import math_verifier

logger = structlog.get_logger(__name__)

# Genuine reaction arrows (a structural notation signal, NOT a subject keyword).
# '=' and '\to' are deliberately excluded — they appear constantly in math
# (identities), limits ("x \to 0"), and CS (mappings), and would otherwise drag
# every equation into the chemistry atom-balancer.
_REACTION_ARROWS = ("\\rightarrow", "\\longrightarrow", "\\xrightarrow", "->", "→", "⟶")


class VerificationService:
    async def verify(
        self,
        teaching_sequence: list[dict[str, Any]],
        *,
        domain: str = "general",
        final_answer_type: str = "conceptual",
        query: str = "",
    ) -> VerificationReport:
        domain_key = (domain or "general").lower()
        report = VerificationReport(domain=domain_key, has_formal_verifier=False)

        # 1. Universal factual/logical narration check (LLM-based; gated by the
        #    enable_llm_factual_verification setting). Subject-agnostic.
        try:
            results = await factual_verifier.verify(teaching_sequence, query=query, domain=domain_key)
            report.results.extend(results)
        except Exception as exc:
            logger.warning("verification.factual_error", error=str(exc))

        # 2. Select formal verifiers from STRUCTURE only — never from the subject.
        has_equations = False
        has_reactions = False
        has_code = False

        for step in teaching_sequence:
            prim = step.get("visual_primitive") or {}
            if not isinstance(prim, dict):
                continue
            ptype = str(prim.get("type", "")).lower()
            data = prim.get("data") or {}
            if ptype in ("equation", "equation_write", "equation_highlight"):
                has_equations = True
                latex = str(data.get("latex") or data.get("full_latex") or data.get("equation") or "").strip()
                if any(a in latex for a in _REACTION_ARROWS):
                    has_reactions = True
            elif ptype in ("code_block", "complexity_label"):
                has_code = True

        formal_verifiers = []
        if has_equations:
            formal_verifiers.append(math_verifier)      # universal symbolic check
        if has_reactions:
            formal_verifiers.append(chemistry_verifier)
        if has_code:
            formal_verifiers.append(algorithms_verifier)
        formal_verifiers = list(dict.fromkeys(formal_verifiers))

        if formal_verifiers:
            report.has_formal_verifier = True
            for verifier in formal_verifiers:
                try:
                    results = await asyncio.to_thread(verifier.verify, teaching_sequence, query=query)
                    report.results.extend(results)
                except Exception as exc:
                    logger.warning("verification.verifier_error", verifier=verifier.name, error=str(exc))

        logger.info(
            "verification.report",
            domain=domain_key,
            verified=len(report.verified),
            unverified=len(report.unverified),
            rejected=len(report.rejected),
        )
        return report


verification_service = VerificationService()
