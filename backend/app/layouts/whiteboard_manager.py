"""
WhiteboardManager — document-flow layout orchestrator.

Converts DSL instructions into positioned canvas shapes using a
DocumentFlowLayout cursor that flows content top-to-bottom, wraps
automatically, and advances to a new page when the current one fills.

Architecture
────────────
    DSLInstruction
        ↓
    DocumentFlowLayout.place(height, width)   ← cursor advances
        ↓
    Specific shape builder (_build_equation, _build_annotation …)
        ↓
    [shape dicts with canvas coordinates]

No coordinate is ever hardcoded here.  Every x,y comes from the
document-flow cursor or from a domain-aware layout engine
(TreeLayoutEngine, GraphLayoutEngine, etc.) whose output is then
translated by the cursor to absolute canvas position.
"""

from __future__ import annotations

import math
import uuid
import random
from typing import Any, Optional

import structlog

from app.dsl.primitives import DSLInstruction, DSLPrimitiveType
from app.layouts.document_flow import (
    DocumentFlowLayout,
    GAP_TINY, GAP_SMALL, GAP_MEDIUM, GAP_LARGE, GAP_SECTION,
    MARGIN_LEFT, MARGIN_TOP, PAGE_W, PAGE_H,
)
from app.layouts.spatial_region_manager import SpatialRegionManager, Rect
from app.layouts.topology import TopologyResolver, LayoutStrategyRegistry, TopologyType
from app.layouts.hierarchical_layout import HierarchicalLayoutStrategy
from app.layouts.sequential_layout import SequentialLayoutStrategy
from app.layouts.constraint_graph_layout import ConstraintGraphLayoutStrategy
from app.layouts.containment_layout import ContainmentLayoutStrategy
from app.layouts.vector_field_layout import VectorFieldLayoutStrategy
from app.layouts.flow_layout import FlowLayoutStrategy
from app.layouts.timeline_layout import TimelineLayoutStrategy
from app.layouts.orbital_layout import OrbitalLayoutStrategy
from app.layouts.regional_layout import RegionalLayoutStrategy
from app.world_model.adapter import LegacyAdapter
from app.scene_graph.schemas import SceneEntity, SceneRelationship, SceneAnnotation

logger = structlog.get_logger(__name__)



def _densify_path(
    path: list,
    min_points: int = 40,
    pixels_per_point: float = 4.0,
) -> list:
    """Catmull-Rom densification — same as original whiteboard_manager."""
    if not path or len(path) < 2:
        return [list(p) for p in path]

    pts = [[float(p[0]), float(p[1])] for p in path]

    arc_length = 0.0
    for i in range(len(pts) - 1):
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        arc_length += math.sqrt(dx * dx + dy * dy)

    target = max(min_points, int(arc_length / pixels_per_point) + 1)
    if len(pts) >= target:
        return pts

    padded = [pts[0]] + pts + [pts[-1]]
    result = []
    n_segs = len(pts) - 1
    pps = max(2, target // max(1, n_segs))

    for seg in range(n_segs):
        p0, p1, p2, p3 = padded[seg], padded[seg+1], padded[seg+2], padded[seg+3]
        count = pps if seg < n_segs - 1 else pps + 1
        for k in range(count):
            t  = k / pps
            t2 = t * t; t3 = t2 * t
            x  = 0.5 * ((2*p1[0]) + (-p0[0]+p2[0])*t + (2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*t2 + (-p0[0]+3*p1[0]-3*p2[0]+p3[0])*t3)
            y  = 0.5 * ((2*p1[1]) + (-p0[1]+p2[1])*t + (2*p0[1]-5*p1[1]+4*p2[1]-p3[1])*t2 + (-p0[1]+3*p1[1]-3*p2[1]+p3[1])*t3)
            result.append([x, y])

    if result and (result[-1][0] != pts[-1][0] or result[-1][1] != pts[-1][1]):
        result.append(list(pts[-1]))
    return result


class WhiteboardManager:
    """Document-flow whiteboard layout coordinator."""

    # Minimum densification points per stroke category
    _STROKE_MIN_PTS = 60
    _RECT_MIN_PTS   = 80
    _ARROW_MIN_PTS  = 50
    _TRAJ_MIN_PTS   = 80
    _SKETCH_MIN_PTS = 50

    def __init__(self) -> None:
        self._flow          = DocumentFlowLayout()
        self._region_mgr    = SpatialRegionManager()
        self._resolver      = TopologyResolver()
        self._registry      = LayoutStrategyRegistry()

        # Register strategies
        self._registry.register([TopologyType.HIERARCHICAL], "tree", HierarchicalLayoutStrategy())
        self._registry.register([TopologyType.LINEAR], "linked_list", SequentialLayoutStrategy())
        self._registry.register([TopologyType.GRAPH], "graph", ConstraintGraphLayoutStrategy())
        self._registry.register([TopologyType.GRAPH], "radial", ConstraintGraphLayoutStrategy())
        self._registry.register([TopologyType.CONTAINMENT], "nested_memory", ContainmentLayoutStrategy())
        self._registry.register([TopologyType.CONTAINMENT, TopologyType.LINEAR], "containerized_linear", ContainmentLayoutStrategy())
        self._registry.register([TopologyType.VECTOR_FIELD], "vectors", VectorFieldLayoutStrategy())
        self._registry.register([TopologyType.FLOW], "curve", FlowLayoutStrategy())
        self._registry.register([TopologyType.REGIONAL], "sketch", RegionalLayoutStrategy())

        # shape registry (id → shape) — used by _layout_equation_write
        # to look up parent equation positions, and by pointers.
        self._shapes: dict[str, dict[str, Any]] = {}

    # ── Properties forwarded from document flow ────────────────────

    @property
    def flow(self) -> DocumentFlowLayout:
        """Read-only access to the document-flow cursor (spatial authority).

        Downstream timing/reasoning code reads board state (space_state,
        utilization, content_width) through this; placement still goes via
        process_instruction / set_column on the manager.
        """
        return self._flow

    @property
    def scene_index(self) -> int:
        return self._flow.scene_index

    @scene_index.setter
    def scene_index(self, v: int) -> None:
        # Jump to page v, restoring the last known cursor on that page so doubt
        # answers append below existing content instead of writing from the top.
        if self._flow._page != v:
            self._flow.restore_page(v)

    @property
    def current_column(self) -> str:
        return self._flow.current_column

    def set_column(self, column: str) -> None:
        """Set the active column for content placement (full | left | right)."""
        self._flow.set_column(column)

    @property
    def region_manager(self) -> SpatialRegionManager:
        return self._region_mgr

    def consume_scene_transitions(self) -> list[dict[str, Any]]:
        return self._flow.consume_transitions()

    # ── Serialization (cross-generation page continuity) ────────────
    # The document-flow cursor and per-page cursor history cross request
    # boundaries. Per-page cursors are critical: without them, restore_page()
    # falls back to MARGIN_TOP and doubt/continuation content overlaps existing
    # board work by writing from y=50 on a page that already has content.
    def to_state(self) -> dict[str, Any]:
        # Always write the current page's live y into the cursor dict so that any
        # future restore_page() back to this page resumes below existing content.
        cursors = dict(self._flow._page_cursors)
        cursors[self._flow._page] = float(self._flow.current_y)
        return {
            "page":         int(self._flow._page),
            "y":            float(self._flow.current_y),
            "page_cursors": cursors,
        }

    @classmethod
    def from_state(cls, state: Optional[dict[str, Any]]) -> "WhiteboardManager":
        wb = cls()
        if state is not None:  # allow non-None empty dicts through so get() defaults apply
            try:
                wb._flow._page    = int(state.get("page", 0))
                saved_y           = float(state.get("y", MARGIN_TOP))
                wb._flow._y       = saved_y
                wb._flow._y_left  = saved_y
                wb._flow._y_right = saved_y
                raw = state.get("page_cursors") or {}
                wb._flow._page_cursors = {int(k): float(v) for k, v in raw.items()}
            except (TypeError, ValueError):
                pass
        return wb

    def configure_for_domain(self, domain: str) -> None:
        """Pure orchestrator configuration."""
        self._region_mgr.configure_for_domain(domain)
        self._flow.set_content_width(1128.0)

    # ── Main entry point ───────────────────────────────────────────

    def process_instruction(self, instruction: DSLInstruction) -> list[dict[str, Any]]:
        """
        Convert a DSL instruction into positioned canvas shapes.

        All shapes receive their (x, y) from the document-flow cursor.
        """
        if instruction.action == "delete":
            return self._handle_delete(instruction)
        if instruction.action == "clear":
            return self._handle_clear(instruction)

        handlers = {
            # ── Equations ──────────────────────────────────────────
            DSLPrimitiveType.EQUATION:               self._layout_equation,
            DSLPrimitiveType.EQUATION_WRITE:         self._layout_equation_write,
            DSLPrimitiveType.EQUATION_HIGHLIGHT:     self._layout_equation_highlight,
            # ── Text ───────────────────────────────────────────────
            DSLPrimitiveType.ANNOTATION:             self._layout_annotation,
            DSLPrimitiveType.CALLOUT:                self._layout_callout,
            # ── Code / algorithms ─────────────────────────────────
            DSLPrimitiveType.CODE_BLOCK:             self._layout_code_block,
            DSLPrimitiveType.CODE_EXPLANATION_FLOW:  self._layout_code_explanation_flow,
            DSLPrimitiveType.ALGORITHM_STEP:         self._layout_algorithm_step,
            DSLPrimitiveType.COMPLEXITY_LABEL:       self._layout_complexity_label,
            # ── Data structures ────────────────────────────────────
            DSLPrimitiveType.BINARY_TREE:            self._layout_via_strategy,
            DSLPrimitiveType.HEAP:                   self._layout_via_strategy,
            DSLPrimitiveType.LINKED_LIST:            self._layout_via_strategy,
            DSLPrimitiveType.GRAPH:                  self._layout_via_strategy,
            DSLPrimitiveType.GRAPH_FUNCTION:         self._layout_graph_function,
            DSLPrimitiveType.STACK:                  self._layout_stack_ds,
            DSLPrimitiveType.QUEUE:                  self._layout_queue,
            DSLPrimitiveType.ARRAY:                  self._layout_array,
            # ── Memory (right-column — bypass flow) ────────────────
            DSLPrimitiveType.STACK_FRAME:            self._layout_via_strategy,
            DSLPrimitiveType.HEAP_OBJECT:            self._layout_heap_object,
            DSLPrimitiveType.POINTER:                self._layout_pointer,
            # ── Domain diagrams ────────────────────────────────────
            DSLPrimitiveType.PHYSICS_DIAGRAM:        self._layout_via_strategy,
            DSLPrimitiveType.FREE_BODY_DIAGRAM:      self._layout_via_strategy,
            DSLPrimitiveType.TRAJECTORY_DIAGRAM:     self._layout_via_strategy,
            DSLPrimitiveType.MOLECULAR_GEOMETRY:     self._layout_via_strategy,
            # ── Strokes & sketches ─────────────────────────────────
            DSLPrimitiveType.DRAW_STROKE:            self._layout_draw_stroke,
            DSLPrimitiveType.STROKE_CURVE:           self._layout_stroke_curve,
            DSLPrimitiveType.PROCEDURAL_SKETCH:      self._layout_via_strategy,
        }

        handler = handlers.get(instruction.primitive_type)
        if not handler:
            logger.warning("whiteboard.unknown_primitive", type=instruction.primitive_type)
            return []

        shapes = handler(instruction)

        # Register all shapes
        for shape in shapes:
            if shape.get("action") == "delete":
                continue
            shape.setdefault("scene_index", self._flow.page)
            shape.setdefault("scene_id",    f"scene_{self._flow.page}")
            self._shapes[shape["id"]] = shape

        return shapes

    # ── Equation layout ────────────────────────────────────────────

    def _estimate_latex_text_len(self, latex: str) -> int:
        """Approximate visible character count of a LaTeX string."""
        import re
        cleaned = re.sub(r'\\[a-zA-Z]+', 'X', latex)
        cleaned = re.sub(r'[{}^_& \\]', '', cleaned)
        return len(cleaned)

    def _fit_equation_font(self, latex: str, font_size: float) -> tuple[float, float, float]:
        """
        Return (font_size, width, height) for an equation, shrinking the font
        when the natural width would exceed the usable content column so the
        equation always fits the board horizontally instead of overflowing.
        """
        max_w   = self._flow.content_width * 0.92
        n       = max(1, self._estimate_latex_text_len(latex))
        # Natural width at the requested font size.
        natural = max(350.0, n * font_size * 0.65)
        if natural > max_w:
            # Scale the font down proportionally (clamp so it stays legible).
            font_size = max(20.0, font_size * (max_w / natural))
        w = min(max(350.0, n * font_size * 0.65), max_w)
        h = self._flow.estimate_equation_height(latex, font_size)
        return font_size, w, h

    def _estimate_latex_dim(self, latex: str, font_size: float) -> tuple[float, float]:
        """Return (estimated_width, estimated_height)."""
        _, w, h = self._fit_equation_font(latex, font_size)
        return w, h

    def _layout_equation(self, instruction: DSLInstruction) -> list[dict]:
        data      = instruction.data
        latex     = data.get("latex", "")
        font_size = float(data.get("font_size", 48))
        eq_id     = data.get("equation_id") or f"eq_{uuid.uuid4().hex[:8]}"

        font_size, w, h = self._fit_equation_font(latex, font_size)
        pos  = self._flow.place(h, w, align="center", gap_after=GAP_SMALL)

        shape = {
            "id":     eq_id,
            "type":   "equation",
            "x":      pos.cx,   # renderer expects centre x for equations
            "y":      pos.cy,
            "width":  w,
            "height": h,
            "props":  {
                "latex":          latex,
                "font_size":      int(font_size),
                "total_duration_ms": instruction.duration_ms or 1500,
                "board_id":       data.get("board_id") or eq_id,
                "board_role":     data.get("board_role"),
                "write_mode":     data.get("write_mode", "create"),
                "append_latex":   data.get("append_latex"),
                "full_latex":     data.get("full_latex"),
                "parent_board_id":data.get("parent_board_id"),
                "group_id":       data.get("group_id") or data.get("board_id") or eq_id,
            },
        }
        return [shape]

    def _layout_equation_write(self, instruction: DSLInstruction) -> list[dict]:
        data      = instruction.data
        eq_id     = data.get("equation_id")
        font_size = float(data.get("font_size", 48))
        latex     = data.get("latex", "")

        parent = self._shapes.get(eq_id) if eq_id else None
        if parent:
            # Re-use parent position (this is a follow-on write to the same board)
            x, y, w, h = parent["x"], parent["y"], parent["width"], parent["height"]
            font_size = float(parent.get("props", {}).get("font_size", font_size))
        else:
            font_size, w, h = self._fit_equation_font(latex, font_size)
            pos  = self._flow.place(h, w, align="center", gap_after=GAP_SMALL)
            x, y = pos.cx, pos.cy

        data.setdefault("total_duration_ms", instruction.duration_ms or 1500)
        sid = f"{eq_id or 'eq'}_write_{uuid.uuid4().hex[:6]}"
        shape = {
            "id":     sid,
            "type":   "equation_write",
            "x":      x,
            "y":      y,
            "width":  w,
            "height": h,
            "props":  {
                **data,
                "font_size":      int(font_size),
                "board_id":       data.get("board_id") or eq_id,
                "board_role":     data.get("board_role"),
                "write_mode":     data.get("write_mode", "create"),
                "append_latex":   data.get("append_latex"),
                "full_latex":     data.get("full_latex"),
                "parent_board_id":data.get("parent_board_id"),
                "group_id":       data.get("group_id") or data.get("board_id") or eq_id,
            },
        }
        return [shape]

    def _layout_equation_highlight(self, instruction: DSLInstruction) -> list[dict]:
        data = instruction.data
        return [{
            "id":     data.get("highlight_id", f"hl_{uuid.uuid4().hex[:6]}"),
            "type":   "equation_highlight",
            "x":      0, "y": 0, "width": 0, "height": 0,
            "props":  data,
        }]

    # ── Annotation / callout ───────────────────────────────────────

    def _layout_annotation(self, instruction: DSLInstruction) -> list[dict]:
        data      = instruction.data
        text      = data.get("text", "")
        font_size = float(data.get("font_size", data.get("size", 34)))
        ann_id    = data.get("annotation_id", f"ann_{uuid.uuid4().hex[:8]}")

        h = self._flow.estimate_text_height(text, font_size)
        w = self._flow.content_width
        pos = self._flow.place(h, w, align="center", gap_after=GAP_MEDIUM)

        shape = {
            "id":     ann_id,
            "type":   "annotation",
            "x":      pos.cx,   # renderer anchors annotations at centre (anchor=0.5)
            "y":      pos.cy,
            "width":  w,
            "height": h,
            "props":  {
                "text":        text,
                "style":       data.get("style", "default"),
                "duration_ms": instruction.duration_ms or max(800, len(text) * 60),
                "color":       data.get("color"),
                "font_size":   int(font_size),
            },
        }
        return [shape]

    def _layout_callout(self, instruction: DSLInstruction) -> list[dict]:
        data  = instruction.data
        title = data.get("title", "")
        body  = data.get("body", "")
        text  = f"{title}: {body}" if body else title

        h   = self._flow.estimate_text_height(text, 20.0) + 24.0
        pos = self._flow.place(h, min(600.0, self._flow.content_width * 0.75),
                               align="left", gap_after=GAP_MEDIUM)
        return [{
            "id":     data.get("callout_id", f"callout_{uuid.uuid4().hex[:8]}"),
            "type":   "callout",
            "x":      pos.x,
            "y":      pos.y,
            "width":  pos.width,
            "height": h,
            "props":  {"title": title, "body": body,
                       "style": data.get("style", "info")},
        }]

    # ── Code and algorithm blocks ──────────────────────────────────

    def _layout_code_block(self, instruction: DSLInstruction) -> list[dict]:
        data = instruction.data
        code = data.get("code", "")
        h    = self._flow.estimate_code_height(code, font_size=18.0)
        w    = self._flow.content_width
        pos  = self._flow.place(h, w, align="left", gap_after=GAP_LARGE)
        return [{
            "id":     data.get("code_id", f"code_{uuid.uuid4().hex[:8]}"),
            "type":   "code_block",
            "x":      pos.x, "y": pos.y,
            "width":  w, "height": h,
            "props":  {
                "language":      data.get("language", "python"),
                "code":          code,
                "highlight_line":data.get("highlight_line"),
                "annotations":   data.get("annotations", {}),
            },
        }]

    def _layout_code_explanation_flow(self, instruction: DSLInstruction) -> list[dict]:
        return self._layout_code_block(instruction)

    def _layout_algorithm_step(self, instruction: DSLInstruction) -> list[dict]:
        data      = instruction.data
        text      = f"{data.get('title', 'Step')}: {data.get('explanation', '')}"
        h         = self._flow.estimate_text_height(text, 20.0) + 24.0
        w         = self._flow.content_width
        pos       = self._flow.place(h, w, align="left", gap_after=GAP_MEDIUM)
        return [{
            "id":     data.get("step_id", f"step_{uuid.uuid4().hex[:8]}"),
            "type":   "algorithm_step",
            "x":      pos.x, "y": pos.y,
            "width":  w, "height": h,
            "props":  data,
        }]

    def _layout_complexity_label(self, instruction: DSLInstruction) -> list[dict]:
        data = instruction.data
        text = f"{data.get('big_o', 'O(n)')} — {data.get('description', '')}"
        h    = self._flow.estimate_text_height(text, 20.0) + 16.0
        pos  = self._flow.place(h, min(400.0, self._flow.content_width * 0.5),
                               align="right", gap_after=GAP_SMALL)
        return [{
            "id":     data.get("label_id", f"complexity_{uuid.uuid4().hex[:8]}"),
            "type":   "complexity_label",
            "x":      pos.x, "y": pos.y,
            "width":  pos.width, "height": h,
            "props":  data,
        }]

    # ── Data structures (all horizontal or tree) ───────────────────

    def _layout_via_strategy(self, instruction: DSLInstruction) -> list[dict]:
        world_model = LegacyAdapter.adapt(instruction)
        descriptor = self._resolver.resolve(world_model)
        strategy = self._registry.resolve(descriptor)
        if not strategy:
            logger.warning("whiteboard.no_strategy_found", type=instruction.primitive_type)
            return []
            
        semantic_elements = strategy.layout(world_model, descriptor, self._flow, self._region_mgr)
        
        # Convert semantic elements to low-level rendering shapes
        shapes = []
        for element in semantic_elements:
            if isinstance(element, SceneEntity):
                if "path" in element.properties:
                    shapes.append({
                        "id": element.id,
                        "type": "draw_stroke",
                        "x": element.x,
                        "y": element.y,
                        "width": element.width,
                        "height": element.height,
                        "props": {
                            "stroke_id": f"stroke_{element.id}",
                            "path": element.properties.get("path"),
                            "color": element.properties.get("color", "#FFFFFF"),
                            "thickness": element.properties.get("thickness", 2.0),
                        }
                    })
                else:
                    shapes.append({
                        "id": element.id,
                        "type": "container" if element.semantic_role == "container" else "node",
                        "x": element.x,
                        "y": element.y,
                        "width": element.width,
                        "height": element.height,
                        "props": {
                            "label": element.label,
                            "visual_role": element.semantic_role,
                            **element.properties
                        }
                    })
            elif isinstance(element, SceneRelationship):
                if "path" in element.properties:
                    shapes.append({
                        "id": element.id,
                        "type": "draw_stroke",
                        "x": element.x,
                        "y": element.y,
                        "width": element.width,
                        "height": element.height,
                        "props": {
                            "stroke_id": f"stroke_{element.id}",
                            "path": element.properties.get("path"),
                            "color": element.properties.get("color", "#FFFFFF"),
                            "thickness": element.properties.get("thickness", 2.0),
                            "visual_role": element.semantic_role,
                        }
                    })
                    
                    tip_path = element.properties.get("tip_path")
                    if tip_path:
                        shapes.append({
                            "id": f"{element.id}_tip",
                            "type": "draw_stroke",
                            "x": element.x,
                            "y": element.y,
                            "width": element.width,
                            "height": element.height,
                            "props": {
                                "stroke_id": f"stroke_{element.id}_tip",
                                "path": tip_path,
                                "color": element.properties.get("color", "#FFFFFF"),
                                "thickness": element.properties.get("thickness", 2.0),
                                "visual_role": element.semantic_role,
                            }
                        })

                else:
                    shapes.append({
                        "id": element.id,
                        "type": "connector",
                        "x": element.x,
                        "y": element.y,
                        "width": element.width,
                        "height": element.height,
                        "props": {
                            "from_node": element.source_id,
                            "to_node": element.target_id,
                            "directed": element.properties.get("directed", False),
                            "stroke": element.properties.get("stroke", "#555"),
                            "visual_role": element.semantic_role,
                            **element.properties
                        }
                    })
            elif isinstance(element, SceneAnnotation):
                shapes.append({
                    "id": element.id,
                    "type": "annotation",
                    "x": element.x,
                    "y": element.y,
                    "width": element.width,
                    "height": element.height,
                    "props": {
                        "text": element.text,
                        "color": element.properties.get("color", "#FFFFFF"),
                        "font_size": element.properties.get("font_size", 20),
                        "duration_ms": element.properties.get("duration_ms", 1200),
                        "visual_role": element.properties.get("visual_role", "annotation"),
                        **element.properties
                    }
                })
        return shapes

    def _layout_graph_function(self, instruction: DSLInstruction) -> list[dict]:
        from app.services.graph_compiler import graph_compiler
        data     = instruction.data
        equation = data.get("equation") or data.get("latex") or "y = x"
        color    = data.get("stroke") or data.get("color") or "#00D4FF"
        gid      = data.get("function_id") or f"graph_{uuid.uuid4().hex[:8]}"

        h   = self._flow.estimate_graph_height()
        pos = self._flow.place(h, self._flow.content_width,
                               align="center", gap_after=GAP_LARGE)

        return graph_compiler.compile(
            equation=equation,
            cx=pos.cx,
            cy=pos.cy,
            color=color,
            gid=gid,
        )

    def _layout_array(self, instruction: DSLInstruction) -> list[dict]:
        data   = instruction.data
        values = data.get("values", [])
        sid    = data.get("structure_id", "array")
        h      = self._flow.estimate_array_height()
        pos    = self._flow.place(h, self._flow.content_width,
                                  align="center", gap_after=GAP_MEDIUM)
        cell_w, cell_h = 70, 60
        start_x = pos.cx - (len(values) * cell_w) / 2
        highlights = data.get("highlight_indices", [])
        shapes = []
        for i, v in enumerate(values):
            shapes.append({
                "id":     f"{sid}_cell_{i}",
                "type":   "rectangle",
                "x":      start_x + i * cell_w,
                "y":      pos.cy - cell_h / 2,
                "width":  cell_w,
                "height": cell_h,
                "props":  {
                    "text":   str(v),
                    "fill":   "#00D4FF" if i in highlights else "#1a1a2e",
                    "stroke": "#00D4FF",
                    "index":  i,
                },
            })
        return shapes

    def _layout_stack_ds(self, instruction: DSLInstruction) -> list[dict]:
        data  = instruction.data
        items = data.get("items", [])
        sid   = data.get("structure_id", "stack")
        h     = self._flow.estimate_stack_height(len(items))
        pos   = self._flow.place(h, 220.0, align="center", gap_after=GAP_LARGE)
        iw, ih = 200, 50
        shapes = []
        x = pos.cx - iw / 2
        for i, item in enumerate(reversed(items)):
            shapes.append({
                "id":     f"{sid}_item_{i}",
                "type":   "rectangle",
                "x":      x,
                "y":      pos.y + i * (ih + 5),
                "width":  iw,
                "height": ih,
                "props":  {
                    "text":   str(item),
                    "fill":   "#00D4FF" if i == 0 else "#1a1a2e",
                    "stroke": "#00D4FF",
                },
            })
        return shapes

    def _layout_queue(self, instruction: DSLInstruction) -> list[dict]:
        data  = instruction.data
        items = data.get("items", [])
        sid   = data.get("structure_id", "queue")
        h     = self._flow.estimate_array_height()
        pos   = self._flow.place(h, self._flow.content_width,
                                 align="center", gap_after=GAP_MEDIUM)
        iw, ih = 80, 60
        shapes = []
        start_x = pos.cx - (len(items) * (iw + 10)) / 2
        for i, item in enumerate(items):
            shapes.append({
                "id":     f"{sid}_item_{i}",
                "type":   "rectangle",
                "x":      start_x + i * (iw + 10),
                "y":      pos.cy - ih / 2,
                "width":  iw,
                "height": ih,
                "props":  {"text": str(item), "fill": "#1a1a2e", "stroke": "#FF6B6B"},
            })
        return shapes

    # ── Memory (bypass document flow — fixed right-column region) ──


    def _layout_heap_object(self, instruction: DSLInstruction) -> list[dict]:
        data = instruction.data
        pos  = self._region_mgr.get_next_position_in_region("HEAP_REGION", 200, 100)
        if not pos:
            pos = (2900, 2200)
        return [{
            "id":     data.get("object_id", f"heap_{uuid.uuid4().hex[:8]}"),
            "type":   "node",
            "x":      pos[0], "y": pos[1],
            "width":  200, "height": 100,
            "props":  {
                "object_type": data.get("object_type", "Object"),
                "fields":      data.get("fields", {}),
                "address":     data.get("address", ""),
                "visual_role": "entity",
            },
        }]

    def _layout_pointer(self, instruction: DSLInstruction) -> list[dict]:
        data = instruction.data
        return [{
            "id":     data.get("pointer_id", f"ptr_{uuid.uuid4().hex[:8]}"),
            "type":   "connector",
            "x":      0, "y": 0, "width": 0, "height": 0,
            "props":  {
                "source": data.get("source", ""),
                "target": data.get("target", ""),
                "label":  data.get("label", ""),
                "color":  data.get("color", "#FF6B6B"),
                "visual_role": "pointer",
            },
        }]

    # ── Domain diagrams (physics, chemistry, etc.) ─────────────────


    # ── Strokes & procedural sketches ──────────────────────────────

    def _layout_draw_stroke(self, instruction: DSLInstruction) -> list[dict]:
        data      = instruction.data
        raw_path  = data.get("path", [])
        stroke_id = data.get("stroke_id", f"stroke_{uuid.uuid4().hex[:8]}")

        # Decouple from coordinate reading; use a standard flow box size
        standalone = not data.get("_positioned_by_parent")
        if standalone:
            self._flow.place(80.0, 200.0, align="left", gap_after=GAP_SMALL)

        dense = _densify_path(raw_path, min_points=self._STROKE_MIN_PTS,
                              pixels_per_point=4.0)
        return [{
            "id":     stroke_id, "type": "stroke",
            "x":      0, "y": 0, "width": 0, "height": 0,
            "props":  {**data, "path": dense},
        }]

    def _layout_stroke_curve(self, instruction: DSLInstruction) -> list[dict]:
        data      = instruction.data
        raw_path  = data.get("path", [])
        stroke_id = data.get("stroke_id", f"curve_{uuid.uuid4().hex[:8]}")
        dense     = _densify_path(raw_path, min_points=self._STROKE_MIN_PTS,
                                  pixels_per_point=4.0)
        return [{
            "id":     stroke_id, "type": "stroke_curve",
            "x":      0, "y": 0, "width": 0, "height": 0,
            "props":  {**data, "path": dense},
        }]


    # ── Utility ────────────────────────────────────────────────────

    def get_shape(self, shape_id: str) -> Optional[dict]:
        return self._shapes.get(shape_id)

    def get_all_shapes(self) -> dict[str, dict]:
        return dict(self._shapes)

    def clear_page(self, scene_index: int) -> list[dict]:
        to_remove = [sid for sid, s in self._shapes.items()
                     if s.get("scene_index", 0) == scene_index]
        for sid in to_remove:
            self._shapes.pop(sid, None)
        return [{"id": sid, "action": "delete"} for sid in to_remove]

    def _handle_delete(self, instruction: DSLInstruction) -> list[dict]:
        sid = instruction.data.get("shape_id", "")
        self._shapes.pop(sid, None)
        return [{"id": sid, "action": "delete"}]

    def _handle_clear(self, instruction: DSLInstruction) -> list[dict]:
        page  = self._flow.page
        to_rm = [sid for sid, s in self._shapes.items()
                 if s.get("scene_index", 0) == page]
        for sid in to_rm:
            self._shapes.pop(sid, None)
        return [{"id": sid, "action": "delete"} for sid in to_rm]

    def _get_region(self, instruction: DSLInstruction, fallback: Rect) -> Rect:
        return self._region_mgr.get_region_rect(instruction.region) or fallback

    def get_camera_for_structure(self, structure_id: str) -> dict[str, float]:
        return {"x": self._flow.center_x, "y": self._flow.current_y, "zoom": 1.0}
