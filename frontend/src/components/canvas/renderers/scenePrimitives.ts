/**
 * scenePrimitives.ts — Shared Pixi canvas render helpers.
 *
 * Extracted from PixiCanvas so node, edge, and humanized line rendering
 * can be reused without keeping the main canvas component responsible for
 * the drawing algorithms themselves.
 */

import * as PIXI from "pixi.js";

export interface CanvasTheme {
  bg: number;
  node: number;
  nodeStroke: number;
  nodeText: number;
  edge: number;
  grid: number;
  annotation: number;
  equation: number;
  stackFrame: number;
  stackFrameStroke: number;
  studentInk: number;
  stroke: number;
  highlight: number;
  gridAlpha: number;
}

const COLORS = {
  highlight: 0xf59e0b,
  highlightSoft: 0x422006,
  emphasis: 0xf2cc60,
};

export interface NodeProceduralOptions {
  progress?: number;
  r?: number;
  highlight?: boolean;
  fill?: string | number | null;
  stroke?: string | number | null;
  dynamicWidth?: number | null;
  type?: string | null;
  pointerSectionWidth?: number | null;
  showPerimeter?: boolean;
}

export interface NodeCompleteOptions {
  r?: number;
  highlight?: boolean;
  focusIntensity?: number;
  timeMs?: number;
  fill?: string | number | null;
  stroke?: string | number | null;
  dynamicWidth?: number | null;
  type?: string | null;
  pointerSectionWidth?: number | null;
}

function resolveHexColor(colorStr: string | number | null | undefined, defaultColor: number = 0xffffff): number {
  if (colorStr === null || colorStr === undefined) return defaultColor;
  if (typeof colorStr === "number") {
    return Number.isFinite(colorStr) ? colorStr : defaultColor;
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

  if (normalized.startsWith("#")) return parseInt(normalized.replace("#", "0x"), 16);
  if (normalized.startsWith("0x")) return parseInt(normalized, 16);

  return defaultColor;
}

export function drawHumanLine(
  g: PIXI.Graphics,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  progress: number,
  color: number,
  width: number,
  alpha: number,
  seed: number
): void {
  const clampedProgress = Math.max(0, Math.min(1, progress));
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.max(1, Math.hypot(dx, dy));
  const steps = Math.max(2, Math.ceil(len / 16));
  const limit = Math.max(2, Math.floor(steps * clampedProgress));
  const perpX = -dy / len;
  const perpY = dx / len;

  g.moveTo(x1, y1);
  for (let i = 1; i <= limit; i++) {
    const t = i / steps;
    const eased = t * t * (3 - 2 * t);
    const wobble = Math.sin(seed * 0.017 + t * Math.PI * 5.0) * 0.55 * (0.35 + Math.abs(0.5 - t));
    const drift = Math.sin(seed * 0.031 + t * Math.PI * 2.0) * 0.28;
    g.lineTo(
      x1 + dx * eased + perpX * (wobble + drift),
      y1 + dy * eased + perpY * (wobble + drift)
    );
  }
  g.stroke({ width, color, alpha, cap: "round", join: "round" });
}

export function drawHumanArrow(
  g: PIXI.Graphics,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  progress: number,
  color: number,
  width: number,
  alpha: number,
  seed: number
): void {
  drawHumanLine(g, x1, y1, x2, y2, progress, color, width, alpha, seed);
  if (progress < 0.75) return;

  const angle = Math.atan2(y2 - y1, x2 - x1) + Math.PI;
  const arrowSize = 6;
  const x3 = x2 + arrowSize * Math.cos(angle - 0.45);
  const y3 = y2 + arrowSize * Math.sin(angle - 0.45);
  const x4 = x2 + arrowSize * Math.cos(angle + 0.45);
  const y4 = y2 + arrowSize * Math.sin(angle + 0.45);
  drawHumanLine(g, x2, y2, x3, y3, 1, color, width, alpha, seed + 11);
  drawHumanLine(g, x2, y2, x4, y4, 1, color, width, alpha, seed + 19);
}

export function drawNodeProcedural(g: PIXI.Graphics, theme: CanvasTheme, opts: NodeProceduralOptions = {}) {
  const { progress = 1, r = 28, highlight = false, fill = null, stroke = null, dynamicWidth = null, type = null, pointerSectionWidth = null, showPerimeter = true } = opts;

  const pProg = showPerimeter ? Math.min(1, progress / 0.65) : 0;
  const fProg = Math.max(0, Math.min(1, (progress - 0.60) / 0.35));

  const w = dynamicWidth !== null && dynamicWidth !== undefined ? dynamicWidth : r * 2;
  const h = r * 2;
  const cr = 8;

  g.clear();

  if (fProg > 0 && fill !== "transparent") {
    const fillColor = resolveHexColor(fill, highlight ? COLORS.highlightSoft : theme.node);
    g.roundRect(-w / 2, -r, w, h, cr);
    g.fill({ color: fillColor, alpha: Math.min(0.9, fProg * 0.9) });
  }

  if (pProg > 0 && stroke !== "transparent") {
    const strokeColor = resolveHexColor(stroke, highlight ? COLORS.highlight : theme.nodeStroke);
    const strokeWidth = highlight ? 2.5 : 1.5;

    g.roundRect(-w / 2, -r, w, h, cr);
    g.stroke({ width: strokeWidth, color: strokeColor, cap: "round", join: "round", alpha: pProg * 0.95 });

    if (pointerSectionWidth && pProg >= 1) {
      const dividerX = w / 2 - pointerSectionWidth * 1.11111111;
      g.moveTo(dividerX, -r);
      g.lineTo(dividerX, r);
      g.stroke({ width: strokeWidth, color: strokeColor, cap: "round", join: "round", alpha: 0.95 });
    }
  }
}

export function drawNodeComplete(g: PIXI.Graphics, theme: CanvasTheme, opts: NodeCompleteOptions = {}) {
  const { r = 28, highlight = false, focusIntensity = 0, timeMs = 0, fill = null, stroke = null, dynamicWidth = null, type = null, pointerSectionWidth = null } = opts;
  const w = dynamicWidth !== null && dynamicWidth !== undefined ? dynamicWidth : r * 2;
  const h = r * 2;
  const cr = 8;
  g.clear();

  if (focusIntensity > 0 && stroke !== "transparent") {
    const pulseAlpha = 0.15 + Math.sin(timeMs * 0.006) * 0.1 * focusIntensity;
    g.roundRect(-w / 2 - 4, -r - 4, w + 8, h + 8, 12);
    g.fill({ color: COLORS.emphasis, alpha: pulseAlpha });
  }

  g.roundRect(-w / 2, -r, w, h, cr);
  if (fill !== "transparent") {
    const fillColor = resolveHexColor(fill, highlight ? COLORS.highlightSoft : theme.node);
    g.fill({ color: fillColor, alpha: 0.9 });
  }
  if (stroke !== "transparent") {
    const strokeColor = resolveHexColor(stroke, highlight ? COLORS.highlight : theme.nodeStroke);
    g.stroke({ width: highlight ? 2.5 : 1.5, color: strokeColor, alpha: 0.95 });
  }

  if (pointerSectionWidth && stroke !== "transparent") {
    const dividerX = w / 2 - pointerSectionWidth * 1.11111111;
    const strokeColor = resolveHexColor(stroke, highlight ? COLORS.highlight : theme.nodeStroke);
    g.moveTo(dividerX, -r);
    g.lineTo(dividerX, r);
    g.stroke({ width: highlight ? 2.5 : 1.5, color: strokeColor, alpha: 0.95 });
  }
}

export function drawTreeEdge(
  g: PIXI.Graphics,
  theme: CanvasTheme,
  from: { x: number; y: number },
  to: { x: number; y: number },
  progress: number = 1,
  directed: boolean = false,
  color: number | null = null,
  textElement: PIXI.Text | null = null,
  label: string = ""
) {
  g.clear();
  if (textElement) textElement.text = "";
  if (progress <= 0) return;

  const dx = to.x - from.x, dy = to.y - from.y;
  const len = Math.sqrt(dx * dx + dy * dy);
  if (len === 0) return;

  const targetX = from.x + dx * progress;
  const targetY = from.y + dy * progress;
  const edgeColor = color !== null ? color : theme.edge;

  g.moveTo(from.x, from.y);
  g.lineTo(targetX, targetY);
  g.stroke({ width: 2.0, color: edgeColor, alpha: 0.85, cap: "round" });

  if (directed && progress > 0.3) {
    const arrowSize = 8;
    const angle = Math.atan2(dy, dx);
    const arrowAngle = angle + Math.PI;

    const x1 = targetX + arrowSize * Math.cos(arrowAngle - 0.45);
    const y1 = targetY + arrowSize * Math.sin(arrowAngle - 0.45);
    const x2 = targetX + arrowSize * Math.cos(arrowAngle + 0.45);
    const y2 = targetY + arrowSize * Math.sin(arrowAngle + 0.45);

    g.moveTo(targetX, targetY).lineTo(x1, y1);
    g.moveTo(targetX, targetY).lineTo(x2, y2);
    g.stroke({ width: 2.0, color: edgeColor, alpha: 0.85, cap: "round", join: "round" });
  }

  if (textElement) {
    // Keep edge labels hidden while we move to stroke-driven glyphs.
    textElement.text = "";
    textElement.alpha = 0;
  }
}
