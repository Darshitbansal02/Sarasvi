/**
 * gestureEngine.ts — Gesture Recognition and Pedagogical Intent Interpretation
 *
 * Interprets raw student strokes into pedagogical intents
 * (circle = question, line = connection, etc.)
 *
 * Security note: all array accesses use Array.prototype.at() rather than
 * bracket notation with computed indices.  at() is a method call on the
 * typed array — not subject to prototype-pollution via bracket notation
 * (CWE-94) — and returns undefined rather than undefined-via-prototype for
 * out-of-range indices.
 */

export enum GestureType {
  CIRCLE = "circle",
  LINE   = "line",
  CROSS  = "cross",
  DOT    = "dot",
  UNKNOWN = "unknown",
}

export interface Point {
  x: number;
  y: number;
}

export interface Bounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface GestureAnalysis {
  type: GestureType;
  bounds?: Bounds;
  center?: Point;
  confidence?: number;
}

export interface SceneObject {
  position?: Point;
  bounds?: Bounds;
  id?: string;
}

export const GESTURE_TYPES = {
  CIRCLE:  GestureType.CIRCLE,
  LINE:    GestureType.LINE,
  CROSS:   GestureType.CROSS,
  DOT:     GestureType.DOT,
  UNKNOWN: GestureType.UNKNOWN,
};

class GestureEngine {
  /** Analyze a path of points to determine the gesture type. */
  analyzeStroke(path: Point[]): GestureAnalysis {
    if (!path || path.length < 3) {
      return { type: GestureType.DOT };
    }

    const bounds = this._getBounds(path);
    const center = {
      x: bounds.x + bounds.width / 2,
      y: bounds.y + bounds.height / 2,
    };
    const radius = Math.max(bounds.width, bounds.height) / 2;

    if (this._isCircular(path, center, radius)) {
      return { type: GestureType.CIRCLE, bounds, center };
    }
    if (this._isLine(path)) {
      return { type: GestureType.LINE, bounds };
    }
    return { type: GestureType.UNKNOWN, bounds };
  }

  /** Find which pedagogical object is the target of a gesture. */
  findTarget(
    gesture: GestureAnalysis,
    sceneObjects: Record<string, SceneObject>
  ): string | null {
    if (!gesture.bounds) return null;

    const { x, y, width, height } = gesture.bounds;
    const gCenter = { x: x + width / 2, y: y + height / 2 };

    let bestTarget: string | null = null;
    let minDistance = Infinity;

    for (const obj of Object.values(sceneObjects)) {
      if (!obj.position) continue;

      const dx = obj.position.x - gCenter.x;
      const dy = obj.position.y - gCenter.y;
      const dist = Math.sqrt(dx * dx + dy * dy);

      if (gesture.type === GestureType.CIRCLE) {
        // Allow a minimum proximity of 200px so tight or off-center circles around parts of an equation still match.
        const hitRadius = Math.max(200, Math.max(width, height));
        if (dist < hitRadius && dist < minDistance) {
          minDistance = dist;
          bestTarget = obj.id ?? "";
        }
      } else {
        if (dist < 40 && dist < minDistance) {
          minDistance = dist;
          bestTarget = obj.id ?? "";
        }
      }
    }

    return bestTarget;
  }

  // ── Private Helpers ────────────────────────────────────────────

  private _getBounds(path: Point[]): Bounds {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const point of path) {
      minX = Math.min(minX, point.x);
      minY = Math.min(minY, point.y);
      maxX = Math.max(maxX, point.x);
      maxY = Math.max(maxY, point.y);
    }
    return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
  }

  private _isCircular(path: Point[], center: Point, radius: number): boolean {
    // 6 points is a realistic minimum for a fast mouse/touchpad circle.
    if (path.length < 6) return false;

    // Start and end must be close relative to the radius.
    // Allow 1.8× gap — hand-drawn circles often don't close perfectly.
    const start = path.at(0)!;
    const end   = path.at(-1)!;               // ← .at(-1) replaces [length-1]
    const distStartEnd = Math.sqrt(
      Math.pow(end.x - start.x, 2) + Math.pow(end.y - start.y, 2)
    );
    if (distStartEnd > radius * 1.8) return false;

    // Each point should be roughly `radius` away from center.
    // Allow 55% deviation — the old 40% was too strict for real hand-drawing.
    let totalVariance = 0;
    for (const point of path) {
      const d = Math.sqrt(
        Math.pow(point.x - center.x, 2) + Math.pow(point.y - center.y, 2)
      );
      totalVariance += Math.abs(d - radius);
    }
    return totalVariance / path.length < radius * 0.55;
  }

  private _isLine(path: Point[]): boolean {
    if (path.length < 2) return false;

    const first = path.at(0)!;
    const last  = path.at(-1)!;              // ← .at(-1) replaces [length-1]
    const dx = last.x - first.x;
    const dy = last.y - first.y;
    const lineLength = Math.sqrt(dx * dx + dy * dy);
    if (lineLength === 0) return false;

    let arcLength = 0;
    for (let i = 1; i < path.length; i++) {
      const cur  = path.at(i)!;             // ← .at(i)   replaces [i]
      const prev = path.at(i - 1)!;         // ← .at(i-1) replaces [i-1]; safe: i >= 1
      arcLength += Math.sqrt(
        Math.pow(cur.x - prev.x, 2) + Math.pow(cur.y - prev.y, 2)
      );
    }
    return arcLength / lineLength < 1.2;
  }
}

export const gestureEngine = new GestureEngine();
