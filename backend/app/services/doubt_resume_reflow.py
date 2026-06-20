"""
doubt_resume_reflow — re-flow the not-yet-drawn lesson content around a doubt.

When a student interrupts a lesson with a doubt, the backend answers it (G2),
then auto-resumes the remaining original-lesson events (G3). Those remaining
events carry their ORIGINAL pre-doubt coordinates, which now collide with the
doubt answer that was just written into the same space.

This module recomputes the remaining items' positions so they flow BELOW the
doubt answer, by routing every item through the SAME DocumentFlowLayout engine
that produced the original lesson — seeded at the cursor the doubt left behind on
each page. Using the real layout authority (instead of hand-rolled per-page delta
math in the route handler) gives correct, overlap-free behaviour for:

  • vertical shift                — items move down by exactly what the doubt used
  • page cascades                 — items pushed past a page bottom flow onto the
                                    next page at that page's resume cursor
  • independent per-page cursors  — each page keeps its own resume position
  • original vertical rhythm      — inter-item gaps are preserved where sensible

Horizontal position WITHIN a page is preserved exactly, so centred equations stay
centred and diagrams keep their internal geometry; only vertical flow and page
assignment are recomputed.

This is layer-correct per CLAUDE.md: layout stays the backend's single authority,
and the frontend still renders purely from the (now-shifted) coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from app.layouts.document_flow import (
    DocumentFlowLayout,
    MARGIN_TOP,
    MARGIN_BOTTOM,
    PAGE_W,
    PAGE_H,
    GAP_TINY,
    GAP_SMALL,
    GAP_LARGE,
)

logger = structlog.get_logger(__name__)

# Equations and annotations store (x, y) as the CENTRE of the block; everything
# else stores the top-left. The reflow needs to know which so it can convert
# between centre/top consistently.
_CENTERED_TYPES = ("equation", "annotation")


@dataclass
class ReflowResult:
    """Output of reflow_remaining_assets."""
    shifts: dict[str, tuple[float, float]]   # obj_id -> (delta_x, delta_y)
    end_cursors: dict[int, float]            # page_index -> final y cursor
    max_page: int


def _orig_page(x: float) -> int:
    return int(x // PAGE_W) if x and x > 0 else 0


def _top_of(asset: dict[str, Any]) -> float:
    y = float(asset.get("y", 0.0))
    h = float(asset.get("height", 0.0))
    return y - h / 2.0 if asset.get("type") in _CENTERED_TYPES else y


def _bottom_of(asset: dict[str, Any]) -> float:
    y = float(asset.get("y", 0.0))
    h = float(asset.get("height", 0.0))
    return y + h / 2.0 if asset.get("type") in _CENTERED_TYPES else y + h


def _gap_to_next(ordered: list[dict[str, Any]], idx: int) -> float:
    """Original vertical gap to the next item when both sit on the same original
    page, clamped to sane bounds so a weird gap can't explode or collapse layout.
    Falls back to GAP_MEDIUM across page boundaries or at the tail."""
    from app.layouts.document_flow import GAP_MEDIUM, GAP_SMALL, GAP_LARGE
    if idx + 1 >= len(ordered):
        return GAP_MEDIUM
    cur = ordered[idx]
    nxt = ordered[idx + 1]
    if _orig_page(float(nxt.get("x", 0.0))) != _orig_page(float(cur.get("x", 0.0))):
        return GAP_MEDIUM
    gap = _top_of(nxt) - _bottom_of(cur)
    return max(GAP_SMALL, min(GAP_LARGE, gap))


def reflow_remaining_assets(
    assets: list[dict[str, Any]],
    post_doubt_cursors: dict[int, float],
    start_page: int,
    *,
    mutate: bool = True,
) -> ReflowResult:
    """
    Re-flow ``assets`` (the remaining, not-yet-drawn lesson items) so they appear
    below the doubt answer instead of at their original coordinates.

    Args:
        assets: layout-asset dicts, each with ``id``/``x``/``y``/``width``/
            ``height``/``type``. When ``mutate`` is True (default) each dict's
            ``x``/``y`` are updated in place to the new absolute canvas coords —
            the frontend reads these for positioning.
        post_doubt_cursors: page_index -> y the doubt answer left the cursor at.
        start_page: the page the doubt was answered on (interrupted_max_page).
        mutate: when False, ``assets`` are left untouched and only the shift map
            is returned (used by tests).

    Returns:
        ReflowResult with per-object shifts, final per-page cursors, and max page.
    """
    start_page = int(start_page)
    seeded_cursors = {int(k): float(v) for k, v in post_doubt_cursors.items()}

    valid = [a for a in assets if a.get("x") is not None and a.get("y") is not None]
    if not valid:
        end = dict(seeded_cursors) or {start_page: MARGIN_TOP}
        return ReflowResult(shifts={}, end_cursors=end, max_page=max(end.keys(), default=start_page))

    # Reading order = original (page, top-y); matches the start_ms ordering of the
    # remaining event stream and preserves the lesson's intended sequence.
    ordered = sorted(valid, key=lambda a: (_orig_page(float(a.get("x", 0.0))), _top_of(a)))

    flow = DocumentFlowLayout()
    flow._page_cursors = dict(seeded_cursors)
    flow._page = start_page
    seed_y = seeded_cursors.get(start_page, MARGIN_TOP)
    flow._y = flow._y_left = flow._y_right = seed_y
    flow._column = "full"

    usable_h = PAGE_H - MARGIN_BOTTOM - MARGIN_TOP

    shifts: dict[str, tuple[float, float]] = {}

    for idx, asset in enumerate(ordered):
        obj_id = str(asset.get("id") or "")
        x_orig = float(asset.get("x", 0.0))
        y_orig = float(asset.get("y", 0.0))
        h = max(1.0, float(asset.get("height", 0.0)))
        w = max(1.0, float(asset.get("width", 0.0)))
        centered = asset.get("type") in _CENTERED_TYPES
        op = _orig_page(x_orig)

        # Detect original column based on original horizontal center
        cx_orig = x_orig if centered else x_orig + w / 2.0
        cx_in_page = cx_orig - op * PAGE_W

        if cx_in_page < 444.0:
            col = "left"
        elif cx_in_page > 732.0:
            col = "right"
        else:
            col = "full"

        flow.set_column(col)

        gap_after = _gap_to_next(ordered, idx)

        # Clamp the height used for cursor bookkeeping so a pathologically tall
        # item can't wedge page-advance; it still renders at full size.
        place_h = min(h, usable_h)
        pos = flow.place(place_h, w, align="center", gap_after=gap_after)
        new_page = pos.page

        # Preserve horizontal-within-page; only the page offset may change.
        x_in_page = x_orig - op * PAGE_W
        new_x = new_page * PAGE_W + x_in_page

        # pos.y is the TOP of the allocated block; restore centre semantics for
        # equation/annotation so the stored coordinate keeps the same meaning.
        new_y = pos.y + (h / 2.0 if centered else 0.0)

        if obj_id:
            shifts[obj_id] = (new_x - x_orig, new_y - y_orig)

        if mutate:
            asset["x"] = new_x
            asset["y"] = new_y

    end_cursors = dict(flow._page_cursors)
    end_cursors[flow._page] = flow.current_y
    max_page = max(end_cursors.keys(), default=start_page)

    logger.info(
        "doubt_resume_reflow.completed",
        items=len(ordered),
        start_page=start_page,
        max_page=max_page,
        end_cursors={k: round(v, 1) for k, v in end_cursors.items()},
    )
    return ReflowResult(shifts=shifts, end_cursors=end_cursors, max_page=max_page)


def shift_stroke_points_in_list(strokes: list, delta_x: float, delta_y: float):
    """Shift x1, x2, y1, y2, and points list in stroke entries (modifies in place)."""
    if not isinstance(strokes, list):
        return
    for stroke in strokes:
        if isinstance(stroke, dict):
            if "x1" in stroke and delta_x != 0.0:
                stroke["x1"] = float(stroke["x1"]) + delta_x
            if "x2" in stroke and delta_x != 0.0:
                stroke["x2"] = float(stroke["x2"]) + delta_x
            if "y1" in stroke and delta_y != 0.0:
                stroke["y1"] = float(stroke["y1"]) + delta_y
            if "y2" in stroke and delta_y != 0.0:
                stroke["y2"] = float(stroke["y2"]) + delta_y
            
            points = stroke.get("points")
            if isinstance(points, list):
                new_points = []
                for pt in points:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        pt_list = list(pt)
                        pt_list[0] = float(pt_list[0]) + delta_x
                        pt_list[1] = float(pt_list[1]) + delta_y
                        new_points.append(tuple(pt_list) if isinstance(pt, tuple) else pt_list)
                    else:
                        new_points.append(pt)
                stroke["points"] = new_points


def shift_coordinates_in_payload_by_delta(payload: dict, delta_x: float, delta_y: float):
    """Shift path, position, x, y, and camera_x inside event payloads (modifies in place)."""
    if not isinstance(payload, dict):
        return
    # Shift paths (lists of coordinates, supports tuple values)
    path = payload.get("path")
    if isinstance(path, list):
        new_path = []
        for pt in path:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                new_pt = [float(pt[0]) + delta_x, float(pt[1]) + delta_y]
                new_path.append(tuple(new_pt) if isinstance(pt, tuple) else new_pt)
            elif isinstance(pt, dict):
                pt_copy = dict(pt)
                if "x" in pt_copy:
                    pt_copy["x"] = float(pt_copy["x"]) + delta_x
                if "y" in pt_copy:
                    pt_copy["y"] = float(pt_copy["y"]) + delta_y
                new_path.append(pt_copy)
            else:
                new_path.append(pt)
        payload["path"] = new_path
    # Shift annotation position
    pos = payload.get("position")
    if isinstance(pos, dict):
        if "x" in pos:
            pos["x"] = float(pos["x"]) + delta_x
        if "y" in pos:
            pos["y"] = float(pos["y"]) + delta_y
    # Shift direct x, y coordinates if present
    if "x" in payload:
        payload["x"] = float(payload["x"]) + delta_x
    if "y" in payload:
        payload["y"] = float(payload["y"]) + delta_y
    if "camera_x" in payload:
        payload["camera_x"] = float(payload["camera_x"]) + delta_x

