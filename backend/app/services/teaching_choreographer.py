# teaching_choreographer.py — Authoritative Pedagogical Choreography Planner

import uuid
from typing import Any, Dict, List, Optional, Tuple
from app.dsl.primitives import DSLInstruction, DSLPrimitiveType


def _split_narration_at_anchor(narration: str, anchor: Optional[str]) -> Tuple[str, str]:
    """
    Nib-on-word: split a step's narration around the phrase that introduces its
    visual so the teacher says up to that phrase, draws, then keeps explaining.
    Returns (before_incl_anchor, after). Falls back to (narration, "") — write
    after the full narration — when there is no usable anchor (missing, blank,
    not an exact substring, or only a trivial tail would remain).
    """
    text = (narration or "").strip()
    if not text or not anchor:
        return text, ""
    a = anchor.strip()
    if not a:
        return text, ""
    idx = text.lower().find(a.lower())
    if idx < 0:
        return text, ""
    split_at = idx + len(a)
    before = text[:split_at].strip()
    after = text[split_at:].lstrip(" \t,;:.—–-").strip()
    # Don't split off a trivial tail — keeps each TTS phrase natural.
    if not before or len(after) < 8:
        return text, ""
    return before, after


class ChoreographyStep:
    def __init__(
        self,
        step_id: str,
        parent_step_id: Optional[str],
        action_type: str,  # Maps directly to v2 timeline event types
        payload: Dict[str, Any],
        reasoning_step_id: Optional[str] = None
    ):
        self.step_id = step_id
        self.parent_step_id = parent_step_id
        self.action_type = action_type
        self.payload = payload
        self.reasoning_step_id = reasoning_step_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "parent_step_id": self.parent_step_id,
            "action_type": self.action_type,
            "payload": self.payload,
            "reasoning_step_id": self.reasoning_step_id
        }

class TeachingChoreographer:
    """
    Authoritative Choreography Planner:
    Defines the logical sequence of speech narration, whiteboard drawings,
    focus highlights, and attention targets before any visual coordinates
    or speech waveforms are generated.
    """
    
    def choreograph(self, instructions: List[DSLInstruction]) -> List[ChoreographyStep]:
        steps: List[ChoreographyStep] = []
        last_step_id = None

        # Helper to generate unique step IDs
        def make_id(prefix: str) -> str:
            return f"ch_{prefix}_{uuid.uuid4().hex[:6]}"

        # Pre-emit scene start
        scene_start_id = make_id("scene_start")
        steps.append(ChoreographyStep(
            step_id=scene_start_id,
            parent_step_id=None,
            action_type="scene_start",
            payload={}
        ))
        last_step_id = scene_start_id

        for inst in instructions:
            inst_type = inst.primitive_type
            inst_data = inst.data
            r_id = inst.reasoning_step_id
            
            # 1. Narration Speech & Pause Setup
            narr_text = inst_data.get("_narration_sentence", "") or inst_data.get("narration_anchor", "")
            if not narr_text and inst.narration_anchor:
                narr_text = inst.narration_anchor

            if narr_text:
                speech_id = make_id("speech")
                steps.append(ChoreographyStep(
                    step_id=speech_id,
                    parent_step_id=last_step_id,
                    action_type="speech",
                    payload={
                        "text": narr_text,
                        "instruction_id": inst.instruction_id
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = speech_id
                
                # Check for pauses or emphasis in narration context
                if inst_data.get("pause_after_ms"):
                    pause_id = make_id("speech_pause")
                    steps.append(ChoreographyStep(
                        step_id=pause_id,
                        parent_step_id=last_step_id,
                        action_type="speech_pause",
                        payload={"duration_ms": inst_data.get("pause_after_ms")},
                        reasoning_step_id=r_id
                    ))
                    last_step_id = pause_id

            # 2. Map primitive instructions to visual choreography steps
            # Equations
            if inst_type in [DSLPrimitiveType.EQUATION, DSLPrimitiveType.EQUATION_WRITE]:
                write_id = make_id("write_equation")
                steps.append(ChoreographyStep(
                    step_id=write_id,
                    parent_step_id=last_step_id,
                    action_type="stroke_reveal",
                    payload={
                        "latex": inst_data.get("latex", ""),
                        "equation_id": inst_data.get("equation_id") or f"eq_{uuid.uuid4().hex[:5]}",
                        "font_size": inst_data.get("font_size", 32),
                        "instruction_id": inst.instruction_id
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = write_id

            # Text / Annotations
            elif inst_type in [DSLPrimitiveType.ANNOTATION, DSLPrimitiveType.CALLOUT]:
                text_id = make_id("annotation")
                steps.append(ChoreographyStep(
                    step_id=text_id,
                    parent_step_id=last_step_id,
                    action_type="stroke_reveal",
                    payload={
                        "text": inst_data.get("text") or inst_data.get("body", ""),
                        "annotation_id": inst_data.get("annotation_id") or inst_data.get("callout_id") or f"ann_{uuid.uuid4().hex[:5]}",
                        "font_size": inst_data.get("font_size") or inst_data.get("size", 24),
                        "instruction_id": inst.instruction_id
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = text_id

            # Data structures / diagrams
            elif inst_type.value in ["binary_tree", "linked_list", "graph", "stack", "queue", "array", "heap", "hash_table", "procedural_sketch"]:
                ds_id = make_id("draw_structure")
                steps.append(ChoreographyStep(
                    step_id=ds_id,
                    parent_step_id=last_step_id,
                    action_type="stroke_reveal",
                    payload={
                        "structure_type": inst_type.value,
                        "structure_id": inst_data.get("structure_id") or f"ds_{uuid.uuid4().hex[:5]}",
                        "data": inst_data,
                        "instruction_id": inst.instruction_id
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = ds_id

            # Gesture Events
            elif inst_type == DSLPrimitiveType.TEACHER_GESTURE:
                gest_id = make_id("gesture")
                steps.append(ChoreographyStep(
                    step_id=gest_id,
                    parent_step_id=last_step_id,
                    action_type="gesture",
                    payload={
                        "gesture_id": inst_data.get("gesture_id") or f"gest_{uuid.uuid4().hex[:5]}",
                        "gesture_type": inst_data.get("gesture_type", "circle"),
                        "target_ids": inst_data.get("target_ids", []),
                        "target_region": inst_data.get("target_region"),
                        "duration_ms": inst_data.get("duration_ms", 600),
                        "emphasis": inst_data.get("emphasis", 0.7),
                        "color": inst_data.get("color", "#FFFF00")
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = gest_id

            # Highlight Events
            elif inst_type in [DSLPrimitiveType.TEACHER_HIGHLIGHT, DSLPrimitiveType.EQUATION_HIGHLIGHT]:
                hl_id = make_id("highlight")
                steps.append(ChoreographyStep(
                    step_id=hl_id,
                    parent_step_id=last_step_id,
                    action_type="highlight",
                    payload={
                        "target_ids": inst_data.get("target_ids") or [inst_data.get("equation_id")] or [],
                        "latex_substring": inst_data.get("latex_substring"),
                        "color": inst_data.get("color", "#FFFF00"),
                        "duration_ms": inst_data.get("duration_ms", 1000)
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = hl_id

            # Attention Focus Events
            elif inst_type == DSLPrimitiveType.ATTENTION_FOCUS:
                focus_start_id = make_id("focus_start")
                steps.append(ChoreographyStep(
                    step_id=focus_start_id,
                    parent_step_id=last_step_id,
                    action_type="focus_start",
                    payload={
                        "focus_id": inst_data.get("focus_id") or f"focus_{uuid.uuid4().hex[:5]}",
                        "target_ids": inst_data.get("target_ids", []),
                        "strategy": inst_data.get("strategy", "pulse"),
                        "intensity": inst_data.get("intensity", 0.7)
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = focus_start_id
                
                # Plan focus end step
                focus_end_id = make_id("focus_end")
                steps.append(ChoreographyStep(
                    step_id=focus_end_id,
                    parent_step_id=last_step_id,
                    action_type="focus_end",
                    payload={
                        "focus_id": inst_data.get("focus_id") or f"focus_{uuid.uuid4().hex[:5]}",
                        "duration_ms": inst_data.get("duration_ms", 800)
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = focus_end_id

            # Camera Movements
            elif inst_type == DSLPrimitiveType.CAMERA_MOVE:
                cam_id = make_id("camera_move")
                steps.append(ChoreographyStep(
                    step_id=cam_id,
                    parent_step_id=last_step_id,
                    action_type="camera_move",
                    payload={
                        "target": inst_data.get("target"),
                        "zoom_level": inst_data.get("zoom_level"),
                        "duration_ms": inst_data.get("duration_ms", 500)
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = cam_id

            # Simulations
            elif inst_type == DSLPrimitiveType.SIMULATION_START:
                sim_start_id = make_id("simulation_start")
                steps.append(ChoreographyStep(
                    step_id=sim_start_id,
                    parent_step_id=last_step_id,
                    action_type="simulation_start",
                    payload={
                        "simulation_id": inst_data.get("simulation_id") or f"sim_{uuid.uuid4().hex[:5]}",
                        "simulation_type": inst_data.get("simulation_type"),
                        "target_ids": inst_data.get("target_ids", []),
                        "parameters": inst_data.get("parameters", {}),
                        "duration_ms": inst_data.get("duration_ms", 5000)
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = sim_start_id

            elif inst_type == DSLPrimitiveType.SIMULATION_STEP:
                sim_step_id = make_id("simulation_update")
                steps.append(ChoreographyStep(
                    step_id=sim_step_id,
                    parent_step_id=last_step_id,
                    action_type="simulation_update",
                    payload={
                        "simulation_id": inst_data.get("simulation_id"),
                        "updates": inst_data.get("updates", {}),
                        "duration_ms": inst_data.get("duration_ms", 200)
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = sim_step_id

            # Code blocks — emitted as stroke_reveal; compiler maps to annotation event
            elif inst_type in [DSLPrimitiveType.CODE_BLOCK, DSLPrimitiveType.CODE_EXPLANATION_FLOW]:
                code_id = make_id("code_block")
                steps.append(ChoreographyStep(
                    step_id=code_id,
                    parent_step_id=last_step_id,
                    action_type="stroke_reveal",
                    payload={
                        "code": inst_data.get("code", ""),
                        "language": inst_data.get("language", "python"),
                        "structure_id": inst_data.get("code_id") or f"code_{uuid.uuid4().hex[:5]}",
                        "instruction_id": inst.instruction_id
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = code_id

            # Complexity / algorithm labels — emitted as stroke_reveal; compiler maps to annotation
            elif inst_type in [DSLPrimitiveType.COMPLEXITY_LABEL, DSLPrimitiveType.ALGORITHM_STEP]:
                lbl_id = make_id("complexity")
                steps.append(ChoreographyStep(
                    step_id=lbl_id,
                    parent_step_id=last_step_id,
                    action_type="stroke_reveal",
                    payload={
                        "text": (inst_data.get("text") or
                                 f"{inst_data.get('big_o', '')} {inst_data.get('description', '')}".strip() or
                                 inst_data.get("label", "")),
                        "annotation_id": inst_data.get("annotation_id") or f"lbl_{uuid.uuid4().hex[:5]}",
                        "font_size": inst_data.get("font_size", 24),
                        "instruction_id": inst.instruction_id
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = lbl_id

            # Pauses
            elif inst_type in [DSLPrimitiveType.COGNITIVE_PAUSE, DSLPrimitiveType.PAUSE_EMPHASIS]:
                pause_id = make_id("cursor_pause")
                steps.append(ChoreographyStep(
                    step_id=pause_id,
                    parent_step_id=last_step_id,
                    action_type="cursor_pause",
                    payload={
                        "duration_ms": inst_data.get("duration_ms", 400),
                        "reason": inst_data.get("reason", "thinking"),
                        "hesitation_strength": inst_data.get("hesitation_strength", 0.5),
                        "cursor_drift": inst_data.get("cursor_drift", True)
                    },
                    reasoning_step_id=r_id
                ))
                last_step_id = pause_id

        # Post-emit scene end
        scene_end_id = make_id("scene_end")
        steps.append(ChoreographyStep(
            step_id=scene_end_id,
            parent_step_id=last_step_id,
            action_type="scene_end",
            payload={}
        ))

        return steps

    def choreograph_ast(self, ast: Any) -> List[ChoreographyStep]:
        """
        Natively choreograph segments and reasoning steps from a TeachingAST
        instead of legacy flat DSL instructions.
        """
        steps: List[ChoreographyStep] = []
        last_step_id = None

        # Helper to generate unique step IDs
        def make_id(prefix: str) -> str:
            import uuid
            return f"ch_{prefix}_{uuid.uuid4().hex[:6]}"

        # Pre-emit scene start
        scene_start_id = make_id("scene_start")
        steps.append(ChoreographyStep(
            step_id=scene_start_id,
            parent_step_id=None,
            action_type="scene_start",
            payload={}
        ))
        last_step_id = scene_start_id

        for segment in ast.segments:
            for step in segment.reasoning_steps:
                r_id = step.step_id

                # Nib-on-word: split the narration around the phrase that
                # introduces the visual — say up to it, draw, then continue.
                anchor = step.visual.reveal_anchor if step.visual else None
                narration_before, narration_after = _split_narration_at_anchor(step.narration, anchor)

                # 1. Narration up to (and including) the introducing phrase
                if narration_before:
                    speech_id = make_id("speech")
                    steps.append(ChoreographyStep(
                        step_id=speech_id,
                        parent_step_id=last_step_id,
                        action_type="speech",
                        payload={
                            "text": narration_before,
                            "reasoning_step_id": r_id,
                        },
                        reasoning_step_id=r_id
                    ))
                    last_step_id = speech_id

                # 2. Visual — drawn the moment the introducing phrase finishes
                if step.visual:
                    vtype = step.visual.visual_type
                    vdata = step.visual.data
                    
                    if vtype in ["equation", "equation_write"]:
                        write_id = make_id("write_equation")
                        steps.append(ChoreographyStep(
                            step_id=write_id,
                            parent_step_id=last_step_id,
                            action_type="stroke_reveal",
                            payload={
                                "latex": vdata.get("latex", ""),
                                "equation_id": vdata.get("equation_id") or step.visual.board_id or f"eq_{uuid.uuid4().hex[:5]}",
                                "font_size": vdata.get("font_size", 32),
                                "instruction_id": r_id,
                                "visual_type": vtype,
                            },
                            reasoning_step_id=r_id
                        ))
                        last_step_id = write_id
                    elif vtype in ["annotation", "callout"]:
                        text_id = make_id("annotation")
                        steps.append(ChoreographyStep(
                            step_id=text_id,
                            parent_step_id=last_step_id,
                            action_type="stroke_reveal",
                            payload={
                                "text": vdata.get("text") or vdata.get("body", ""),
                                "annotation_id": vdata.get("annotation_id") or vdata.get("callout_id") or f"ann_{uuid.uuid4().hex[:5]}",
                                "font_size": vdata.get("font_size") or vdata.get("size", 24),
                                "instruction_id": r_id,
                                "visual_type": vtype,
                            },
                            reasoning_step_id=r_id
                        ))
                        last_step_id = text_id
                    elif vtype in ["binary_tree", "linked_list", "graph", "stack", "queue", "array", "heap", "hash_table", "procedural_sketch"]:
                        ds_id = make_id("draw_structure")
                        steps.append(ChoreographyStep(
                            step_id=ds_id,
                            parent_step_id=last_step_id,
                            action_type="stroke_reveal",
                            payload={
                                "structure_type": vtype,
                                "structure_id": vdata.get("structure_id") or f"ds_{uuid.uuid4().hex[:5]}",
                                "data": vdata,
                                "instruction_id": r_id,
                                "visual_type": vtype,
                            },
                            reasoning_step_id=r_id
                        ))
                        last_step_id = ds_id
                    elif vtype == "teacher_gesture":
                        gest_id = make_id("gesture")
                        steps.append(ChoreographyStep(
                            step_id=gest_id,
                            parent_step_id=last_step_id,
                            action_type="gesture",
                            payload={
                                "gesture_id": vdata.get("gesture_id") or f"gest_{uuid.uuid4().hex[:5]}",
                                "gesture_type": vdata.get("gesture_type", "circle"),
                                "target_ids": vdata.get("target_ids", []),
                                "target_region": vdata.get("target_region"),
                                "duration_ms": vdata.get("duration_ms", 600),
                                "emphasis": vdata.get("emphasis", 0.7),
                                "color": vdata.get("color", "#FFFF00"),
                                "visual_type": vtype,
                            },
                            reasoning_step_id=r_id
                        ))
                        last_step_id = gest_id
                    elif vtype in ["teacher_highlight", "equation_highlight"]:
                        hl_id = make_id("highlight")
                        steps.append(ChoreographyStep(
                            step_id=hl_id,
                            parent_step_id=last_step_id,
                            action_type="highlight",
                            payload={
                                "target_ids": vdata.get("target_ids") or [vdata.get("equation_id")] or [],
                                "latex_substring": vdata.get("latex_substring"),
                                "color": vdata.get("color", "#FFFF00"),
                                "duration_ms": vdata.get("duration_ms", 1000),
                                "visual_type": vtype,
                            },
                            reasoning_step_id=r_id
                        ))
                        last_step_id = hl_id
                    elif vtype == "attention_focus":
                        focus_start_id = make_id("focus_start")
                        steps.append(ChoreographyStep(
                            step_id=focus_start_id,
                            parent_step_id=last_step_id,
                            action_type="focus_start",
                            payload={
                                "focus_id": vdata.get("focus_id") or f"focus_{uuid.uuid4().hex[:5]}",
                                "target_ids": vdata.get("target_ids", []),
                                "strategy": vdata.get("strategy", "pulse"),
                                "intensity": vdata.get("intensity", 0.7),
                                "visual_type": vtype,
                            },
                            reasoning_step_id=r_id
                        ))
                        last_step_id = focus_start_id
                        
                        focus_end_id = make_id("focus_end")
                        steps.append(ChoreographyStep(
                            step_id=focus_end_id,
                            parent_step_id=last_step_id,
                            action_type="focus_end",
                            payload={
                                "focus_id": vdata.get("focus_id") or f"focus_{uuid.uuid4().hex[:5]}",
                                "duration_ms": vdata.get("duration_ms", 800),
                                "visual_type": vtype,
                            },
                            reasoning_step_id=r_id
                        ))
                        last_step_id = focus_end_id
                    elif vtype == "camera_move":
                        cam_id = make_id("camera_move")
                        steps.append(ChoreographyStep(
                            step_id=cam_id,
                            parent_step_id=last_step_id,
                            action_type="camera_move",
                            payload={
                                "target": vdata.get("target"),
                                "zoom_level": vdata.get("zoom_level"),
                                "duration_ms": vdata.get("duration_ms", 500),
                                "visual_type": vtype,
                            },
                            reasoning_step_id=r_id
                        ))
                        last_step_id = cam_id
                    elif vtype == "simulation_start":
                        sim_start_id = make_id("simulation_start")
                        steps.append(ChoreographyStep(
                            step_id=sim_start_id,
                            parent_step_id=last_step_id,
                            action_type="simulation_start",
                            payload={
                                "simulation_id": vdata.get("simulation_id") or f"sim_{uuid.uuid4().hex[:5]}",
                                "simulation_type": vdata.get("simulation_type"),
                                "target_ids": vdata.get("target_ids", []),
                                "parameters": vdata.get("parameters", {}),
                                "duration_ms": vdata.get("duration_ms", 5000),
                                "visual_type": vtype,
                            },
                            reasoning_step_id=r_id
                        ))
                        last_step_id = sim_start_id
                    elif vtype == "simulation_step":
                        sim_step_id = make_id("simulation_update")
                        steps.append(ChoreographyStep(
                            step_id=sim_step_id,
                            parent_step_id=last_step_id,
                            action_type="simulation_update",
                            payload={
                                "simulation_id": vdata.get("simulation_id"),
                                "updates": vdata.get("updates", {}),
                                "duration_ms": vdata.get("duration_ms", 200),
                                "visual_type": vtype,
                            },
                            reasoning_step_id=r_id
                        ))
                        last_step_id = sim_step_id
                    elif vtype in ["code_block", "code_explanation_flow"]:
                        code_id = make_id("code_block")
                        steps.append(ChoreographyStep(
                            step_id=code_id,
                            parent_step_id=last_step_id,
                            action_type="stroke_reveal",
                            payload={
                                "code": vdata.get("code", ""),
                                "language": vdata.get("language", "python"),
                                "structure_id": vdata.get("code_id") or f"code_{uuid.uuid4().hex[:5]}",
                                "instruction_id": r_id,
                                "visual_type": vtype,
                            },
                            reasoning_step_id=r_id
                        ))
                        last_step_id = code_id
                    elif vtype in ["complexity_label", "algorithm_step"]:
                        lbl_id = make_id("complexity")
                        steps.append(ChoreographyStep(
                            step_id=lbl_id,
                            parent_step_id=last_step_id,
                            action_type="stroke_reveal",
                            payload={
                                "text": (vdata.get("text") or
                                         f"{vdata.get('big_o', '')} {vdata.get('description', '')}".strip() or
                                         vdata.get("label", "")),
                                "annotation_id": vdata.get("annotation_id") or f"lbl_{uuid.uuid4().hex[:5]}",
                                "font_size": vdata.get("font_size", 24),
                                "instruction_id": r_id,
                                "visual_type": vtype,
                            },
                            reasoning_step_id=r_id
                        ))
                        last_step_id = lbl_id
                    elif vtype in ["cognitive_pause", "pause_emphasis"]:
                        pause_id = make_id("cursor_pause")
                        steps.append(ChoreographyStep(
                            step_id=pause_id,
                            parent_step_id=last_step_id,
                            action_type="cursor_pause",
                            payload={
                                "duration_ms": vdata.get("duration_ms", 400),
                                "reason": vdata.get("reason", "thinking"),
                                "hesitation_strength": vdata.get("hesitation_strength", 0.5),
                                "cursor_drift": vdata.get("cursor_drift", True),
                                "visual_type": vtype,
                            },
                            reasoning_step_id=r_id
                        ))
                        last_step_id = pause_id

                # 3. Remaining narration — the teacher keeps explaining after
                #    writing the visual (the second half of the nib-on-word split).
                if narration_after:
                    speech_after_id = make_id("speech")
                    steps.append(ChoreographyStep(
                        step_id=speech_after_id,
                        parent_step_id=last_step_id,
                        action_type="speech",
                        payload={
                            "text": narration_after,
                            "reasoning_step_id": r_id,
                        },
                        reasoning_step_id=r_id
                    ))
                    last_step_id = speech_after_id

        # Post-emit scene end
        scene_end_id = make_id("scene_end")
        steps.append(ChoreographyStep(
            step_id=scene_end_id,
            parent_step_id=last_step_id,
            action_type="scene_end",
            payload={}
        ))

        return steps

teaching_choreographer = TeachingChoreographer()


