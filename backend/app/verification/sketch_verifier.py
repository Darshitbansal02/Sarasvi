"""
sketch_verifier.py — the render-and-check loop for procedural sketches.

A procedural_sketch is geometry the LLM generated *blind* (it never sees the
canvas), so on any tier — and especially the rate-limited free tier where asking
the model to redraw is slow and often repeats the same mistake — the reliable
guarantee comes from a deterministic verify-and-repair pass at render time rather
than a costly re-plan loop.

This module runs in NORMALIZED [0,1] sketch space, BEFORE shapes are mapped into
canvas pixels by `_resolve_sketch_shapes`, and does two things:

  1. PER-SHAPE REPAIR — drop or fix geometry that can never draw correctly:
     NaN/inf coords, degenerate sizes (radius ≤ 0), too-few-point curves/polygons,
     zero-length lines/arrows, empty labels; clamp wild coordinates back on-canvas.

  2. WHOLE-SKETCH AUTO-FRAME — compute the content bounding box and, if the drawing
     is tiny, off-centre, or lop-sided, apply ONE uniform (aspect-preserving) affine
     transform to every shape so the figure fills the region with a clean margin.
     This is the deterministic answer to "the LLM placed everything in a corner":
     we re-frame it instead of re-drawing it.

`verify_and_repair_shapes` returns the repaired shapes plus a report (counts +
human-readable issues) for logging.  It never raises — a verifier that crashes a
lesson is worse than an imperfect drawing.
"""

from __future__ import annotations

import math
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Frame the content into [MARGIN, 1-MARGIN] of the region when auto-framing.
_FRAME_MARGIN = 0.08
# Only re-frame when the content is meaningfully mis-sized/off-centre, so a
# well-composed sketch is left untouched.
_REFRAME_LOW = 0.55    # content spans < 55% of a usable axis → scale up
_REFRAME_HIGH = 1.02   # content spills past the usable axis → scale down
# Never blow a tiny noisy sketch up by more than this (avoids amplifying garbage).
_MAX_UPSCALE = 2.6
# A point this far outside [0,1] is treated as a coordinate the model got wrong.
_CLAMP_LO, _CLAMP_HI = -0.25, 1.25
_SAFE_LO, _SAFE_HI = 0.02, 0.98

# Shapes whose presence makes a drawing read as a real object (a body/outline),
# as opposed to pure annotation (labels, connector lines, arrows).
_OUTLINE_TYPES = {
    "circle", "ellipse", "blob", "arc", "rect", "rectangle", "triangle",
    "diamond", "polygon", "ngon", "star", "cloud", "curve", "path",
    "freeform", "polyline", "wavy_line",
}


def _finite(*vals: Any) -> bool:
    try:
        return all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals)
    except TypeError:
        return False


def _as_xy(pt: Any) -> list[float] | None:
    if isinstance(pt, (list, tuple)) and len(pt) >= 2 and _finite(pt[0], pt[1]):
        return [float(pt[0]), float(pt[1])]
    return None


# ── Per-shape geometry accessors ──────────────────────────────────────────────
# Each returns the list of mutable coordinate refs and size fields so bounds and
# transforms can be computed uniformly without a giant per-type switch repeated
# in three places.

def _shape_points(shape: dict) -> list[list[float]]:
    """All [x,y] coordinate points a shape carries (already validated finite)."""
    pts: list[list[float]] = []
    for key in ("center", "position", "start", "end"):
        p = _as_xy(shape.get(key))
        if p:
            pts.append(p)
    for key in ("points", "vertices"):
        seq = shape.get(key)
        if isinstance(seq, (list, tuple)):
            for raw in seq:
                p = _as_xy(raw)
                if p:
                    pts.append(p)
    return pts


def _shape_extent(shape: dict) -> float:
    """Half-size of the shape around its centre, in normalized units (for bbox)."""
    cand: list[float] = []
    for key in ("radius", "r", "rx", "ry", "amplitude"):
        v = shape.get(key)
        if isinstance(v, (int, float)) and math.isfinite(v):
            cand.append(abs(float(v)))
    for key in ("width", "height"):
        v = shape.get(key)
        if isinstance(v, (int, float)) and math.isfinite(v):
            cand.append(abs(float(v)) / 2.0)
    return max(cand) if cand else 0.0


def _shape_bounds(shape: dict) -> tuple[float, float, float, float] | None:
    pts = _shape_points(shape)
    if not pts:
        return None
    ext = _shape_extent(shape)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs) - ext, min(ys) - ext, max(xs) + ext, max(ys) + ext)


# ── Per-shape repair ──────────────────────────────────────────────────────────

def _repair_shape(shape: dict, issues: list[str]) -> dict | None:
    """Return a cleaned copy of the shape, or None to drop it."""
    if not isinstance(shape, dict):
        return None
    stype = str(shape.get("type", "")).lower()
    s = dict(shape)

    # Drop shapes whose coordinates contain NaN/inf.
    for key in ("center", "position", "start", "end"):
        if key in s and _as_xy(s.get(key)) is None and s.get(key) is not None:
            issues.append(f"{stype}: bad {key} coordinate dropped")
            return None
    for key in ("points", "vertices"):
        if key in s and isinstance(s[key], (list, tuple)):
            cleaned = [p for p in (_as_xy(p) for p in s[key]) if p is not None]
            s[key] = cleaned

    # Type-specific degeneracy + size repair.
    if stype in ("circle",):
        r = s.get("radius", s.get("r"))
        if not (isinstance(r, (int, float)) and r > 1e-4):
            issues.append("circle: non-positive radius dropped")
            return None
    elif stype in ("ellipse", "blob", "cloud"):
        for k in ("rx", "ry"):
            v = s.get(k)
            if not (isinstance(v, (int, float)) and v > 1e-4):
                issues.append(f"{stype}: non-positive {k} repaired")
                s[k] = 0.06
    elif stype == "arc":
        if not any(isinstance(s.get(k), (int, float)) and s.get(k) > 1e-4
                   for k in ("radius", "r", "rx", "ry")):
            issues.append("arc: no positive radius dropped")
            return None
    elif stype in ("rect", "rectangle", "triangle", "diamond"):
        for k in ("width", "height"):
            v = s.get(k)
            if not (isinstance(v, (int, float)) and v > 1e-4):
                issues.append(f"{stype}: non-positive {k} repaired")
                s[k] = 0.1
    elif stype in ("polygon", "ngon"):
        verts = s.get("vertices")
        if isinstance(verts, list) and verts:
            if len(verts) < 3:
                issues.append("polygon: < 3 vertices dropped")
                return None
        else:  # regular n-gon
            r = s.get("radius")
            if not (isinstance(r, (int, float)) and r > 1e-4):
                issues.append("polygon: n-gon without positive radius dropped")
                return None
    elif stype == "star":
        if not any(isinstance(s.get(k), (int, float)) and s.get(k) > 1e-4
                   for k in ("radius", "rx", "ry")):
            issues.append("star: no positive radius dropped")
            return None
    elif stype in ("curve", "path", "freeform", "polyline"):
        if len(s.get("points") or []) < 2:
            issues.append(f"{stype}: < 2 points dropped")
            return None
    elif stype in ("line", "arrow", "wavy_line"):
        a, b = _as_xy(s.get("start")), _as_xy(s.get("end"))
        if a is None or b is None:
            issues.append(f"{stype}: missing endpoint dropped")
            return None
        if math.hypot(a[0] - b[0], a[1] - b[1]) < 1e-3:
            issues.append(f"{stype}: zero-length dropped")
            return None
    elif stype == "label":
        if not str(s.get("text", "")).strip():
            issues.append("label: empty text dropped")
            return None

    # Clamp coordinates that are wildly off-canvas back to a safe margin. Mild
    # overshoot (just past 0/1) is left alone — the region has bleed room and
    # clamping it would distort intended shapes.
    def _clamp_pt(p: list[float]) -> list[float]:
        nx, ny = p[0], p[1]
        if nx < _CLAMP_LO or nx > _CLAMP_HI or ny < _CLAMP_LO or ny > _CLAMP_HI:
            issues.append("coordinate clamped on-canvas")
            nx = min(_SAFE_HI, max(_SAFE_LO, nx))
            ny = min(_SAFE_HI, max(_SAFE_LO, ny))
        return [nx, ny]

    for key in ("center", "position", "start", "end"):
        if _as_xy(s.get(key)) is not None:
            s[key] = _clamp_pt([float(s[key][0]), float(s[key][1])])
    for key in ("points", "vertices"):
        if isinstance(s.get(key), list):
            s[key] = [_clamp_pt(p) for p in s[key]]

    return s


# ── Whole-sketch auto-frame ───────────────────────────────────────────────────

def _apply_transform(shape: dict, scale: float, tx: float, ty: float) -> None:
    """Uniform affine transform in-place: p' = p*scale + t; sizes *= scale."""
    def _t(p: Any) -> list[float] | None:
        xy = _as_xy(p)
        if xy is None:
            return None
        return [xy[0] * scale + tx, xy[1] * scale + ty]

    for key in ("center", "position", "start", "end"):
        if key in shape:
            np = _t(shape.get(key))
            if np:
                shape[key] = np
    for key in ("points", "vertices"):
        if isinstance(shape.get(key), list):
            shape[key] = [_t(p) or p for p in shape[key]]
    for key in ("radius", "r", "rx", "ry", "width", "height", "amplitude"):
        v = shape.get(key)
        if isinstance(v, (int, float)) and math.isfinite(v):
            shape[key] = v * scale


def _auto_frame(shapes: list[dict], issues: list[str]) -> None:
    """Re-frame the content to fill the region (aspect-preserving) when it is
    too small, too large, or off-centre. Operates in-place on normalized shapes."""
    bounds = [b for b in (_shape_bounds(s) for s in shapes) if b]
    if not bounds:
        return
    minx = min(b[0] for b in bounds)
    miny = min(b[1] for b in bounds)
    maxx = max(b[2] for b in bounds)
    maxy = max(b[3] for b in bounds)
    w = maxx - minx
    h = maxy - miny
    if w < 1e-4 or h < 1e-4:
        return

    usable = 1.0 - 2 * _FRAME_MARGIN
    span = max(w, h)
    # Already well-framed? leave it.
    if _REFRAME_LOW <= span <= _REFRAME_HIGH:
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        if abs(cx - 0.5) < 0.12 and abs(cy - 0.5) < 0.12:
            return

    scale = usable / span
    scale = min(scale, _MAX_UPSCALE)
    # Centre the content box within the region.
    new_w, new_h = w * scale, h * scale
    tx = (1.0 - new_w) / 2 - minx * scale
    ty = (1.0 - new_h) / 2 - miny * scale
    for s in shapes:
        _apply_transform(s, scale, tx, ty)
    issues.append(f"auto-framed (scale={scale:.2f})")


# ── Public entry point ────────────────────────────────────────────────────────

def verify_and_repair_shapes(
    shapes: list[dict], *, sketch_id: str = "sketch"
) -> tuple[list[dict], dict[str, Any]]:
    """Sanitize and auto-frame a procedural-sketch shape list.

    Returns (repaired_shapes, report). Never raises.
    """
    report: dict[str, Any] = {"sketch_id": sketch_id, "issues": [], "dropped": 0,
                              "in": len(shapes or []), "out": 0}
    if not isinstance(shapes, list) or not shapes:
        return ([] if not isinstance(shapes, list) else shapes), report

    issues: list[str] = report["issues"]
    repaired: list[dict] = []
    try:
        for shape in shapes:
            fixed = _repair_shape(shape, issues)
            if fixed is None:
                report["dropped"] += 1
                continue
            repaired.append(fixed)

        if repaired:
            _auto_frame(repaired, issues)

        # Structural quality signals (informational — drawing still renders).
        non_label = [s for s in repaired if str(s.get("type", "")).lower() != "label"]
        has_outline = any(
            str(s.get("type", "")).lower() in _OUTLINE_TYPES for s in non_label
        )
        if non_label and not has_outline:
            issues.append("no outline/body shape — drawing may read as loose marks")
        if 0 < len(non_label) < 2:
            issues.append("very few shapes — drawing may be too sparse")
    except Exception as exc:  # never let the verifier break a lesson
        logger.warning("sketch_verifier.error", sketch_id=sketch_id, error=str(exc))
        return shapes, report

    report["out"] = len(repaired)
    if issues or report["dropped"]:
        logger.info(
            "sketch_verifier.repaired",
            sketch_id=sketch_id,
            shapes_in=report["in"],
            shapes_out=report["out"],
            dropped=report["dropped"],
            issues=issues[:12],
        )
    return repaired, report
