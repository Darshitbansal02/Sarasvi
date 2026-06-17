import { hashSeed } from "./proceduralNoise";

export enum GESTURE_TYPE {
  CIRCLE = "circle",
  UNDERLINE = "underline",
  POINT = "point",
  TAP = "tap",
  BRACKET = "bracket",
  ARROW = "arrow",
  WAVE = "wave",
}

export interface GestureBounds {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
}

export interface StartGestureParams {
  gestureId: string;
  gestureType: GESTURE_TYPE | string;
  bounds: GestureBounds;
  durationMs?: number;
  emphasis?: number;
  color?: number;
  startMs?: number;
  path?: [number, number][]; // Precomputed path from backend
}

export interface GestureState {
  gestureId: string;
  gestureType: GESTURE_TYPE | string;
  bounds: GestureBounds;
  durationMs: number;
  emphasis: number;
  color: number;
  startMs: number;
  progress: number;
  pathPoints: [number, number][];
  seed: number;
  active: boolean;
  currentPathIndex: number;
}

export interface GestureRenderData {
  gestureId: string;
  gestureType: GESTURE_TYPE | string;
  path: [number, number][];
  progress: number;
  alpha: number;
  color: number;
  thickness: number;
}

export class GestureDynamics {
  private _activeGestures: Map<string, GestureState>;
  private _gestureQueue: any[];

  constructor() {
    this._activeGestures = new Map<string, GestureState>();
    this._gestureQueue = [];
  }

  public startGesture({
    gestureId,
    gestureType,
    bounds,
    durationMs = 600,
    emphasis = 0.7,
    color = 0xf2cc60,
    startMs = 0,
    path = []
  }: StartGestureParams): void {
    const seed = hashSeed(gestureId);
    
    // Use precomputed path if supplied by backend, otherwise fall back to simple circle bounds
    let pathPoints = path;
    if (!pathPoints || pathPoints.length === 0) {
      const { x = 0, y = 0, width = 100, height = 50 } = bounds || {};
      const cx = x + width / 2;
      const cy = y + height / 2;
      pathPoints = [[cx, cy], [cx + 10, cy + 10]]; // simple fallback stub
    }

    this._activeGestures.set(gestureId, {
      gestureId,
      gestureType,
      bounds,
      durationMs,
      emphasis,
      color,
      startMs,
      progress: 0,
      pathPoints,
      seed,
      active: true,
      currentPathIndex: 0,
    });
  }

  public tick(absoluteTimeMs: number): GestureRenderData[] {
    const renderData: GestureRenderData[] = [];
    const removalQueue: string[] = [];

    for (const [gestureId, gesture] of this._activeGestures) {
      const elapsed = absoluteTimeMs - gesture.startMs;
      gesture.progress = Math.max(0, Math.min(1, elapsed / Math.max(1, gesture.durationMs)));

      if (gesture.progress >= 1) {
        const fadeElapsed = elapsed - gesture.durationMs;
        if (fadeElapsed > 500) {
          removalQueue.push(gestureId);
          continue;
        }

        renderData.push({
          gestureId,
          gestureType: gesture.gestureType,
          path: gesture.pathPoints,
          progress: 1,
          alpha: Math.max(0, 1 - fadeElapsed / 500),
          color: gesture.color,
          thickness: 2 + gesture.emphasis * 2,
        });
      } else {
        renderData.push({
          gestureId,
          gestureType: gesture.gestureType,
          path: gesture.pathPoints,
          progress: gesture.progress,
          alpha: gesture.emphasis,
          color: gesture.color,
          thickness: 2 + gesture.emphasis * 2,
        });
      }
    }

    for (const id of removalQueue) {
      this._activeGestures.delete(id);
    }

    return renderData;
  }

  public hasActiveGestures(): boolean {
    return this._activeGestures.size > 0;
  }

  public reset(): void {
    this._activeGestures.clear();
    this._gestureQueue = [];
  }
}