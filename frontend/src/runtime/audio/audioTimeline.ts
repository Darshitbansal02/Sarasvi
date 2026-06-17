/**
 * audioTimeline.ts — Authoritative Audio Master Clock
 *
 * THE single source of temporal truth for the entire teaching runtime.
 * ALL motion, drawing, cursor, narration, and camera must synchronize TO this clock.
 *
 * Architecture:
 * AudioContext.currentTime (hardware clock)
 * → AudioTimeline (master authority)
 * → TemporalScheduler (motion events)
 * → NarrationSync (speech anchors)
 * → CursorActor (drawing position)
 * → StrokeScheduler (stroke growth)
 * → CameraController (attention shifts)
 *
 * Key principle: Nothing draws until audio says so.
 */

// ── Audio Timeline States ──────────────────────────────────────

export enum AUDIO_TIMELINE_STATE {
  IDLE = "idle",
  LOADING = "loading",
  READY = "ready",
  PLAYING = "playing",
  PAUSED = "paused",
  BUFFERING = "buffering",
  COMPLETED = "completed",
  ERROR = "error",
}

// ── Struct & Callback Interfaces ───────────────────────────────

export interface SpeechMark {
  time: number;
  type: string;
  value: string;
  start: number;
  end: number;
  absoluteMs?: number;
  _fired?: boolean;
  duration?: number;
  word_index?: number;
}

export interface SegmentRegistryEntry {
  startMs: number;
  durationMs: number;
  marks: SpeechMark[];
  _markCursor?: number;
}

export interface CurrentWordResult {
  word: string;
  startMs: number;
  endMs: number;
}

export interface AudioTimelineMetrics {
  state: AUDIO_TIMELINE_STATE;
  currentTimeMs: number;
  playbackRate: number;
  latencyOffsetMs: number;
  driftMs: number;
  fps: number;
  segmentCount: number;
  audioContextState: string;
}

export interface FrameCallbackEntry {
  handle: number;
  cb: (timeMs: number, deltaMs: number) => void;
  active: boolean;
}

export type SubscriberCallback = (timeMs: number, readyMarks: SpeechMark[]) => void;

// ── Clock Reconciliation ───────────────────────────────────────

class DriftCompensator {
  private _alpha: number;
  private _drift: number;
  private _samples: number[];
  private _maxSamples: number;

  constructor(alpha: number = 0.1) {
    this._alpha = alpha;
    this._drift = 0;
    this._samples = [];
    this._maxSamples = 20;
  }

  public addSample(serverMs: number, clientMs: number): void {
    const drift = clientMs - serverMs;
    this._samples.push(drift);
    if (this._samples.length > this._maxSamples) {
      this._samples.shift();
    }
    
    // Median drift (robust against outliers)
    const sorted = [...this._samples].sort((a, b) => a - b);
    this._drift = sorted[Math.floor(sorted.length / 2)];
  }

  public get correctedOffsetMs(): number {
    return this._drift;
  }

  public reset(): void {
    this._drift = 0;
    this._samples = [];
  }
}

// ── AudioTimeline ──────────────────────────────────────────────

export class AudioTimeline {
  public _audioContext: AudioContext | null;
  public state: AUDIO_TIMELINE_STATE;

  private _masterTimeMs: number;
  private _startAudioContextTime: number;
  private _startWallTime: number;
  private _playbackRate: number;
  private _isRunning: boolean;
  private _latencyOffsetMs: number;
  private _driftCompensator: DriftCompensator;
  private _speechMarks: SpeechMark[];
  private _speechMarkCursor: number;
  private _segments: Map<string, SegmentRegistryEntry>;
  private _subscribers: Map<string, SubscriberCallback>;
  private _frameCallbacks: FrameCallbackEntry[];
  private _lastFrameTime: number;
  private _frameCount: number;
  private _fps: number;
  private _rafHandle: number | null;
  private _autoSuspendedByVisibility: boolean;

  constructor() {
    this._audioContext = null;
    this.state = AUDIO_TIMELINE_STATE.IDLE;

    // Master time tracking
    this._masterTimeMs = 0;
    this._startAudioContextTime = 0;
    this._startWallTime = 0;

    // Playback state
    this._playbackRate = 1.0;
    this._isRunning = false;

    // Latency & Drift systems
    this._latencyOffsetMs = 0;
    this._driftCompensator = new DriftCompensator();

    // Registry allocations
    this._speechMarks = [];
    this._speechMarkCursor = 0;
    this._segments = new Map();
    this._subscribers = new Map();
    this._frameCallbacks = [];

    // Performance telemetry
    this._lastFrameTime = 0;
    this._frameCount = 0;
    this._fps = 60;
    this._rafHandle = null;
    this._autoSuspendedByVisibility = false;
  }

  // ── Public API ─────────────────────────────────────────────

  /**
   * Initialize AudioContext. Call on first user gesture.
   */
  public async init(): Promise<void> {
    if (this._audioContext) {
      if (this._audioContext.state === "suspended") {
        this._audioContext.resume().catch(e => console.warn("[AudioTimeline] Resume failed:", e));
      }
      return;
    }
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      this._audioContext = new AudioCtx({ latencyHint: "interactive" });
      if (this._audioContext.state === "suspended") {
        this._audioContext.resume().catch(e => console.warn("[AudioTimeline] Resume on create failed:", e));
      }

      // Measure actual output hardware latency boundaries
      if ((this._audioContext as any).outputLatency !== undefined) {
        this._latencyOffsetMs = (this._audioContext as any).outputLatency * 1000;
      } else if ((this._audioContext as any).baseLatency !== undefined) {
        this._latencyOffsetMs = (this._audioContext as any).baseLatency * 1000 + 20;
      } else {
        this._latencyOffsetMs = 80; // Fallback bound
      }

      this.state = AUDIO_TIMELINE_STATE.READY;
    } catch (err) {
      console.warn("[AudioTimeline] AudioContext failed, using wall clock fallback:", err);
      this._latencyOffsetMs = 100;
      this.state = AUDIO_TIMELINE_STATE.READY;
    }
    this._setupVisibilityHandler();
  }

  /**
   * Register a TTS segment with its speech marks.
   */
  public registerSegment(segmentId: string, absoluteStartMs: number, durationMs: number, speechMarks: SpeechMark[] = []): void {
    this._segments.set(segmentId, {
      startMs: absoluteStartMs,
      durationMs,
      marks: speechMarks.map(mark => ({
        ...mark,
        absoluteMs: absoluteStartMs + mark.time,
        _fired: false
      })),
    });
  }

  /**
   * Start playback authority context.
   */
  public start(fromMs: number = 0): void {
    this._masterTimeMs = fromMs;
    this._startWallTime = performance.now();
    if (this._audioContext) {
      this._startAudioContextTime = this._audioContext.currentTime;
    }
    this._isRunning = true;
    this.state = AUDIO_TIMELINE_STATE.PLAYING;
    this._scheduleFrame();
  }

  /**
   * Pause playback timeline.
   *
   * Suspends the AudioContext too: that halts every already-scheduled edge-tts
   * source AND freezes audioContext.currentTime, so the master clock (which is
   * derived from it) stops in lock-step with the silenced voice. Without the
   * suspend, a "pause" froze only the ink while the voice kept talking and the
   * clock kept advancing — so on resume the ink snapped forward to catch up.
   */
  public pause(): void {
    if (this._isRunning) {
      this._masterTimeMs = this.currentTimeMs;
      this._isRunning = false;
    }
    this.state = AUDIO_TIMELINE_STATE.PAUSED;
    if (this._rafHandle !== null) {
      cancelAnimationFrame(this._rafHandle);
      this._rafHandle = null;
    }
    if (this._audioContext && this._audioContext.state === "running") {
      this._audioContext.suspend().catch(() => { /* best-effort */ });
    }
  }

  /**
   * Resume active playback timeline.
   *
   * Resumes the AudioContext first so scheduled sources continue from exactly
   * where they were suspended, then re-anchors the master clock to the (resumed)
   * audio time. Because currentTime did not advance while suspended, voice + ink
   * resume perfectly in sync.
   */
  public resume(): void {
    if (this.state !== AUDIO_TIMELINE_STATE.PAUSED) return;
    if (this._audioContext && this._audioContext.state === "suspended") {
      this._audioContext.resume().catch(() => { /* best-effort */ });
    }
    this._startWallTime = performance.now();
    if (this._audioContext) {
      this._startAudioContextTime = this._audioContext.currentTime;
    }
    this._isRunning = true;
    this.state = AUDIO_TIMELINE_STATE.PLAYING;
    this._scheduleFrame();
  }

  /**
   * Seek structural indices to target milliseconds.
   */
  public seek(targetMs: number): void {
    const wasRunning = this._isRunning;
    if (wasRunning) {
      this.pause();
    }
    this._masterTimeMs = Math.max(0, targetMs);
    this._startWallTime = performance.now();
    if (this._audioContext) {
      this._startAudioContextTime = this._audioContext.currentTime;
    }
    this._speechMarkCursor = 0;
    this._driftCompensator.reset();
    
    // Reset structural state on child markers
    for (const [, seg] of this._segments) {
      seg._markCursor = 0;
      for (const mark of seg.marks) {
        mark._fired = false;
      }
    }
    
    if (wasRunning) {
      this.start(this._masterTimeMs);
    }
  }

  /**
   * Set timeline playback rate.
   */
  public setPlaybackRate(rate: number): void {
    const clamped = Math.max(0.25, Math.min(4.0, rate));
    const currentMs = this.currentTimeMs;
    this._playbackRate = clamped;
    this._masterTimeMs = currentMs;
    this._startWallTime = performance.now();
    if (this._audioContext) {
      this._startAudioContextTime = this._audioContext.currentTime;
    }
  }

  /**
   * Reconcile visual layout synchronization matrices with remote clock states.
   */
  public reconcileWithServer(serverTimeMs: number): void {
    // No-op: serverTimeMs is absolute epoch time whereas client relative clock is session-relative.
    // Reconciling them directly causes large negative drift which freezes the clock.
  }

  alignClock(absoluteStartMs: number, audioContextStartTime: number): void {
    this._masterTimeMs = absoluteStartMs;
    this._startAudioContextTime = audioContextStartTime;
    this._startWallTime = performance.now();
    this._driftCompensator.reset();

    // alignClock is the SOLE authoritative clock anchor: real audio (or the
    // web-speech fallback) has just been scheduled, so start/keep the master
    // clock running from this exact anchor. This guarantees the timeline tracks
    // actual playback — ink can no longer lead the voice the way it did when the
    // clock was started/force-aligned on wall-time before audio was scheduled.
    // Idempotent with the init-time start(); _scheduleFrame() cancels any prior
    // RAF first, so re-anchoring per speech segment keeps drift at ~0.
    this._isRunning = true;
    this.state = AUDIO_TIMELINE_STATE.PLAYING;
    this._scheduleFrame();
  }

  /**
   * Register a subscriber for real-time audio clock steps.
   */
  public subscribe(id: string, cb: SubscriberCallback): void {
    this._subscribers.set(id, cb);
  }

  /**
   * Unsubscribe tracking indices.
   */
  public unsubscribe(id: string): void {
    this._subscribers.delete(id);
  }

  /**
   * Register a high-frequency layout processing loop frame hook.
   */
  public onFrame(cb: (timeMs: number, deltaMs: number) => void): number {
    const handle = this._frameCallbacks.length;
    this._frameCallbacks.push({ handle, cb, active: true });
    return handle;
  }

  /**
   * Deallocate high-frequency processing hook.
   */
  public offFrame(handle: number): void {
    const entry = this._frameCallbacks.find(e => e.handle === handle);
    if (entry) entry.active = false;
  }

  /**
   * Core authoritative current timeline context calculator.
   */
  public get currentTimeMs(): number {
    if (!this._isRunning) return this._masterTimeMs;

    let raw: number;
    if (this._audioContext && this._audioContext.state === "running") {
      const audioElapsed = (this._audioContext.currentTime - this._startAudioContextTime) * 1000;
      raw = this._masterTimeMs + audioElapsed * this._playbackRate;
    } else {
      const wallElapsed = performance.now() - this._startWallTime;
      raw = this._masterTimeMs + wallElapsed * this._playbackRate;
    }

    return Math.max(this._masterTimeMs, raw - this._latencyOffsetMs + this._driftCompensator.correctedOffsetMs);
  }

  /**
   * Collect due phonemes / text events inside evaluation windows.
   */
  public getReadySpeechMarks(windowMs: number = 50): SpeechMark[] {
    const now = this.currentTimeMs;
    const ready: SpeechMark[] = [];

    for (const [, seg] of this._segments) {
      for (const mark of seg.marks) {
        if (mark.absoluteMs !== undefined) {
          if (mark.absoluteMs >= now && mark.absoluteMs <= now + windowMs) {
            if (!mark._fired) {
              ready.push(mark);
            }
          } else if (mark.absoluteMs < now && !mark._fired) {
            mark._fired = true; // Flag structural context missing window boundaries
          }
        }
      }
    }

    return ready;
  }

  /**
   * Pull explicit structural information matching currently running segment values.
   */
  public getCurrentWord(): CurrentWordResult | null {
    const now = this.currentTimeMs;
    for (const [, seg] of this._segments) {
      for (const mark of seg.marks) {
        if (mark.absoluteMs !== undefined && mark.type === "word") {
          const duration = mark.duration || 300;
          if (mark.absoluteMs <= now && now < mark.absoluteMs + duration) {
            return {
              word: mark.value,
              startMs: mark.absoluteMs,
              endMs: mark.absoluteMs + duration
            };
          }
        }
      }
    }
    return null;
  }

  /**
   * Pull currently active spoken word boundary index.
   */
  public getCurrentWordIndex(): number | null {
    const now = this.currentTimeMs;
    for (const [, seg] of this._segments) {
      if (now >= seg.startMs && now <= seg.startMs + seg.durationMs) {
        for (const mark of seg.marks) {
          if (mark.absoluteMs !== undefined && mark.type === "word") {
            const duration = mark.duration || 300;
            if (mark.absoluteMs <= now && now < mark.absoluteMs + duration) {
              return mark.word_index ?? null;
            }
          }
        }
      }
    }
    return null;
  }

  /**
   * Emit full metrics context tracking variables.
   */
  public getMetrics(): AudioTimelineMetrics {
    return {
      state: this.state,
      currentTimeMs: this.currentTimeMs,
      playbackRate: this._playbackRate,
      latencyOffsetMs: this._latencyOffsetMs,
      driftMs: this._driftCompensator.correctedOffsetMs,
      fps: this._fps,
      segmentCount: this._segments.size,
      audioContextState: this._audioContext?.state || "none",
    };
  }

  /**
   * Flush active engines.
   */
  public reset(): void {
    this.pause();
    this._masterTimeMs = 0;
    this._segments.clear();
    this._speechMarkCursor = 0;
    this._driftCompensator.reset();
    this._subscribers.clear();
    this._frameCallbacks = [];
    this.state = AUDIO_TIMELINE_STATE.IDLE;
  }

  // ── Private Loop Implementations ───────────────────────────

  private _setupVisibilityHandler(): void {
    if (typeof document === "undefined") return;
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        // Tab moved to background: freeze the clock so AudioContext.currentTime
        // doesn't race ahead and dump queued events all at once on return.
        // Only auto-pause if we are actively playing — a user-initiated pause
        // must not be disturbed.
        if (this._isRunning && this.state === AUDIO_TIMELINE_STATE.PLAYING) {
          this._autoSuspendedByVisibility = true;
          this.pause();
        }
      } else {
        // Tab returned to foreground: resume only if we were the ones who paused.
        if (this._autoSuspendedByVisibility) {
          this._autoSuspendedByVisibility = false;
          this.resume();
        }
      }
    });
  }

  private _scheduleFrame(): void {
    if (this._rafHandle !== null) cancelAnimationFrame(this._rafHandle);
    this._rafHandle = requestAnimationFrame((wallTime: number) => this._onFrame(wallTime));
  }

  private _onFrame(wallTime: number): void {
    if (!this._isRunning) return;

    const now = this.currentTimeMs;
    const delta = wallTime - this._lastFrameTime;
    this._lastFrameTime = wallTime;

    this._frameCount++;
    if (this._frameCount % 60 === 0) {
      this._fps = Math.round(1000 / Math.max(1, delta));
    }

    const readyMarks = this.getReadySpeechMarks(16);
    readyMarks.forEach(m => { m._fired = true; });

    for (const [, cb] of this._subscribers) {
      try { cb(now, readyMarks); } catch (e) { /* Execution Guard isolation */ }
    }

    for (const entry of this._frameCallbacks) {
      if (entry.active) {
        try { entry.cb(now, delta); } catch (e) { /* Execution Guard isolation */ }
      }
    }

    this._scheduleFrame();
  }
}

// ── Singleton ──────────────────────────────────────────────────
export const audioTimeline = new AudioTimeline();