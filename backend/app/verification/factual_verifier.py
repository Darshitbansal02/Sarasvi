"""
Factual verifier — optionally checks general knowledge claims using LLM.

Controlled by settings.enable_llm_factual_verification.
When False (default): Marks claims as UNVERIFIED directly, with zero API calls.
When True: Uses a deep, Rigorous LLM verification call to verify factual
statements, and supports failing closed (REJECTED) on verified factual errors.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.config.settings import get_settings
from app.utils.llm_client import llm_client
from app.verification.base import ClaimVerification, VerificationStatus

logger = structlog.get_logger(__name__)


class FactualVerifier:
    name = "factual"

    async def verify(
        self,
        teaching_sequence: list[dict[str, Any]],
        *,
        query: str = "",
        domain: str = "general",
        **_: Any,
    ) -> list[ClaimVerification]:
        """
        Verify factual claims in the teaching sequence.
        If enable_llm_factual_verification is False, returns UNVERIFIED with zero LLM calls.
        """
        # Collect narration and visual summaries
        steps_summary = []
        narration_only = []
        for i, step in enumerate(teaching_sequence):
            narr = str(step.get("narration_sentence", "")).strip()
            if narr:
                narration_only.append(narr)
            prim = step.get("visual_primitive") or {}
            prim_type = prim.get("type", "")
            prim_data = prim.get("data", {}) if isinstance(prim, dict) else {}
            prim_summary = f"{prim_type}: {prim_data}" if prim_type else "None"
            steps_summary.append(f"Step {i+1}:\n- Narration: {narr}\n- Whiteboard: {prim_summary}")

        full_narration = " ".join(narration_only).strip()
        if not full_narration:
            return []

        claim_label = (full_narration[:120] + "…") if len(full_narration) > 120 else full_narration

        settings = get_settings()
        if not getattr(settings, "enable_llm_factual_verification", False):
            # Default Mode: 0 API calls, fast fallback
            logger.info(
                "factual_verifier.skip_llm_call_disabled",
                domain=domain,
                claim_length=len(full_narration),
            )
            return [
                ClaimVerification(
                    claim=claim_label,
                    domain=domain,
                    status=VerificationStatus.UNVERIFIED,
                    confidence=0.0,
                    reason="Factual LLM verification disabled by configuration (0 API calls mode).",
                    verifier=self.name,
                )
            ]

        # Advanced Mode: Run deep LLM verification
        logger.info(
            "factual_verifier.start_llm_cross_verification",
            domain=domain,
            query=query,
        )

        sequence_str = "\n\n".join(steps_summary)

        system_prompt = (
            "You are an enterprise-grade SaaS Factual and Logical Verification Agent.\n"
            "Your role is to run a rigorous, multi-subject verification of the provided teaching sequence "
            "against the user's initial query/topic. You verify history, biology, geography, mathematics, "
            "law, medicine, computer science, and all other domains.\n\n"
            "Analyze the teaching sequence step-by-step. For any factual statements, math equations, or "
            "explanations:\n"
            "1. Cross-reference them with authoritative ground truth.\n"
            "2. Identify any objective factual errors, logical inconsistencies, incorrect equations, or false statements.\n"
            "3. Grade each critical claim with one of the following statuses:\n"
            "   - 'verified': The statement/equation is factually correct, accurate, and aligned with standard knowledge.\n"
            "   - 'rejected': The statement/equation contains a clear, objective error (e.g. wrong date, false historical fact, incorrect science, mathematically wrong statement, false definition). You MUST reject it if it is objectively wrong.\n"
            "   - 'unverified': The statement is subjective, speculative, or cannot be definitively checked.\n\n"
            "Be conservative with 'rejected': only reject if a claim is objectively wrong. If it's correct but worded "
            "differently, mark it 'verified'.\n\n"
            "You must return a JSON response with the following format:\n"
            "{\n"
            "  \"domain\": \"the verified subject domain\",\n"
            "  \"verdicts\": [\n"
            "    {\n"
            "      \"claim\": \"the exact statement or equation being verified\",\n"
            "      \"status\": \"verified\" | \"rejected\" | \"unverified\",\n"
            "      \"reason\": \"clear, detailed explanation of why it has this status and what the correct fact is\"\n"
            "    }\n"
            "  ]\n"
            "}"
        )

        user_prompt = (
            f"Query/Topic: {query}\n"
            f"Assigned Domain: {domain}\n\n"
            f"Teaching Sequence:\n{sequence_str}"
        )

        try:
            response = await llm_client.generate_json(system_prompt, user_prompt)
            verdicts = response.get("verdicts", [])
            results = []
            for v in verdicts:
                claim = v.get("claim", "")
                status_str = str(v.get("status", "unverified")).lower()
                reason = v.get("reason", "")

                if status_str == "verified":
                    status = VerificationStatus.VERIFIED
                    confidence = 0.95
                elif status_str == "rejected":
                    status = VerificationStatus.REJECTED
                    confidence = 0.95
                else:
                    status = VerificationStatus.UNVERIFIED
                    confidence = 0.4

                results.append(
                    ClaimVerification(
                        claim=claim,
                        domain=domain,
                        status=status,
                        confidence=confidence,
                        reason=reason,
                        verifier=self.name,
                    )
                )
            if not results:
                # Fallback if empty verdicts list returned
                results.append(
                    ClaimVerification(
                        claim=claim_label,
                        domain=domain,
                        status=VerificationStatus.VERIFIED,
                        confidence=0.5,
                        reason="No explicit errors detected in narration sequence.",
                        verifier=self.name,
                    )
                )
            return results

        except Exception as e:
            logger.error("factual_verifier.llm_call_failed", error=str(e))
            # Gracefully degrade to unverified on LLM client errors (SaaS resilience)
            return [
                ClaimVerification(
                    claim=claim_label,
                    domain=domain,
                    status=VerificationStatus.UNVERIFIED,
                    confidence=0.0,
                    reason=f"Verification skipped due to network/API error: {str(e)}",
                    verifier=self.name,
                )
            ]


factual_verifier = FactualVerifier()
