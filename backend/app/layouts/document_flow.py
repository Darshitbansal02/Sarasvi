"""
DocumentFlowLayout — document-based whiteboard layout engine.

The whiteboard is an infinite vertical document, not a coordinate canvas.
Content flows top-to-bottom within each page.  When a page fills, the
engine advances to the next page automatically and emits a scene-transition
event that the frontend uses to pan the camera.

Coordinate system
─────────────────
Pages are arranged horizontally: page N starts at canvas x = N × PAGE_W.
Within each page, y runs 0 (top) → PAGE_H (bottom).

Content occupies:
    x ∈ [page_offset + MARGIN_LEFT,  page_offset + MARGIN_LEFT + content_width]
    y ∈ [MARGIN_TOP,                  PAGE_H - MARGIN_BOTTOM]

Usage
─────
    flow = DocumentFlowLayout()
    flow.set_content_width(3760)        # call once per domain
    pos  = flow.place(item_h, item_w)   # allocate space, returns canvas coords
    flow.spacer(32)                     # add blank vertical space
    trans = flow.consume_transitions()  # page-break events for frontend
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any


# ── Page geometry ─────────────────────────────────────────────────
# Canvas units match the frontend board: boardWidth=1200, boardHeight=750.
# scaleX=1, scaleY=1 in PixiCanvas — 1 canvas unit = 1 screen pixel.
# Pages are arranged horizontally: page N starts at canvas x = N × PAGE_W.

PAGE_W          = 1200.0    # canvas units per page (horizontal) — matches boardWidth
PAGE_H          = 750.0     # canvas units per page (vertical)   — matches boardHeight
MARGIN_TOP      = 50.0      # large enough to clear any canvas chrome at all fitScale values
MARGIN_BOTTOM   = 25.0
MARGIN_LEFT     = 24.0
MARGIN_RIGHT    = 24.0

# Post-item vertical gaps — calibrated for the 1200×750 board.
GAP_TINY        = 6.0       # between tightly related items (e.g. eq + highlight)
GAP_SMALL       = 14.0      # between inline equations in a derivation
GAP_MEDIUM      = 24.0      # between distinct content blocks
GAP_LARGE       = 38.0      # after diagrams, code blocks, complex structures
GAP_SECTION     = 55.0      # between major lesson sections

# ── Spatial-pressure thresholds ───────────────────────────────────
# Fraction of the usable page height consumed.  These translate raw
# geometry into an abstract planning signal so that reasoning and
# choreography layers consume a high-level state ("ample" | "limited" |
# "nearly_full") instead of pixel measurements.  The layout engine stays
# the sole authority on geometry.
SPACE_LIMITED_RATIO     = 0.66   # ≥ this fraction used → "limited"
SPACE_NEARLY_FULL_RATIO = 0.85   # ≥ this fraction used → "nearly_full"


@dataclass
class Position:
    """Canvas-space position of a placed content block."""
    x:        float          # left edge (canvas absolute)
    y:        float          # top edge (canvas absolute)
    cx:       float          # horizontal centre
    cy:       float          # vertical centre
    width:    float
    height:   float
    page:     int
    scene_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "x":        self.x,
            "y":        self.y,
            "cx":       self.cx,
            "cy":       self.cy,
            "width":    self.width,
            "height":   self.height,
            "page":     self.page,
            "scene_id": self.scene_id,
        }


class DocumentFlowLayout:
    """
    Single-authority layout cursor for the Sarasvi whiteboard.

    All block-level content (equations, annotations, diagrams, code, data
    structures) flows through this engine.  Fixed-position content
    (STACK_FRAME in the right column, HEAP_OBJECT in the bottom-right
    region, POINTER arrows) bypasses the flow and uses its own layout.
    """

    def __init__(self, content_width: float = 1128.0) -> None:
        self._content_width: float    = max(300.0, content_width)
        self._page:          int      = 0
        self._y:             float    = MARGIN_TOP
        self._transitions:   list[dict[str, Any]] = []
        self._column:        str      = "full" # full | left | right
        self._y_left:        float    = MARGIN_TOP
        self._y_right:       float    = MARGIN_TOP
        # Per-page cursor memory: page_index → y at the time we left that page.
        # Populated when _advance_page() is called so that jumping back to a
        # previous page (e.g. doubt answer on a page already written) resumes at
        # the bottom of existing content rather than the top.
        self._page_cursors:  dict[int, float] = {}

    # ── Configuration ──────────────────────────────────────────────

    def set_content_width(self, width: float) -> None:
        """Set the usable horizontal width of the writing column."""
        self._content_width = max(300.0, width)

    def set_column(self, column: str) -> None:
        """
        Set the active column for content placement.
        full  — uses the entire content width
        left  — uses the left half of the content width
        right — uses the right half of the content width
        """
        if column not in ("full", "left", "right"):
            return
        
        # When switching to full, sync y to the lowest point reached in columns
        if column == "full" and self._column != "full":
            self._y = max(self._y_left, self._y_right)
        
        # When switching from full to columns, initialize column y
        if column != "full" and self._column == "full":
            self._y_left = self._y
            self._y_right = self._y

        self._column = column

    def reset(self) -> None:
        self._page = 0
        self._y    = MARGIN_TOP
        self._y_left = MARGIN_TOP
        self._y_right = MARGIN_TOP
        self._column = "full"
        self._transitions.clear()
        self._page_cursors.clear()

    def restore_page(self, page_idx: int) -> None:
        """Jump the cursor to page_idx, resuming at the last known y on that page.

        Used when generating a doubt answer on a page the student is viewing —
        content will be appended below existing material instead of overwriting
        it from y=MARGIN_TOP.
        """
        self._page_cursors[self._page] = self.current_y
        saved_y = self._page_cursors.get(page_idx, MARGIN_TOP)
        self._page    = page_idx
        self._y       = saved_y
        self._y_left  = saved_y
        self._y_right = saved_y
        self._column  = "full"

    # ── Read-only state ────────────────────────────────────────────

    @property
    def current_column(self) -> str:
        return self._column

    @property
    def page(self) -> int:
        return self._page

    @property
    def scene_index(self) -> int:
        return self._page

    @property
    def content_width(self) -> float:
        if self._column == "full":
            return self._content_width
        return (self._content_width - GAP_MEDIUM) / 2

    @property
    def center_x(self) -> float:
        """Horizontal centre of the active column on the current page."""
        ox = self._page_x_offset()
        if self._column == "full":
            return ox + MARGIN_LEFT + self._content_width / 2
        if self._column == "left":
            return ox + MARGIN_LEFT + self.content_width / 2
        # right
        return ox + MARGIN_LEFT + self.content_width + GAP_MEDIUM + self.content_width / 2

    @property
    def left_x(self) -> float:
        """Left edge of the active column on the current page."""
        ox = self._page_x_offset()
        if self._column == "left" or self._column == "full":
            return ox + MARGIN_LEFT
        # right
        return ox + MARGIN_LEFT + self.content_width + GAP_MEDIUM

    @property
    def current_y(self) -> float:
        if self._column == "left":
            return self._y_left
        if self._column == "right":
            return self._y_right
        return self._y

    @property
    def available_on_page(self) -> float:
        """Expose remaining vertical space on the current page for spatial awareness."""
        return self._available_on_page()

    @property
    def utilization(self) -> float:
        """Fraction of the usable page height already consumed (0.0–1.0)."""
        used = self.current_y - MARGIN_TOP
        return max(0.0, min(1.0, used / self._usable_height()))

    @property
    def space_state(self) -> str:
        """Abstract spatial-pressure signal: 'ample' | 'limited' | 'nearly_full'.

        Downstream reasoning/choreography layers consume this instead of raw
        pixel measurements, keeping teaching decisions decoupled from geometry.
        """
        u = self.utilization
        if u >= SPACE_NEARLY_FULL_RATIO:
            return "nearly_full"
        if u >= SPACE_LIMITED_RATIO:
            return "limited"
        return "ample"

    # ── Scene transitions ──────────────────────────────────────────

    def consume_transitions(self) -> list[dict[str, Any]]:
        """Return and clear pending page-break transition events."""
        t = list(self._transitions)
        self._transitions.clear()
        return t

    # ── Core placement ─────────────────────────────────────────────

    def place(
        self,
        item_height: float,
        item_width:  float | None = None,
        *,
        align:          str   = "center",   # center | left | right
        gap_after:      float = GAP_MEDIUM,
        force_new_page: bool  = False,
    ) -> Position:
        """
        Reserve (item_width × item_height) in document flow.

        Returns the top-left and centre canvas coordinates of the allocated
        block.  Advances the cursor.  Emits a page break if the item doesn't
        fit on the current page.

        align:
            "center" — horizontally centred in the content column
            "left"   — flush to the left margin
            "right"  — flush to the right edge of the content column
        """
        col_w = self.content_width
        if item_width is None:
            item_width = col_w

        item_height = max(1.0, item_height)
        item_width  = max(1.0, min(item_width, col_w))

        if force_new_page:
            self._advance_page()
        else:
            self._ensure_fits(item_height)

        ox = self._page_x_offset()
        base_lx = self.left_x

        if align == "center":
            lx = base_lx + (col_w - item_width) / 2
        elif align == "right":
            lx = base_lx + col_w - item_width
        else:   # left
            lx = base_lx

        curr_y = self.current_y

        pos = Position(
            x=lx,
            y=curr_y,
            cx=lx + item_width / 2,
            cy=curr_y + item_height / 2,
            width=item_width,
            height=item_height,
            page=self._page,
            scene_id=f"scene_{self._page}",
        )

        new_y = curr_y + item_height + gap_after
        if self._column == "left":
            self._y_left = new_y
        elif self._column == "right":
            self._y_right = new_y
        else:
            self._y = new_y
            
        return pos

    def spacer(self, height: float = GAP_SECTION) -> None:
        """Insert blank vertical space (e.g. between lesson sections)."""
        if self.current_y + height > PAGE_H - MARGIN_BOTTOM:
            self._advance_page()
        else:
            if self._column == "left":
                self._y_left += height
            elif self._column == "right":
                self._y_right += height
            else:
                self._y += height

    # ── Height estimators ──────────────────────────────────────────

    def estimate_equation_height(
        self, latex: str, font_size: float = 28.0
    ) -> float:
        """
        Estimate the rendered height of a LaTeX equation.

        Heuristics (conservative — we slightly over-estimate to avoid
        content hitting the bottom margin):
        - Plain inline equation: font_size × 1.25
        - One \\frac layer adds 0.45 × font_size
        - \\sqrt adds 0.2 × font_size
        - Matrix rows: rows × font_size × 1.0
        - \\sum / \\int / \\prod with limits: + 0.4 × font_size
        """
        if not latex:
            return font_size * 1.25

        scale   = 1.25
        frac_n  = latex.count("\\frac")
        scale  += frac_n * 0.45

        if "\\sqrt" in latex:
            scale += 0.2
        if re.search(r"\\begin\{[pb]?matrix\}", latex):
            rows   = max(1, latex.count("\\\\") + 1)
            scale  = max(scale, rows * 1.0)
        if re.search(r"\\(sum|int|prod|lim)", latex):
            scale += 0.4

        return max(font_size * 1.25, font_size * scale)

    def estimate_text_height(
        self, text: str, font_size: float = 22.0, padding: float = 8.0
    ) -> float:
        """
        Estimate the rendered height of a wrapped text block.

        Wrapping uses 0.55 × font_size as average character width (matches
        the Outfit sans-serif font used for annotations at typical sizes).
        """
        if not text:
            return font_size * 1.6 + padding
        chars_per_line  = max(1.0, self.content_width / (font_size * 0.55))
        n_lines         = max(1, math.ceil(len(text) / chars_per_line))
        return n_lines * font_size * 1.6 + padding

    def estimate_diagram_height(
        self, *, n_vectors: int = 3, diagram_type: str = "generic"
    ) -> float:
        """Estimate height for diagram types (physics, sketch, molecular)."""
        base = {
            "physics":   200.0 + n_vectors * 35.0,
            "fbd":       180.0 + n_vectors * 35.0,
            "molecular": 200.0,
            "trajectory":150.0,
            # Sketches are object drawings — give them a generous, roughly SQUARE
            # box (paired with a square region in RegionalLayoutStrategy) so a
            # silhouette keeps its real aspect ratio instead of being squashed into
            # a thin wide strip.
            "sketch":    440.0,
        }.get(diagram_type, 240.0)
        return min(base, self._usable_height())

    def estimate_graph_height(self) -> float:
        """Height for a graph_function plot (axes + curve + label)."""
        # GraphCompiler uses axis_units=5.5, scale=25 → axis_len = 137px.
        # Total: 2 × 137 + 60 (labels) ≈ 334px, capped at usable height.
        # GraphCompiler emits axis shapes ≈300 canvas units tall (1200-space).
        return min(300.0, self._usable_height())

    def estimate_code_height(self, code: str, font_size: float = 18.0) -> float:
        """Estimate height for a code block."""
        n_lines = max(1, code.count("\n") + 1)
        return max(160.0, n_lines * font_size * 1.5 + 40.0)

    def estimate_tree_height(self, node_count: int) -> float:
        """Estimate height for a binary tree."""
        depth = max(1, math.ceil(math.log2(max(1, node_count) + 1)))
        return min(depth * 70.0 + 30.0, self._usable_height())

    def estimate_list_height(self, node_count: int) -> float:
        """Estimate height for a linked list (horizontal layout)."""
        return 100.0   # lists are always horizontal, single-row

    def estimate_stack_height(self, item_count: int) -> float:
        """Estimate height for a vertical stack data structure."""
        return min(max(120.0, item_count * 45.0), self._usable_height())

    def estimate_array_height(self) -> float:
        """Estimate height for a horizontal array."""
        return 80.0

    # ── Internal helpers ───────────────────────────────────────────

    def _page_x_offset(self, page: int | None = None) -> float:
        return (page if page is not None else self._page) * PAGE_W

    def _usable_height(self) -> float:
        return PAGE_H - MARGIN_TOP - MARGIN_BOTTOM

    def _available_on_page(self) -> float:
        return PAGE_H - MARGIN_BOTTOM - self.current_y

    def _ensure_fits(self, item_height: float) -> None:
        """Advance to next page if item_height doesn't fit."""
        if item_height > self._available_on_page():
            self._advance_page()

    def _advance_page(self) -> None:
        # Save the cursor on the page we're leaving.
        self._page_cursors[self._page] = self.current_y
        next_page = self._page + 1
        self._page = next_page
        # If this page already has content (e.g. doubt overflow into a page that
        # the initial lesson already wrote), resume at the bottom of that content
        # instead of the top so we never overwrite existing items.
        saved_y = self._page_cursors.get(next_page, MARGIN_TOP)
        self._y       = saved_y
        self._y_left  = saved_y
        self._y_right = saved_y
        self._transitions.append({
            "scene_index": self._page,
            "scene_id":    f"scene_{self._page}",
            "camera_x":    self._page * PAGE_W,
            "label":       f"Page {self._page + 1}",
            "region":      "MAIN_VISUAL_REGION",
            "reason":      "document_overflow",
        })
