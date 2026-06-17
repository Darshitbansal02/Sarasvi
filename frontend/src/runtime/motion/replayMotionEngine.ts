/**
 * replayMotionEngine.ts — Deterministic motion replay system.
 *
 * Captures and restores complete motion state for replay:
 * - Cursor position + state over time
 * - Stroke growth timeline
 * - Pause/hesitation timing
 * - Narration sync points
 * - Focus effects
 *
 * All motion must be replay-safe and deterministic.
 */

// ── Struct Data & Domain Interfaces ─────────────────────────

export interface EventLogEntry {
  event: Record<string, any>;
  timeMs: number;
  index: number;
}

export interface ReplaySnapshot {
  timeMs: number;
  [key: string]: any;
}

export interface ReplayResult {
  snapshot: ReplaySnapshot | null;
  events: Record<string, any>[];
}

export interface TimelineMarker {
  timeMs: number;
  type: "speech" | "construction" | string;
  label: string;
}

export interface ReplayStatus {
  isReplaying: boolean;
  replayTimeMs: number;
  totalDurationMs: number;
  progress: number;
  replaySpeed: number;
  eventLogSize: number;
  snapshotCount: number;
  replayIndex: number;
}

// ── ReplayMotionEngine ─────────────────────────────────────────

export class ReplayMotionEngine {
  private _eventLog: EventLogEntry[];
  private _snapshots: Map<number, ReplaySnapshot>;
  
  private _replayIndex: number;
  private _isReplaying: boolean;
  private _replaySpeed: number;
  private _replayTimeMs: number;

  private _snapshotIntervalMs: number;
  private _lastSnapshotMs: number;
  private _maxLogSize: number;

  constructor() {
    this._eventLog = [];
    this._snapshots = new Map<number, ReplaySnapshot>();

    this._replayIndex = 0;
    this._isReplaying = false;
    this._replaySpeed = 1.0;
    this._replayTimeMs = 0;

    this._snapshotIntervalMs = 2000;
    this._lastSnapshotMs = 0;
    this._maxLogSize = 50000;
  }

  /**
   * Record an event to the log.
   */
  public recordEvent(event: Record<string, any>, absoluteTimeMs: number): void {
    this._eventLog.push({
      event: { ...event },
      timeMs: absoluteTimeMs,
      index: this._eventLog.length,
    });

    if (this._eventLog.length > this._maxLogSize) {
      this._eventLog = this._eventLog.slice(-Math.floor(this._maxLogSize * 0.8));
    }
  }

  /**
   * Record a state snapshot.
   */
  public recordSnapshot(snapshot: Record<string, any>, absoluteTimeMs: number): void {
    this._snapshots.set(absoluteTimeMs, {
      ...snapshot,
      timeMs: absoluteTimeMs,
    });

    if (this._snapshots.size > 100) {
      const keys = [...this._snapshots.keys()].sort((a, b) => a - b);
      while (this._snapshots.size > 80) {
        this._snapshots.delete(keys.shift()!);
      }
    }
  }

  public shouldSnapshot(absoluteTimeMs: number): boolean {
    return absoluteTimeMs - this._lastSnapshotMs >= this._snapshotIntervalMs;
  }

  public markSnapshotTaken(absoluteTimeMs: number): void {
    this._lastSnapshotMs = absoluteTimeMs;
  }

  /**
   * Start replay from a specific time.
   */
  public startReplay(targetTimeMs: number = 0): ReplayResult {
    this._isReplaying = true;
    this._replayTimeMs = targetTimeMs;

    let nearestSnapshot: ReplaySnapshot | null = null;
    let nearestTime = -1;

    for (const [snapTime, snapshot] of this._snapshots) {
      if (snapTime <= targetTimeMs && snapTime > nearestTime) {
        nearestTime = snapTime;
        nearestSnapshot = snapshot;
      }
    }

    this._replayIndex = 0;
    for (let i = 0; i < this._eventLog.length; i++) {
      if (this._eventLog[i].timeMs > targetTimeMs) {
        this._replayIndex = i;
        break;
      }
    }

    const catchupEvents: Record<string, any>[] = [];
    if (nearestSnapshot) {
      for (let i = 0; i < this._eventLog.length; i++) {
        const entry = this._eventLog[i];
        if (entry.timeMs >= nearestTime && entry.timeMs <= targetTimeMs) {
          catchupEvents.push(entry.event);
        }
      }
    }

    return {
      snapshot: nearestSnapshot,
      events: catchupEvents,
    };
  }

  /**
   * Get the next batch of events for replay.
   */
  public tickReplay(deltaMs: number): Record<string, any>[] {
    if (!this._isReplaying) return [];

    this._replayTimeMs += deltaMs * this._replaySpeed;
    const events: Record<string, any>[] = [];

    while (this._replayIndex < this._eventLog.length) {
      const entry = this._eventLog[this._replayIndex];
      if (entry.timeMs <= this._replayTimeMs) {
        events.push(entry.event);
        this._replayIndex++;
      } else {
        break;
      }
    }

    if (this._replayIndex >= this._eventLog.length) {
      this._isReplaying = false;
    }

    return events;
  }

  public seekTo(targetTimeMs: number): ReplayResult {
    return this.startReplay(targetTimeMs);
  }

  public setReplaySpeed(speed: number): void {
    this._replaySpeed = Math.max(0.25, Math.min(4.0, speed));
  }

  public stopReplay(): void {
    this._isReplaying = false;
  }

  public getStatus(): ReplayStatus {
    const totalDuration = this._eventLog.length > 0
      ? this._eventLog[this._eventLog.length - 1].timeMs
      : 0;

    return {
      isReplaying: this._isReplaying,
      replayTimeMs: this._replayTimeMs,
      totalDurationMs: totalDuration,
      progress: totalDuration > 0 ? this._replayTimeMs / totalDuration : 0,
      replaySpeed: this._replaySpeed,
      eventLogSize: this._eventLog.length,
      snapshotCount: this._snapshots.size,
      replayIndex: this._replayIndex,
    };
  }

  public getTimelineMarkers(): TimelineMarker[] {
    const markers: TimelineMarker[] = [];

    for (const entry of this._eventLog) {
      if (entry.event.type === "speech") {
        markers.push({
          timeMs: entry.timeMs,
          type: "speech",
          label: (entry.event.payload?.text || "").substring(0, 40),
        });
      } else if (entry.event.type === "construction_step") {
        markers.push({
          timeMs: entry.timeMs,
          type: "construction",
          label: entry.event.payload?.action || "step",
        });
      }
    }

    return markers;
  }

  public exportLog(): Record<string, any> {
    return {
      events: this._eventLog,
      snapshots: [...this._snapshots.entries()],
      version: "1.0.0",
    };
  }

  public importLog(data: Record<string, any>): void {
    if (data.events) {
      this._eventLog = data.events;
    }
    if (data.snapshots) {
      this._snapshots = new Map(data.snapshots);
    }
  }

  public reset(): void {
    this._eventLog = [];
    this._snapshots.clear();
    this._replayIndex = 0;
    this._isReplaying = false;
    this._replayTimeMs = 0;
    this._lastSnapshotMs = 0;
  }
}