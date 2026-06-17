/**
 * Live writing diagnostics for browser console validation.
 * Assert: distanceToTip < 3 during static equation write; revealPercent === 100 when stroke completes.
 */

import {
  canRevealStrokeYet,
  centerStrokePoints,
  clipPointsForReveal,
  findCurrentWriteStroke,
  isTextObjectInWriteWindow,
  getEquationWriteEndMs,
  getRevealOrder,
  maxRevealOrderIndexAtTime,
  resolveActiveWritingEquationId,
  resolveStrokeStateForRender,
  shouldDrawStrokeForTiming,
} from "@/components/canvas/renderers/canvasRenderHelpers";
import type { StrokeEntry } from "@/runtime/motion/glyphLayoutEngine";

export interface WritingDiagnosticsSnapshot {
  t: number;
  nibX: number;
  nibY: number;
  activeStrokeTipX: number | null;
  activeStrokeTipY: number | null;
  distanceToTip: number | null;
  visiblePoints: number;
  totalPoints: number;
  revealPercent: number;
  activeObjectId: string | null;
  activeEquationId: string | null;
  writingTipEquationId: string | null;
  revealingEquationIds: string[];
  inkAheadStrokes: number[];
  nibRevealOrderIndex: number;
  activeStrokeIndex: number | null;
  inkAuthority: string | null;
  cursorState: string;
  violations: string[];
}

function interpolateStrokeTip(
  s: StrokeEntry,
  tau: number,
  layoutHalfW: number,
  safeTextX: number,
  safeTextY: number
): { x: number; y: number; totalPoints: number; visiblePoints: number; revealPercent: number } {
  const easedTau = tau * tau * (3 - 2 * tau);

  if (s.points && s.points.length >= 2) {
    const pts = s.points;
    const totalPoints = pts.length;
    const idx = easedTau * (totalPoints - 1);
    const low = Math.floor(idx);
    const high = Math.min(totalPoints - 1, low + 1);
    const localTau = idx - low;
    const lx = pts[low][0] + (pts[high][0] - pts[low][0]) * localTau;
    const ly = pts[low][1] + (pts[high][1] - pts[low][1]) * localTau;
    const visibleCount = Math.max(2, Math.floor(easedTau * (totalPoints - 1)) + 1);
    return {
      x: safeTextX + lx,
      y: safeTextY + ly,
      totalPoints,
      visiblePoints: visibleCount,
      revealPercent: easedTau,
    };
  }

  const lx = s.x1 + easedTau * (s.x2 - s.x1);
  const ly = s.y1 + easedTau * (s.y2 - s.y1);
  return {
    x: safeTextX + lx,
    y: safeTextY + ly,
    totalPoints: 2,
    visiblePoints: easedTau >= 1 ? 2 : Math.max(1, Math.ceil(easedTau * 2)),
    revealPercent: easedTau,
  };
}

export function computeWritingDiagnostics(
  sceneObjects: Record<string, any>,
  motionState: any,
  currentTimeMs: number
): WritingDiagnosticsSnapshot {
  const cursor = motionState?.cursor ?? {};
  const nibX = cursor.writingTip?.x ?? cursor.x ?? 0;
  const nibY = cursor.writingTip?.y ?? cursor.y ?? 0;
  const violations: string[] = [];

  const candidates = Object.values(sceneObjects).filter(
    (obj: any) =>
      (obj.type === "annotation" || obj.type === "equation" || obj.type === "equation_write") &&
      currentTimeMs >= (obj.startMs || 0) &&
      currentTimeMs <= getEquationWriteEndMs(obj)
  );

  const activeEquationId = resolveActiveWritingEquationId(sceneObjects, motionState, currentTimeMs);

  const activeObj =
    (activeEquationId && sceneObjects[activeEquationId]) ||
    (candidates.length > 0
      ? candidates.reduce((latest: any, obj: any) => (obj.startMs > latest.startMs ? obj : latest))
      : null);

  if (!activeObj || !activeObj._strokesLayout?.length) {
    const growing = (motionState?.strokes || []).find((st: any) => st.state === "growing");
    const tip = growing?.points?.at(-1);
    const distanceToTip =
      tip && Number.isFinite(tip[0])
        ? Math.hypot(nibX - tip[0], nibY - tip[1])
        : null;
    if (distanceToTip !== null && distanceToTip > 3) {
      violations.push(`distanceToTip=${distanceToTip.toFixed(1)}px (motion ink)`);
    }
    const revealingEquationIds = motionState?.revealingEquationIds ?? [];
    if (revealingEquationIds.length > 0) {
      violations.push(`concurrentReveal=${revealingEquationIds.join(",")}`);
    }
    return {
      t: currentTimeMs,
      nibX,
      nibY,
      activeStrokeTipX: tip?.[0] ?? null,
      activeStrokeTipY: tip?.[1] ?? null,
      distanceToTip,
      visiblePoints: growing?.points?.length ?? 0,
      totalPoints: growing?.points?.length ?? 0,
      revealPercent: growing?.progress ?? 0,
      activeObjectId: null,
      activeEquationId: activeEquationId,
      writingTipEquationId: motionState?.writingTipEquationId ?? activeEquationId,
      revealingEquationIds,
      inkAheadStrokes: [],
      nibRevealOrderIndex: -1,
      activeStrokeIndex: null,
      inkAuthority: growing ? "motion" : null,
      cursorState: cursor.state ?? "idle",
      violations,
    };
  }

  const strokes: StrokeEntry[] = activeObj._strokesLayout || [];
  const charStates = activeObj._charStates;
  const layoutHalfW = (activeObj._totalTextWidth ?? 0) / 2;
  const safeTextX = activeObj._safeTextX ?? activeObj.position?.x ?? 0;
  const safeTextY = activeObj._safeTextY ?? activeObj.position?.y ?? 0;

  const revealOrder = getRevealOrder(strokes, activeObj._constructionSequence);
  const currentWrite = findCurrentWriteStroke(revealOrder, strokes, charStates, currentTimeMs);

  let activeStrokeIndex: number | null = null;
  let tipX: number | null = null;
  let tipY: number | null = null;
  let visiblePoints = 0;
  let totalPoints = 0;
  let revealPercent = 0;

  if (currentWrite && strokes.at(currentWrite.strokeIndex)) {
    activeStrokeIndex = currentWrite.strokeIndex;
    const s = strokes.at(currentWrite.strokeIndex)!;
    const strokeDur = currentWrite.cState.endMs - currentWrite.cState.startMs;
    const tau =
      strokeDur > 0
        ? Math.min(1, Math.max(0, (currentTimeMs - currentWrite.cState.startMs) / strokeDur))
        : 1;
    const cState = resolveStrokeStateForRender(
      currentWrite.strokeIndex,
      s,
      strokes,
      charStates,
      currentTimeMs
    );
    const interp = interpolateStrokeTip(s, tau, layoutHalfW, safeTextX, safeTextY);
    tipX = interp.x;
    tipY = interp.y;
    totalPoints = interp.totalPoints;
    if (cState && s.points && s.points.length >= 2) {
      const centered = s.points;
      const visible = clipPointsForReveal(centered, cState, currentTimeMs);
      visiblePoints = visible.length;
      revealPercent =
        cState.endMs > cState.startMs
          ? Math.min(1, (currentTimeMs - cState.startMs) / (cState.endMs - cState.startMs))
          : 1;
    } else {
      visiblePoints = interp.visiblePoints;
      revealPercent = interp.revealPercent;
    }
  }

  if (tipX === null && cursor.writingTip) {
    tipX = cursor.writingTip.x;
    tipY = cursor.writingTip.y;
  }

  const distanceToTip =
    tipX !== null && tipY !== null ? Math.hypot(nibX - tipX, nibY - tipY) : null;

  if (distanceToTip !== null && distanceToTip > 3 && cursor.state === "drawing") {
    violations.push(`distanceToTip=${distanceToTip.toFixed(1)}px`);
  }
  if (currentWrite && currentTimeMs >= currentWrite.cState.endMs && revealPercent < 0.99) {
    violations.push(`revealPercent=${(revealPercent * 100).toFixed(0)}% after stroke end`);
  }
  if (!cursor.writingTip && isTextObjectInWriteWindow(activeObj, currentTimeMs)) {
    violations.push("writingTip=null during active write");
  }

  const revealingEquationIds = motionState?.revealingEquationIds ?? [];
  if (revealingEquationIds.length > 0) {
    violations.push(`concurrentReveal=${revealingEquationIds.join(",")}`);
  }
  if (activeEquationId && activeObj?.id && activeEquationId !== activeObj.id) {
    violations.push(`nibEquationMismatch=nib:${activeEquationId} ink:${activeObj.id}`);
  }

  const nibRevealOrderIndex = maxRevealOrderIndexAtTime(revealOrder, strokes, charStates, currentTimeMs);
  const inkAheadStrokes: number[] = [];
  const completedStrokeMax = activeObj._boardCompletedStrokeMaxIndex as number | undefined;
  const isActiveWriter = activeEquationId === activeObj.id;

  if (isActiveWriter && nibRevealOrderIndex >= 0) {
    for (let oi = 0; oi < revealOrder.length; oi++) {
      if (oi <= nibRevealOrderIndex) continue;
      const j = revealOrder[oi]!;
      if (completedStrokeMax !== undefined && j <= completedStrokeMax) continue;
      const s = strokes.at(j)!;
      const cState = resolveStrokeStateForRender(j, s, strokes, charStates, currentTimeMs);
      if (
        !cState ||
        !shouldDrawStrokeForTiming(cState, charStates, currentTimeMs, activeObj.startMs || 0) ||
        !canRevealStrokeYet(j, revealOrder, strokes, charStates, currentTimeMs)
      ) {
        continue;
      }
      let hasVisible = false;
      if (s.points && s.points.length >= 2) {
        const centered = s.points;
        const visible = clipPointsForReveal(centered, cState, currentTimeMs);
        hasVisible = visible.length >= 2;
      } else if (currentTimeMs >= cState.startMs) {
        hasVisible = true;
      }
      if (hasVisible) inkAheadStrokes.push(j);
    }
  }

  if (inkAheadStrokes.length > 0) {
    violations.push(`inkAhead=${inkAheadStrokes.map((i) => `line_${i}`).join(",")}`);
    violations.push(`inkAheadByTime=${inkAheadStrokes.map((i) => `line_${i}`).join(",")}`);
  }

  return {
    t: currentTimeMs,
    nibX,
    nibY,
    activeStrokeTipX: tipX,
    activeStrokeTipY: tipY,
    distanceToTip,
    visiblePoints,
    totalPoints,
    revealPercent,
    activeObjectId: activeObj.id ?? null,
    activeEquationId: activeEquationId ?? activeObj.id ?? null,
    writingTipEquationId: motionState?.writingTipEquationId ?? activeEquationId,
    revealingEquationIds,
    inkAheadStrokes,
    nibRevealOrderIndex,
    activeStrokeIndex,
    inkAuthority: activeObj._inkAuthority ?? "static",
    cursorState: cursor.state ?? "idle",
    violations,
  };
}
