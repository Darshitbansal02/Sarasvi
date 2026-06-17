/**
 * teacherMotor.ts — Single Runtime Authority
 *
 * Enforces the TeacherMotor as the single transactional authority for all runtime state.
 * All React components and Zustand stores observe state emissions from this motor,
 * completely decoupled from local frame timing. Driven strictly by the central audio clock.
 */

import { ConstructionRuntime, CONSTRUCTION_PHASE } from "./constructionRuntime";
import { audioTimeline } from "../audio/audioTimeline";
import { audioEventBridge } from "../audio/audioEventBridge";
import { ttsPlayer } from "../audio/ttsPlayer";
import { interactionArbiter, OWNER, OWNERSHIP_PRIORITY } from "../interaction/interactionArbiter";
import { interruptionCoordinator } from "../interaction/interruptionCoordinator";

// ── Struct Data & Domain Interfaces ───────────────────────────

export interface TeacherMotorInitOptions {
  cursorX?: number;
  cursorY?: number;
  sessionId?: string;
}

export interface SpeakParams {
  text: string;
  segmentId?: string;
  absoluteStartMs: number;
  audioData?: ArrayBuffer | null;
  speechMarks?: any[];
  provider?: string;
}

export interface MotionRenderState {
  cursor: {
    visible: boolean;
    x: number;
    y: number;
    gazeX?: number;
    gazeY?: number;
    state: string;
    isEyeAhead?: boolean;
    alpha?: number;
    radius?: number;
    writingTip?: { x: number; y: number } | null;
  };
  strokes: any[];
  gestures: any[];
  focusState: {
    activeEffects: any[];
    globalDimLevel: number;
    focusedObjectIds: Set<string>;
  };
  narrationStatus: {
    progress: number;
    state: string;
    isAudioSynced: boolean;
  };
  phase: CONSTRUCTION_PHASE | string;
  activeWritingEquationId?: string | null;
  writingTipEquationId?: string | null;
  revealingEquationIds?: string[];
  sceneObjects: Record<string, any>;
  actors: {
    totalActors: number;
  };
  time: number;
  audioMetrics: Record<string, any>;
  fps?: number;
}

// ── TeacherMotor Class ─────────────────────────────────────────

class TeacherMotor {
  public runtime: ConstructionRuntime;
  private _initialized: boolean;
  private _sessionId: string | null;

  // Render state cache for external decoupled listeners (Zustand/React)
  private _lastRenderState: MotionRenderState | null;
  private _renderStateVersion: number;

  constructor() {
    this.runtime = new ConstructionRuntime();
    this._initialized = false;
    this._sessionId = null;
    this._lastRenderState = null;
    this._renderStateVersion = 0;
  }

  /**
   * Initialize for a new session.
   * Securely binds all audio, narration, and interruption coordinator loops.
   *
   * @param options - Spatial alignment configurations and identifiers
   */
  public async init(options: TeacherMotorInitOptions = {}): Promise<void> {
    // Reset singleton audio/tts instances to prevent duplicate callback accumulation and leaks
    ttsPlayer.reset();
    audioTimeline.reset();
    audioEventBridge.reset();

    this.runtime.reset();
    this.runtime.cursor.x = options.cursorX ?? 400;
    this.runtime.cursor.y = options.cursorY ?? 300;
    this.runtime.start();

    this._sessionId = options.sessionId || null;
    this._initialized = true;

    // Initialize hardware audio routing nodes
    await audioTimeline.init();

    // Securely bridge speech mark sequences directly into drawing schedulers
    audioEventBridge.connect({
      temporalScheduler: this.runtime.temporalScheduler as any,
      narrationSync: this.runtime.narrationSync,
      cursorActor: this.runtime.cursor,
      strokeScheduler: this.runtime.strokeScheduler,
    });

    // FIX: Unpack into three positional arguments to satisfy the InterruptionCoordinator interface contract
    interruptionCoordinator.connect(
      this,
      this.runtime.temporalScheduler,
      null // Attached dynamically by runtimeStore mapping handlers afterwards
    );

    // TTS player callback wiring
    ttsPlayer.onWord(({ word, startMs }: { word: string; startMs: number; endMs: number }) => {
      // Feed actual word firing times directly into text pacing maps to bypass heuristics
      this.runtime.narrationSync.onRealWordFired(word, startMs);
    });

    ttsPlayer.onSegmentEnd((segmentId: string) => {
      interactionArbiter.unlock();
    });

    // Initialize default primary board control parameters
    interactionArbiter.request(OWNER.TEACHER, OWNERSHIP_PRIORITY.TEACHER_NORMAL, "Session initialized", 0);
  }

  /**
   * Process an event from the incoming architectural NDJSON event log stream.
   * Automatically passes timeline ticks to keep stream sequences in alignment.
   *
   * @param evt - The abstract timeline directive payload
   */
  public processEvent(evt: any, timeMs?: number): void {
    if (!this._initialized) {
      this.init().catch(err => console.error("[TeacherMotor] Lazy-init breakdown:", err));
    }
    const targetTimeMs = timeMs !== undefined ? timeMs : (audioTimeline.currentTimeMs || 0);
    this.runtime.processEvent(evt, targetTimeMs);
  }

  /**
   * Advance the physical system layers by one delta step.
   * Triggered continuously by the main system loop ticker (Pixi App loop).
   *
   * @param deltaMs - Internal frame duration step mapping (ms)
   * @returns Pure type-asserted render snapshot metadata
   */
  public tick(deltaMs: number): MotionRenderState {
    if (!this._initialized) return this._emptyState();

    // Force temporal physics reconciliation directly against the hardware clock thread
    this.runtime.temporalScheduler.tick(deltaMs);

    // Pull un-aliased layout configurations
    const state = this.runtime.getRenderState() as MotionRenderState;
    this._lastRenderState = state;
    this._renderStateVersion++;

    return state;
  }

  // ── TTS Synthesis Integrations ───────────────────────────────

  /**
   * Register and stream audio buffers to establish the master audio time context.
   *
   * @param params - Text phrasing nodes alongside absolute play targets
   */
  public async speak({ text, segmentId, absoluteStartMs, audioData = null, speechMarks = [], provider = "edge_tts" }: SpeakParams): Promise<void> {
    if (!text) return;

    const targetSegmentId = segmentId || `speech_${absoluteStartMs}`;

    await audioEventBridge.registerSpeechSegment({
      segmentId: targetSegmentId,
      text,
      absoluteStartMs,
      audioData,
      speechMarks,
      provider,
    });

    // Trigger physical audio driver layers (takes clock control authority instantly)
    await ttsPlayer.playSegment(targetSegmentId);
  }

  /**
   * Decode a speech segment's audio ahead of fire-time (called from
   * runtimeStore.ingestEvent when the event arrives, well before its start_ms).
   * Removes the decode latency that otherwise delayed first audio relative to
   * ink. Best-effort and idempotent.
   */
  public preloadSpeechAudio(segmentId: string, audioData: ArrayBuffer | string | null): void {
    if (!segmentId || !audioData) return;
    ttsPlayer.preloadAudio(segmentId, audioData).catch(() => { /* best-effort */ });
  }

  // ── Poly-Morphic Layer Proxies ───────────────────────────────

  public getCursorState(): any {
    return this.runtime.cursor.getSnapshot();
  }

  public getStrokeRenderData(): any {
    return this.runtime.strokeScheduler.getAllRenderData();
  }

  public getGestureRenderData(): any {
    const timeMs = audioTimeline.currentTimeMs;
    return this.runtime.gestureDynamics.tick(timeMs);
  }

  public getObjectFocusState(objectId: string): any {
    return this.runtime.focusEngine.getObjectFocusState(objectId);
  }

  public getSceneObjects(): Record<string, any> {
    return this.runtime.getRenderState().sceneObjects;
  }

  public getNarrationStatus(): any {
    return this.runtime.narrationSync.getStatus();
  }

  public getPhase(): string {
    return this.runtime.phase;
  }

  // ── Playback Controls ───────────────────────────────────────

  public setPlaybackRate(rate: number): void {
    this.runtime.temporalScheduler.setPlaybackRate(rate);
  }

  public setHesitationPacing(multiplier: number): void {
    if (typeof (this.runtime.hesitationEngine as any).setPacing === "function") {
      (this.runtime.hesitationEngine as any).setPacing(multiplier);
    }
  }

  public pause(): void {
    this.runtime.pause();
  }

  public resume(): void {
    this.runtime.resume();
  }

  public reset(): void {
    ttsPlayer.stop();
    audioTimeline.reset();
    audioEventBridge.reset();
    this.runtime.reset();
    interactionArbiter.reset();
    interruptionCoordinator.reset();
    this._initialized = false;
    this._lastRenderState = null;
    this._sessionId = null;
    this._renderStateVersion = 0;
  }

  // ── Student Canvas Interaction Infrastructure ────────────────

  /**
   * Safe allocation router requesting canvas input focus locks for student nodes.
   */
  public requestStudentOwnership(reason: string = ""): { granted: boolean; queued: boolean; waitMs: number } {
    return interactionArbiter.request(
      OWNER.STUDENT,
      OWNERSHIP_PRIORITY.STUDENT_ACTIVE,
      reason,
      30000
    );
  }

  /**
   * Release control locks and safely return primary authority back to the teacher.
   */
  public releaseStudentOwnership(): void {
    interactionArbiter.release(OWNER.STUDENT);
    interactionArbiter.request(OWNER.TEACHER, OWNERSHIP_PRIORITY.TEACHER_NORMAL, "Student released", 0);
  }

  /**
   * Interrupt the teacher timeline loop sequence (Socratic detour injection).
   */
  public async interrupt(context: any): Promise<boolean> {
    return interruptionCoordinator.interrupt(context);
  }

  /**
   * Resume baseline pedagogical streams once a clear detour exit path has been determined.
   */
  public async resumeFromInterruption(): Promise<void> {
    // FIX: Remove unaccepted tracking parameter configuration arguments
    return interruptionCoordinator.resume();
  }

  public setInteractionMode(mode: string): void {
    interactionArbiter.setMode(mode as any);
  }

  public getArbiterState(): any {
    return interactionArbiter.getState();
  }

  // ── Snapshot Serialization ──────────────────────────────────

  public takeSnapshot(): Record<string, any> {
    return this.runtime.takeSnapshot();
  }

  public isActive(): boolean {
    return this._initialized &&
      this.runtime.phase !== CONSTRUCTION_PHASE.IDLE &&
      this.runtime.phase !== CONSTRUCTION_PHASE.COMPLETED;
  }

  public getAudioMetrics(): Record<string, any> {
    return {
      ...audioTimeline.getMetrics(),
      arbiter: interactionArbiter.getState(),
      interruption: (interruptionCoordinator as any).state || {},
    };
  }

  // ── Private Fallbacks ───────────────────────────────────────

  private _emptyState(): MotionRenderState {
    return {
      cursor: { visible: false, x: 0, y: 0, state: "hidden" },
      strokes: [],
      gestures: [],
      focusState: { activeEffects: [], globalDimLevel: 0, focusedObjectIds: new Set<string>() },
      narrationStatus: { progress: 0, state: "idle", isAudioSynced: false },
      phase: CONSTRUCTION_PHASE.IDLE,
      sceneObjects: {},
      actors: { totalActors: 0 },
      time: 0,
      audioMetrics: audioTimeline.getMetrics(),
    };
  }
}

// Global Singleton Export Allocation
export const teacherMotor = new TeacherMotor();