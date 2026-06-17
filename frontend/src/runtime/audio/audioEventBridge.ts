/**
 * audioEventBridge.ts — Audio→Motion Synchronization Conduit
 *
 * The bridge between the audio master clock (AudioTimeline) and every
 * motion subsystem (cursor, strokes, narration, focus, camera).
 *
 * This replaces the fake _charsPerSecond timing with REAL audio synchronization.
 *
 * Data flow:
 * AudioTimeline (master clock)
 * → AudioEventBridge
 * → TemporalScheduler.reconcile()    [clock sync]
 * → NarrationSync.syncToAudio()      [speech anchors]
 * → CursorActor.syncToPhoneme()      [cursor rhythm]
 * → StrokeScheduler.syncToSpeech()   [stroke timing]
 * → PhonemeClock.tick()              [sub-word events]
 */

import { audioTimeline } from "./audioTimeline";
import { ttsPlayer } from "./ttsPlayer";
import { phonemeClock } from "./phonemeClock";
import { audioLatencyCompensator, motionJitterBuffer } from "./audioLatencyCompensator";
import { speechMarksParser } from "./speechMarksParser";

// ── Motion Subsystem Interfaces ────────────────────────────────

export interface TemporalScheduler {
  currentTimeMs: number;
  _absoluteTimeMs: number;
  enqueueEvent(event: {
    start_ms: number;
    type: string;
    payload: Record<string, any>;
  }): void;
}

export interface NarrationSync {
  onRealWordFired?(word: string, startMs: number): void;
}

export interface CursorActor {
  setRhythmMultiplier?(rhythm: number): void;
  pause?(durationMs: number, deceleration: number): void;
}

export interface StrokeScheduler {
  // Retained for framework hook compliance
}

export interface ConnectSystemsParams {
  temporalScheduler: TemporalScheduler | null;
  narrationSync: NarrationSync | null;
  cursorActor: CursorActor | null;
  strokeScheduler: StrokeScheduler | null;
}

export interface AudioSegmentDescriptor {
  text: string;
  startMs: number;
}

export interface WordTriggerAction {
  action: string; // "draw" | "highlight" | "focus" | "camera" | "pause"
  targetIds: string[];
}

export interface WordBoundaryPayload {
  word: string;
  startMs: number;
  endMs: number;
}

export interface RegisterSegmentParams {
  segmentId: string;
  text: string;
  absoluteStartMs: number;
  audioData?: ArrayBuffer | string | null;
  speechMarks?: any[];
  provider?: string;
}

// ── AudioEventBridge Class ─────────────────────────────────────

export class AudioEventBridge {
  private _temporalScheduler: TemporalScheduler | null;
  private _narrationSync: NarrationSync | null;
  private _cursorActor: CursorActor | null;
  private _strokeScheduler: StrokeScheduler | null;

  private _pendingSegments: Map<string, AudioSegmentDescriptor>;
  private _syncEnabled: boolean;
  private _lastSyncMs: number;
  private _syncIntervalMs: number;
  private _wordTriggers: Map<string, WordTriggerAction[]>;

  private _activeSegmentId: string | null;
  private _activeSegmentStartMs: number;

  private _onWordCallbacks: Array<(ev: WordBoundaryPayload) => void>;
  private _onSegmentStartCallbacks: Array<(segmentId: string) => void>;
  private _onSegmentEndCallbacks: Array<(segmentId: string) => void>;

  private _frameHandle: number | null;
  private _initialized: boolean;

  constructor() {
    // Connected motion systems
    this._temporalScheduler = null;
    this._narrationSync = null;
    this._cursorActor = null;
    this._strokeScheduler = null;

    // Segment registry
    this._pendingSegments = new Map();

    // Synchronization state
    this._syncEnabled = true;
    this._lastSyncMs = 0;
    this._syncIntervalMs = 100; // Reconcile every 100ms

    // Word → visual action mapping
    this._wordTriggers = new Map();

    // Active segment cursor
    this._activeSegmentId = null;
    this._activeSegmentStartMs = 0;

    // Callbacks arrays
    this._onWordCallbacks = [];
    this._onSegmentStartCallbacks = [];
    this._onSegmentEndCallbacks = [];

    // Operational handles
    this._frameHandle = null;
    this._initialized = false;
  }

  /**
   * Connect to motion subsystems. Call once at startup.
   */
  public connect({ temporalScheduler, narrationSync, cursorActor, strokeScheduler }: ConnectSystemsParams): void {
    this._temporalScheduler = temporalScheduler;
    this._narrationSync = narrationSync;
    this._cursorActor = cursorActor;
    this._strokeScheduler = strokeScheduler;

    // Calibrate from AudioContext if available via structural check
    const ctx = (audioTimeline as any)._audioContext;
    if (ctx) {
      audioLatencyCompensator.initFromAudioContext(ctx);
    }

    // Subscribe to authoritative timeline frames
    this._frameHandle = audioTimeline.onFrame((timeMs: number, deltaMs: number) => {
      this._onAudioFrame(timeMs, deltaMs);
    });

    // Subscribe to TTS word boundaries
    ttsPlayer.onWord(({ word, startMs, endMs }: WordBoundaryPayload) => {
      this._onWord(word, startMs, endMs);
    });

    ttsPlayer.onSegmentEnd((segmentId: string) => {
      this._onSegmentEnd(segmentId);
    });

    // Instantiate network jitter tracking hooks
    this._setupJitterTracking();

    this._initialized = true;
  }

  /**
   * Register a speech segment for synchronized playback.
   */
  public async registerSpeechSegment({
    segmentId,
    text,
    absoluteStartMs,
    audioData = null,
    speechMarks = [],
    provider = "edge_tts"
  }: RegisterSegmentParams): Promise<any[]> {
    this._pendingSegments.set(segmentId, { text, startMs: absoluteStartMs });

    // Normalize structural speech marks
    let parsedMarks: any[] = [];
    if (speechMarks.length > 0) {
      parsedMarks = speechMarksParser.parse(speechMarks, provider);
    } else {
      // Generate heuristic boundaries from raw content metrics
      const estimateFn = (ttsPlayer as any)._estimateDuration;
      const estimatedDuration = estimateFn ? estimateFn(text) : (text.length / 15) * 1000;
      parsedMarks = speechMarksParser.generateFromText(text, estimatedDuration);
    }

    // Buffer handoff to playback audio pipeline
    await ttsPlayer.loadSegment({
      segmentId,
      text,
      absoluteStartMs,
      audioData,
      speechMarks: parsedMarks,
      provider: provider as any,
    });

    // Populate sub-word alignment matrices
    phonemeClock.synthesizeFromWords(
      parsedMarks
        .filter((m: any) => m.type === "word")
        .map((m: any) => ({
          ...m,
          absoluteMs: absoluteStartMs + m.time,
        }))
    );

    return parsedMarks;
  }

  /**
   * Register a word → visual action trigger.
   * When this word is spoken, fire the action.
   */
  public registerWordTrigger(word: string, action: string, targetIds: string[] = []): void {
    const key = word.toLowerCase().trim();
    if (!this._wordTriggers.has(key)) {
      this._wordTriggers.set(key, []);
    }
    this._wordTriggers.get(key)!.push({ action, targetIds });
  }

  /**
   * Get the current playback time from the audio master clock.
   */
  public get currentTimeMs(): number {
    return audioTimeline.currentTimeMs;
  }

  /**
   * Get current word being spoken.
   */
  public getCurrentWord(): any {
    return audioTimeline.getCurrentWord();
  }

  /**
   * Get cursor rhythm (0..1) based on current phoneme.
   */
  public getCursorRhythm(): number {
    return phonemeClock.getPenRhythm(audioTimeline.currentTimeMs);
  }

  /**
   * Get speech stress level (0..1) for pen pressure modulation.
   */
  public getStressLevel(): number {
    return phonemeClock.getStressLevel(audioTimeline.currentTimeMs);
  }

  /**
   * Set synchronization enabled/disabled state flags.
   */
  public setSyncEnabled(enabled: boolean): void {
    this._syncEnabled = enabled;
  }

  /**
   * Register word callback.
   */
  public onWord(cb: (ev: WordBoundaryPayload) => void): void {
    this._onWordCallbacks.push(cb);
  }

  /**
   * Register segment start callback.
   */
  public onSegmentStart(cb: (segmentId: string) => void): void {
    this._onSegmentStartCallbacks.push(cb);
  }

  /**
   * Register segment end callback.
   */
  public onSegmentEnd(cb: (segmentId: string) => void): void {
    this._onSegmentEndCallbacks.push(cb);
  }

  /**
   * Clear contextual running registers.
   */
  public reset(): void {
    this._pendingSegments.clear();
    this._wordTriggers.clear();
    this._activeSegmentId = null;
    this._onWordCallbacks = [];
    this._onSegmentStartCallbacks = [];
    this._onSegmentEndCallbacks = [];
    phonemeClock.reset();
  }

  // ── Private Core Interpolation Processing Loops ─────────────

  private _onAudioFrame(timeMs: number, deltaMs: number): void {
    if (!this._syncEnabled) return;

    // 1. Reconcile TemporalScheduler alignment with audio master timeline
    if (this._temporalScheduler && timeMs - this._lastSyncMs >= this._syncIntervalMs) {
      const schedulerTime = this._temporalScheduler.currentTimeMs;
      const drift = Math.abs(schedulerTime - timeMs);

      if (drift > 50) {
        const correction = (timeMs - schedulerTime) * 0.3; // 30% dampening step correction per evaluation
        this._temporalScheduler._absoluteTimeMs += correction;
      }

      this._lastSyncMs = timeMs;
    }

    // 2. Refresh sub-word timing structures to calculate visual pen speed multipliers
    const phonemeEvents = phonemeClock.tick(timeMs);
    if (phonemeEvents.length > 0 && this._cursorActor) {
      const rhythm = phonemeClock.getPenRhythm(timeMs);
      if (this._cursorActor.setRhythmMultiplier) {
        this._cursorActor.setRhythmMultiplier(rhythm);
      }
    }
  }

  private _onWord(word: string, startMs: number, endMs: number): void {
    this._onWordCallbacks.forEach(cb => cb({ word, startMs, endMs }));

    const key = word.toLowerCase().replace(/[^a-z]/g, "");
    const triggers = this._wordTriggers.get(key) || [];

    for (const trigger of triggers) {
      this._fireTrigger(trigger, startMs);
    }

    if (this._narrationSync?.onRealWordFired) {
      this._narrationSync.onRealWordFired(word, startMs);
    }
  }

  private _onSegmentEnd(segmentId: string): void {
    this._onSegmentEndCallbacks.forEach(cb => cb(segmentId));
    phonemeClock.reset();
  }

  private _fireTrigger({ action, targetIds }: WordTriggerAction, timeMs: number): void {
    switch (action) {
      case "draw":
        if (this._temporalScheduler) {
          this._temporalScheduler.enqueueEvent({
            start_ms: timeMs,
            type: "progressive_reveal",
            payload: { target_ids: targetIds },
          });
        }
        break;
      case "highlight":
        if (this._temporalScheduler) {
          this._temporalScheduler.enqueueEvent({
            start_ms: timeMs,
            type: "attention_focus",
            payload: { target_ids: targetIds, strategy: "pulse", duration_ms: 600, intensity: 0.8 },
          });
        }
        break;
      case "pause":
        if (this._cursorActor) {
          this._cursorActor.pause?.(300, 0.5);
        }
        break;
    }
  }

  private _setupJitterTracking(): void {
    let lastArrival = performance.now();
    const originalEnqueue = motionJitterBuffer.push.bind(motionJitterBuffer);

    motionJitterBuffer.push = (event: any) => {
      const now = performance.now();
      const jitter = Math.abs(now - lastArrival - 33); // Normal frame refresh delta baseline at 33ms
      lastArrival = now;
      
      audioLatencyCompensator.addJitterMeasurement(Math.min(jitter, 500));
      motionJitterBuffer.adaptTo((audioLatencyCompensator as any)._networkJitterMs || 0);
      originalEnqueue(event);
    };
  }
}

// ── Singleton Instance ─────────────────────────────────────────
export const audioEventBridge = new AudioEventBridge();