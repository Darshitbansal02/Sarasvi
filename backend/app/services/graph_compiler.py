"""
GraphCompiler — Backend curve generation for graph_function primitives.

Responsibility:
  Parse a mathematical expression, sample it, and emit universal
  draw_stroke + annotation shapes.  The frontend never evaluates math.

Architecture:
  equation string (e.g. "y = x^2")
      ↓
  parse_expression()          — safe LaTeX→Python transpilation
      ↓
  sample_curve()              — 80 points from x = -4 to +4
      ↓
  build_shapes()              — axes, ticks, curve as draw_stroke
                              — equation label as annotation
      ↓
  universal shapes returned to whiteboard_manager

Supported syntax:
  y = f(x) or bare f(x) expressions.
  Operators: +, -, *, /, ^ (→ **), parentheses.
  Functions: sin, cos, tan, sqrt, exp, log, ln, abs,
             asin, acos, atan, sinh, cosh, tanh.
  Constants: pi, e.
"""

from __future__ import annotations

import math
import re
import uuid
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ── Safe evaluation environment ──────────────────────────────────

_SAFE_ENV: dict[str, Any] = {
    # trig
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    # other
    "sqrt": math.sqrt, "abs": abs,
    "exp": math.exp, "log": math.log, "ln": math.log,
    "log10": math.log10, "log2": math.log2,
    "floor": math.floor, "ceil": math.ceil,
    # constants
    "pi": math.pi, "e": math.e,
    # builtins the evaluator needs
    "__builtins__": {},
}


def _transpile(expr: str) -> str:
    """Convert LaTeX-ish math to safe Python. Handles ^ and implicit mul."""
    # Strip "y =" prefix
    cleaned = re.sub(r"^\s*y\s*=\s*", "", expr, flags=re.IGNORECASE).strip()
    # ^ → **
    cleaned = re.sub(r"\^", "**", cleaned)
    # e^… handled by **; ln( → log(
    cleaned = re.sub(r"\bln\b", "log", cleaned)
    return cleaned


def _safe_eval(expr: str, x: float) -> float | None:
    env = {**_SAFE_ENV, "x": x}
    try:
        result = eval(compile(expr, "<graph>", "eval"), env)  # noqa: S307
        if isinstance(result, (int, float)) and math.isfinite(result):
            return float(result)
    except Exception:
        pass
    return None


# ── GraphCompiler ─────────────────────────────────────────────────


class GraphCompiler:
    """Compile a math expression into universal draw_stroke shapes."""

    # Viewport parameters (matched to graphRenderHelpers.ts scale 25 px/unit)
    SCALE: float = 25.0          # canvas pixels per math unit
    AXIS_UNITS: float = 5.5      # axis extends ±AXIS_UNITS math units
    N_SAMPLES: int = 80          # number of x samples
    X_MIN: float = -5.0
    X_MAX: float = 5.0
    Y_CLAMP: float = 5.0         # clip spikes

    def compile(
        self,
        equation: str,
        cx: float,
        cy: float,
        color: str = "#00D4FF",
        axis_color: str = "#4E5A65",
        gid: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return a list of draw_stroke + annotation shapes centered at (cx, cy).

        cx, cy are whiteboard canvas coordinates (world-space).
        """
        gid = gid or f"graph_{uuid.uuid4().hex[:8]}"
        shapes: list[dict[str, Any]] = []

        axis_len = self.AXIS_UNITS * self.SCALE

        # ── X axis ───────────────────────────────────────────────
        x_axis = self._axis_path(
            x1=cx - axis_len - 8, y1=cy,
            x2=cx + axis_len + 8, y2=cy,
        )
        shapes.append(self._stroke_shape(f"{gid}_xaxis", x_axis, axis_color, 1.5))

        # X axis arrowhead (rightward)
        shapes.append(self._stroke_shape(
            f"{gid}_xarrow",
            self._arrowhead(cx + axis_len + 8, cy, "right"),
            axis_color, 1.5,
        ))

        # ── Y axis ───────────────────────────────────────────────
        y_axis = self._axis_path(
            x1=cx, y1=cy + axis_len + 8,
            x2=cx, y2=cy - axis_len - 8,
        )
        shapes.append(self._stroke_shape(f"{gid}_yaxis", y_axis, axis_color, 1.5))

        # Y axis arrowhead (upward — canvas Y is inverted)
        shapes.append(self._stroke_shape(
            f"{gid}_yarrow",
            self._arrowhead(cx, cy - axis_len - 8, "up"),
            axis_color, 1.5,
        ))

        # ── Tick marks ────────────────────────────────────────────
        for i in range(-int(self.AXIS_UNITS), int(self.AXIS_UNITS) + 1):
            if i == 0:
                continue
            tick_x = cx + i * self.SCALE
            tick_y = cy + i * self.SCALE
            shapes.append(self._stroke_shape(
                f"{gid}_tickx_{i}",
                [[tick_x, cy - 4], [tick_x, cy + 4]],
                axis_color, 0.8,
            ))
            shapes.append(self._stroke_shape(
                f"{gid}_ticky_{i}",
                [[cx - 4, tick_y], [cx + 4, tick_y]],
                axis_color, 0.8,
            ))

        # ── Curve ─────────────────────────────────────────────────
        curve_points = self._sample(equation)
        if curve_points:
            # Split at discontinuities (large jumps)
            segments = self._split_segments(curve_points)
            for seg_idx, seg in enumerate(segments):
                if len(seg) < 2:
                    continue
                canvas_pts = [
                    [cx + px * self.SCALE, cy - py * self.SCALE]
                    for px, py in seg
                ]
                shapes.append(self._stroke_shape(
                    f"{gid}_curve_{seg_idx}",
                    canvas_pts,
                    color,
                    2.5,
                ))

        # ── Equation label ────────────────────────────────────────
        label = equation.strip()
        shapes.append({
            "id": f"{gid}_label",
            "type": "annotation",
            "x": cx + axis_len * 0.6,
            "y": cy - axis_len - 20,
            "width": 160,
            "height": 30,
            "props": {
                "text": label,
                "color": color,
                "font_size": 14,
                "duration_ms": 600,
            },
        })

        return shapes

    # ── Helpers ───────────────────────────────────────────────────

    def _sample(self, equation: str) -> list[tuple[float, float]]:
        expr = _transpile(equation)
        points: list[tuple[float, float]] = []
        for i in range(self.N_SAMPLES + 1):
            x = self.X_MIN + (self.X_MAX - self.X_MIN) * i / self.N_SAMPLES
            y = _safe_eval(expr, x)
            if y is not None:
                y = max(-self.Y_CLAMP, min(self.Y_CLAMP, y))
                points.append((x, y))
        return points

    def _split_segments(
        self, points: list[tuple[float, float]]
    ) -> list[list[tuple[float, float]]]:
        """Split the point list at large vertical jumps (discontinuities)."""
        if not points:
            return []
        threshold = self.Y_CLAMP * 1.2
        segments: list[list[tuple[float, float]]] = [[points[0]]]
        for prev, curr in zip(points, points[1:]):
            if abs(curr[1] - prev[1]) > threshold:
                segments.append([])
            segments[-1].append(curr)
        return [s for s in segments if len(s) >= 2]

    def _axis_path(
        self, x1: float, y1: float, x2: float, y2: float
    ) -> list[list[float]]:
        """Dense points along a straight axis line."""
        n = max(40, int(abs(x2 - x1 + y2 - y1) / 4))
        return [
            [x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n]
            for i in range(n + 1)
        ]

    def _arrowhead(
        self, tip_x: float, tip_y: float, direction: str
    ) -> list[list[float]]:
        """Small V-shaped arrowhead."""
        s = 6.0
        if direction == "right":
            return [
                [tip_x - s, tip_y - s * 0.5],
                [tip_x, tip_y],
                [tip_x - s, tip_y + s * 0.5],
            ]
        if direction == "up":
            return [
                [tip_x - s * 0.5, tip_y + s],
                [tip_x, tip_y],
                [tip_x + s * 0.5, tip_y + s],
            ]
        return []

    def _stroke_shape(
        self,
        sid: str,
        path: list[list[float]],
        color: str,
        thickness: float,
    ) -> dict[str, Any]:
        return {
            "id": sid,
            "type": "draw_stroke",
            "x": 0, "y": 0, "width": 0, "height": 0,
            "props": {
                "stroke_id": sid,
                "path": path,
                "color": color,
                "thickness": thickness,
            },
        }


graph_compiler = GraphCompiler()
