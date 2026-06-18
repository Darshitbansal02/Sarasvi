/**
 * strokeScheduler.ts — Cursor-Driven Stroke Generation
 *
 * FIXED: Cursor is now the MOTOR AUTHORITY.
 * Strokes emerge FROM cursor motion, not the other way around.
 *
 * All functions are pure, deterministic, and enhanced to model human material wear 
 * (chalk bluntness flattening) and kinetic upstroke/downstroke writing asymmetry.
 */

import { Spring2D, SPRING_PRESETS, Easing, VelocityTracker } from "./motionPhysics";
import { audioEventBridge } from "../audio/audioEventBridge";

// ── Stroke States & Enums ──────────────────────────────────────

export enum STROKE_STATE {
  PENDING = "pending",
  GROWING = "growing",
  PAUSED = "paused",
  COMPLETED = "completed",
}

// ── Struct Data & Domain Interfaces ───────────────────────────

export interface ActiveStrokeOptions {
  strokeId: string;
  waypoints?: [number, number][];
  targetPath?: [number, number][];
  durationMs?: number;
  color?: string;
  thickness?: number;
  startMs?: number;
  difficulty?: number;
  pressures?: number[];
  widths?: number[];
}

export interface StrokeRenderState {
  strokeId: string;
  state: STROKE_STATE;
  progress: number;
  points: [number, number][];
  pressures: number[];
  widths: number[];
  color: string;
  baseThickness: number;
  completed: boolean;
  cursorX: number;
  cursorY: number;
  hasBackendDynamics?: boolean;
}

interface WaypointSegment {
  duration: number;
  fromIdx: number;
}

// ── Procedural Noise (Inline Deterministic Core) ───────────────

function hashSeed(str: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = (h * 0x01000193) >>> 0;
  }
  return h;
}

function pseudoRand(seed: number, idx: number): number {
  let x = (seed ^ (idx * 2654435761)) >>> 0;
  x = ((x >> 16) ^ x) * 0x45d9f3b >>> 0;
  x = ((x >> 16) ^ x);
  return (x >>> 0) / 0xffffffff;
}

function handInstability(seed: number, idx: number, velocity: number, scale: number = 1.0): { dx: number; dy: number } {
  const speedFactor = Math.min(1, velocity * 20);
  const wobble = 0.18 + speedFactor * 0.55;
  const noiseX = (pseudoRand(seed, idx * 2) - 0.5) * scale * wobble;
  const noiseY = (pseudoRand(seed, idx * 2 + 1) - 0.5) * scale * wobble;
  return { dx: noiseX, dy: noiseY };
}

function strokePressure(t: number, maxPressure: number, seed: number): number {
  const gaussian = Math.exp(-Math.pow((t - 0.3) / 0.4, 2));
  const noise = pseudoRand(seed, Math.floor(t * 100)) * 0.1;
  return Math.min(maxPressure, 0.3 + gaussian * maxPressure + noise);
}

function humanDrawBody(t: number): number {
  if (t <= 0 || t >= 1) return 0;
  return 1 - Math.pow(Math.abs(2 * t - 1), 1.4);
}

function strokeMotionEnvelope(progress: number, difficulty: number, curvature: number): number {
  const clamped = Math.max(0, Math.min(1, progress));
  const entry = Math.min(1, clamped / 0.16);
  const exit = Math.min(1, (1 - clamped) / 0.16);
  const body = 0.72 + 0.38 * humanDrawBody(clamped);
  const curvaturePenalty = 1 - Math.min(0.28, curvature * 0.09);
  const difficultyPenalty = 1 - Math.min(0.38, difficulty * 0.22);
  return Math.max(0.12, entry * exit * body * curvaturePenalty * difficultyPenalty);
}

// ── WaypointPath ───────────────────────────────────────────────

export class WaypointPath {
  private _waypoints: [number, number][];
  private _totalMs: number;
  private _segments: WaypointSegment[];

  constructor(waypoints: [number, number][], totalMs: number) {
    this._waypoints = waypoints;
    this._totalMs = totalMs;
    this._segments = this._buildSegments();
  }

  /**
   * Get target position at relative progress time t (0..1).
   * Smoothly interpolated with a Catmull-Rom spline model.
   */
  public getPosition(t: number): [number, number] {
    if (this._segments.length === 0) return [0, 0];
    if (t <= 0) return this._waypoints.at(0)!;
    if (t >= 1) return this._waypoints.at(this._waypoints.length - 1)!;

    let elapsed = 0;
    for (let i = 0; i < this._segments.length; i++) {
      const seg = this._segments.at(i)!;
      if (elapsed + seg.duration > t) {
        const localT = (t - elapsed) / seg.duration;
        return this._catmullRom(i, localT);
      }
      elapsed += seg.duration;
    }
    return this._waypoints.at(this._waypoints.length - 1)!;
  }

  private _catmullRom(segIdx: number, t: number): [number, number] {
    const pts = this._waypoints;
    const p0 = pts.at(Math.max(0, segIdx - 1))!;
    const p1 = pts.at(segIdx)!;
    const p2 = pts.at(Math.min(pts.length - 1, segIdx + 1))!;
    const p3 = pts.at(Math.min(pts.length - 1, segIdx + 2))!;

    const t2 = t * t;
    const t3 = t2 * t;

    const x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3);
    const y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3);

    return [x, y];
  }

  private _buildSegments(): WaypointSegment[] {
    if (this._waypoints.length < 2) return [];
    const n = this._waypoints.length - 1;
    return Array.from({ length: n }, (_, i) => {
      const p0 = this._waypoints.at(i)!;
      const p1 = this._waypoints.at(i + 1)!;
      const dist = Math.sqrt(Math.pow(p1[0] - p0[0], 2) + Math.pow(p1[1] - p0[1], 2));
      return { duration: dist, fromIdx: i };
    }).map((seg, _, all) => {
      const total = all.reduce((s, x) => s + x.duration, 0);
      return { ...seg, duration: total > 0 ? seg.duration / total : 1 / all.length };
    });
  }
}

// ── ActiveStroke ───────────────────────────────────────────────

export class ActiveStroke {
  public strokeId: string;
  public durationMs: number;
  public color: string;
  public baseThickness: number;
  public startMs: number;
  public difficulty: number;

  public drawnPoints: [number, number][];
  public drawnPressure: number[];
  public drawnWidths: number[];

  public state: STROKE_STATE;
  public progress: number;
  public currentProgress: number;

  public _waypoints: [number, number][];
  public _waypointPath: WaypointPath;
  public _seed: number;
  public _lastPointIndex: number;
  public _cursorX: number;
  public _cursorY: number;
  public _smoothX: number;
  public _smoothY: number;
  public _currentVelocity: number;
  public _lastCurvature: number;

  public _spring: Spring2D;
  public _velocityTracker: VelocityTracker;
  public _phonemePressureMultiplier: number;
  
  // Human Material Modification: Keep track of cumulative trace distance to drive chalk bluntness
  public _accumulatedDistance: number;

  public backendPressures?: number[];
  public backendWidths?: number[];

  constructor({ strokeId, waypoints, targetPath, durationMs = 400, color = "#FFFFFF", thickness = 2, startMs = 0, difficulty = 0.5, pressures, widths }: ActiveStrokeOptions) {
    this.strokeId = strokeId;
    this._waypoints = waypoints || targetPath || [];
    this._waypointPath = new WaypointPath(this._waypoints, durationMs);

    this.durationMs = Math.max(16, durationMs);
    this.color = color;
    this.baseThickness = thickness;
    this.startMs = startMs;
    this.difficulty = difficulty;

    this.drawnPoints = [];
    this.drawnPressure = [];
    this.drawnWidths = [];

    this.state = STROKE_STATE.PENDING;
    this.progress = 0;
    this.currentProgress = 0;

    this._seed = hashSeed(strokeId);
    this._lastPointIndex = 0;
    this._cursorX = 0;
    this._cursorY = 0;
    this._smoothX = 0;
    this._smoothY = 0;
    this._currentVelocity = 0;
    this._lastCurvature = 0;

    this._spring = new Spring2D(SPRING_PRESETS.cursor_drawing);
    this._velocityTracker = new VelocityTracker(80);
    this._phonemePressureMultiplier = 1.0;
    this._accumulatedDistance = 0;

    this.backendPressures = pressures;
    this.backendWidths = widths;
  }
}

// ── StrokeScheduler ────────────────────────────────────────────

export class StrokeScheduler {
  private _activeStrokes: Map<string, ActiveStroke>;
  private _completedStrokes: Map<string, ActiveStroke>;
  private _maxCompleted: number;
  /** Only this stroke may couple to the live cursor — prevents travel-line artifacts. */
  private _activeStrokeId: string | null;

  constructor() {
    this._activeStrokes = new Map<string, ActiveStroke>();
    this._completedStrokes = new Map<string, ActiveStroke>();
    // 2000 keeps every stroke from a long lesson in the motion layer.
    // sceneRenderer takes over rendering for completed strokes (progress ≥ 0.98),
    // so eviction from this cache only matters during live replay / mStrokeLayer mode.
    this._maxCompleted = 2000;
    this._activeStrokeId = null;
  }

  public scheduleStroke(params: ActiveStrokeOptions): string {
    const stroke = new ActiveStroke(params);
    this._activeStrokes.set(params.strokeId, stroke);
    return params.strokeId;
  }

  /**
   * Force-finish a stroke at its semantic endpoint (pen-up boundary).
   */
  public forceComplete(strokeId: string): void {
    const stroke = this._activeStrokes.get(strokeId);
    if (!stroke || stroke.state === STROKE_STATE.COMPLETED) return;
    this._snapStrokeToEndpoint(stroke);
    stroke.state = STROKE_STATE.COMPLETED;
    stroke.progress = 1;
    stroke.currentProgress = 1;
    if (this._activeStrokeId === strokeId) {
      this._activeStrokeId = null;
    }
  }

  /** End every in-progress stroke except an optional successor (used before beginStroke). */
  public forceCompleteAllGrowing(exceptStrokeId?: string): void {
    for (const [id, stroke] of this._activeStrokes) {
      if (id === exceptStrokeId) continue;
      if (stroke.state === STROKE_STATE.GROWING || stroke.state === STROKE_STATE.PAUSED) {
        this.forceComplete(id);
      }
    }
  }

  public getActiveStrokeId(): string | null {
    return this._activeStrokeId;
  }

  public beginStroke(strokeId: string, absoluteTimeMs: number, cursorPosition: { x: number; y: number } | null | undefined): void {
    const stroke = this._activeStrokes.get(strokeId);
    if (!stroke) return;

    this.forceCompleteAllGrowing(strokeId);

    stroke.state = STROKE_STATE.GROWING;
    stroke.startMs = absoluteTimeMs;
    this._activeStrokeId = strokeId;

    const startX = cursorPosition?.x ?? (stroke._waypoints[0]?.[0] || 0);
    const startY = cursorPosition?.y ?? (stroke._waypoints[0]?.[1] || 0);
    stroke._spring.reset(startX, startY);
    stroke._spring.setTarget(startX, startY);
    stroke._cursorX = startX;
    stroke._cursorY = startY;
    stroke._smoothX = startX;
    stroke._smoothY = startY;
    stroke._accumulatedDistance = 0;
  }

  public pauseStroke(strokeId: string): void {
    const stroke = this._activeStrokes.get(strokeId);
    if (stroke && stroke.state === STROKE_STATE.GROWING) stroke.state = STROKE_STATE.PAUSED;
  }

  public resumeStroke(strokeId: string): void {
    const stroke = this._activeStrokes.get(strokeId);
    if (stroke && stroke.state === STROKE_STATE.PAUSED) stroke.state = STROKE_STATE.GROWING;
  }

  public tick(absoluteTimeMs: number, deltaMs: number, cursorPosition: { x: number; y: number } | null | undefined): StrokeRenderState[] {
    const renderStates: StrokeRenderState[] = [];
    const completedKeys: string[] = [];

    for (const [strokeId, stroke] of this._activeStrokes) {
      if (stroke.state === STROKE_STATE.GROWING) {
        const cursorForStroke =
          strokeId === this._activeStrokeId ? cursorPosition : null;
        this._growStroke(stroke, absoluteTimeMs, deltaMs, cursorForStroke);
      }

      if (stroke.state === STROKE_STATE.COMPLETED) {
        if (this._activeStrokeId === strokeId) {
          this._activeStrokeId = null;
        }
        completedKeys.push(strokeId);
        this._completedStrokes.set(strokeId, stroke);
        
        if (this._completedStrokes.size > this._maxCompleted) {
          const firstKey = this._completedStrokes.keys().next().value;
          if (firstKey !== undefined) this._completedStrokes.delete(firstKey);
        }
      }

      renderStates.push(this._getStrokeRenderState(stroke));
    }

    for (const id of completedKeys) {
      this._activeStrokes.delete(id);
    }

    for (const [, stroke] of this._completedStrokes) {
      renderStates.push(this._getStrokeRenderState(stroke));
    }

    return renderStates;
  }

  public getStrokeState(strokeId: string): ActiveStroke | null {
    return this._activeStrokes.get(strokeId) || this._completedStrokes.get(strokeId) || null;
  }

  public getStrokeTip(strokeId: string): { x: number; y: number } | null {
    const stroke = this._activeStrokes.get(strokeId) || this._completedStrokes.get(strokeId);
    if (!stroke) return null;
    if (stroke.state === STROKE_STATE.GROWING) {
      return { x: stroke._smoothX, y: stroke._smoothY };
    }
    if (stroke.drawnPoints.length === 0) return null;
    const last = stroke.drawnPoints.at(-1)!;
    return { x: last[0], y: last[1] };
  }

  public getActiveStrokeTip(): { x: number; y: number } | null {
    for (const stroke of this._activeStrokes.values()) {
      if (stroke.state === STROKE_STATE.GROWING) {
        return { x: stroke._smoothX, y: stroke._smoothY };
      }
    }
    return null;
  }

  public hasActiveStrokes(): boolean {
    for (const [, stroke] of this._activeStrokes) {
      if (stroke.state === STROKE_STATE.GROWING) return true;
    }
    return false;
  }

  public getAllRenderData(): StrokeRenderState[] {
    const data: StrokeRenderState[] = [];
    for (const [, stroke] of this._activeStrokes) data.push(this._getStrokeRenderState(stroke));
    // Completed strokes are NOT included: sceneRenderer's static strokeLayer takes over
    // at progress ≥ 0.98. Including them here double-draws every finished diagram stroke
    // (once on mStrokeLayer from here, once on strokeLayer from sceneRenderer).
    return data;
  }

  public reset(): void {
    this._activeStrokes.clear();
    this._completedStrokes.clear();
    this._activeStrokeId = null;
  }

  // ── Private Internal Architecture Handlers ───────────────────

  private _snapStrokeToEndpoint(stroke: ActiveStroke): void {
    if (stroke._waypoints.length === 0) return;
    const end = stroke._waypointPath.getPosition(1);
    const last = stroke.drawnPoints.at(-1);
    if (!last || Math.hypot(last[0] - end[0], last[1] - end[1]) > 0.5) {
      const stressLevel = audioEventBridge.getStressLevel?.() ?? 0.5;
      stroke.drawnPoints.push([end[0], end[1]]);
      stroke.drawnPressure.push(0.75);
      stroke.drawnWidths.push(stroke.baseThickness * (0.9 + stressLevel * 0.2));
      stroke._cursorX = end[0];
      stroke._cursorY = end[1];
    }
  }

  private _growStroke(stroke: ActiveStroke, absoluteTimeMs: number, deltaMs: number, cursorPosition: { x: number; y: number } | null | undefined): void {
    // ── Audio-clock-driven reveal ────────────────────────────────────
    // Progress is governed by the master audio clock (absoluteTimeMs) relative to
    // the stroke's scheduled start + backend-authored duration, so the pen traces
    // the stroke in LOCKSTEP with narration — exactly like equation _charStates —
    // instead of free-running on frame deltas. Position is still spring-smoothed
    // below for a natural nib. Per-frame catch-up is capped so a one-off clock
    // jump can't snap the whole stroke at once; the runtime clock is already
    // surge-clamped upstream, so steady playback tracks the audio exactly.
    const audioElapsed = absoluteTimeMs - stroke.startMs;

    stroke.currentProgress =
        stroke.durationMs > 0
            ? Math.max(
                  0,
                  Math.min(1, audioElapsed / stroke.durationMs)
              )
            : 1;

    const easedProgress = Easing.humanDraw(stroke.currentProgress);
    stroke.progress = easedProgress;
    const rawProgress = stroke.currentProgress;

    const semanticTarget = stroke._waypointPath.getPosition(easedProgress);

    if (easedProgress > 0.02 && easedProgress < 0.98) {
      const pPrev = stroke._waypointPath.getPosition(easedProgress - 0.015);
      const pCurr = semanticTarget;
      const pNext = stroke._waypointPath.getPosition(easedProgress + 0.015);
      
      const v1 = [pCurr[0] - pPrev[0], pCurr[1] - pPrev[1]];
      const v2 = [pNext[0] - pCurr[0], pNext[1] - pCurr[1]];
      
      const len1 = Math.sqrt(v1[0]*v1[0] + v1[1]*v1[1]);
      const len2 = Math.sqrt(v2[0]*v2[0] + v2[1]*v2[1]);
      if (len1 > 0.1 && len2 > 0.1) {
        const dot = (v1[0]*v2[0] + v1[1]*v2[1]) / (len1 * len2);
        const cosSim = Math.max(-1, Math.min(1, dot));
        stroke._lastCurvature = Math.acos(cosSim);
      }
    } else {
      stroke._lastCurvature = 0;
    }

    const rhythm = audioEventBridge.getCursorRhythm?.() ?? 0.5;
    const stressLevel = audioEventBridge.getStressLevel?.() ?? 0.5;

    stroke._spring.x.stiffness = SPRING_PRESETS.cursor_drawing.stiffness * (0.6 + stressLevel * 0.4);
    stroke._spring.y.stiffness = SPRING_PRESETS.cursor_drawing.stiffness * (0.6 + stressLevel * 0.4);
    stroke._spring.x.damping = SPRING_PRESETS.cursor_drawing.damping * (0.8 + (1.0 - rhythm) * 0.4);
    stroke._spring.y.damping = SPRING_PRESETS.cursor_drawing.damping * (0.8 + (1.0 - rhythm) * 0.4);

    stroke._spring.setTarget(semanticTarget[0], semanticTarget[1]);

    const physPos = stroke._spring.tick(deltaMs);
    stroke._smoothX = physPos.x;
    stroke._smoothY = physPos.y;

    const velocity = stroke._spring.x.velocity ** 2 + stroke._spring.y.velocity ** 2;
    const speed = Math.sqrt(velocity);
    stroke._currentVelocity = speed;

    const settleWeight = Math.max(0, Math.min(1, (rawProgress - 0.82) / 0.18));
    const noiseScale = Math.max(0.05, (0.22 + stroke.difficulty * 0.22) * (1.08 - rhythm * 0.75) * (1 - settleWeight * 0.5));
    const instability = handInstability(stroke._seed, stroke.drawnPoints.length, speed, noiseScale);

    let px = physPos.x + instability.dx;
    let py = physPos.y + instability.dy;

    if (settleWeight > 0) {
      const settleEase = settleWeight * settleWeight;
      px = px + (semanticTarget[0] - px) * settleEase * 0.22;
      py = py + (semanticTarget[1] - py) * settleEase * 0.22;
    }

    if (cursorPosition && Number.isFinite(cursorPosition.x) && Number.isFinite(cursorPosition.y)) {
      const dx = cursorPosition.x - px;
      const dy = cursorPosition.y - py;
      const dist = Math.hypot(dx, dy);
      const coupling = Math.min(0.85, 0.56 + dist / 20);
      px += dx * coupling;
      py += dy * coupling;

      if (dist <= 2.8 || settleWeight > 0.65) {
        px = cursorPosition.x;
        py = cursorPosition.y;
      }

      stroke._smoothX = px;
      stroke._smoothY = py;
    }

    stroke._velocityTracker.addSample(px, py, absoluteTimeMs);
    const { speed: trackedSpeed } = stroke._velocityTracker.getVelocity();

    const lastPoint = stroke.drawnPoints.at(-1);
    const minDist = 0.5;
    if (!lastPoint || Math.sqrt(Math.pow(px - lastPoint[0], 2) + Math.pow(py - lastPoint[1], 2)) >= minDist) {
      if (lastPoint) {
        // Track displacement to calculate chalk wear accumulation
        stroke._accumulatedDistance += Math.hypot(px - lastPoint[0], py - lastPoint[1]);
      }

      const timeSinceStart = Math.max(0, absoluteTimeMs - stroke.startMs);
      const t = Math.min(1, timeSinceStart / stroke.durationMs);
      
      let pressure = 0.8;
      let width = stroke.baseThickness;

      if (stroke.backendPressures && stroke.backendPressures.length > 0 && stroke.backendWidths && stroke.backendWidths.length > 0) {
        const pi = t * (stroke.backendPressures.length - 1);
        const plo = Math.floor(pi);
        const phi = Math.min(stroke.backendPressures.length - 1, plo + 1);
        const f = pi - plo;
        pressure = stroke.backendPressures[plo] + (stroke.backendPressures[phi] - stroke.backendPressures[plo]) * f;

        const wi = t * (stroke.backendWidths.length - 1);
        const wlo = Math.floor(wi);
        const whi = Math.min(stroke.backendWidths.length - 1, wlo + 1);
        width = stroke.backendWidths[wlo] + (stroke.backendWidths[whi] - stroke.backendWidths[wlo]) * f;
      } else {
        const basePressure = strokePressure(t, 0.8, stroke._seed);
        const phonemePressure = 0.6 + stressLevel * 0.4;
        const pressureEnvelope = 0.9 + 0.18 * humanDrawBody(rawProgress);
        pressure = Math.min(1, basePressure * phonemePressure * pressureEnvelope);

        // Width: variations driven dynamically via speed and vocal stress metrics
        const velocityFactor = 1 - Math.min(0.5, trackedSpeed * 50);
        
        // Chalk tip flattening: develops slowly over ~6000px, max +12% width.
        // The old 1800px / +35% threshold made strokes visibly thicken mid-session.
        const wearMultiplier = 1.0 + Math.min(0.12, stroke._accumulatedDistance / 6000);
        const widthEnvelope = 0.92 + 0.2 * humanDrawBody(rawProgress);
        width = stroke.baseThickness * (0.7 + velocityFactor * 0.6) * (0.9 + stressLevel * 0.3) * wearMultiplier * widthEnvelope;

        // HUMAN ENHANCEMENT: Upstroke Asymmetry vs Downstroke Asymmetry
        const isDownstroke = lastPoint && py > lastPoint[1];
        const isUpstroke = lastPoint && py < lastPoint[1];
        let directionPressure = 1.0;
        let directionWidth = 1.0;
        if (lastPoint) {
          const segDx = px - lastPoint[0];
          const segDy = py - lastPoint[1];
          const segLen = Math.max(0.001, Math.hypot(segDx, segDy));
          const verticalBias = segDy / segLen;
          const rightBias = segDx / segLen;

          // Handwriting generally loads heavier on descending, forward-moving strokes.
          directionPressure = 1.0 + Math.max(0, verticalBias) * 0.18 + Math.max(0, rightBias) * 0.05;
          directionWidth = 1.0 + Math.max(0, verticalBias) * 0.16 + Math.max(0, rightBias) * 0.03;

          // Backtracking or lift-like segments should feel lighter.
          if (verticalBias < 0) {
            directionPressure *= 0.9;
            directionWidth *= 0.88;
          }
        }
        
        if (isDownstroke) {
          // High downward pressure vectors matching mechanical gravity drag profiles
          pressure = Math.min(1.0, pressure * (1.18 + stressLevel * 0.12) * directionPressure);
          width = width * (1.25 + stressLevel * 0.15) * directionWidth;
        } else if (isUpstroke) {
          // Wispy, delicate lifting upstrokes matching standard biomechanics
          pressure = Math.max(0.15, pressure * 0.82 * directionPressure);
          width = width * 0.85 * directionWidth;
        } else {
          pressure = Math.min(1.0, pressure * directionPressure);
          width = width * directionWidth;
        }
      }

      stroke.drawnPoints.push([px, py]);
      stroke.drawnPressure.push(pressure);
      stroke.drawnWidths.push(width);

      stroke._cursorX = px;
      stroke._cursorY = py;
    }

    if (rawProgress >= 1.0) {
      stroke.state = STROKE_STATE.COMPLETED;
      stroke.progress = 1;
    }
  }

  private _getStrokeRenderState(stroke: ActiveStroke): StrokeRenderState {
    return {
      strokeId: stroke.strokeId,
      state: stroke.state,
      progress: stroke.progress,
      points: stroke.drawnPoints,
      pressures: stroke.drawnPressure,
      widths: stroke.drawnWidths,
      color: stroke.color,
      baseThickness: stroke.baseThickness,
      completed: stroke.state === STROKE_STATE.COMPLETED,
      cursorX: stroke._cursorX,
      cursorY: stroke._cursorY,
      hasBackendDynamics: Boolean(stroke.backendPressures && stroke.backendPressures.length > 0),
    };
  }
}