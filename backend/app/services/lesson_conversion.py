"""
Convert teaching_sequence JSON into semantic_primitives for ProceduralRenderer.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

import structlog

from app.dsl.primitives import DSLInstruction, DSLPrimitiveType

logger = structlog.get_logger(__name__)


def teaching_sequence_to_semantic_primitives(
    teaching_sequence: list[dict[str, Any]],
    *,
    repair_latex: Callable[[str, str], str] | None = None,
    topic: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Returns (semantic_primitives, narration_parts)."""
    semantic_primitives: list[dict[str, Any]] = []
    narration_parts: list[str] = []

    for step in teaching_sequence:
        narration_sentence = step.get("narration_sentence", "")
        step_id = step.get("step_id")
        if narration_sentence:
            narration_parts.append(narration_sentence)
        prim = step.get("visual_primitive")
        if not prim:
            if narration_sentence:
                # Speech-only step: emit a cognitive_pause so the cursor
                # drifts naturally while the teacher speaks, instead of
                # creating an empty annotation that produces pen motion
                # over invisible ink.
                speech_ms = int((len(narration_sentence) / 12.0) * 1000)
                pause_ms = speech_ms + narration_sentence.count(".") * 400 + narration_sentence.count(",") * 200
                prim_dict = {
                    "type": "cognitive_pause",
                    "data": {
                        "duration_ms": max(800, pause_ms),
                        "reason": "speech_only",
                        "hesitation_strength": 0.3,
                        "cursor_drift": True,
                    },
                    "duration_ms": max(800, pause_ms),
                    "_narration_sentence": narration_sentence,
                }
                if step_id:
                    prim_dict["reasoning_step_id"] = step_id
                semantic_primitives.append(prim_dict)
            continue

        if isinstance(prim, dict):
            if narration_sentence:
                sentence_ms = int((len(narration_sentence) / 12.0) * 1000)
                punctuation_pause_ms = (
                    narration_sentence.count(".") * 400 + narration_sentence.count(",") * 200
                )
                prim["duration_ms"] = sentence_ms + punctuation_pause_ms
                prim["_narration_sentence"] = narration_sentence
                words = [w.strip(".,!?;:\"'") for w in narration_sentence.split() if w.strip(".,!?;:\"'")]
                if words:
                    prim["narration_anchor"] = words[0]
            else:
                prim["duration_ms"] = 3000  # Fallback duration for visual drawing if narration is empty
                prim["_narration_sentence"] = ""
            if step_id:
                prim["reasoning_step_id"] = step_id

        semantic_primitives.append(prim)

    return semantic_primitives, narration_parts


def semantic_primitives_to_dsl_instructions(
    semantic_primitives: list[dict[str, Any]],
    *,
    repair_latex: Callable[[str, str], str] | None = None,
    topic: str = "",
) -> list[DSLInstruction]:
    """Convert primitive dicts to DSLInstruction list; logs instead of silent skip."""
    instructions: list[DSLInstruction] = []
    dropped: list[Any] = []

    for prim in semantic_primitives:
        if not prim:
            continue

        ptype = None
        pdata: dict[str, Any] = {}
        duration_ms = 0

        if isinstance(prim, dict):
            if "type" in prim:
                ptype = prim["type"]
                pdata = prim.get("data") or {
                    k: v for k, v in prim.items() if k not in ("type", "duration_ms", "region")
                }
                duration_ms = prim.get("duration_ms", 0)
            elif "primitive_type" in prim:
                ptype = prim["primitive_type"]
                pdata = prim.get("data") or {}
                duration_ms = prim.get("duration_ms", 0)
            else:
                for k, v in prim.items():
                    if k in ("duration_ms", "region"):
                        continue
                    for member in DSLPrimitiveType:
                        if member.value.lower() == k.lower():
                            ptype = member.value
                            pdata = copy.deepcopy(v) if isinstance(v, dict) else {}
                            duration_ms = prim.get("duration_ms", 0)
                            break
                    if ptype:
                        break

        if not ptype:
            dropped.append(prim)
            logger.warning("lesson_conversion.invalid_primitive", primitive=prim)
            continue

        try:
            prim_enum = DSLPrimitiveType(ptype)
        except ValueError:
            matched = None
            for member in DSLPrimitiveType:
                if member.value.lower() == str(ptype).lower():
                    matched = member
                    break
            if not matched:
                dropped.append(prim)
                logger.warning("lesson_conversion.unsupported_primitive", ptype=ptype)
                continue
            prim_enum = matched

        narration_sentence = prim.get("_narration_sentence", "")
        if narration_sentence:
            pdata["_narration_sentence"] = narration_sentence

        if prim_enum in {DSLPrimitiveType.EQUATION, DSLPrimitiveType.EQUATION_WRITE}:
            latex_value = str(
                pdata.get("latex") or pdata.get("equation") or pdata.get("formula") or ""
            ).strip()
            if not latex_value and repair_latex:
                latex_value = repair_latex(topic, narration_sentence)
                logger.warning(
                    "lesson_conversion.repaired_empty_latex",
                    inferred_latex=latex_value,
                    topic=topic,
                )
            pdata["latex"] = latex_value

        instructions.append(
            DSLInstruction(
                primitive_type=prim_enum,
                duration_ms=duration_ms,
                data=pdata,
                reasoning_step_id=prim.get("reasoning_step_id") if isinstance(prim, dict) else None,
            )
        )

    if dropped:
        logger.warning("lesson_conversion.dropped_count", count=len(dropped))

    return instructions
