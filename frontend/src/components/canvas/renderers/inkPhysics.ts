/**
 * inkPhysics.ts — Handwriting and stroke rendering helpers for Pixi canvas.
 *
 * Extracted from PixiCanvas so live writing physics and stroke visualization
 * can evolve independently from scene orchestration.
 *
 * The ribbon renderer builds a true variable-width polygon (left offsets +
 * right offsets reversed) with rounded semicircle end caps, rather than a
 * series of independent line-segment strokes.  This eliminates the "bead"
 * artifact at segment joints and gives smooth, continuous width variation.
 */

import * as PIXI from "pixi.js";

export interface InkPhysicsOptions {
  baseWidth?: number;
  color?: number;
  alpha?: number;
  pressures?: number[] | null;
  widths?: number[] | null;
  taperStart?: number;
  taperEnd?: number;
  spacing?: number;
  velocityDamping?: number;
  wobbleAmount?: number;
}

function resolveHexColor(colorStr: string | number | null | undefined, defaultColor: number = 0xffffff): number {
  if (colorStr === null || colorStr === undefined) return defaultColor;
  if (typeof colorStr === "number") {
    return (Number.isFinite(colorStr) && !Number.isNaN(colorStr)) ? colorStr : defaultColor;
  }

  const palette: Record<string, number> = {
    silver: 0xE0E6ED,
    blue: 0x82AAFF,
    cyan: 0x00D4FF,
    amber: 0xFFAD60,
    coral: 0xFF6B6B,
    grey: 0x4E5A65,
    orange: 0xf59e0b,
    green: 0x22c55e,
    red: 0xef4444,
  };

  const normalized = String(colorStr).toLowerCase().trim();
  if (palette[normalized] !== undefined) return palette[normalized];

  if (normalized.startsWith("#")) {
    const val = parseInt(normalized.replace("#", "0x"), 16);
    return Number.isNaN(val) ? defaultColor : val;
  }
  if (normalized.startsWith("0x")) {
    const val = parseInt(normalized, 16);
    return Number.isNaN(val) ? defaultColor : val;
  }

  return defaultColor;
}

export function pathLength(points: [number, number][]): number {
  if (!points || points.length < 2) return 0;
  let len = 0;
  for (let i = 1; i < points.length; i++) {
    len += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
  }
  return len;
}

export function simplifyStrokePoints(points: [number, number][], minDistance: number = 1.25): [number, number][] {
  // Preserve short curves (parentheses, brackets) — dropping the middle point destroys the arc.
  if (!points || points.length <= 4) return points;
  const len = pathLength(points);
  if (len < 24) {
    minDistance = Math.min(minDistance, 0.35);
  } else if (len < 48) {
    minDistance = Math.min(minDistance, 0.75);
  }

  const simplified: [number, number][] = [points[0]];
  let lastX = points[0][0];
  let lastY = points[0][1];

  for (let i = 1; i < points.length - 1; i++) {
    const pt = points[i];
    const dx = pt[0] - lastX;
    const dy = pt[1] - lastY;
    if ((dx * dx + dy * dy) >= (minDistance * minDistance)) {
      simplified.push(pt);
      lastX = pt[0];
      lastY = pt[1];
    }
  }

  const lastPoint = points[points.length - 1];
  const tail = simplified[simplified.length - 1];
  if (tail[0] !== lastPoint[0] || tail[1] !== lastPoint[1]) {
    simplified.push(lastPoint);
  }

  return simplified;
}

/**
 * Draw a variable-width ink ribbon as a filled polygon with rounded caps.
 *
 * Algorithm:
 *   1. Compute per-point half-widths (pressure × velocity × taper × wobble).
 *   2. Compute smooth per-point normals (average of adjacent segment normals).
 *   3. Offset each point left and right by its half-width along the normal.
 *   4. Build a closed polygon: startCap → left side → endCap → right side reversed.
 *   5. Fill the polygon in one draw call.
 *
 * This replaces the old per-segment stroke() loop and eliminates bead artifacts
 * at segment joints while giving geometrically correct variable-width strokes.
 */
export function drawInkPhysicsRibbon(g: PIXI.Graphics, points: [number, number][], opts: InkPhysicsOptions = {}) {
  if (!points || points.length < 2) return;

  const strokePoints = simplifyStrokePoints(points);
  const n = strokePoints.length;
  if (n < 2) return;

  const pathLen = pathLength(strokePoints);
  const isShort = pathLen < 36;

  const {
    baseWidth = 5.5,
    color = 0xffffff,
    alpha = 0.9,
    pressures = null,
    widths = null,
    taperStart = isShort ? 0.02 : 0.06,
    taperEnd = isShort ? 0.02 : 0.06,
    velocityDamping = isShort ? 0.002 : 0.006,
    wobbleAmount = 0.01,
  } = opts;

  // ─── 1. Per-point half-widths ─────────────────────────────────
  // When the backend has pre-computed pressure and thickness (4-tuple path points),
  // `widths` carries the per-point stroke diameter that already encodes velocity,
  // pressure, taper, and organic wobble.  Re-applying velocity, poolBoost, or wobble
  // on top of those values would double-process backend work.  In that case we skip
  // every frontend modifier and use the backend width directly.
  const hasBackendWidths = Boolean(widths && widths.length > 1);
  const hw: number[] = new Array(n);
  for (let i = 0; i < n; i++) {
    const globalT = i / (n - 1);

    let pressure = 0.8;
    if (pressures && pressures.length > 1) {
      const pi = globalT * (pressures.length - 1);
      const plo = Math.floor(pi);
      const phi = Math.min(pressures.length - 1, plo + 1);
      pressure = pressures[plo] + (pressures[phi] - pressures[plo]) * (pi - plo);
    }

    let w = baseWidth;
    if (widths && widths.length > 1) {
      const wi = globalT * (widths.length - 1);
      const wlo = Math.floor(wi);
      const whi = Math.min(widths.length - 1, wlo + 1);
      w = widths[wlo] + (widths[whi] - widths[wlo]) * (wi - wlo);
    }

    const minHalf = isShort ? 1.1 : 0.4;

    if (hasBackendWidths) {
      // Backend width already encodes velocity, taper, wobble, and pooling.
      // Only halve it to convert diameter → ribbon half-width offset.
      hw[i] = Math.max(minHalf, w) * 0.5;
    } else {
      // No backend dynamics — compute frontend ink physics as before.
      // Velocity estimate from span across neighbors
      const nextPt = strokePoints[Math.min(n - 1, i + 1)];
      const prevPt = strokePoints[Math.max(0, i - 1)];
      const spanDx = nextPt[0] - prevPt[0];
      const spanDy = nextPt[1] - prevPt[1];
      const spanLen = Math.sqrt(spanDx * spanDx + spanDy * spanDy) * 0.5;
      const vFactor = Math.max(0.5, 1.0 - spanLen * velocityDamping);

      const taperIn  = (taperStart > 0 && globalT < taperStart) ? globalT / taperStart : 1;
      const taperOut = (taperEnd   > 0 && globalT > 1 - taperEnd) ? (1 - globalT) / taperEnd : 1;
      const taper = Math.min(taperIn, taperOut);

      // Organic ink width variation — 6 cycles per stroke matches real pen wobble.
      const wobble = 1 + Math.sin(globalT * 6.0 + i * 0.3) * wobbleAmount;

      // Ink pooling: the pen is momentarily still at stroke start, so ink pools
      // slightly (extra 12% width for the first 4% of the stroke).
      const poolBoost = globalT < 0.04 ? 1 + (1 - globalT / 0.04) * 0.12 : 1;

      hw[i] = Math.max(minHalf, w * pressure * vFactor * taper * wobble * poolBoost) * 0.5;
    }
  }

  // ─── 2. Smooth per-point normals ─────────────────────────────
  // Each point averages the normals of its adjacent segments for
  // smooth transitions around curves (no bead artifacts).
  const nnx: number[] = new Array(n);
  const nny: number[] = new Array(n);
  for (let i = 0; i < n; i++) {
    let ax = 0, ay = 0;
    if (i > 0) {
      const dx = strokePoints[i][0] - strokePoints[i - 1][0];
      const dy = strokePoints[i][1] - strokePoints[i - 1][1];
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      ax += -dy / len;
      ay += dx / len;
    }
    if (i < n - 1) {
      const dx = strokePoints[i + 1][0] - strokePoints[i][0];
      const dy = strokePoints[i + 1][1] - strokePoints[i][1];
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      ax += -dy / len;
      ay += dx / len;
    }
    const nLen = Math.sqrt(ax * ax + ay * ay) || 1;
    nnx[i] = ax / nLen;
    nny[i] = ay / nLen;
  }

  // ─── 3. Left / right offset vertices ─────────────────────────
  const lx: number[] = new Array(n);
  const ly: number[] = new Array(n);
  const rx: number[] = new Array(n);
  const ry: number[] = new Array(n);
  for (let i = 0; i < n; i++) {
    const px = strokePoints[i][0], py = strokePoints[i][1];
    lx[i] = px + nnx[i] * hw[i];  ly[i] = py + nny[i] * hw[i];
    rx[i] = px - nnx[i] * hw[i];  ry[i] = py - nny[i] * hw[i];
  }

  // ─── 4. Rounded end cap helpers ───────────────────────────────
  // 8 steps gives smooth semicircles even on thick strokes without extra cost.
  const CAP_STEPS = 8;

  // Start cap: sweep from rx[0] backward around to lx[0]
  // Forward direction at start: pt0 → pt1
  const sfwdAngle = Math.atan2(
    strokePoints[1][1] - strokePoints[0][1],
    strokePoints[1][0] - strokePoints[0][0]
  );
  // angle formula: (sfwdAngle - π/2) - π*k/CAP_STEPS
  // k=0 → sfwdAngle-π/2 = rx direction, k=CAP_STEPS → sfwdAngle+π/2 = lx direction

  // End cap: sweep from lx[n-1] forward around to rx[n-1]
  // Forward direction at end: pt[n-2] → pt[n-1]
  const efwdAngle = Math.atan2(
    strokePoints[n - 1][1] - strokePoints[n - 2][1],
    strokePoints[n - 1][0] - strokePoints[n - 2][0]
  );
  // angle formula: (efwdAngle + π/2) - π*k/CAP_STEPS
  // k=0 → efwdAngle+π/2 = lx direction, k=CAP_STEPS → efwdAngle-π/2 = rx direction

  // ─── 5. Draw the complete polygon ────────────────────────────
  // Path: moveTo rx[0] → start cap → left side → end cap → right side reversed
  g.moveTo(rx[0], ry[0]);

  for (let k = 1; k <= CAP_STEPS; k++) {
    const ang = sfwdAngle - Math.PI / 2 - (Math.PI * k / CAP_STEPS);
    g.lineTo(
      strokePoints[0][0] + hw[0] * Math.cos(ang),
      strokePoints[0][1] + hw[0] * Math.sin(ang)
    );
  }
  // cap now at lx[0], ly[0]

  for (let i = 0; i < n; i++) g.lineTo(lx[i], ly[i]);

  for (let k = 1; k <= CAP_STEPS; k++) {
    const ang = efwdAngle + Math.PI / 2 - (Math.PI * k / CAP_STEPS);
    g.lineTo(
      strokePoints[n - 1][0] + hw[n - 1] * Math.cos(ang),
      strokePoints[n - 1][1] + hw[n - 1] * Math.sin(ang)
    );
  }
  // cap now at rx[n-1], ry[n-1]

  for (let i = n - 1; i >= 0; i--) g.lineTo(rx[i], ry[i]);
  // back at rx[0], ry[0] — polygon closed by fill()

  g.fill({ color, alpha });
}

export function renderMotionStroke(g: PIXI.Graphics, stroke: any, boardTheme: string) {
  if (!stroke.points || stroke.points.length < 2) return;
  g.clear();

  const pts = stroke.points;
  const sColor = resolveHexColor(stroke.color, 0xffffff);
  const finalColor = (boardTheme === "light" && sColor === 0xffffff) ? 0x000000 : sColor;
  const baseWidth = Math.max(5.5, (stroke.baseThickness || 2) * 2.8);

  let avgPressure = 0.8;
  if (stroke.pressures && stroke.pressures.length > 0) {
    avgPressure = stroke.pressures.reduce((a: number, b: number) => a + b, 0) / stroke.pressures.length;
  }
  const baseAlpha = Math.min(0.95, 0.68 + avgPressure * 0.28);

  const hasBackendDynamics = Boolean(stroke.hasBackendDynamics);

  drawInkPhysicsRibbon(g, pts, {
    baseWidth,
    color: finalColor,
    alpha: baseAlpha,
    pressures: stroke.pressures,
    widths: stroke.widths,
    taperStart: hasBackendDynamics ? 0.0 : Math.max(0.04, Math.min(0.12, stroke.points?.length ? 0.06 + Math.min(0.04, stroke.points.length / 1400) : 0.08)),
    taperEnd: hasBackendDynamics ? 0.0 : 0.12,
    wobbleAmount: hasBackendDynamics ? 0.0 : 0.014,
  });
}
