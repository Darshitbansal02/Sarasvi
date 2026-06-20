import * as PIXI from "pixi.js";
import type { StrokeEntry } from "@/runtime/motion/glyphLayoutEngine";
import { audioTimeline } from "@/runtime/audio/audioTimeline";

export interface CanvasTheme {
  bg?: number;
  node?: number;
  nodeStroke?: number;
  nodeText?: number;
  annotation?: number;
  equation?: number;
  edge?: number;
  grid?: number;
  gridAlpha?: number;
  stroke?: number;
  stackFrame?: number;
  stackFrameStroke?: number;
  studentInk?: number;
  highlight?: number;
}

function drawDashedLine(g: PIXI.Graphics, x1: number, y1: number, x2: number, y2: number): void {
  const dx = x2 - x1, dy = y2 - y1;
  const len = Math.sqrt(dx * dx + dy * dy);
  const dashLen = 6, gapLen = 6; // Increased lengths for faster processing on low-end CPUs
  const steps = len / (dashLen + gapLen);
  for (let i = 0; i < steps; i++) {
    const t = i / steps, tNext = (i + 0.5) / steps;
    g.moveTo(x1 + dx * t, y1 + dy * t).lineTo(x1 + dx * tNext, y1 + dy * tNext);
  }
  g.stroke();
}

export interface LegacyStrokeOptions {
  id?: string;
  color?: number;
  thickness?: number;
  alpha?: number;
}

/** Prefer explicit per-stroke timing from motion planner (line_N), not glyph-aggregated char_N. */
export function resolveStrokeStateDirect(
  strokeIndex: number,
  charStates: any[] | undefined
): StrokeTimingState | null {
  if (!charStates) return null;
  const direct = charStates.find(
    (c: any) =>
      c.type === "stroke" &&
      (c.id === `line_${strokeIndex}` || c.strokeIndex === strokeIndex)
  );
  if (!direct) return null;
  return {
    startMs: direct.startMs,
    endMs: direct.endMs,
    wordBoundaryIndex: direct.wordBoundaryIndex,
    absoluteStartMs: direct.absoluteStartMs,
    absoluteEndMs: direct.absoluteEndMs
  };
}

/**
 * Full pedagogical reveal order: every constructionSequence step (glyph + stroke),
 * not stroke-only steps (which skips glyph ink ordering).
 */
export function getRevealOrder(
  strokes: StrokeEntry[],
  constructionSequence?: Array<{ type: string; index: number }>
): number[] {
  if (!constructionSequence?.length) {
    return strokes.map((_, i) => i);
  }

  const order: number[] = [];
  const seen = new Set<number>();

  for (const step of constructionSequence) {
    if (step.type === "stroke") {
      if (step.index >= 0 && step.index < strokes.length && !seen.has(step.index)) {
        order.push(step.index);
        seen.add(step.index);
      }
    } else if (step.type === "glyph") {
      strokes.forEach((s, idx) => {
        if (s.charIndex === step.index && !seen.has(idx)) {
          order.push(idx);
          seen.add(idx);
        }
      });
    }
  }

  strokes.forEach((_, idx) => {
    if (!seen.has(idx)) order.push(idx);
  });

  return order.length > 0 ? order : strokes.map((_, i) => i);
}

/** @deprecated Use getRevealOrder */
export function getStrokeDrawOrder(
  strokes: StrokeEntry[],
  constructionSequence?: Array<{ type: string; index: number }>
): number[] {
  return getRevealOrder(strokes, constructionSequence);
}

function resolveStrokeTiming(
  strokeIndex: number,
  strokes: StrokeEntry[],
  charStates: any[] | undefined,
  currentTimeMs: number
): StrokeTimingState | null {
  const direct = resolveStrokeStateDirect(strokeIndex, charStates);
  if (direct) return direct;
  const stroke = strokes.at(strokeIndex);
  if (!stroke || !charStates) return null;
  const resolved = resolveStrokeStateForRender(
    strokeIndex,
    stroke,
    strokes,
    charStates,
    currentTimeMs
  );
  if (!resolved) return null;
  return { startMs: resolved.startMs, endMs: resolved.endMs };
}

export function resolveStrokeStateForRender(strokeIndex: number, stroke: StrokeEntry, strokes: StrokeEntry[], charStates: any[] | undefined, currentTimeMs: number): any | null {
  if (!charStates) return null;

  const directTiming = resolveStrokeStateDirect(strokeIndex, charStates);
  if (directTiming) {
    return { type: "stroke", id: `line_${strokeIndex}`, ...directTiming };
  }

  const direct = charStates.find((c: any) => c.type === "stroke" && c.id === `line_${strokeIndex}`);
  if (direct) return direct;

  if (stroke.charIndex !== undefined) {
    const charState = charStates.find((c: any) => c.id === `char_${stroke.charIndex}`);
    if (!charState) return null;

    const siblingStrokes = strokes
      .map((candidate, index) => ({ candidate, index }))
      .filter(({ candidate }) => candidate.charIndex === stroke.charIndex);
    const order = siblingStrokes.findIndex(({ index }) => index === strokeIndex);
    if (order < 0) return charState;

    const charDuration = Math.max(1, charState.endMs - charState.startMs);
    const perStrokeDuration =
        Math.max(
            60,
            charDuration /
            Math.max(
                1,
                siblingStrokes.length
            )
        );
    return {
      ...charState,
      type: "stroke",
      id: `line_${strokeIndex}`,
      startMs: charState.startMs + order * perStrokeDuration,
      endMs: charState.startMs + (order + 1) * perStrokeDuration,
    };
  }

  return null;
}

export interface StrokeTimingState {
  startMs: number;
  endMs: number;
  wordBoundaryIndex?: number;
  absoluteStartMs?: number;
  absoluteEndMs?: number;
}

/** Clip polyline points to progressive reveal progress (0–1 along path).
 * Points may be 2-tuple [x,y] or wider [x,y,pressure,thickness].
 * Extra dimensions are preserved and linearly interpolated at the boundary
 * so backend-computed pressure and thickness survive to the ribbon renderer. */
export function clipPointsForReveal(
  pts: number[][],
  cState: StrokeTimingState | null,
  currentTimeMs: number
): number[][] {
  if (!pts || pts.length < 2) return [];
  if (!cState) return pts;

  const startMs =
      cState.absoluteStartMs ??
      cState.startMs;

  const endMs =
      cState.absoluteEndMs ??
      cState.endMs;

  if (currentTimeMs < startMs) {
      return [];
  }

  if (currentTimeMs >= endMs) {
      return pts;
  }

  const localProgress = Math.min(
      1,
      Math.max(
          0,
          (currentTimeMs - startMs) /
          Math.max(1, endMs - startMs)
      )
  );
  const eased = localProgress * localProgress * (3 - 2 * localProgress);
  const totalPoints = pts.length;
  const drawCount = Math.floor(eased * (totalPoints - 1));
  const visible: number[][] = pts.slice(0, drawCount + 1);
  if (drawCount < totalPoints - 1) {
    const pLast = pts[drawCount]!;
    const pNext = pts[drawCount + 1]!;
    const t = eased * (totalPoints - 1) - drawCount;
    // Interpolate x, y, and any extra backend dimensions (pressure, thickness, …)
    const dims = Math.max(pLast.length, pNext.length);
    const boundary: number[] = [];
    for (let d = 0; d < dims; d++) {
      const a = pLast[d] ?? 0;
      const b = pNext[d] ?? pLast[d] ?? 0;
      boundary.push(a + t * (b - a));
    }
    visible.push(boundary);
  }
  return visible.length >= 2 ? visible : [];
}

/** Center layout-space stroke coordinates to match glyph centering in the container.
 * Preserves backend pressure/thickness dimensions (indices 2 and 3) so the ribbon
 * renderer can use them without re-computing ink physics. */
export function centerStrokePoints(
  pts: number[][],
  halfWidth: number
): number[][] {
  if (!halfWidth) return pts;
  return pts.map((pt) => {
    const shifted: number[] = [pt[0] - halfWidth, pt[1]];
    for (let i = 2; i < pt.length; i++) shifted.push(pt[i]!);
    return shifted;
  });
}

export function shouldDrawStrokeForTiming(
  cState: StrokeTimingState | null,
  charStates: any[] | undefined,
  currentTimeMs: number,
  objStartMs: number
): boolean {
  if (charStates && charStates.length > 0) {
      if (!cState) return false;

      const startMs =
          cState.absoluteStartMs ??
          cState.startMs;

      return currentTimeMs >= startMs;
  }
  return currentTimeMs - objStartMs > 400;
}

const TEXT_OBJECT_TYPES = new Set(["annotation", "equation", "equation_write"]);

export function estimateTextDurationMs(obj: {
  startMs?: number;
  data?: Record<string, any>;
}): number {
  return Math.max(
    900,
    Math.floor(
      (obj.data?.total_duration_ms ||
        obj.data?.duration_ms ||
        (obj.data?.per_char_ms &&
        (obj.data?.metadata?.token_count || obj.data?.metadata?.tokens?.length)
          ? obj.data.per_char_ms *
            (obj.data.metadata?.token_count || obj.data.metadata?.tokens?.length || 1)
          : 1000)) * 0.94
    )
  );
}

/** End of progressive reveal — prefer actual charState timeline over narration estimate. */
export function getEquationWriteEndMs(
  obj: {
    startMs?: number;
    _charStates?: Array<{ endMs: number }>;
    data?: Record<string, any>;
  }
): number {
  const cs = obj._charStates;
  if (cs?.length) return Math.max(...cs.map((c) => c.endMs));
  return (obj.startMs || 0) + estimateTextDurationMs(obj);
}

export function isTextObjectInWriteWindow(
  obj: { type?: string; startMs?: number; _charStates?: Array<{ endMs: number }>; data?: Record<string, any>; _lockedComplete?: boolean },
  timeMs: number
): boolean {
  if (!obj.type || !TEXT_OBJECT_TYPES.has(obj.type)) return false;
  if (obj._lockedComplete) return false;
  const start = obj.startMs || 0;
  return timeMs >= start && timeMs <= getEquationWriteEndMs(obj);
}

/** Single active writer: motor id, else earliest incomplete equation in the lane. */
export function resolveActiveWritingEquationId(
  sceneObjects: Record<string, any>,
  motionState: { activeWritingEquationId?: string | null } | null | undefined,
  currentTimeMs: number
): string | null {
  if (motionState?.activeWritingEquationId) return motionState.activeWritingEquationId;

  const incomplete = Object.values(sceneObjects)
    .filter((obj) => isTextObjectInWriteWindow(obj, currentTimeMs))
    .filter((obj) => {
      const end = getEquationWriteEndMs(obj);
      return currentTimeMs < end;
    })
    .sort((a, b) => (a.startMs || 0) - (b.startMs || 0));

  return incomplete[0]?.id ?? null;
}

/** Strokes may only reveal after all prior construction-order strokes have finished. */
export function canRevealStrokeYet(
  strokeIndex: number,
  revealOrder: number[],
  strokes: StrokeEntry[],
  charStates: any[] | undefined,
  currentTimeMs: number
): boolean {
  if (!charStates?.length) return true;
  const pos = revealOrder.indexOf(strokeIndex);
  if (pos <= 0) return true;
  for (let i = 0; i < pos; i++) {
    const priorIdx = revealOrder[i]!;
    const prior = resolveStrokeTiming(priorIdx, strokes, charStates, currentTimeMs);
    if (!prior) {
      // If we don't have timing for a prior stroke, check if it was part of an
      // earlier segment (priorIdx is less than the first strokeIndex in charStates).
      const validStrokeIndices = charStates
        .filter(cs => cs && cs.type === "stroke" && cs.strokeIndex !== undefined)
        .map(cs => cs.strokeIndex as number);
      if (validStrokeIndices.length > 0) {
        const firstActiveStrokeIdx = Math.min(...validStrokeIndices);
        if (priorIdx < firstActiveStrokeIdx) {
          continue; // Prior stroke is from a completed segment/equation
        }
      }
      return false;
    }
    const endMs = prior.absoluteEndMs ?? prior.endMs;
    if (currentTimeMs < endMs) return false;
  }
  return true;
}

export function findCurrentWriteStroke(
  revealOrder: number[],
  strokes: StrokeEntry[],
  charStates: any[] | undefined,
  currentTimeMs: number
): { strokeIndex: number; cState: StrokeTimingState; orderIndex: number } | null {
  if (!charStates?.length) return null;

  for (let orderIndex = 0; orderIndex < revealOrder.length; orderIndex++) {
    const strokeIndex = revealOrder[orderIndex]!;
    const cState = resolveStrokeTiming(strokeIndex, strokes, charStates, currentTimeMs);
    if (!cState) continue;
    const endMs = cState.absoluteEndMs ?? cState.endMs;
    const startMs =
        cState.absoluteStartMs ??
        cState.startMs;

    if (
        currentTimeMs >= startMs &&
        currentTimeMs <= endMs
    ) {
        return {
            strokeIndex,
            cState,
            orderIndex
        };
    }
  }

  const lastIdx = revealOrder.at(-1);
  if (lastIdx === undefined) return null;
  const lastOrderIndex = revealOrder.length - 1;
  const last = resolveStrokeTiming(lastIdx, strokes, charStates, currentTimeMs);
  if (last) {
    const startMs = last.absoluteStartMs ?? last.startMs;
    if (currentTimeMs >= startMs) {
      return { strokeIndex: lastIdx, cState: last, orderIndex: lastOrderIndex };
    }
  }
  return null;
}

/**
 * Time-based maximum reveal-order index for the visible nib.
 * Stops at the first stroke that is currently in-flight and never
 * advances past later strokes even if the logical current write moves on.
 */
export function maxRevealOrderIndexAtTime(
  revealOrder: number[],
  strokes: StrokeEntry[],
  charStates: any[] | undefined,
  currentTimeMs: number,
  isLocked?: boolean
): number {
  if (!charStates?.length) return revealOrder.length - 1;

  let maxVisibleOrderIndex = -1;

  for (let orderIndex = 0; orderIndex < revealOrder.length; orderIndex++) {
    const strokeIndex = revealOrder[orderIndex]!;
    const cState = resolveStrokeTiming(strokeIndex, strokes, charStates, currentTimeMs);
    const isAlreadyWritten = isLocked && cState && (cState.absoluteStartMs ?? cState.startMs) <= 500;

    if (!isAlreadyWritten && !canRevealStrokeYet(strokeIndex, revealOrder, strokes, charStates, currentTimeMs)) {
      break;
    }

    if (!cState) continue;
    const startMs = cState.absoluteStartMs ?? cState.startMs;
    if (!isAlreadyWritten && currentTimeMs < startMs) break;

    maxVisibleOrderIndex = orderIndex;
    const endMs = cState.absoluteEndMs ?? cState.endMs;
    if (!isAlreadyWritten && currentTimeMs < endMs + 25) {
      return maxVisibleOrderIndex;
    }
  }

  return maxVisibleOrderIndex;
}

/** Max reveal-order index the nib has reached (for nib-led ink cap). */
export function getNibMaxRevealOrderIndex(
  revealOrder: number[],
  strokes: StrokeEntry[],
  charStates: any[] | undefined,
  currentTimeMs: number,
  isLocked?: boolean
): number {
  return maxRevealOrderIndexAtTime(revealOrder, strokes, charStates, currentTimeMs, isLocked);
}

export function drawStackFrameProcedural(g: PIXI.Graphics, theme: CanvasTheme, w: number = 220, h: number = 60, progress: number = 1, highlight: boolean = false, showBorder: boolean = true) {
  g.clear();
  if (progress <= 0) return;

  const color = highlight ? 0xf2cc60 : theme.stackFrameStroke || 0x2f81f7;
  const bodyColor = theme.stackFrame || 0x161b22;
  const headerColor = highlight ? 0x2a1a00 : 0x30363d;

  if (progress > 0.6) {
    const fillProg = (progress - 0.6) / 0.4;
    g.roundRect(-w / 2, -h / 2, w, h, 4);
    g.fill({ color: bodyColor, alpha: fillProg * 0.9 });
    if (fillProg > 0.3) {
      const lidProg = (fillProg - 0.3) / 0.7;
      g.roundRect(-w / 2, -h / 2, w, 20, 4);
      g.fill({ color: headerColor, alpha: lidProg });
    }
  }

  const perimProgress = showBorder ? Math.min(1, progress / 0.6) : 0;
  if (perimProgress > 0) {
    g.roundRect(-w / 2, -h / 2, w, h, 4);
    g.stroke({ width: highlight ? 2 : 1.5, color, alpha: perimProgress * 0.9 });
  }
}

export function drawLegacyStroke(g: PIXI.Graphics, path: [number, number][], progress: number, opts: LegacyStrokeOptions = {}) {
  if (!path || path.length < 2) return;

  const validPath = path.filter(pt => pt && pt[0] !== undefined && pt[1] !== undefined);
  if (validPath.length < 2) return;

  const limit = Math.max(2, Math.floor(validPath.length * Math.max(0, progress)));
  if (limit < 2) return;

  g.clear();
  const end = Math.min(limit, validPath.length);

  const ptStart = validPath.at(0);
  if (ptStart) g.moveTo(ptStart[0], ptStart[1]);
  for (let i = 1; i < end - 1; i++) {
    const pt = validPath.at(i);
    const ptNext = validPath.at(i + 1);
    const x = pt?.[0] ?? 0;
    const y = pt?.[1] ?? 0;
    const nx = ptNext?.[0] ?? 0;
    const ny = ptNext?.[1] ?? 0;
    g.quadraticCurveTo(x, y, (x + nx) / 2, (y + ny) / 2);
  }

  const ptEnd = validPath.at(end - 1);
  if (ptEnd) {
    g.lineTo(ptEnd[0], ptEnd[1]);
  }
  g.stroke({
    width: opts.thickness || 2,
    color: opts.color || 0xffffff,
    cap: "round",
    join: "round",
    alpha: opts.alpha !== undefined ? opts.alpha : 0.9,
  });
}

export { drawDashedLine };
