# presentation_compiler.py — Compiled Presentation Orchestrator
#
# v2: Real-teacher timeline behaviors:
#   • Think-before-write pauses (400-800ms cursor drift before writing)
#   • Distance-proportional cursor moves (not fixed 350ms)
#   • Speech-writing overlap (teacher talks while writing)
#   • Post-write contemplation (300-600ms after complex equations)

import math
import uuid
import structlog
from typing import Any, Dict, List, Optional
from app.layouts.whiteboard_manager import WhiteboardManager
from app.layouts.document_flow import PAGE_W, PAGE_H, GAP_MEDIUM
from app.services.glyph_compiler import compile_latex_to_layout, compile_text_to_layout
from app.services.timeline_validator import validate_timeline
from app.dsl.primitives import DSLInstruction, DSLPrimitiveType

from app.services.teaching_choreographer import teaching_choreographer
from app.services.audio_planner import audio_planner
from app.services.teacher_motion_planner import teacher_motion_planner
from app.human_stroke_engine.pen_model import PenDynamicsModel
from app.human_stroke_engine.stroke_physics import StrokePhysicsEngine

logger = structlog.get_logger(__name__)


# Segment types representing a major new teaching unit that should not be
# split across a page boundary.
_MAJOR_SEGMENT_TYPES = frozenset({"introduction", "derivation", "mental_model"})

# Horizontal auto-scaling — fit wide content inside a column.
_COLUMN_H_PADDING      = 40.0   # breathing room reserved inside the column width
_MIN_EQUATION_FONT     = 14.0
_MIN_TEXT_FONT         = 12.0
_DEFAULT_EQUATION_FONT = 32.0
_DEFAULT_TEXT_FONT     = 24.0

# Non-content primitives that carry no board geometry (skipped by the layout pass).
_NON_LAYOUT_TYPES = frozenset({
    "camera_move", "cognitive_pause", "teacher_gesture",
    "simulation_start", "simulation_step", "pause_emphasis",
    "cursor_move", "pen_state", "attention_focus", "narration_sync",
})

# Primitive types that flow through the document cursor and can therefore be
# paired side-by-side in left/right columns. Diagrams, code and data structures
# use region strategies and always take the full width.
_PAIRABLE_TYPES = frozenset({
    DSLPrimitiveType.ANNOTATION,
    DSLPrimitiveType.CALLOUT,
    DSLPrimitiveType.EQUATION,
    DSLPrimitiveType.EQUATION_WRITE,
})

# Master switch for auto two-column layout (side-by-side narrow items).
# Flip to False to fall back to single full-width flow.
_AUTO_COLUMN_ENABLED = True


def _pixel_distance(a: tuple, b: tuple) -> float:
    """Euclidean distance between two (x, y) points."""
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _cursor_move_duration_ms(distance: float) -> int:
    """Proportional cursor move duration — faster for short hops, slower for jumps.
    Real teachers don't teleport: short moves ~200ms, long jumps ~600ms."""
    if distance < 30:
        return 150
    elif distance < 150:
        return int(200 + distance * 0.8)
    elif distance < 500:
        return int(280 + distance * 0.5)
    else:
        return min(700, int(350 + distance * 0.3))


def _think_pause_ms(action_type: str, difficulty: float) -> int:
    """Pre-write thinking pause — simulates teacher looking at the board.
    Harder content = longer pause. Equations get more thinking time."""
    base = 400 if action_type == "stroke_reveal" else 250
    difficulty_bonus = int(difficulty * 400)  # 0-400ms extra for hard steps
    return min(800, base + difficulty_bonus)


def _post_write_pause_ms(is_equation: bool, stroke_count: int) -> int:
    """Post-write contemplation — teacher pauses after writing to let it sink in.
    Complex equations (many strokes) get longer pauses."""
    if not is_equation:
        return 0  # No pause after annotations
    if stroke_count > 20:
        return 600  # Complex equation — long pause
    elif stroke_count > 8:
        return 400  # Medium equation
    else:
        return 200  # Simple equation


def _paginate_timeline(
    timeline: List[Dict[str, Any]],
    layout_assets: Dict[str, Any],
    base_scene_index: int,
    page_w: float = 1200.0,
) -> List[Dict[str, Any]]:
    """
    Multi-page support. The document flow advances to a new page when content
    overflows the board height, placing later shapes at page-N coordinates
    (x ≥ N*page_w). This pass (a) inserts a scene_start event whenever the page
    increases so the frontend CREATES the new page, and (b) stamps EVERY event
    with its scene_index so the frontend assigns it to the right page — which is
    also what lets the student scroll back through earlier pages (history).
    """
    def _event_x(evt: Dict[str, Any]) -> Optional[float]:
        p = evt.get("payload") or {}
        t = evt.get("type")
        if t == "stroke_reveal":
            asset = layout_assets.get(p.get("object_id")) if isinstance(layout_assets, dict) else None
            if isinstance(asset, dict) and asset.get("x") is not None:
                return float(asset["x"])
        elif t == "draw_stroke":
            path = p.get("path") or []
            if path and len(path[0]) >= 1:
                return float(path[0][0])
        elif t == "annotation":
            pos = p.get("position") or {}
            if pos.get("x") is not None:
                return float(pos["x"])
        elif t in ("cursor_move", "camera_move"):
            path = p.get("path") or []
            if path:
                first = path[0]
                if isinstance(first, dict) and first.get("x") is not None:
                    return float(first["x"])
                if isinstance(first, (list, tuple)) and first:
                    return float(first[0])
        return None

    out: List[Dict[str, Any]] = []
    current_page = base_scene_index
    for evt in timeline:
        if evt.get("type") == "scene_start":
            current_page = (evt.get("payload") or {}).get("scene_index", current_page)
            evt.setdefault("payload", {})["scene_index"] = current_page
            out.append(evt)
            continue
        x = _event_x(evt)
        page = int(x // page_w) if x is not None else current_page
        if page < base_scene_index:
            page = current_page
        if page > current_page:
            for p in range(current_page + 1, page + 1):
                out.append({
                    "event_id": f"evt_scene_start_{uuid.uuid4().hex[:6]}",
                    "parent_event_id": None,
                    "start_ms": evt.get("start_ms", 0),
                    "type": "scene_start",
                    "payload": {
                        "scene_index": p,
                        "scene_id": f"scene_{p}",
                        "label": f"Page {p + 1}",
                        "camera_x": p * page_w,
                        "camera_y": 375,
                        "reason": "document_overflow",
                    },
                })
            current_page = page
        evt.setdefault("payload", {})["scene_index"] = page
        out.append(evt)
    return out


class PresentationCompiler:
    """
    Compiler pipeline orchestrator:
    Teaching Choreographer -> Audio Planner -> Teacher Motion Planner -> Presentation Compiler -> Timeline Validator.
    
    Produces a structured Compiled Lesson Artifact with schema version 2.0.0.
    """

    def __init__(self, whiteboard_manager: WhiteboardManager):
        self.whiteboard = whiteboard_manager
        self.scene_width = PAGE_W
        self.scene_height = PAGE_H

    # ── Layout-pass helpers ────────────────────────────────────────

    def _measure_width(self, instruction: DSLInstruction) -> float:
        """Natural rendered width of a pairable instruction at its current font."""
        data = instruction.data
        if instruction.primitive_type in (DSLPrimitiveType.EQUATION, DSLPrimitiveType.EQUATION_WRITE):
            font_sz = float(data.get("font_size", _DEFAULT_EQUATION_FONT))
            return compile_latex_to_layout(data.get("latex", ""), font_sz)["width"]
        font_sz = float(data.get("font_size", _DEFAULT_TEXT_FONT))
        return compile_text_to_layout(data.get("text", ""), font_sz)["width"]

    def _autoscale_to_column(self, instruction: DSLInstruction) -> None:
        """Shrink annotation/callout font to fit the active column width.

        Equations are intentionally excluded: whiteboard_manager._fit_equation_font
        already scales them to the active column width at placement time. Pre-scaling
        here would cause double-shrinking and make equations illegibly small.
        """
        if instruction.primitive_type not in (DSLPrimitiveType.ANNOTATION, DSLPrimitiveType.CALLOUT):
            return
        max_w = self.whiteboard.flow.content_width - _COLUMN_H_PADDING
        data = instruction.data
        font_sz = float(data.get("font_size", _DEFAULT_TEXT_FONT))
        w = compile_text_to_layout(data.get("text", ""), font_sz)["width"]
        if w > max_w:
            data["font_size"] = max(_MIN_TEXT_FONT, font_sz * (max_w / w))

    def _can_pair(self, a: DSLInstruction, b: Optional[DSLInstruction]) -> bool:
        """Whether two consecutive content items may sit side-by-side.

        Conservative on purpose: both must be narrow text/equation primitives,
        independent (b must not depend on a, preserving derivation reading
        order), from the same teaching segment, each must fit a half-width
        column, and the page must have ample room so the pair isn't split by a
        page break mid-pair.
        """
        if not _AUTO_COLUMN_ENABLED or b is None:
            return False
        if a.primitive_type not in _PAIRABLE_TYPES or b.primitive_type not in _PAIRABLE_TYPES:
            return False
        if b.depends_on and b.depends_on == a.instruction_id:
            return False
        if a.data.get("_segment_type") != b.data.get("_segment_type"):
            return False
        if self.whiteboard.flow.space_state != "ample":
            return False
        half_col = (self.whiteboard.flow.content_width - GAP_MEDIUM) / 2 - _COLUMN_H_PADDING
        if half_col <= 0:
            return False
        return self._measure_width(a) <= half_col and self._measure_width(b) <= half_col

    def _place_and_track(
        self, instruction: DSLInstruction, page_before: int,
        instruction_transitions: list, page_utilization: dict,
    ) -> None:
        """Place one instruction and record its page utilization + transitions."""
        shapes = self.whiteboard.process_instruction(instruction)
        instruction.data["_layout_shapes"] = shapes

        page_idx = self.whiteboard.scene_index
        page_utilization[page_idx] = max(
            page_utilization.get(page_idx, 0), self.whiteboard.flow.utilization * 100
        )

        transitions = self.whiteboard.consume_scene_transitions()
        if transitions:
            instruction_transitions.append({
                "instruction_id": instruction.instruction_id,
                "transitions": transitions,
                "page_before": page_before,
                "page_after": page_idx,
                "segment_type": instruction.data.get("_segment_type", "unknown"),
            })

    def compile_presentation(
        self,
        semantic_instructions: Any = None,
        explanation_text: str = "",
        scene_index: int = 0,
        student_confusion: float = 0.0,
        audio_details: Optional[List[Dict[str, Any]]] = None,
        simulation_spec: Optional[Any] = None,
        review_instructions: Optional[List[DSLInstruction]] = None,
        strategy: Optional[Any] = None,
        lineage: Optional[Dict[str, str]] = None,
        visual_spec: Optional[Any] = None,
        *,
        ast: Optional[Any] = None
    ) -> Dict[str, Any]:
        if ast is not None:
            semantic_instructions = ast
        else:
            ast = None

        if hasattr(semantic_instructions, "segments"):
            ast = semantic_instructions
            explanation_text = ast.all_narration

            # Safeguard: Ensure all reasoning step IDs are globally unique in the AST
            all_step_ids = [step.step_id for seg in ast.segments for step in seg.reasoning_steps if step.step_id]
            if len(all_step_ids) != len(set(all_step_ids)):
                seen = set()
                duplicates = [x for x in all_step_ids if x in seen or seen.add(x)]
                logger.error("duplicate_reasoning_step_id", duplicates=duplicates)
                raise AssertionError(f"TeachingAST contains duplicate reasoning step IDs: {duplicates}")

            
            if hasattr(ast, "student_profile") and ast.student_profile:
                if not strategy:
                    strategy = ast.student_profile.get("strategy")
            
            lineage = {
                "semantic_id": getattr(ast, "plan_id", ""),
                "requirements_id": getattr(ast, "skeleton_id", ""),
                "strategy_id": "",
                "representation_id": ""
            }

            mapped_instructions = []
            for segment in ast.segments:
                for step in segment.reasoning_steps:
                    if step.visual:
                        vtype = step.visual.visual_type
                        vdata = step.visual.data
                        try:
                            prim_type = DSLPrimitiveType(vtype.value if hasattr(vtype, "value") else vtype)
                        except ValueError:
                            prim_type = DSLPrimitiveType.ANNOTATION
                        
                        if prim_type in (DSLPrimitiveType.EQUATION, DSLPrimitiveType.EQUATION_WRITE):
                            if isinstance(vdata, dict):
                                latex_val = str(
                                    vdata.get("latex") or vdata.get("equation") or vdata.get("formula") or ""
                                ).strip()
                                vdata["latex"] = latex_val

                        inst = DSLInstruction(
                            instruction_id=step.step_id,
                            primitive_type=prim_type,
                            data={**vdata, "_segment_type": segment.segment_type.value},
                            depends_on=step.depends_on[0] if step.depends_on else None,
                            difficulty=step.difficulty,
                            narration_anchor=step.narration,
                            reasoning_step_id=step.step_id,
                        )
                        mapped_instructions.append(inst)
            semantic_instructions = mapped_instructions

        # 0. Merge review instructions if present (P0 Task 3)
        if review_instructions:
            semantic_instructions = review_instructions + semantic_instructions

        # Realize visual specifications to whiteboard primitives downstream in compiler (P1 Task 5)
        if visual_spec:
            rep_type = visual_spec.representation_type if hasattr(visual_spec, "representation_type") else str(visual_spec.get("representation_type", "none"))
            rep_details = visual_spec.representation_details if hasattr(visual_spec, "representation_details") else (visual_spec.get("representation_details") or {})
            
            if rep_type == "relationship_network":
                semantic_instructions.append(
                    DSLInstruction(
                        instruction_id=f"dsl_net_{uuid.uuid4().hex[:6]}",
                        primitive_type=DSLPrimitiveType.GRAPH,
                        data={
                            "structure_id": "network_1",
                            "nodes": rep_details.get("nodes", []),
                            "edges": rep_details.get("edges", []),
                            "layout_algorithm": rep_details.get("layout", "force_directed")
                        },
                        region="MAIN_VISUAL_REGION",
                        duration_ms=1500,
                    )
                )
            elif rep_type == "process_flow":
                semantic_instructions.append(
                    DSLInstruction(
                        instruction_id=f"dsl_flow_{uuid.uuid4().hex[:6]}",
                        primitive_type=DSLPrimitiveType.GRAPH,
                        data={
                            "structure_id": "flow_1",
                            "nodes": rep_details.get("nodes", []),
                            "edges": rep_details.get("edges", []),
                            "layout_algorithm": "hierarchical"
                        },
                        region="MAIN_VISUAL_REGION",
                        duration_ms=1200,
                    )
                )
            elif rep_type in ["state_evolution", "structural_sketch", "comparative_matrix"]:
                semantic_instructions.append(
                    DSLInstruction(
                        instruction_id=f"dsl_sketch_{uuid.uuid4().hex[:6]}",
                        primitive_type=DSLPrimitiveType.PROCEDURAL_SKETCH,
                        data={
                            "sketch_id": "rep_sketch_1",
                            "shapes": rep_details.get("shapes", []),
                            "region": "MAIN_VISUAL_REGION"
                        },
                        region="MAIN_VISUAL_REGION",
                        duration_ms=1200,
                    )
                )

        logger.info("compiler.start", instruction_count=len(semantic_instructions), scene_index=scene_index)
        self._emitted_shape_ids = set()

        # Process strategy for pacing and metadata (P1 Task 4)
        strategy_dict = {}
        pacing_val = "normal"
        if strategy:
            strategy_dict = strategy.model_dump() if hasattr(strategy, "model_dump") else strategy
            params = strategy_dict.get("parameters", [])
            for p in params:
                if p.get("name") == "pacing":
                    pacing_val = str(p.get("value", "normal")).lower()

        lineage_dict = lineage or {}

        # 1. Document Layout Pass (Spatial Metadata Pass & Board Space Analyzer)
        # We track physical transitions and board utilization for metadata-driven orchestration.
        instruction_transitions = []
        page_utilization = {} # scene_index -> % used

        content_instructions = [
            inst for inst in semantic_instructions
            if inst.primitive_type.value not in _NON_LAYOUT_TYPES
        ]

        idx = 0
        while idx < len(content_instructions):
            instruction = content_instructions[idx]
            seg_type = instruction.data.get("_segment_type", "unknown")

            # Record state before placement (kept across a proactive break so the
            # resulting transition metadata reflects the page actually left).
            page_before = self.whiteboard.scene_index

            # Board Space Analyzer — Proactive Transition Logic.
            # Only break proactively when the page is nearly_full (≥85% used),
            # not merely "limited" (≥66%). At 85% there is genuinely no room for
            # a major new segment; at 66% there are ~225 px remaining which is
            # enough for several items and should not be wasted.
            if seg_type in _MAJOR_SEGMENT_TYPES and self.whiteboard.flow.space_state == "nearly_full":
                logger.info("compiler.proactive_page_break",
                            segment=seg_type,
                            space_state=self.whiteboard.flow.space_state)
                self.whiteboard.flow._advance_page()

            # Auto Two-Column Pass — place two narrow, independent items
            # side-by-side, otherwise flow full-width.
            partner = content_instructions[idx + 1] if idx + 1 < len(content_instructions) else None

            if self._can_pair(instruction, partner):
                self.whiteboard.set_column("left")
                self._autoscale_to_column(instruction)
                self._place_and_track(instruction, page_before, instruction_transitions, page_utilization)

                self.whiteboard.set_column("right")
                self._autoscale_to_column(partner)
                self._place_and_track(partner, page_before, instruction_transitions, page_utilization)

                self.whiteboard.set_column("full")
                logger.info("compiler.column_pair",
                            left=instruction.instruction_id,
                            right=partner.instruction_id,
                            segment=seg_type)
                idx += 2
            else:
                self.whiteboard.set_column("full")
                self._autoscale_to_column(instruction)
                self._place_and_track(instruction, page_before, instruction_transitions, page_utilization)
                idx += 1

        # 1a. Spatial Metadata Synchronization Pass
        # No hardcoded text. Instead, we emit structured metadata and sync markers.
        for trans_info in instruction_transitions:
            inst_id = trans_info["instruction_id"]
            
            # Find the instruction and mark it for camera synchronization
            for inst in semantic_instructions:
                if inst.instruction_id == inst_id:
                    # Sync Drift Fix: Marker for choreography to wait for narration
                    inst.data["_requires_camera_block"] = True
                    inst.data["_transition_metadata"] = {
                        "type": "page_transition",
                        "from_page": trans_info["page_before"],
                        "to_page": trans_info["page_after"],
                        "reason": "document_overflow",
                        "context": trans_info["segment_type"]
                    }
                    break
            
            if ast:
                for segment in ast.segments:
                    for step in segment.reasoning_steps:
                        if step.step_id == inst_id:
                            step.visual.data["_requires_camera_block"] = True
                            step.visual.data["_transition_metadata"] = inst.data["_transition_metadata"]
                            break

        # 2. Teaching Choreography Pass
        if ast:
            choreography_steps = teaching_choreographer.choreograph_ast(ast)
        else:
            choreography_steps = teaching_choreographer.choreograph(semantic_instructions)

        timeline = []
        stroke_assets = {}
        layout_assets = {}
        audio_assets = {}
        gesture_events = []
        current_time_ms = 0
        active_speech_end_time = 0

        page_x_base = scene_index * self.scene_width
        scene_start_event_id = f"evt_scene_start_{uuid.uuid4().hex[:6]}"

        # Base cursor starting position
        last_cursor_pos = (page_x_base + 100, 375.0)

        # O(1) lookup indices for choreography step → DSLInstruction resolution.
        # The AST choreography path stamps instruction_id = reasoning_step.step_id
        # (e.g. "r1"), while the legacy DSL path stamps instruction_id = the
        # DSLInstruction's auto-generated UUID ("dsl_abc12345"). Both must resolve.
        _inst_by_instruction_id: dict[str, Any] = {
            x.instruction_id: x for x in semantic_instructions
        }
        _inst_by_reasoning_step_id: dict[str, Any] = {
            x.reasoning_step_id: x
            for x in semantic_instructions
            if x.reasoning_step_id
        }

        # Process Choreography Steps to compile flat timeline
        # Fetch the choreographer's scene_start step id
        ch_scene_start_id = choreography_steps[0].step_id if choreography_steps else None

        # Process Choreography Steps to compile flat timeline
        for step in choreography_steps:
            action_type = step.action_type
            payload = step.payload
            
            # Parent event fallback to scene start
            parent_id = step.parent_step_id if step.parent_step_id else scene_start_event_id
            if parent_id == ch_scene_start_id:
                parent_id = scene_start_event_id
            
            # Map context-based emotion
            diff = 0.5
            if semantic_instructions:
                diff = semantic_instructions[0].difficulty
            emotion_profile = teacher_motion_planner.derive_emotion_from_context(diff, action_type)
            modulators = teacher_motion_planner.get_physics_modulators(emotion_profile, pacing=pacing_val)

            # Lineage & Strategy Injector
            def inject_lineage(evt_dict, step_node=step):
                if "payload" not in evt_dict:
                    evt_dict["payload"] = {}
                evt_payload = evt_dict["payload"]
                evt_payload["semantic_id"] = lineage_dict.get("semantic_id")
                evt_payload["requirements_id"] = lineage_dict.get("requirements_id")
                evt_payload["strategy_id"] = lineage_dict.get("strategy_id")
                evt_payload["representation_id"] = lineage_dict.get("representation_id")
                evt_payload["reasoning_step_id"] = getattr(step_node, "reasoning_step_id", None) if step_node else None
                if strategy_dict:
                    evt_payload["strategy"] = strategy_dict

            # A. Scene Start/End Events
            if action_type == "scene_start":
                timeline.append({
                    "event_id": scene_start_event_id,
                    "parent_event_id": None,
                    "start_ms": current_time_ms,
                    "type": "scene_start",
                    "payload": {
                        "scene_index": scene_index,
                        "scene_id": f"scene_{scene_index}",
                        "label": f"Page {scene_index + 1}",
                        "camera_x": page_x_base,
                        "camera_y": 375,
                        "emotion_profile": emotion_profile
                    }
                })

            elif action_type == "scene_end":
                timeline.append({
                    "event_id": f"evt_scene_end_{uuid.uuid4().hex[:6]}",
                    "parent_event_id": parent_id,
                    "start_ms": current_time_ms,
                    "type": "scene_end",
                    "payload": {}
                })

            # B. Speech / Pauses
            elif action_type == "speech":
                text = payload.get("text", "")
                narr_plan = audio_planner.plan_speech_narration(text)
                narr_duration = narr_plan["total_duration_ms"]
                
                # Advance current_time_ms to clear the previous speech + concurrent visuals
                current_time_ms = max(current_time_ms, active_speech_end_time)
                
                timeline.append({
                    "event_id": step.step_id,
                    "parent_event_id": parent_id,
                    "start_ms": current_time_ms,
                    "type": "speech",
                    "payload": {
                        "text": text,
                        "duration_ms": narr_duration,
                        "words": narr_plan["speech_events"],
                        "emotion_profile": emotion_profile
                    }
                })
                # Do NOT advance current_time_ms directly; track the speech end time
                # so subsequent visual actions run concurrently with it.
                active_speech_end_time = current_time_ms + narr_duration

            elif action_type == "speech_pause":
                duration = payload.get("duration_ms", 300)
                current_time_ms = max(current_time_ms, active_speech_end_time)
                timeline.append({
                    "event_id": step.step_id,
                    "parent_event_id": parent_id,
                    "start_ms": current_time_ms,
                    "type": "speech_pause",
                    "payload": {
                        "duration_ms": duration
                    }
                })
                current_time_ms += duration
                active_speech_end_time = current_time_ms

            # C. Whiteboard Draw Elements (Stroke Reveal)
            elif action_type == "stroke_reveal":
                inst_id = payload.get("instruction_id")
                # AST choreography stamps instruction_id = reasoning_step.step_id;
                # legacy DSL choreography stamps the DSLInstruction's own UUID.
                # Check both indices so neither path silently drops visual elements.
                target_inst = (
                    _inst_by_instruction_id.get(inst_id)
                    or _inst_by_reasoning_step_id.get(inst_id)
                )
                if not target_inst:
                    continue

                inst_type = target_inst.primitive_type
                inst_data = target_inst.data

                # Refresh difficulty for THIS instruction so pacing/emotion/timing
                # reflect its actual complexity, not the first instruction's value.
                if target_inst.difficulty is not None:
                    diff = float(target_inst.difficulty)
                    emotion_profile = teacher_motion_planner.derive_emotion_from_context(diff, action_type)
                    modulators = teacher_motion_planner.get_physics_modulators(emotion_profile, pacing=pacing_val)

                # Setup default layout coordinates
                pos_x = page_x_base + 100
                pos_y = 200
                layout_shapes = inst_data.get("_layout_shapes", [])
                if layout_shapes:
                    pos_x = layout_shapes[0].get("x", pos_x)
                    pos_y = layout_shapes[0].get("y", pos_y)

                # Determine Object ID
                obj_id = (
                    payload.get("equation_id") or 
                    payload.get("annotation_id") or 
                    payload.get("structure_id") or 
                    f"obj_{uuid.uuid4().hex[:5]}"
                )

                # Fetch layout assets based on type
                width = 0.0
                height = 0.0
                glyphs = []
                construction_sequence = []
                strokes = []

                if inst_type in [DSLPrimitiveType.EQUATION, DSLPrimitiveType.EQUATION_WRITE]:
                    latex = payload.get("latex", "")
                    compiled_math = compile_latex_to_layout(latex, payload.get("font_size", 32))
                    width = compiled_math["width"]
                    height = compiled_math["height"]
                    glyphs = compiled_math["glyphs"]
                    strokes = compiled_math["strokes"]
                    construction_sequence = compiled_math.get("constructionSequence", [])

                elif inst_type in [DSLPrimitiveType.ANNOTATION, DSLPrimitiveType.CALLOUT]:
                    text = payload.get("text", "")
                    compiled_text = compile_text_to_layout(text, float(payload.get("font_size", 24)))
                    width = compiled_text["width"]
                    height = compiled_text["height"]
                    glyphs = compiled_text["glyphs"]
                    strokes = compiled_text["strokes"]
                    construction_sequence = compiled_text.get("constructionSequence", [])

                # ── Stroke physics enrichment (equations + annotations only) ─
                # 1. Hesitation micro-tremor: adds organic wobble to strokes in
                #    high-difficulty steps, simulating a teacher pausing mid-letter.
                # 2. Pressure dynamics: converts flat (x, y) paths to calligraphic
                #    (x, y, pressure, thickness) ribbons — thick downstrokes, thin
                #    upstrokes — matching real pen behaviour.
                if strokes:
                    wobble_amt = modulators.get("wobbleIntensity", 0.5) * 2.5
                    base_font_sz = float(payload.get("font_size", 32))
                    base_thick = max(2.0, base_font_sz * 0.06)
                    for s in strokes:
                        pts = s.get("points")
                        if not pts or len(pts) < 2:
                            continue
                        # Hesitation only on complex content
                        if diff > 0.55 and len(pts) >= 5:
                            target_idx = max(1, int(len(pts) * 0.35))
                            pts = StrokePhysicsEngine.simulate_hesitation(
                                list(pts), target_idx, wobble_amt
                            )
                        # Calligraphic pressure: (x, y) → (x, y, pressure, thickness)
                        dynamics = PenDynamicsModel.compute_stroke_dynamics(
                            [(pt[0], pt[1]) for pt in pts],
                            base_thickness=float(s.get("thickness", base_thick)),
                            is_diagram=False,
                        )
                        # Use lists (not tuples) so every point is a distinct
                        # Python object — shared/interned tuples confuse
                        # json.dumps circular-reference detection.
                        s["points"] = [
                            [d["x"], d["y"], d["pressure"], d["thickness"]]
                            for d in dynamics
                        ]

                # Setup layout coordinates with safe clamping
                pos_x = page_x_base + 100
                pos_y = 200
                layout_shapes = inst_data.get("_layout_shapes", [])
                if layout_shapes:
                    pos_x = layout_shapes[0].get("x", pos_x)
                    pos_y = layout_shapes[0].get("y", pos_y)

                BOARD_WIDTH = 1200
                BOARD_HEIGHT = 750
                half_w = width / 2.0
                safe_min_x = half_w + 15
                safe_max_x = BOARD_WIDTH - half_w - 15
                
                # Clamp within the shape's OWN page. Coordinates are absolute —
                # page N spans [N*1200, (N+1)*1200) — so clamping against a global
                # 0..1200 would drag any page-2+ content back onto page 0.
                if width > 0:
                    _page_of = int(pos_x // BOARD_WIDTH) if pos_x > 0 else 0
                    _page_off = _page_of * BOARD_WIDTH
                    safe_x = _page_off + max(safe_min_x, min(safe_max_x, pos_x - _page_off))
                else:
                    safe_x = pos_x
                safe_y = max(12.0, min(BOARD_HEIGHT - 12.0, pos_y)) if height > 0 else pos_y

                # Assign compiled layout assets
                if inst_type in [DSLPrimitiveType.EQUATION, DSLPrimitiveType.EQUATION_WRITE]:
                    layout_assets[obj_id] = {
                        "type": "equation",
                        "latex": payload.get("latex", ""),
                        "x": safe_x,
                        "y": safe_y,
                        "width": width,
                        "height": height,
                        "glyphs": glyphs
                    }
                    stroke_assets[obj_id] = strokes
                elif inst_type in [DSLPrimitiveType.ANNOTATION, DSLPrimitiveType.CALLOUT]:
                    layout_assets[obj_id] = {
                        "type": "annotation",
                        "text": payload.get("text", ""),
                        "x": safe_x,
                        "y": safe_y,
                        "width": width,
                        "height": height,
                        "glyphs": glyphs
                    }
                    stroke_assets[obj_id] = strokes
                else:  # Diagram types: data structures, graphs, procedural sketches
                    layout_assets[obj_id] = {
                        "type": inst_type.value,
                        "shapes": layout_shapes
                    }

                    # Emit each laid-out shape as an INDIVIDUAL renderable timeline
                    # event so the diagram actually draws. Previously the shapes were
                    # only stored in layout_assets, which the frontend never expands,
                    # so EVERY diagram (data structure, graph, procedural_sketch) was
                    # laid out but never drawn. draw_stroke + annotation both render
                    # today, so the pen traces each shape in sequence.
                    # The lead event carries the choreography step_id so later
                    # events that parent to this step (e.g. scene_end) resolve.
                    think_ms = _think_pause_ms(action_type, diff)
                    timeline.append({
                        "event_id": step.step_id,
                        "parent_event_id": parent_id,
                        "start_ms": current_time_ms,
                        "type": "cursor_pause",
                        "payload": {
                            "duration_ms": think_ms,
                            "reason": "pre_draw_thinking",
                            "hesitation_strength": min(0.8, diff + 0.2),
                            "cursor_drift": True,
                        },
                    })
                    current_time_ms += think_ms

                    for _shp in layout_shapes:
                        _props = _shp.get("props", {})
                        shape_id = _shp.get("id")
                        if shape_id:
                            if shape_id in self._emitted_shape_ids:
                                continue
                            self._emitted_shape_ids.add(shape_id)

                        if _shp.get("type") == "annotation":
                            _txt = _props.get("text", "")
                            if not _txt:
                                continue
                            _dur = int(_props.get("duration_ms", 900))
                            _cx = _shp.get("x", 0) + _shp.get("width", 0) / 2.0
                            _cy = _shp.get("y", 0) + _shp.get("height", 0) / 2.0
                            timeline.append({
                                "event_id": f"evt_dlbl_{uuid.uuid4().hex[:6]}",
                                "parent_event_id": parent_id,
                                "start_ms": current_time_ms,
                                "type": "annotation",
                                "payload": {
                                    "annotation_id": _shp.get("id"),
                                    "text": _txt,
                                    "position": {"x": _cx, "y": _cy},
                                    "color": _props.get("color", "#FFFFFF"),
                                    "font_size": _props.get("font_size", 20),
                                    "duration_ms": _dur,
                                    "scene_index": scene_index,
                                },
                            })
                            current_time_ms += int(_dur * 0.5)
                        elif _shp.get("type") in ("code_block", "code_explanation_flow"):
                            # Code blocks render as annotation (monospace text) — the
                            # frontend has no dedicated code renderer, but annotation
                            # covers all text-on-board use cases.
                            _code = _props.get("code", "")
                            _lang = _props.get("language", "")
                            _display = f"[{_lang}]\n{_code}" if _lang else _code
                            if not _display.strip():
                                continue
                            _lines = _display.strip().split("\n")
                            _dur = max(800, len(_lines) * 280)
                            _cx = _shp.get("x", 0) + _shp.get("width", 0) / 2.0
                            _cy = _shp.get("y", 0) + _shp.get("height", 0) / 2.0
                            timeline.append({
                                "event_id": f"evt_code_{uuid.uuid4().hex[:6]}",
                                "parent_event_id": parent_id,
                                "start_ms": current_time_ms,
                                "type": "annotation",
                                "payload": {
                                    "annotation_id": _shp.get("id"),
                                    "text": _display,
                                    "position": {"x": _cx, "y": _cy},
                                    "color": "#4FC3F7",
                                    "font_size": int(_props.get("font_size", 16)),
                                    "duration_ms": _dur,
                                    "scene_index": scene_index,
                                },
                            })
                            current_time_ms += int(_dur * 0.4)
                        elif _shp.get("type") in ("complexity_label", "algorithm_step"):
                            _big_o = _props.get("big_o", "")
                            _desc = _props.get("description", "")
                            _txt = (_props.get("text") or
                                    (f"{_big_o} — {_desc}".strip(" —") if _big_o or _desc else "") or
                                    _props.get("label", ""))
                            if not _txt:
                                continue
                            _dur = int(_props.get("duration_ms", 700))
                            _cx = _shp.get("x", 0) + _shp.get("width", 0) / 2.0
                            _cy = _shp.get("y", 0) + _shp.get("height", 0) / 2.0
                            timeline.append({
                                "event_id": f"evt_lbl_{uuid.uuid4().hex[:6]}",
                                "parent_event_id": parent_id,
                                "start_ms": current_time_ms,
                                "type": "annotation",
                                "payload": {
                                    "annotation_id": _shp.get("id"),
                                    "text": _txt,
                                    "position": {"x": _cx, "y": _cy},
                                    "color": "#CE93D8",
                                    "font_size": int(_props.get("font_size", 20)),
                                    "duration_ms": _dur,
                                    "scene_index": scene_index,
                                },
                            })
                            current_time_ms += int(_dur * 0.5)
                        else:  # draw_stroke / any pen shape (path is absolute, dense)
                            _path = _props.get("path", [])
                            if not _path or len(_path) < 2:
                                continue

                            # Procedural-sketch strokes are freehand teacher marks —
                            # use natural speed-sensitive pressure (is_diagram=False) so
                            # lines taper and vary in weight like a real hand.
                            # Data-structure box outlines never reach this branch (they're
                            # node/connector types), so is_diagram=False is always correct.
                            thick = float(_props.get("thickness", 2.0))
                            raw_pts = [(pt[0], pt[1]) for pt in _path]

                            # Add micro-tremor hesitation at turning points for harder concepts
                            if diff > 0.55 and len(raw_pts) >= 5:
                                target_idx = max(1, int(len(raw_pts) * 0.4))
                                wobble_amt = (diff - 0.3) * 3.0
                                raw_pts = [
                                    (p[0], p[1]) for p in
                                    StrokePhysicsEngine.simulate_hesitation(
                                        list(raw_pts), target_idx, wobble_amt
                                    )
                                ]

                            dynamics = PenDynamicsModel.compute_stroke_dynamics(
                                raw_pts,
                                base_thickness=thick,
                                is_diagram=False,
                            )
                            enriched_path = [
                                [d["x"], d["y"], d["pressure"], d["thickness"]]
                                for d in dynamics
                            ]

                            _dur = max(450, min(2500, int(len(_path) * 6)))
                            timeline.append({
                                "event_id": f"evt_dstroke_{uuid.uuid4().hex[:6]}",
                                "parent_event_id": parent_id,
                                "start_ms": current_time_ms,
                                "type": "draw_stroke",
                                "payload": {
                                    "stroke_id": _props.get("stroke_id", _shp.get("id")),
                                    "path": enriched_path,
                                    "color": _props.get("color", "#FFFFFF"),
                                    "thickness": thick,
                                    "duration_ms": _dur,
                                    "scene_index": scene_index,
                                },
                            })
                            current_time_ms += _dur

                    if layout_shapes:
                        _last_path = (layout_shapes[-1].get("props", {}) or {}).get("path")
                        if _last_path:
                            last_cursor_pos = (_last_path[-1][0], _last_path[-1][1])
                    # Diagram fully emitted as its own events — skip the
                    # equation-specific think/cursor/stroke_reveal path below.
                    continue

                # ── Think-before-write pause ──────────────────────────
                # Real teachers pause and look at the board before writing.
                think_ms = _think_pause_ms(action_type, diff)
                timeline.append({
                    "event_id": f"evt_think_{uuid.uuid4().hex[:6]}",
                    "parent_event_id": parent_id,
                    "start_ms": current_time_ms,
                    "type": "cursor_pause",
                    "payload": {
                        "duration_ms": think_ms,
                        "reason": "pre_write_thinking",
                        "hesitation_strength": min(0.8, diff + 0.2),
                        "cursor_drift": True,
                    }
                })
                current_time_ms += think_ms

                # ── Distance-proportional cursor movement ─────────────
                if strokes:
                    first_stroke = strokes[0]
                    target_start = (safe_x + first_stroke["x1"], safe_y + first_stroke["y1"])
                    move_dist = _pixel_distance(last_cursor_pos, target_start)
                    move_ms = _cursor_move_duration_ms(move_dist)
                    move_path = teacher_motion_planner.plan_cursor_move(
                        last_cursor_pos, target_start, move_ms, modulators
                    )
                    
                    timeline.append({
                        "event_id": f"evt_cursor_{uuid.uuid4().hex[:6]}",
                        "parent_event_id": parent_id,
                        "start_ms": current_time_ms,
                        "type": "cursor_move",
                        "payload": {
                            "path": move_path,
                            "duration_ms": move_ms,
                        }
                    })
                    current_time_ms += move_ms
                    last_cursor_pos = target_start

                # ── Stroke reveal with speech-writing overlap ─────────
                # Real teachers start writing while they're still talking.
                # We overlap the stroke_reveal with the preceding speech by
                # shifting start_ms back 200ms (the speech event already advanced
                # the clock, so we reclaim a small overlap window).
                is_eq = inst_type in [
                    DSLPrimitiveType.EQUATION, DSLPrimitiveType.EQUATION_WRITE
                ]
                # ~340ms per pen stroke (was 300 — felt rushed), with a floor so
                # short equations/labels still write at a legible, human pace.
                # This per-stroke time is what the _charStates schedule is built
                # from below, so it directly governs on-screen writing speed.
                reveal_duration = (
                    max(900, int(len(strokes) * 340 * modulators.get("strokeDurationMultiplier", 1.0)))
                    if strokes else 800
                )
                reveal_start = current_time_ms

                # Compute exact _charStates on the backend
                num_strokes = len(strokes)
                if num_strokes > 0:
                    stroke_lengths = []
                    for s in strokes:
                        pts = s.get("points")
                        if not pts or len(pts) < 2:
                            stroke_lengths.append(10.0)
                            continue
                        length = 0.0
                        for k in range(len(pts) - 1):
                            dx = pts[k+1][0] - pts[k][0]
                            dy = pts[k+1][1] - pts[k][1]
                            length += math.hypot(dx, dy)
                        stroke_lengths.append(max(5.0, length))
                    
                    total_length = sum(stroke_lengths) or 1.0
                    trans_dur = 0.0
                    lift_dur = 0.0
                    if num_strokes > 1:
                        trans_dur = min(reveal_duration * 0.25, (num_strokes - 1) * 80.0)
                        lift_dur = trans_dur / (num_strokes - 1)
                    draw_duration = reveal_duration - trans_dur

                    draw_order = []
                    if construction_sequence:
                        for seq_step in construction_sequence:
                            if seq_step.get("type") == "stroke" and 0 <= seq_step.get("index", -1) < num_strokes:
                                draw_order.append(seq_step["index"])
                    if not draw_order:
                        draw_order = list(range(num_strokes))

                    speech_evt = next(
                        (
                            e for e in reversed(timeline)
                            if e["type"] == "speech"
                            and e["event_id"] == parent_id
                        ),
                        None
                    )

                    actual_reveal_start = current_time_ms

                    # Gap 5 Fix: Sync Drift / Ghost Writing
                    # If this instruction triggered a page break, we MUST NOT overlap
                    # it with the previous narration. We wait for the speech to fully finish.
                    if target_inst.data.get("_requires_camera_block"):
                        actual_reveal_start = max(current_time_ms, active_speech_end_time)
                        timeline.append({
                            "event_id": f"evt_sync_block_{uuid.uuid4().hex[:6]}",
                            "parent_event_id": parent_id,
                            "start_ms": actual_reveal_start,
                            "type": "narration_block",
                            "payload": {
                                "reason": "page_transition_sync",
                                "block_until_ms": active_speech_end_time
                            }
                        })
                    elif speech_evt:
                        speech_words = speech_evt["payload"].get("words", [])

                        if speech_words:
                            speech_start = speech_evt["start_ms"]

                            speech_overlap_start = (
                                speech_start +
                                int(speech_evt["payload"]["duration_ms"] * 0.1)
                            )

                            actual_reveal_start = max(
                                current_time_ms,
                                speech_overlap_start
                            )

                    curr_stroke_ms = float(actual_reveal_start)

                    char_states = [None] * num_strokes
                    for oi, i in enumerate(draw_order):
                        stroke_draw_dur = draw_duration * (stroke_lengths[i] / total_length)
                        char_states[i] = {
                            "id": f"line_{i}",
                            "type": "stroke",
                            "startMs": int(curr_stroke_ms),
                            "endMs": int(curr_stroke_ms + stroke_draw_dur),
                            "strokeIndex": i,
                            "absoluteStartMs": int(curr_stroke_ms),
                            "absoluteEndMs": int(curr_stroke_ms + stroke_draw_dur)
                        }
                        curr_stroke_ms += stroke_draw_dur
                        if oi < len(draw_order) - 1:
                            curr_stroke_ms += lift_dur
                    
                    for i in range(num_strokes):
                        if char_states[i] is None:
                            char_states[i] = {
                                "id": f"line_{i}",
                                "type": "stroke",
                                "strokeIndex": i,
                                "startMs": int(actual_reveal_start),
                                "endMs": int(actual_reveal_start + reveal_duration),
                                "absoluteStartMs": int(actual_reveal_start),
                                "absoluteEndMs": int(actual_reveal_start + reveal_duration)
                            }

                    layout_assets[obj_id]["_revealStartMs"] = actual_reveal_start
                    layout_assets[obj_id]["_charStates"] = char_states
                    layout_assets[obj_id]["_totalTextWidth"] = width
                    layout_assets[obj_id]["_safeTextX"] = safe_x
                    layout_assets[obj_id]["_safeTextY"] = safe_y
                    layout_assets[obj_id]["_constructionSequence"] = construction_sequence
                    reveal_start = actual_reveal_start

                timeline.append({
                    "event_id": step.step_id,
                    "parent_event_id": parent_id,
                    "start_ms": actual_reveal_start,
                    "type": "stroke_reveal",
                    "payload": {
                        "object_id": obj_id,
                        "duration_ms": reveal_duration,
                        "emotion_profile": emotion_profile,
                    }
                })
                # Effective end of stroke: start + duration, minus the overlap reclaim
                current_time_ms = actual_reveal_start + reveal_duration
                
                # Update pointer to ending position
                if strokes:
                    last_stroke = strokes[-1]
                    last_cursor_pos = (safe_x + last_stroke["x2"], safe_y + last_stroke["y2"])

                # ── Post-write contemplation pause ────────────────────
                # Teacher pauses after completing a complex equation.
                post_ms = _post_write_pause_ms(is_eq, len(strokes))
                if post_ms > 0:
                    timeline.append({
                        "event_id": f"evt_contemplate_{uuid.uuid4().hex[:6]}",
                        "parent_event_id": parent_id,
                        "start_ms": current_time_ms,
                        "type": "cursor_pause",
                        "payload": {
                            "duration_ms": post_ms,
                            "reason": "post_write_contemplation",
                            "hesitation_strength": 0.3,
                            "cursor_drift": True,
                        }
                    })
                    current_time_ms += post_ms

            # D. Gestures
            elif action_type == "gesture":
                gesture_type = payload.get("gesture_type", "circle")
                target_ids = payload.get("target_ids", [])
                
                # Derive bounds based on targets
                g_bounds = {"x": page_x_base + 100, "y": 300, "width": 200, "height": 100}
                if target_ids and target_ids[0] in layout_assets:
                    target_asset = layout_assets[target_ids[0]]
                    g_bounds = {
                        "x": target_asset.get("x", g_bounds["x"]),
                        "y": target_asset.get("y", g_bounds["y"]),
                        "width": target_asset.get("width", g_bounds["width"]),
                        "height": target_asset.get("height", g_bounds["height"])
                    }
                
                # Generates the coordinate trace path on the backend
                g_path = teacher_motion_planner.plan_gesture_path(gesture_type, g_bounds)
                
                # First move cursor to start of gesture
                if g_path:
                    move_path = teacher_motion_planner.plan_cursor_move(last_cursor_pos, g_path[0], 300, modulators)
                    timeline.append({
                        "event_id": f"evt_cursor_{uuid.uuid4().hex[:6]}",
                        "parent_event_id": parent_id,
                        "start_ms": current_time_ms,
                        "type": "cursor_move",
                        "payload": {
                            "path": move_path,
                            "duration_ms": 300
                        }
                    })
                    current_time_ms += 300
                    last_cursor_pos = g_path[-1]

                timeline.append({
                    "event_id": step.step_id,
                    "parent_event_id": parent_id,
                    "start_ms": current_time_ms,
                    "type": "gesture",
                    "payload": {
                        "gesture_id": payload.get("gesture_id"),
                        "gesture_type": gesture_type,
                        "target_ids": target_ids,
                        "target_region": payload.get("target_region"),
                        "path": g_path,
                        "duration_ms": payload.get("duration_ms", 600),
                        "emphasis": payload.get("emphasis", 0.7),
                        "color": payload.get("color", "#FFFF00"),
                        "emotion_profile": emotion_profile
                    }
                })
                # Add to gesture events for dual run fallback comparisons
                gesture_events.append({
                    "gesture_id": payload.get("gesture_id"),
                    "gesture_type": gesture_type,
                    "path": g_path,
                    "duration_ms": payload.get("duration_ms", 600),
                    "start_ms": current_time_ms
                })
                current_time_ms += payload.get("duration_ms", 600)

            # E. Highlights
            elif action_type == "highlight":
                timeline.append({
                    "event_id": step.step_id,
                    "parent_event_id": parent_id,
                    "start_ms": current_time_ms,
                    "type": "highlight",
                    "payload": {
                        "target_ids": payload.get("target_ids", []),
                        "latex_substring": payload.get("latex_substring"),
                        "color": payload.get("color", "#FFFF00"),
                        "duration_ms": payload.get("duration_ms", 1000)
                    }
                })
                current_time_ms += payload.get("duration_ms", 1000)

            # F. Focus / Camera
            elif action_type in ["focus_start", "focus_end"]:
                timeline.append({
                    "event_id": step.step_id,
                    "parent_event_id": parent_id,
                    "start_ms": current_time_ms,
                    "type": action_type,
                    "payload": payload
                })
                if action_type == "focus_end":
                    current_time_ms += payload.get("duration_ms", 800)

            elif action_type == "camera_move":
                target = payload.get("target")
                cam_duration = payload.get("duration_ms", 500)
                
                target_pos = (page_x_base + 600, 375)
                if target and target in layout_assets:
                    target_asset = layout_assets[target]
                    target_pos = (target_asset.get("x", target_pos[0]), target_asset.get("y", target_pos[1]))
                
                cam_path = teacher_motion_planner.plan_camera_panning(last_cursor_pos, target_pos, cam_duration)
                
                timeline.append({
                    "event_id": step.step_id,
                    "parent_event_id": parent_id,
                    "start_ms": current_time_ms,
                    "type": "camera_move",
                    "payload": {
                        "path": cam_path,
                        "duration_ms": cam_duration,
                        "zoom_level": payload.get("zoom_level", 1.0)
                    }
                })
                current_time_ms += cam_duration

            # G. Simulations
            elif action_type == "simulation_start":
                timeline.append({
                    "event_id": step.step_id,
                    "parent_event_id": parent_id,
                    "start_ms": current_time_ms,
                    "type": "simulation_start",
                    "payload": {
                        **payload,
                        "simulation_specification": simulation_spec.model_dump() if (simulation_spec and hasattr(simulation_spec, "model_dump")) else simulation_spec
                    }
                })
                current_time_ms += payload.get("duration_ms", 5000)

            elif action_type == "simulation_update":
                timeline.append({
                    "event_id": step.step_id,
                    "parent_event_id": parent_id,
                    "start_ms": current_time_ms,
                    "type": "simulation_update",
                    "payload": payload
                })
                current_time_ms += payload.get("duration_ms", 200)

            # H. Pauses
            elif action_type == "cursor_pause":
                duration = payload.get("duration_ms", 400)
                timeline.append({
                    "event_id": step.step_id,
                    "parent_event_id": parent_id,
                    "start_ms": current_time_ms,
                    "type": "cursor_pause",
                    "payload": payload
                })
                current_time_ms += duration

        current_time_ms = max(current_time_ms, active_speech_end_time)

        # Enrich timeline with lineage & strategy parameters (P1 Task 6)
        for evt in timeline:
            step_id = evt.get("event_id")
            matching_step = next((s for s in choreography_steps if s.step_id == step_id), None)
            
            if "payload" not in evt:
                evt["payload"] = {}
            evt_payload = evt["payload"]
            evt_payload["semantic_id"] = lineage_dict.get("semantic_id")
            evt_payload["requirements_id"] = lineage_dict.get("requirements_id")
            evt_payload["strategy_id"] = lineage_dict.get("strategy_id")
            evt_payload["representation_id"] = lineage_dict.get("representation_id")
            
            if matching_step and matching_step.reasoning_step_id:
                evt_payload["reasoning_step_id"] = matching_step.reasoning_step_id
            elif "reasoning_step_id" not in evt_payload:
                parent_id = evt.get("parent_event_id")
                parent_step = next((s for s in choreography_steps if s.step_id == parent_id), None)
                if parent_step and parent_step.reasoning_step_id:
                    evt_payload["reasoning_step_id"] = parent_step.reasoning_step_id
                    
            if strategy_dict:
                evt_payload["strategy"] = strategy_dict

        # Multi-page: insert scene_start per overflow page + stamp scene_index so
        # the board flows onto new pages and earlier pages remain browsable.
        timeline = _paginate_timeline(timeline, layout_assets, scene_index)

        # Validate final timeline schema — pass layout_assets so the orphan-equation
        # check can verify every compiled equation has a stroke_reveal event.
        validate_timeline(timeline, layout_assets=layout_assets)

        compiled_artifact = {
            "version": "2.0.0",
            "timeline": timeline,
            "stroke_assets": stroke_assets,
            "layout_assets": layout_assets,
            "audio_assets": audio_assets,
            "compiled_instructions": semantic_instructions,
            "emotion_profile": {
                "difficulty": diff,
                "overall_confusion": student_confusion
            },
            "gesture_events": gesture_events,
            "metadata": {
                "total_duration_ms": current_time_ms,
                "scene_index": scene_index,
                "spatial_analysis": {
                    "page_utilization": page_utilization,
                    "horizontal_auto_scaled": True
                }
            }
        }

        # Float Normalization (P2 Task 8)
        # Optimized in-place version to prevent copy/alloc overhead and deep recursion, with cycle detection.
        def round_floats(obj, visited=None):
            if visited is None:
                visited = set()
            
            obj_id = id(obj)
            if obj_id in visited:
                return obj
            visited.add(obj_id)

            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, float):
                        obj[k] = round(v, 4)
                    elif isinstance(v, (dict, list)):
                        round_floats(v, visited)
            elif isinstance(obj, list):
                for i, x in enumerate(obj):
                    if isinstance(x, float):
                        obj[i] = round(x, 4)
                    elif isinstance(x, (dict, list)):
                        round_floats(x, visited)
            return obj

        compiled_artifact = round_floats(compiled_artifact)
        
        logger.info("compiler.success", duration=current_time_ms)
        return compiled_artifact
