/**
 * temporalScheduler.ts — Audio-Reconciled Motion Timeline
 *
 * FIXED (Retained from source context):
 * - Now reconciles with AudioTimeline (master clock) to prevent drift
 * - Added jitter buffer integration for bursty WebSocket events
 * - Added clock interpolation for smooth playback despite network variance
 * - Added priority queues (narration > motion > background)
 *
 * The temporal scheduler is NO LONGER the clock authority.
 * AudioTimeline.currentTimeMs is the master.
 * This scheduler OBSERVES and RECONCILES with it.
 */

import { audioTimeline } from "../audio/audioTimeline";
import { motionJitterBuffer } from "../audio/audioLatencyCompensator";

// ── Struct Data & Domain Interfaces ───────────────────────────

export interface SchedulerEvent {
  type: string;
  start_ms?: number;
  payload?: Record<string, any>;
  _priority?: number;
  [key: string]: any;
}

export interface TickCallbackEntry {
  id: number;
  cb: (currentTimeMs: number, deltaMs: number) => void;
  active: boolean;
}

export interface SchedulerMetrics {
  currentTimeMs: number;
  audioTimeMs: number;
  audioClockDriftMs: number;
  playbackRate: number;
  isRunning: boolean;
  queueDepth: number;
  jitterBufferDepth: number;
  processedCount: number;
  fps: number;
}

export interface TemporalSchedulerTickResult {
  readyEvents: SchedulerEvent[];
  timeMs: number;
  deltaMs: number;
  queueDepth: number;
  fps: number;
  audioClockDriftMs: number;
  jitterBufferDepth: number;
}

export interface PriorityQueueGroup {
  high: SchedulerEvent[];
  normal: SchedulerEvent[];
  low: SchedulerEvent[];
}

// ── Event Priority Allocation ──────────────────────────────────

const EVENT_PRIORITY: Record<string, number> = {
  narration_sync: 0,    // Highest priority — must execute instantly
  speech: 0,
  pen_state: 1,
  cursor_move: 1,
  attention_focus: 2,
  construction_step: 3,
  draw_stroke: 3,
  camera_move: 4,
  cognitive_pause: 5,
  scene_mutation: 5,
  default: 10,
};

function getEventPriority(type: string): number {
  const hasOwn = (obj: any, key: string) => Object.prototype.hasOwnProperty.call(obj, key);
  const isSafe = (key: string) => typeof key === "string" && key !== "__proto__" && key !== "constructor" && key !== "prototype";
  return (type && isSafe(type) && hasOwn(EVENT_PRIORITY, type)) ? Reflect.get(EVENT_PRIORITY, type) : EVENT_PRIORITY.default;
}

// ── TemporalScheduler Class ────────────────────────────────────

export class TemporalScheduler {
  private _absoluteTimeMs: number;
  private _playbackRate: number;
  private _basePlaybackRate: number;
  private _isRunning: boolean;

  private _currentDifficulty: number;
  private _difficultyExpirationMs: number;
  private _activeHesitationExpirationMs: number;

  private _audioClockDriftMs: number;
  private _lastReconcileMs: number;
  private _reconcileIntervalMs: number;
  private _maxCorrectionPerFrameMs: number;

  private _eventQueue: SchedulerEvent[];
  private _priorityQueues: PriorityQueueGroup;
  private _processedCount: number;

  private _useJitterBuffer: boolean;
  private _jitterBufferDepthMs: number;

  private _tickCallbacks: TickCallbackEntry[];

  private _snapshotIntervalMs: number;
  private _lastSnapshotMs: number;
  private _snapshotCallback: ((currentTimeMs: number) => void) | null;

  private _frameCount: number;
  private _lastFpsTime: number;
  private _fps: number;

  private _audioFrameHandle: number | null;

  constructor() {
    // Master tracking context parameters
    this._absoluteTimeMs = 0;
    this._playbackRate = 1.0;
    this._basePlaybackRate = 1.0; // Pacing rate requested by the client user interface
    this._isRunning = false;

    // Pedagogical pacer tracking matrices
    this._currentDifficulty = 0.5;
    this._difficultyExpirationMs = 0;
    this._activeHesitationExpirationMs = 0;

    // Drift alignment metrics
    this._audioClockDriftMs = 0;
    this._lastReconcileMs = 0;
    this._reconcileIntervalMs = 100; // Sample delta constraint window
    this._maxCorrectionPerFrameMs = 5; // Dampened correction step limit

    // Allocation storage registers
    this._eventQueue = [];
    this._priorityQueues = {
      high: [],
      normal: [],
      low: [],
    };
    this._processedCount = 0;

    // Jitter state controls
    this._useJitterBuffer = true;
    this._jitterBufferDepthMs = 150;

    this._tickCallbacks = [];

    this._snapshotIntervalMs = 5000;
    this._lastSnapshotMs = 0;
    this._snapshotCallback = null;

    this._frameCount = 0;
    this._lastFpsTime = 0;
    this._fps = 60;

    this._audioFrameHandle = null;
    this._connectToAudioTimeline();
  }

  // ── Authoritative Clock API ──────────────────────────────────

  /**
   * Retrieves current time context anchored directly to the media clock if running.
   */
  public get currentTimeMs(): number {
    if (audioTimeline.state === "playing") {
      return audioTimeline.currentTimeMs;
    }
    return this._absoluteTimeMs;
  }

  public get playbackRate(): number { 
    return this._playbackRate; 
  }

  public setPlaybackRate(rate: number): void {
    this._basePlaybackRate = Math.max(0.1, Math.min(4.0, rate));
    // Dynamic pacer will interpolate values seamlessly during the next loop pass
  }

  public start(): void {
    this._isRunning = true;
    this._connectToAudioTimeline();
    audioTimeline.start(this._absoluteTimeMs);
  }

  public pause(): void {
    this._isRunning = false;
    audioTimeline.pause();
  }

  public resume(): void {
    this._isRunning = true;
    audioTimeline.resume();
  }

  // ── Callback Subscriptions API ───────────────────────────────

  public onTick(cb: (currentTimeMs: number, deltaMs: number) => void): number {
    const id = this._tickCallbacks.length;
    this._tickCallbacks.push({ id, cb, active: true });
    return id;
  }

  public removeTick(callbackId: number): void {
    const entry = this._tickCallbacks.find(c => c.id === callbackId);
    if (entry) entry.active = false;
  }

  public onSnapshot(cb: (currentTimeMs: number) => void): void { 
    this._snapshotCallback = cb; 
  }

  // ── Event Queue Allocation API ───────────────────────────────

  /**
   * Enqueue an event. Routes immediately through priority pipelines.
   */
  public enqueueEvent(event: SchedulerEvent): void {
    const priority = getEventPriority(event.type);

    if (this._useJitterBuffer && priority >= 3) {
      // Stream un-critical drawing segments directly through network smoothing buffers
      motionJitterBuffer.push(event);
    } else {
      // Immediate structural items bypass buffer tracks
      this._insertSorted(event, priority);
    }
  }

  /**
   * Enqueue a batch array of action blocks.
   */
  public enqueueEvents(events: SchedulerEvent[]): void {
    for (const event of events) {
      this.enqueueEvent(event);
    }
  }

  // ── Main Ticker Frame Processing Pass ────────────────────────

  /**
   * Core frame processing sequence driving visual tracks.
   * Smoothly reconciles coordinate drifts against the hardware audio playhead.
   *
   * @param deltaMs - Discrete temporal frame slice length milliseconds
   * @returns Telemetry metrics tracking performance outputs
   */
  public tick(deltaMs: number): TemporalSchedulerTickResult {
    if (!this._isRunning) {
      return { 
        readyEvents: [], 
        timeMs: this._absoluteTimeMs,
        deltaMs,
        queueDepth: this._eventQueue.length,
        fps: this._fps,
        audioClockDriftMs: this._audioClockDriftMs,
        jitterBufferDepth: motionJitterBuffer.depth
      };
    }

    // ── 1. Reconcile with Audio Master Clock Time Domain ─────
    const audioTimeMs = audioTimeline.currentTimeMs;

    if (audioTimeline.state === "playing" && audioTimeMs > 0) {
      const drift = audioTimeMs - this._absoluteTimeMs;
      
      if (Math.abs(drift) > 30) {
        // Enforce hard positional snaps for massive skips to eliminate layout desyncs
        this._absoluteTimeMs = audioTimeMs;
        this._audioClockDriftMs = 0;
      } else if (Math.abs(drift) > 1) {
        // Correct incremental frame slips smoothly without forcing optical canvas pops
        const correction = Math.sign(drift) * Math.min(Math.abs(drift), this._maxCorrectionPerFrameMs);
        this._absoluteTimeMs += correction;
        this._audioClockDriftMs = drift;
      } else {
        this._absoluteTimeMs = audioTimeMs;
      }
    } else {
      // Fallback independent progression mapping if timeline track drops
      const scaledDelta = deltaMs * this._playbackRate;
      this._absoluteTimeMs += scaledDelta;
    }

    const currentMs = this.currentTimeMs;

    // ── 2. (removed) Transport jitter buffer is owned solely by wsClient ──
    // The shared transport buffer (motionJitterBuffer) must have EXACTLY ONE
    // consumer. This scheduler previously also drained it every frame, racing
    // wsClient's delivery loop — whichever drained a given event first won, and
    // the events this scheduler drained were harvested below and then discarded
    // (teacherMotor.tick ignores tick()'s return value). That silently dropped
    // normal-priority events: draw_stroke / equation_write / annotation /
    // stroke_reveal / construction_step / scene_mutation. wsClient is now the
    // sole drainer, so those events always reach runtimeStore.

    // ── 3. Harvest Due Actions Ordered Strictly by Priority ──
    const readyEvents: SchedulerEvent[] = [];

    while (this._eventQueue.length > 0) {
      const next = this._eventQueue[0];
      if ((next.start_ms || 0) <= currentMs) {
        const evt = this._eventQueue.shift()!;
        readyEvents.push(evt);
        this._processedCount++;

        // Adaptive Pacer Trackers: Intercept cognitive weights to modulate speeds
        if (evt.payload) {
          const p = evt.payload;
          if (p.difficulty !== undefined) {
            this._currentDifficulty = p.difficulty;
            this._difficultyExpirationMs = currentMs + (p.duration_ms || 1000);
          }
          if (evt.type === "cognitive_pause" || evt.type === "pause_emphasis") {
            this._activeHesitationExpirationMs = currentMs + (p.duration_ms || 400);
          }
          if (evt.type === "narration_sync" && (p.visual_action === "highlight" || p.visual_action === "focus")) {
            this._currentDifficulty = 0.85; // Analytical insight triggers drop overall trace speeds
            this._difficultyExpirationMs = currentMs + (p.duration_ms || 800);
          }
        }
      } else {
        break;
      }
    }

    // ── 4. Recalculate Whiteboard Interactivity Pacing Scales 
    this._updatePedagogicalPacing();

    // ── 5. Process Subscribed Execution Hooks ────────────────
    for (const entry of this._tickCallbacks) {
      if (entry.active) {
        try { 
          entry.cb(currentMs, deltaMs); 
        } catch (e) { 
          /* Execution Guard isolation */ 
        }
      }
    }

    // ── 6. Metrics Telemetry Logging ─────────────────────────
    this._frameCount++;
    if (currentMs - this._lastFpsTime >= 1000) {
      this._fps = this._frameCount;
      this._frameCount = 0;
      this._lastFpsTime = currentMs;
    }

    if (this._snapshotCallback && currentMs - this._lastSnapshotMs >= this._snapshotIntervalMs) {
      this._snapshotCallback(currentMs);
      this._lastSnapshotMs = currentMs;
    }

    return {
      readyEvents,
      timeMs: currentMs,
      deltaMs,
      queueDepth: this._eventQueue.length,
      fps: this._fps,
      audioClockDriftMs: this._audioClockDriftMs,
      jitterBufferDepth: motionJitterBuffer.depth,
    };
  }

  /**
   * Reposition playhead indices type-safely across global boundaries.
   */
  public seekTo(targetMs: number): void {
    this._absoluteTimeMs = Math.max(0, targetMs);
    audioTimeline.seek(targetMs);
    motionJitterBuffer.reset();
  }

  /**
   * Fetch current running operational parameters snapshot.
   */
  public getMetrics(): SchedulerMetrics {
    return {
      currentTimeMs: this._absoluteTimeMs,
      audioTimeMs: audioTimeline.currentTimeMs,
      audioClockDriftMs: this._audioClockDriftMs,
      playbackRate: this._playbackRate,
      isRunning: this._isRunning,
      queueDepth: this._eventQueue.length,
      jitterBufferDepth: motionJitterBuffer.depth,
      processedCount: this._processedCount,
      fps: this._fps,
    };
  }

  public flushQueue(): void {
    this._eventQueue = [];
    motionJitterBuffer.reset();
  }

  public reset(): void {
    this._absoluteTimeMs = 0;
    this._eventQueue = [];
    this._processedCount = 0;
    this._isRunning = false;
    this._lastSnapshotMs = 0;
    this._frameCount = 0;
    this._audioClockDriftMs = 0;
    this._currentDifficulty = 0.5;
    this._difficultyExpirationMs = 0;
    this._activeHesitationExpirationMs = 0;
    if (this._audioFrameHandle !== null) {
      audioTimeline.offFrame(this._audioFrameHandle);
      this._audioFrameHandle = null;
    }
    motionJitterBuffer.reset();
  }

  // ── Private Internal Mathematical Engines ──────────────────

  /**
   * Modulates the pacing velocity smoothly based on cognitive load models.
   * Prevents layout desyncs and eliminates audible pitch pops during track scaling.
   */
  private _updatePedagogicalPacing(): void {
    const currentMs = this._absoluteTimeMs;
    
    // Decay abstract stress values back down to a baseline 0.4 rest state over time
    if (currentMs > this._difficultyExpirationMs) {
      this._currentDifficulty = this._currentDifficulty * 0.96 + 0.4 * 0.04;
    }

    let targetRate = 1.0;
    
    if (this._currentDifficulty > 0.6) {
      // Decelerate through highly complex items (up to 25% dampening floor at 0.75x)
      targetRate = 1.0 - (this._currentDifficulty - 0.6) * 0.625;
    } else if (this._currentDifficulty < 0.3) {
      // Confidently cruise through basic operations (up to 20% acceleration ceiling at 1.20x)
      targetRate = 1.0 + (0.3 - this._currentDifficulty) * 0.66;
    }

    // Embed strict focus scales during processing pauses (enforcing 0.65x crawl rate)
    if (currentMs <= this._activeHesitationExpirationMs) {
      targetRate = Math.min(targetRate, 0.65);
    }

    const scaledTarget = targetRate * this._basePlaybackRate;

    // Intercalate tracking steps via exponential smoothing equations to shield system audio engines
    const smoothRate = this._playbackRate * 0.92 + scaledTarget * 0.08;

    if (Math.abs(this._playbackRate - smoothRate) > 0.01) {
      this._playbackRate = Math.max(0.25, Math.min(4.0, smoothRate));
      audioTimeline.setPlaybackRate(this._playbackRate);
    }
  }

  /**
   * Ingress an element onto sorted tracks via dual-parameter binary search layout passes.
   */
  private _insertSorted(event: SchedulerEvent, priority: number): void {
    const startMs = event.start_ms || 0;
    const enriched: SchedulerEvent = { ...event, _priority: priority };

    let lo = 0;
    let hi = this._eventQueue.length;
    
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      const e = this._eventQueue[mid];
      const eStart = e.start_ms || 0;
      
      if (eStart < startMs || (eStart === startMs && e._priority! <= priority)) {
        lo = mid + 1;
      } else {
        hi = mid;
      }
    }
    
    this._eventQueue.splice(lo, 0, enriched);
  }

  private _connectToAudioTimeline(): void {
    if (this._audioFrameHandle !== null) {
      audioTimeline.offFrame(this._audioFrameHandle);
    }
    this._audioFrameHandle = audioTimeline.onFrame((timeMs: number, deltaMs: number) => {
      if (this._isRunning) {
        this._lastReconcileMs = timeMs;
      }
    });
  }
}