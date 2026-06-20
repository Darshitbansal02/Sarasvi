/**
 * runtimeStore.ts — Observer Layer (NOT the clock authority)
 *
 * FIX APPLIED [BUG-6 — Audio Clock Race]:
 * Start `audioTimeline` IMMEDIATELY when the speech event is first processed
 * in `tick()`, before calling `teacherMotor.speak()`. This ensures all
 * objects created in subsequent events in the same batch get the correct
 * `startMs` stamped from the now-running audio clock.
 *
 * FIX APPLIED [C1 — State Machine IDLE→BUFFERING]:
 * Added BUFFERING and STREAMING to IDLE transitions for auto-continue.
 *
 * FIX APPLIED [C4 — WebSpeechTTS removed]:
 * Volume/mute now routes through ttsPlayer (the real audio backend).
 *
 * FIX APPLIED [M4 — Event Listener Leak]:
 * Scene event listeners are now tracked and cleaned up in reset().
 */

import { create } from "zustand";
import { sceneManager } from "./sceneManager";
import { PAGE_W, BOARD_WIDTH, BOARD_HEIGHT } from "./boardConstants";
import { useCognitiveDensityStore } from "./cognitiveDensity";
import { teacherMotor } from "./motion/teacherMotor";
import { computeWritingDiagnostics } from "./writingDiagnostics";
import { ReplayMotionEngine } from "./motion/replayMotionEngine";
import { audioTimeline } from "./audio/audioTimeline";
import { ttsPlayer } from "./audio/ttsPlayer";
import { audioEventBridge } from "./audio/audioEventBridge";
import { interactionArbiter, OWNER } from "./interaction/interactionArbiter";
import { interruptionCoordinator } from "./interaction/interruptionCoordinator";
import { whiteboardCognition } from "./whiteboardCognition";
import { cameraCognition } from "./motion/cameraCognition";
import { teacherStudentPriority } from "./interaction/teacherStudentPriority";
import { metaphorEngine, MetaphorType } from "./metaphorEngine";
import {
  getPedagogicalWriteMode,
  pruneSupersededBoardObjects,
  resolvePedagogicalBoardId,
  resolveSceneObjectBoardId,
  shouldPatchBoard,
} from "./motion/derivationBoard";

// ── Enums & Type Definitions ──────────────────────────────────

export enum RUNTIME_STATES {
  IDLE = "IDLE",
  CONNECTING = "CONNECTING",
  STREAMING = "STREAMING",
  BUFFERING = "BUFFERING",
  PAUSED = "PAUSED",
  INTERRUPTING = "INTERRUPTING",
  REPLAYING = "REPLAYING",
  COMPLETED = "COMPLETED",
  ERROR = "ERROR",
  REMEDIATING = "REMEDIATING"
}

export interface RuntimeMetrics {
  eventsReceived: number;
  queueDepth: number;
  frameTime: number;
  motionActors: number;
  activeStrokes: number;
  fps: number;
  audioLatencyMs: number;
  clockDriftMs: number;
}

export interface PedagogicalState {
  active_concept: string;
  teaching_mode: string;
  pacing_mode: string;
  confusion_level: number;
  explanation_depth: number;
  metaphor_strategy: string;
  remediation_active: boolean;
}

export interface AttentionState {
  primary_focus_object: string | null;
  secondary_focus_objects: string[];
  suppressed_regions: any[];
  active_gesture_target: string | null;
}

export interface CameraState {
  x: number;
  y: number;
  zoom: number;
}

export interface MotionState {
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
  phase: string;
  activeWritingEquationId?: string | null;
  writingTipEquationId?: string | null;
  revealingEquationIds?: string[];
}

export interface ArbiterState {
  owner: string;
  canStudentDraw: boolean;
  isLocked: boolean;
}

export interface ReplanState {
  active: boolean;
  reason: string;
  strategy: string;
  confusion: number;
  timestamp: number;
}

export interface TranscriptEntry {
  t: number;
  who: string;
  text: string;
  streaming?: boolean;
}

export interface TimelineEvent {
  type: string;
  start_ms?: number;
  generation_id?: string;
  payload?: Record<string, any>;
  [key: string]: any;
}

export interface SceneDescriptor {
  scene_id: string;
  label: string;
  concept: string;
  confusion_level: number;
  timeline_offset: number;
  camera_x?: number;
  [key: string]: any;
}

export interface MotionRenderState {
  cursor?: {
    visible: boolean;
    x: number;
    y: number;
    gazeX?: number;
    gazeY?: number;
    state: string;
    isEyeAhead?: boolean;
    alpha?: number;
    radius?: number;
  };
  strokes?: any[];
  gestures?: any[];
  focusState?: {
    activeEffects: any[];
    globalDimLevel: number;
    focusedObjectIds: Set<string>;
  };
  narrationStatus?: {
    progress: number;
    state: string;
    isAudioSynced: boolean;
  };
  phase?: string;
  activeWritingEquationId?: string | null;
  writingTipEquationId?: string | null;
  revealingEquationIds?: string[];
  sceneObjects?: Record<string, any>;
  actors?: { totalActors: number };
  fps?: number;
  audioMetrics?: { latencyOffsetMs?: number; driftMs?: number;[key: string]: any };
}

// ── Global Trace Signatures ────────────────────────────────────

declare global {
  interface Window {
    __cursorTrace?: any[];
    __downloadCursorTrace?: () => void;
  }
}

// ── Store Contracts ───────────────────────────────────────────

export interface RuntimeStoreState {
  runtimeState: RUNTIME_STATES;
  metrics: RuntimeMetrics;
  currentTimeMs: number;
  timelineIndex: number;
  playbackRate: number;
  generationId: string | null;
  sessionId: string | null;
  sessionTopic: string;
  pedagogicalState: PedagogicalState;
  pedagogicalPlan: Record<string, any>;
  attentionState: AttentionState;
  transitionContext: Record<string, any>;
  eventQueue: TimelineEvent[];
  transcript: TranscriptEntry[];
  sceneObjects: Record<string, any>;
  camera: CameraState;
  visualPlan: Record<string, any>;
  cameraLocked: boolean;
  interactionTool: string;
  motionState: MotionState;
  narrationStatus: MotionState["narrationStatus"];
  scenes: SceneDescriptor[];
  activeSceneId: string | null;
  viewedSceneId: string | null;
  /** True when the student has manually navigated to a past page.
   *  While pinned, scene_start events do not auto-advance viewedSceneId. */
  viewedScenePinned: boolean;
  studentStrokes: any[];
  pendingInteraction: any | null;
  interactionMode: string;
  isRemediating: boolean;
  activeMetaphor: string;
  boardTheme: "light" | "dark";
  liveBuffer: TimelineEvent[];
  arbiterState: ArbiterState;
  replanState: ReplanState | null;
  lastStudentGesture: any | null;
  /** Set when lesson generation fails (generation_end with a failure reason).
   *  Drives the session error overlay instead of leaving the loader hanging. */
  errorMessage: string | null;
  checkpointState: import("../types").CheckpointState | null;
  reviewState: import("../types").ReviewState | null;
  detectedMisconceptions: import("../types").MisconceptionEntry[];
  isGenerationCompleted: boolean;
  /** True when a doubt pivot (G2) just finished and auto-resume (G3) is expected.
   *  Prevents premature COMPLETED transition between G2 end and G3 arrival. */
  _awaitingAutoResume: boolean;
}

export interface RuntimeStoreActions {
  setState: (next: RUNTIME_STATES) => void;
  setMetrics: (updates: Partial<RuntimeMetrics>) => void;
  initSession: (sessionId: string) => Promise<void>;
  addScene: (scene: SceneDescriptor) => void;
  updateScene: (sceneId: string, updates: Partial<SceneDescriptor>) => void;
  reset: () => void;
  ingestEvent: (evt: TimelineEvent) => void;
  tick: (deltaMs: number) => void;
  restoreHistoricalScene: (sceneId: string) => Promise<void>;
  returnToLive: () => void;
  triggerRemediation: (metaphor?: string) => void;
  setMetaphor: (metaphor: string) => void;
  seekTime: (targetTimeMs: number) => void;
  togglePlayback: () => void;
  addStudentStroke: (stroke: any) => void;
  clearStudentStrokes: () => void;
  setInteractionMode: (mode: string) => void;
  setInteractionTool: (tool: string) => void;
  triggerInterruption: (context: any) => Promise<boolean>;
  resumeFromInterruption: () => Promise<void>;
  pinViewedScene: (sceneId: string) => void;
  unpinViewedScene: () => void;
  toggleBoardTheme: () => void;
  setTTSRate: (rate: number) => void;
  setTTSVolume: (vol: number) => void;
  applyMutations: (mutations: any[]) => void;
  appendTranscript: (entry: TranscriptEntry) => void;
  submitCheckpointAnswer: (answer: string) => Promise<void>;
  clearCheckpoint: () => void;
}

// ── State Machine Transition Blueprint ──────────────────────────

const TRANSITIONS: Record<RUNTIME_STATES, RUNTIME_STATES[]> = {
  [RUNTIME_STATES.IDLE]: [RUNTIME_STATES.CONNECTING, RUNTIME_STATES.REPLAYING, RUNTIME_STATES.BUFFERING, RUNTIME_STATES.STREAMING, RUNTIME_STATES.INTERRUPTING],
  [RUNTIME_STATES.CONNECTING]: [RUNTIME_STATES.STREAMING, RUNTIME_STATES.ERROR, RUNTIME_STATES.IDLE],
  [RUNTIME_STATES.STREAMING]: [RUNTIME_STATES.INTERRUPTING, RUNTIME_STATES.PAUSED, RUNTIME_STATES.BUFFERING, RUNTIME_STATES.COMPLETED, RUNTIME_STATES.ERROR, RUNTIME_STATES.IDLE, RUNTIME_STATES.REMEDIATING],
  [RUNTIME_STATES.BUFFERING]: [RUNTIME_STATES.STREAMING, RUNTIME_STATES.REPLAYING, RUNTIME_STATES.ERROR, RUNTIME_STATES.INTERRUPTING, RUNTIME_STATES.IDLE],
  [RUNTIME_STATES.PAUSED]: [RUNTIME_STATES.STREAMING, RUNTIME_STATES.REPLAYING, RUNTIME_STATES.IDLE, RUNTIME_STATES.INTERRUPTING],
  [RUNTIME_STATES.INTERRUPTING]: [RUNTIME_STATES.STREAMING, RUNTIME_STATES.ERROR],
  [RUNTIME_STATES.REPLAYING]: [RUNTIME_STATES.PAUSED, RUNTIME_STATES.COMPLETED, RUNTIME_STATES.IDLE, RUNTIME_STATES.STREAMING],
  // STREAMING is allowed from COMPLETED so that a G3 auto-resume arriving after G2
  // completed can re-activate tick() without resetting the whole session.
  [RUNTIME_STATES.COMPLETED]: [RUNTIME_STATES.IDLE, RUNTIME_STATES.REPLAYING, RUNTIME_STATES.STREAMING],
  [RUNTIME_STATES.ERROR]: [RUNTIME_STATES.IDLE, RUNTIME_STATES.STREAMING, RUNTIME_STATES.CONNECTING],
  [RUNTIME_STATES.REMEDIATING]: [RUNTIME_STATES.STREAMING, RUNTIME_STATES.ERROR, RUNTIME_STATES.IDLE]
};

const replayEngine = new ReplayMotionEngine();
let currentGenerationId: string | null = null;
let _sceneEventHandler: ((evt: CustomEvent) => void) | null = null;

// Phase 8 — timeline integrity: dedup events by (generation_id, sequence_number)
// so a duplicated/redelivered event is never applied twice. Cleared whenever the
// active generation changes (interrupt / pivot) and on reset().
const _seenEventKeys = new Set<string>();
function _eventKey(evt: TimelineEvent): string {
  if (evt.sequence_number !== undefined && evt.sequence_number !== null) {
    return `${evt.generation_id || ""}:${evt.sequence_number}`;
  }
  // Fallback when the backend omits sequence_number: include a payload
  // discriminator so two DISTINCT objects emitted at the same start_ms (e.g.
  // several strokes of one figure) are not collapsed into one key and silently
  // dropped as a "duplicate". (start_ms + type alone collided and lost ink.)
  const p = evt.payload || {};
  const pid =
    p.object_id ?? p.stroke_id ?? p.equation_id ?? p.annotation_id ?? p.id ?? "";
  return `${evt.generation_id || ""}:${evt.type}:${evt.start_ms ?? ""}:${pid}`;
}

// Pending buffer for stroke_reveal events that arrive before generation_start
// provides the compiled_artifact with layout_assets for coordinate resolution.
let _pendingStrokeReveals: TimelineEvent[] | null = null;

// Accumulated frame time between throttled cognitive-density store writes. The
// store drives slow pacing multipliers, not per-frame visuals, so writing it
// every frame needlessly churns React subscribers; we batch to ~12.5 Hz and feed
// the summed dt so the store's fatigue/time accounting stays exact.
let _densityAccumMs = 0;
// Throttle for forwarding client-sensed cognitive load to the backend (the sole
// adaptation authority). We only report a sensor reading every few seconds and
// only when it moves meaningfully, so /interaction isn't spammed at frame rate.
let _loadFwdAccumMs = 0;
let _lastSentLoad = -1;

function registerTranscriptListener(get: () => any, set: (u: any) => void) {
  audioEventBridge.onWord(({ word }) => {
    const state = get();
    const transcript = [...state.transcript];
    if (transcript.length > 0) {
      const lastEntry = { ...transcript[transcript.length - 1] };
      if (lastEntry.who === "Sarasvi" && lastEntry.streaming !== false) {
        lastEntry.text = lastEntry.text ? `${lastEntry.text} ${word}` : word;
        transcript[transcript.length - 1] = lastEntry;
        set({ transcript });
      }
    }
  });
}

// ── Zustand Implementation ─────────────────────────────────────

export const useRuntimeStore = create<RuntimeStoreState & RuntimeStoreActions>((set, get) => ({
  runtimeState: RUNTIME_STATES.IDLE,

  metrics: {
    eventsReceived: 0,
    queueDepth: 0,
    frameTime: 0,
    motionActors: 0,
    activeStrokes: 0,
    fps: 60,
    audioLatencyMs: 0,
    clockDriftMs: 0,
  },

  currentTimeMs: 0.0,
  timelineIndex: 0,
  playbackRate: 1.0,
  generationId: null,
  sessionId: null,
  sessionTopic: "",

  pedagogicalState: {
    active_concept: "",
    teaching_mode: "discovery",
    pacing_mode: "adaptive",
    confusion_level: 0,
    explanation_depth: 1,
    metaphor_strategy: "visual",
    remediation_active: false
  },
  pedagogicalPlan: {},

  attentionState: {
    primary_focus_object: null,
    secondary_focus_objects: [],
    suppressed_regions: [],
    active_gesture_target: null
  },

  transitionContext: {},
  eventQueue: [],
  transcript: [],
  sceneObjects: {},
  camera: { x: 0, y: 0, zoom: 1 },
  visualPlan: {},
  cameraLocked: true,
  interactionTool: "pen",

  motionState: {
    cursor: { visible: false, x: 0, y: 0, state: "hidden" },
    strokes: [],
    gestures: [],
    focusState: { activeEffects: [], globalDimLevel: 0, focusedObjectIds: new Set<string>() },
    narrationStatus: { progress: 0, state: "idle", isAudioSynced: false },
    phase: "idle",
  },
  narrationStatus: { progress: 0, state: "idle", isAudioSynced: false },

  scenes: [],
  activeSceneId: null,
  viewedSceneId: null,
  viewedScenePinned: false,
  studentStrokes: [],
  pendingInteraction: null,
  interactionMode: "LECTURE",
  isRemediating: false,
  activeMetaphor: "formal",
  boardTheme: "dark",
  liveBuffer: [],
  arbiterState: { owner: "none", canStudentDraw: false, isLocked: false },
  replanState: null,
  lastStudentGesture: null,
  errorMessage: null,
  checkpointState: null,
  reviewState: null,
  detectedMisconceptions: [],
  isGenerationCompleted: false,
  _awaitingAutoResume: false,

  // ── State Machine Action Logic ───────────────────────────────

  setState: (next: RUNTIME_STATES) => {
    const cur = get().runtimeState;
    if (cur === next) return;
    const allowed = TRANSITIONS[cur] || [];
    if (!allowed.includes(next)) console.warn(`[runtime] invalid transition ${cur} -> ${next}`);
    set({ runtimeState: next });
  },

  setMetrics: (updates: Partial<RuntimeMetrics>) => set((s) => ({ metrics: { ...s.metrics, ...updates } })),

  // ── Session Initialization Logic ──────────────────────────────

  initSession: async (sessionId: string) => {
    set({ sessionId });
    sceneManager.init(sessionId);
    const firstSceneId = sceneManager.createScene(get().pedagogicalState, { scene_id: "scene_0", label: "Page 1" });
    set({ activeSceneId: firstSceneId, viewedSceneId: firstSceneId });

    await teacherMotor.init({ cursorX: 400, cursorY: 300, sessionId });
    replayEngine.reset();

    teacherStudentPriority.connect(teacherMotor);

    interruptionCoordinator.connect(
      teacherMotor,
      teacherMotor.runtime.temporalScheduler,
      { get, set }
    );

    interactionArbiter.onOwnerChange(() => {
      set({ arbiterState: interactionArbiter.getState() });
    });

    registerTranscriptListener(get, set);

    if (typeof window !== "undefined") {
      if (_sceneEventHandler) {
        window.removeEventListener("scene_start", _sceneEventHandler as any);
        window.removeEventListener("runtime:scene-start", _sceneEventHandler as any);
      }

      _sceneEventHandler = (evt: CustomEvent) => {
        const payload = evt.detail || {};
        const sceneIndex = payload.scene_index !== undefined ? payload.scene_index : payload.sceneIndex;
        if (sceneIndex === undefined) return;
        const sId = `scene_${sceneIndex}`;
        const state = get();
        const existingScene = state.scenes.find(sc => sc.scene_id === sId);
        if (!existingScene) {
          get().addScene({
            scene_id: sId,
            label: payload.label || `Page ${sceneIndex + 1}`,
            concept: state.pedagogicalState?.active_concept || "Concept",
            confusion_level: 0,
            timeline_offset: payload.start_ms ?? payload.timeMs ?? state.currentTimeMs,
            camera_x: sceneIndex * PAGE_W
          });
        }
        set({ activeSceneId: sId, viewedSceneId: sId });
      };

      window.addEventListener("scene_start", _sceneEventHandler as any);
      window.addEventListener("runtime:scene-start", _sceneEventHandler as any);
    }
  },

  addScene: (scene: SceneDescriptor) => set((s) => {
    if (s.scenes.some(sc => sc.scene_id === scene.scene_id)) return {};
    return { scenes: [...s.scenes, scene] };
  }),

  updateScene: (sceneId: string, updates: Partial<SceneDescriptor>) => set((s) => ({
    scenes: s.scenes.map(sc => sc.scene_id === sceneId ? { ...sc, ...updates } : sc)
  })),

  reset: () => {
    ttsPlayer.stop();
    teacherMotor.reset();
    replayEngine.reset();
    currentGenerationId = null;
    _seenEventKeys.clear();
    _densityAccumMs = 0;

    if (typeof window !== "undefined" && _sceneEventHandler) {
      window.removeEventListener("scene_start", _sceneEventHandler as any);
      window.removeEventListener("runtime:scene-start", _sceneEventHandler as any);
      _sceneEventHandler = null;
    }

    set({
      runtimeState: RUNTIME_STATES.IDLE,
      currentTimeMs: 0,
      timelineIndex: 0,
      eventQueue: [],
      transcript: [],
      sceneObjects: {},
      camera: { x: 0, y: 0, zoom: 1 },
      generationId: null,
      sessionId: null,
      sessionTopic: "",
      liveBuffer: [],
      scenes: [],
      activeSceneId: null,
      viewedSceneId: null,
      viewedScenePinned: false,
      isRemediating: false,
      activeMetaphor: "formal",
      studentStrokes: [],
      interactionMode: "LECTURE",
      interactionTool: "pen",
      lastStudentGesture: null,
      errorMessage: null,
      motionState: {
        cursor: { visible: false, x: 0, y: 0, state: "hidden" },
        strokes: [],
        gestures: [],
        focusState: { activeEffects: [], globalDimLevel: 0, focusedObjectIds: new Set<string>() },
        narrationStatus: { progress: 0, state: "idle", isAudioSynced: false },
        phase: "idle",
      },
      narrationStatus: { progress: 0, state: "idle", isAudioSynced: false },
      arbiterState: { owner: "none", canStudentDraw: false, isLocked: false },
      isGenerationCompleted: false,
      _awaitingAutoResume: false,
      pedagogicalPlan: {},
    });
  },

  // ── Event Ingestion Subsystems ───────────────────────────────

  ingestEvent: (evt: TimelineEvent) => {
    const state = get();

    if (state.runtimeState === RUNTIME_STATES.REPLAYING) {
      set((s) => ({ liveBuffer: [...s.liveBuffer, evt] }));
      return;
    }

    let nextQueue = [...state.eventQueue];
    let nextGenId = currentGenerationId;
    let nextTranscript = [...state.transcript];

    if (evt.generation_id && evt.generation_id !== currentGenerationId) {
      currentGenerationId = evt.generation_id;
      nextGenId = evt.generation_id;
      _seenEventKeys.clear();
      _pendingStrokeReveals = [];
      ttsPlayer.stop();

      const isPivoting = state.runtimeState === RUNTIME_STATES.INTERRUPTING || state.runtimeState === RUNTIME_STATES.REMEDIATING;
      const recAdded = state.transcript.some(t => t.text === "Recalculating approach..." && (audioTimeline.currentTimeMs - t.t) < 4000);
      const recalculateMessage = (isPivoting && !recAdded) ? [{
        t: audioTimeline.currentTimeMs, who: "System", text: "Recalculating approach..."
      }] : [];

      // Reset the audio clock to 0 so tick()'s monotonicTimeMs calculation starts
      // fresh. Without this, audioTimeline.currentTimeMs retains the old generation's
      // playback position (e.g. 38 000 ms), causing all new events with start_ms
      // below that value to fire in the first few frames — making strokes appear
      // instantly instead of through pen animation.
      audioTimeline.seek(0);

      nextQueue = [];
      nextTranscript = state.transcript.concat(recalculateMessage);

      // Preserve teacher content across generation boundary (doubt pivots).
      // The new generation resets currentTimeMs to 0, which would make all existing
      // scene objects (whose startMs > 0) invisible. Mark them _lockedComplete so
      // sceneRenderer renders them fully regardless of the new clock start.
      const preservedObjects: Record<string, any> = {};
      for (const [id, obj] of Object.entries(state.sceneObjects)) {
        preservedObjects[id] = { ...(obj as any), _lockedComplete: true };
      }
      set({
        generationId: evt.generation_id,
        sceneObjects: preservedObjects,
        motionState: {
          cursor: { visible: false, x: 0, y: 0, state: "hidden" as const },
          strokes: [],
          gestures: [],
          focusState: { activeEffects: [], globalDimLevel: 0, focusedObjectIds: new Set<string>() },
          narrationStatus: { progress: 0, state: "idle", isAudioSynced: false },
          phase: "idle",
        },
        currentTimeMs: 0,
        timelineIndex: 0,
        isGenerationCompleted: false,
        _awaitingAutoResume: false,
        viewedScenePinned: false,
      });
      // For COMPLETED/IDLE (G3 auto-resume): do NOT enter STREAMING here.
      // teacherMotor.init() is async and calls runtime.reset() which zeroes
      // _staticWriteLaneEndMs. If tick() starts before reset(), G3 stroke_reveal
      // events get effectiveStart = old G2 _staticWriteLaneEndMs (~16 000 ms),
      // completely desynchronised from the new currentTimeMs = 0 clock.
      // Wait for init() to finish before allowing tick() to process G3 events.
      teacherMotor.init().then(() => {
        registerTranscriptListener(get, set);
        // Clear stale equation reveal progress for NEW objects only.
        // Locked objects (carried across generation boundary) must keep their
        // eqReveal entries so they don't temporarily disappear and re-reveal
        // stroke-by-stroke when the new generation starts ticking.
        if (typeof globalThis !== "undefined" && (globalThis as any).__eqReveal) {
          const revMap = (globalThis as any).__eqReveal as Map<string, number>;
          const currentObjects = get().sceneObjects;
          for (const eqId of Array.from(revMap.keys())) {
            const obj = currentObjects[eqId];
            if (!obj || !obj._lockedComplete) {
              revMap.delete(eqId);
            }
          }
        }
        if (state.runtimeState === RUNTIME_STATES.INTERRUPTING) {
          console.info("[runtimeStore] Auto-resuming playback from interruption for new Socratic pivot.");
          get().resumeFromInterruption();
        } else if (
          state.runtimeState === RUNTIME_STATES.COMPLETED ||
          state.runtimeState === RUNTIME_STATES.IDLE
        ) {
          // Safe to enter STREAMING now: runtime.reset() has already run inside
          // init(), so _staticWriteLaneEndMs is 0 and temporalScheduler is at 0.
          get().setState(RUNTIME_STATES.STREAMING);
        }
      }).catch((err) => {
        console.error("[runtimeStore] Failed to initialize teacherMotor:", err);
        // Failsafe: if init throws, still enter STREAMING so the session isn't stuck.
        if (
          state.runtimeState === RUNTIME_STATES.COMPLETED ||
          state.runtimeState === RUNTIME_STATES.IDLE
        ) {
          get().setState(RUNTIME_STATES.STREAMING);
        }
      });
    } else if (!currentGenerationId) {
      currentGenerationId = evt.generation_id || null;
      nextGenId = evt.generation_id || null;
      set({ generationId: evt.generation_id });
    }

    // Phase 8: idempotent ingest — drop a duplicate (generation_id, sequence_number).
    const key = _eventKey(evt);
    if (_seenEventKeys.has(key)) return;
    _seenEventKeys.add(key);

    // Decode-ahead: start decoding a speech event's TTS audio the moment it
    // arrives (well before its start_ms), off the critical path, so playback
    // begins with ~0 decode latency when the event fires — keeping first audio
    // tight with the ink. A stable segment_id is stamped here (the backend omits
    // it; sequence_number is unique per generation) so the ingest-time preload
    // and the fire-time playback in tick() key the same cached buffer.
    if (evt.type === "speech" && evt.payload) {
      if (!evt.payload.segment_id) {
        evt.payload.segment_id = `seg_${evt.generation_id || ""}_${evt.sequence_number ?? evt.start_ms ?? ""}`;
      }
      if (evt.payload.audio_data) {
        teacherMotor.preloadSpeechAudio(evt.payload.segment_id, evt.payload.audio_data);
      }
    }

    let eventStartMs = evt.start_ms;
    if (evt.type === "generation_end" && (!eventStartMs || eventStartMs === 0)) {
      const maxStartMs = Math.max(
        state.currentTimeMs,
        nextQueue.reduce((max, e) => Math.max(max, e.start_ms || 0), 0)
      );
      eventStartMs = maxStartMs + 100;
      evt.start_ms = eventStartMs;
    }
    // Events arrive in start_ms order from the backend emit loop, so only pay
    // for a full re-sort when one actually arrives out of order (a redelivery or
    // a buffered stroke_reveal re-injection) — avoids an O(n²) sort over a lesson.
    const _prevStart = nextQueue.length > 0 ? (nextQueue[nextQueue.length - 1].start_ms || 0) : -Infinity;
    nextQueue.push(evt);
    if ((evt.start_ms || 0) < _prevStart) {
      nextQueue.sort((a, b) => (a.start_ms || 0) - (b.start_ms || 0));
    }

    set({
      eventQueue: nextQueue,
      transcript: nextTranscript,
      metrics: {
        ...state.metrics,
        eventsReceived: state.metrics.eventsReceived + 1,
        queueDepth: nextQueue.length
      }
    });
  },

  // ── Core Clock Aggregator Step Loops (Tick) ───────────────────

  tick: (deltaMs: number) => {
    const s = get();
    if (
      s.runtimeState !== RUNTIME_STATES.STREAMING &&
      s.runtimeState !== RUNTIME_STATES.REPLAYING &&
      s.runtimeState !== RUNTIME_STATES.REMEDIATING
    ) return;

    const actualDeltaMs = s.runtimeState === RUNTIME_STATES.REPLAYING
      ? deltaMs * (s.playbackRate || 1.0)
      : deltaMs;

    const rawTimeMs = audioTimeline.currentTimeMs;
    const audioState = String((audioTimeline as any).state);
    // Phase 8 — single monotonic clock. Never let the authoritative time jump
    // backward when the clock source switches. A backward jump previously re-fired
    // events and desynced narration from ink.
    //
    // Diagram-drawing fix: a procedural sketch can take LONGER to draw than the
    // narration. When the narration audio finishes, audioTimeline.currentTimeMs
    // stops advancing (it returns the frozen master time), which previously froze
    // the whole playhead — so every diagram stroke scheduled after the last word
    // never fired and the board stayed half-drawn. While the lesson is still
    // running and the audio is NOT actively driving the clock (idle/ready/ended —
    // but NOT paused, where we must hold), keep the clock moving on wall-clock time
    // so the remaining strokes draw. While audio plays we still follow it exactly,
    // so ink stays voice-synced during narration.
    const audioDriving = audioState === "playing";
    const audioPaused = audioState === "paused";
    const monotonicTimeMs = (audioDriving || audioPaused)
      ? Math.max(s.currentTimeMs, rawTimeMs)
      : Math.max(s.currentTimeMs + actualDeltaMs, rawTimeMs);
    // Clamp the FORWARD step. A clock surge (tab refocus, GC stall, first audio
    // anchor) would otherwise advance the playhead hundreds of ms in one frame,
    // making the pen snap across an entire stroke/equation instantly. Capping the
    // step lets the timeline catch up smoothly over a few frames instead. Normal
    // audio drift (≤5 ms/frame) and steady playback (~16 ms/frame) are far below
    // this cap, so in-sync playback is unaffected; only pathological jumps bite.
    const maxForwardStepMs = Math.max(120, actualDeltaMs * 3);
    const authoritativeTimeMs = Math.min(monotonicTimeMs, s.currentTimeMs + maxForwardStepMs);

    // Keep events that haven't fired yet.
    let nextEventQueue = s.eventQueue.filter((e) => {
      return (e.start_ms || 0) > authoritativeTimeMs;
    });

    const ready = s.eventQueue.filter((e) => (e.start_ms || 0) <= authoritativeTimeMs);

    // ── Timeline-Driven Rendering ─────────────────────────────────
    // Audio is a CONSUMER of the timeline, not a gatekeeper.
    // All events (speech, ink, scenes) are processed in timeline order.
    // Speech events still fire first within the same tick so audio
    // starts before strokes begin, but audio failure does NOT block
    // ink rendering. This prevents the critical chain:
    //   audio fails → ink gate closed → canvas permanently blank
    const INK_TYPES = new Set([
      "draw_stroke", "annotation", "equation_write", "equation",
      "construction_step", "stroke_segment", "stroke_reveal",
    ]);

    // Sort: non-ink first so speech fires before ink (soft sync hint).
    const preInkReady = ready.filter(e => !INK_TYPES.has(e.type));
    const inkReady = ready.filter(e => INK_TYPES.has(e.type));
    const toProcess = [...preInkReady, ...inkReady];

    const objs = { ...s.sceneObjects };
    const transcript = [...s.transcript];
    let nextIndex = s.timelineIndex;
    let activeCompiledArtifact = s.pedagogicalPlan?.compiled_artifact;
    let currentActiveSceneId = s.activeSceneId || "scene_0";
    let nextPedagogicalState = { ...s.pedagogicalState };
    let nextPedagogicalPlan = s.pedagogicalPlan ? { ...s.pedagogicalPlan } : {};
    let nextScenes = [...s.scenes];
    let nextActiveSceneId = s.activeSceneId || "scene_0";
    let nextViewedSceneId = s.viewedSceneId || "scene_0";
    let nextReviewState = s.reviewState;
    let nextReplanState = s.replanState;
    let nextCheckpointState = s.checkpointState;
    let nextDetectedMisconceptions = [...s.detectedMisconceptions];
    let nextIsGenerationCompleted = s.isGenerationCompleted;

    if (toProcess.length > 0) {
      for (const evt of toProcess) {

        // ── Stroke Reveal Gate ───────────────────────────────────────
        if (evt.type === "stroke_reveal") {
          const objId = evt.payload?.object_id;
          const compiledArtifact = activeCompiledArtifact;
          if (!compiledArtifact || !compiledArtifact.layout_assets) {
            // compiled_artifact not yet loaded — buffer this event for replay
            // when generation_start arrives with the artifact.
            if (!_pendingStrokeReveals) _pendingStrokeReveals = [];
            _pendingStrokeReveals.push(evt);
            console.warn(`[runtimeStore] stroke_reveal buffered (no compiled_artifact yet): ${objId}`);
            continue;
          }
          // Enrich event payload with layout assets before calling the motor
          const layoutAsset = compiledArtifact.layout_assets[objId];
          if (layoutAsset) {
            evt.payload = evt.payload || {};
            evt.payload.latex = evt.payload.latex || layoutAsset.latex;
            evt.payload.text = evt.payload.text || layoutAsset.text;
            evt.payload.position = evt.payload.position || { x: layoutAsset.x, y: layoutAsset.y };
            evt.payload.width = evt.payload.width || layoutAsset.width;
            evt.payload.height = evt.payload.height || layoutAsset.height;
            if (process.env.NODE_ENV !== "production") {
              console.log(`[runtimeStore] stroke_reveal resolved for object ${objId}:`, {
                text: evt.payload.text || null,
                latex: evt.payload.latex || null,
                position: evt.payload.position,
                width: evt.payload.width,
                height: evt.payload.height
              });
            }
          } else {
            console.warn(`[runtimeStore] stroke_reveal missing layoutAsset mapping for object ${objId}`);
          }
        }

        teacherMotor.processEvent(evt, authoritativeTimeMs);
        replayEngine.recordEvent(evt, authoritativeTimeMs);

        if (evt.type === "speech") {
          const text = evt.payload?.text || evt.payload?.transcript_chunk || "";
          if (!text.trim()) continue;

          const segmentId = evt.payload?.segment_id || `speech_${authoritativeTimeMs}`;

          const previous = transcript.at(-1);
          const shouldMerge =
            previous?.who === "Sarasvi" &&
            previous.streaming === false &&
            authoritativeTimeMs - previous.t < 2500 &&
            previous.text.length + text.length < 420;

          if (shouldMerge) {
            previous.text = `${previous.text} ${text}`.replace(/\s+/g, " ").trim();
          } else {
            transcript.push({ t: authoritativeTimeMs, who: "Sarasvi", text, streaming: false });
          }

          if (text) {
            // The audio master clock is anchored ONLY by ttsPlayer →
            // audioTimeline.alignClock() once the audio (or web-speech fallback)
            // is actually scheduled. We deliberately do NOT start() or
            // forceAlign() here: doing so re-anchored the timeline to wall-clock
            // at first-speech, so ink began before any sound played. speak()
            // schedules the audio and aligns the clock precisely to playback.
            //
            // Provider resolution: backend always uses edge-tts for synthesis.
            // When audio_data is present, use "edge_tts" so the correct speech-mark
            // parser is chosen. Only fall back to "generic" if no audio_data exists
            // (which means we are in text-only / fallback mode).
            const hasAudio = !!(evt.payload?.audio_data);
            const resolvedProvider = evt.payload?.provider ||
              (hasAudio ? "edge_tts" : "generic");
            teacherMotor.speak({
              text,
              segmentId,
              absoluteStartMs: authoritativeTimeMs,
              audioData: evt.payload?.audio_data || null,
              speechMarks: evt.payload?.speech_marks || evt.payload?.words || [],
              provider: resolvedProvider
            }).catch((err: any) => {
              console.warn("[runtimeStore] unified speak failed, fallback", err);
            });

            if (evt.payload?.is_review) {
              nextReviewState = { active: true, concept: "review", timestamp: authoritativeTimeMs };
            }
          }

        } else if (evt.type === "generation_start") {
          // Backend forwards lesson metadata: learning objective, domain, unverified claims.
          // Update the pedagogical state so the session UI can display them.
          const p = evt.payload || {};
          activeCompiledArtifact = p.compiled_artifact;
          if (activeCompiledArtifact) {
            teacherMotor.runtime.setCompiledArtifact(activeCompiledArtifact);
          }
          nextPedagogicalState = {
            ...nextPedagogicalState,
            active_concept: p.learning_objective || nextPedagogicalState.active_concept,
            teaching_mode: p.primary_domain || nextPedagogicalState.teaching_mode,
          };
          nextPedagogicalPlan = {
            learning_objective: p.learning_objective,
            primary_domain: p.primary_domain,
            concepts: p.concepts || [],
            unverified_claims: p.unverified_claims || [],
            student_profile: p.student_profile || {},
            compiled_artifact: p.compiled_artifact,
          };

          // Replay any stroke_reveal events that were buffered before this artifact loaded
          if (_pendingStrokeReveals && _pendingStrokeReveals.length > 0 && activeCompiledArtifact?.layout_assets) {
            console.info(`[runtimeStore] Replaying ${_pendingStrokeReveals.length} buffered stroke_reveal events`);
            const buffered = _pendingStrokeReveals;
            _pendingStrokeReveals = null;
            // Re-inject buffered events into the queue so they get processed next tick
            nextEventQueue = [...nextEventQueue, ...buffered];
            nextEventQueue.sort((a, b) => (a.start_ms || 0) - (b.start_ms || 0));
          } else {
            _pendingStrokeReveals = null;
          }

        } else if (evt.type === "camera_move") {
          // Handled downstream via camera state updates or merged

        } else if (evt.type === "scene_start") {
          const sId = `scene_${evt.payload?.scene_index}`;
          currentActiveSceneId = sId;
          nextActiveSceneId = sId;
          const existingScene = nextScenes.find(sc => sc.scene_id === sId);
          const nextViewedId = (s.viewedScenePinned ? s.viewedSceneId : sId) || sId;
          nextViewedSceneId = nextViewedId;
          if (!existingScene) {
            nextScenes = [...nextScenes, {
              scene_id: sId,
              label: evt.payload?.label || `Page ${evt.payload?.scene_index + 1}`,
              concept: nextPedagogicalState?.active_concept || "Concept",
              confusion_level: 0,
              timeline_offset: evt.start_ms ?? authoritativeTimeMs,
              camera_x: evt.payload?.camera_x || (evt.payload?.scene_index * PAGE_W),
            }];
          }

        } else if (evt.type === "scene_mutation") {
          const activeSId = currentActiveSceneId;
          const pgIndex = parseInt(activeSId.split("_")[1]) || 0;
          for (const m of (evt.payload?.mutations || [])) {
            if (m.action === "CREATE_OBJECT") {
              Reflect.set(objs, m.id, {
                id: m.id, type: m.type, data: m.data,
                position: m.position, visible: true,
                width: m.width, height: m.height,
                opacity: 0, scale: 0.9, _fadeTarget: 1,
                startMs: evt.start_ms ?? authoritativeTimeMs,
                sceneId: activeSId,
                pageIndex: pgIndex,
                isReview: !!evt.payload?.is_review
              });
              whiteboardCognition.registerObject(m.id, m.position?.x, m.position?.y);
            } else if (m.action === "UPDATE_OBJECT") {
              if (Reflect.has(objs, m.id)) {
                Reflect.set(objs, m.id, { ...Reflect.get(objs, m.id), ...m.updates });
              }
            } else if (m.action === "DELETE_OBJECT") {
              if (Reflect.has(objs, m.id)) {
                Reflect.get(objs, m.id)._fadeTarget = 0;
              }
            }
          }

        } else if (evt.type === "draw_stroke" || evt.type === "equation_write" || evt.type === "stroke_reveal") {
          const activeSId = currentActiveSceneId;
          const pgIndex = parseInt(activeSId.split("_")[1]) || 0;

          let resolvedType = evt.type;
          if (evt.type === "stroke_reveal") {
            const objId = evt.payload?.object_id;
            const compiledArtifact = activeCompiledArtifact;
            const layoutAsset = compiledArtifact?.layout_assets?.[objId];
            if (!layoutAsset) {
              // Layout asset missing for this object_id — use fallback center position
              const pgIdx = parseInt(currentActiveSceneId.split("_")[1]) || 0;
              const fallbackX = pgIdx * PAGE_W + BOARD_WIDTH / 2;
              const fallbackY = BOARD_HEIGHT / 2;
              evt.payload = evt.payload || {};
              evt.payload.position = evt.payload.position || { x: fallbackX, y: fallbackY };
              console.warn(`[runtimeStore] stroke_reveal missing layout asset for ${objId}, using fallback position (${fallbackX}, ${fallbackY})`);
            }
            resolvedType = "equation_write";
          }

          const eqId = evt.payload?.equation_id || evt.payload?.stroke_id || evt.payload?.object_id || `auto_${evt.type}_${nextIndex}`;
          const patchBoard = resolvedType === "equation_write" && shouldPatchBoard(evt.payload || {}, eqId);
          const objId = patchBoard
            ? resolvePedagogicalBoardId(evt.payload || {}, eqId)
            : eqId;
          const payloadSceneIndex =
            evt.payload?.scene_index ?? evt.payload?.metadata?.scene_index;
          const payloadSceneId =
            evt.payload?.scene_id ??
            evt.payload?.metadata?.scene_id ??
            (payloadSceneIndex !== undefined ? `scene_${payloadSceneIndex}` : activeSId);
          const payloadPageIndex =
            payloadSceneIndex !== undefined ? payloadSceneIndex : pgIndex;

          const currentAudioTime = audioTimeline.state === "playing"
            ? audioTimeline.currentTimeMs
            : authoritativeTimeMs;

          const existingObj = Reflect.get(objs, objId);
          if (existingObj) {
            const nextObj: any = {
              ...existingObj,
              type: resolvedType,
              width: evt.payload?.width ?? existingObj.width,
              height: evt.payload?.height ?? existingObj.height,
              data: { ...existingObj.data, ...evt.payload, board_id: evt.payload?.board_id || objId },
              sceneId: existingObj.sceneId || payloadSceneId,
              pageIndex: existingObj.pageIndex ?? payloadPageIndex,
            };

            if (patchBoard) {
              const writeMode = getPedagogicalWriteMode(evt.payload || {});
              let nextLatex = evt.payload?.latex || "";
              if (writeMode === "append" && existingObj._mergedLatex) {
                nextLatex = existingObj._mergedLatex + " " + nextLatex;
              }
              const stepId = evt.payload?.object_id || eqId;
              const currentStepIds = existingObj._boardStepIds || [];
              const nextStepIds = currentStepIds.includes(stepId)
                ? currentStepIds
                : [...currentStepIds, stepId];

              nextObj._mergedLatex = nextLatex;
              nextObj._boardStepIds = nextStepIds;
              nextObj._boardId = objId;
            }

            Reflect.set(objs, objId, nextObj);
          } else {
            const nextObj: any = {
              id: objId, type: resolvedType, data: evt.payload,
              position: evt.payload?.position || { x: 0, y: 0 },
              width: evt.payload?.width, height: evt.payload?.height,
              visible: true, opacity: 1, scale: 1,
              startMs: evt.start_ms ?? currentAudioTime,
              sceneId: payloadSceneId,
              pageIndex: payloadPageIndex,
              _inkAuthority: resolvedType === "draw_stroke" ? "motion" as const : "static" as const,
              _boardId: evt.payload?.board_id || evt.payload?.derivation_id || objId,
              _boardRole: evt.payload?.board_role || evt.payload?.metadata?.board_role,
              _writeMode: evt.payload?.write_mode || evt.payload?.metadata?.write_mode,
            };

            if (patchBoard) {
              const nextLatex = evt.payload?.latex || "";
              const stepId = evt.payload?.object_id || eqId;
              nextObj._mergedLatex = nextLatex;
              nextObj._boardStepIds = [stepId];
              nextObj._boardId = objId;
            }

            Reflect.set(objs, objId, nextObj);
          }

          whiteboardCognition.registerObject(objId, evt.payload?.position?.x || 0, evt.payload?.position?.y || 0);

          // Dev-only stroke diagnostic trace (no-op in production).
          if (process.env.NODE_ENV !== "production" && typeof window !== 'undefined') {
            try {
              const diag = (window as any).__strokeDiagnostics = (window as any).__strokeDiagnostics || [];
              diag.push({ t: authoritativeTimeMs, type: evt.type, id: objId });
              if (diag.length > 500) diag.shift();
            } catch (_) { /* ignore */ }
          }

        } else if (evt.type === "timeline_mutation") {
          if (evt.payload?.action === "REPLAN") {
            nextReplanState = {
              active: true,
              reason: evt.payload.reason || "decelerating",
              strategy: evt.payload.strategy || "rephrase",
              confusion: evt.payload.confusion_level || 0.8,
              timestamp: authoritativeTimeMs
            };
            setTimeout(() => {
              const current = useRuntimeStore.getState().replanState;
              if (current?.timestamp === authoritativeTimeMs) {
                set({ replanState: null });
              }
            }, 4000);
          }

        } else if (
          // Backend emits type="socratic_checkpoint"; legacy path also checks
          // type="pause" with checkpoint_type in payload.
          evt.type === "socratic_checkpoint" ||
          (evt.type === "pause" && evt.payload?.checkpoint_type === "socratic_checkpoint")
        ) {
          nextCheckpointState = {
            active: true,
            questionText: evt.payload?.text || evt.payload?.question || "What do you think?",
            nodeId: evt.payload?.node_id || "chk_1",
            timestamp: authoritativeTimeMs
          };
          audioTimeline.pause();

        } else if (evt.type === "evaluation_result") {
          const isCorrect = evt.payload?.is_correct;
          const detectedMisconception = evt.payload?.detected_misconception;

          if (detectedMisconception) {
            nextDetectedMisconceptions.push({ id: `mc_${Date.now()}`, concept: detectedMisconception, detectedAt: Date.now() });
          }
          nextCheckpointState = null;

        } else if (evt.type === "generation_end") {
          // A failed generation (no content produced) must not leave the loader
          // spinning forever — surface a friendly error and flip to ERROR so the
          // session overlay can offer Retry / Back to dashboard. Successful ends
          // (reason "completed") keep STREAMING until TTS finishes naturally.
          const reason = evt.payload?.reason;
          const isFailure = reason === "error" || reason === "plan_rejected";
          if (isFailure && Object.keys(objs).length === 0) {
            // Use a fixed friendly message — never surface raw backend error text.
            set({ errorMessage: "We couldn't generate this lesson. Please try again." });
            get().setState(RUNTIME_STATES.ERROR);
          } else {
            // If auto-resume is pending (G2 doubt just finished, G3 coming),
            // don't mark generation completed — the lesson isn't done yet.
            if (!s._awaitingAutoResume) {
              nextIsGenerationCompleted = true;
            }
          }
          interactionArbiter.resetIdle();
        }
      }
    }

    // ── 3. Animate Object Opacities ───────────────────────────
    for (const [id, obj] of Object.entries(objs)) {
      const targetOp = obj._fadeTarget ?? 1;
      if (Math.abs(obj.opacity - targetOp) > 0.005) {
        obj.opacity += (targetOp - obj.opacity) * 0.1;
      } else {
        obj.opacity = targetOp;
        if (targetOp === 0) Reflect.deleteProperty(objs, id);
      }
    }

    // ── 4. Process Motor Control Tasks ──────────────────────────
    // FIX: Assert return profile configuration layout types as MotionRenderState explicitly
    const motionRenderState: MotionRenderState = teacherMotor.tick(actualDeltaMs);

    if (process.env.NODE_ENV !== "production" && typeof window !== 'undefined') {
      try {
        const trace = (window as any).__cursorTrace = (window as any).__cursorTrace || [];
        trace.push({ t: authoritativeTimeMs, cursor: motionRenderState.cursor });
        if (trace.length > 2000) trace.shift();
        if (!(window as any).__downloadCursorTrace) {
          (window as any).__downloadCursorTrace = () => {
            const blob = new Blob([JSON.stringify(trace)], { type: 'application/json' });
            const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: 'cursor_trace.json' });
            a.click();
          };
        }
      } catch (_) { /* ignore */ }
    }

    // ── 5. Merge Elements Back To Cache Maps ───────────────────────
    const motionSceneObjects = motionRenderState.sceneObjects || {};
    const mergedObjects = { ...objs };
    const motorPageIndex = parseInt(currentActiveSceneId.split("_")[1]) || 0;
    if (authoritativeTimeMs >= 500) {
      for (const obj of Object.values(mergedObjects)) {
        const boardId = resolveSceneObjectBoardId(obj as any);
        if (!boardId || !(obj as any)._mergedLatex) continue;
        const stepIds = (obj as any)._boardStepIds || [];
        pruneSupersededBoardObjects(mergedObjects, boardId, stepIds, authoritativeTimeMs);
      }
    }

    for (const [id, mObj] of Object.entries(motionSceneObjects)) {
      const existing = Reflect.get(mergedObjects, id);
      if (!existing) {
        Reflect.set(mergedObjects, id, {
          ...(mObj as any),
          sceneId: (mObj as any).sceneId || currentActiveSceneId,
          pageIndex: (mObj as any).pageIndex ?? motorPageIndex,
        });
      } else {
        Reflect.set(mergedObjects, id, {
          ...existing,
          ...(mObj as any),
          id: existing.id,
          sceneId: existing.sceneId || currentActiveSceneId,
          pageIndex: existing.pageIndex ?? motorPageIndex,
          _lockedComplete: existing._lockedComplete || (mObj as any)._lockedComplete,
        });
      }
    }

    if (process.env.NODE_ENV !== "production" && typeof window !== "undefined") {
      try {
        const motionStateForDiag = {
          cursor: {
            ...(motionRenderState.cursor || {}),
            writingTip: (motionRenderState.cursor as { writingTip?: { x: number; y: number } | null })?.writingTip ?? null,
          },
          strokes: motionRenderState.strokes || [],
          activeWritingEquationId: motionRenderState.activeWritingEquationId ?? null,
          writingTipEquationId: motionRenderState.writingTipEquationId ?? null,
          revealingEquationIds: motionRenderState.revealingEquationIds ?? [],
        };
        const diag = computeWritingDiagnostics(mergedObjects, motionStateForDiag, authoritativeTimeMs);
        (window as any).__writingDiagnostics = diag;
      } catch (_) { /* ignore */ }
    }

    // ── 6. Write Temporal Snapshots ──────────────────────────────
    if (replayEngine.shouldSnapshot(authoritativeTimeMs)) {
      replayEngine.recordSnapshot(teacherMotor.takeSnapshot(), authoritativeTimeMs);
      replayEngine.markSnapshotTaken(authoritativeTimeMs);
    }

    const audioMetrics = motionRenderState.audioMetrics || { latencyOffsetMs: 0, driftMs: 0 };
    const arbiterState = interactionArbiter.getState();

    // ── 7. Atomic Layout Dispatches with Saccadic Gaze Overlays ────
    set({
      currentTimeMs: authoritativeTimeMs,
      eventQueue: nextEventQueue,
      sceneObjects: mergedObjects,
      transcript: transcript,
      timelineIndex: nextIndex,
      pedagogicalState: nextPedagogicalState,
      pedagogicalPlan: nextPedagogicalPlan,
      scenes: nextScenes,
      activeSceneId: nextActiveSceneId,
      viewedSceneId: nextViewedSceneId,
      reviewState: nextReviewState,
      replanState: nextReplanState,
      checkpointState: nextCheckpointState,
      detectedMisconceptions: nextDetectedMisconceptions,
      isGenerationCompleted: nextIsGenerationCompleted,
      motionState: {
        cursor: {
          visible: motionRenderState.cursor?.visible ?? false,
          x: motionRenderState.cursor?.x ?? 0,
          y: motionRenderState.cursor?.y ?? 0,
          writingTip: (motionRenderState.cursor as { writingTip?: { x: number; y: number } | null })?.writingTip ?? null,
          gazeX: motionRenderState.cursor?.gazeX ?? motionRenderState.cursor?.x ?? 0,
          gazeY: motionRenderState.cursor?.gazeY ?? motionRenderState.cursor?.y ?? 0,
          state: motionRenderState.cursor?.state ?? "idle",
          isEyeAhead: motionRenderState.cursor?.isEyeAhead ?? false
        },
        activeWritingEquationId: motionRenderState.activeWritingEquationId ?? null,
        writingTipEquationId: motionRenderState.writingTipEquationId ?? null,
        revealingEquationIds: motionRenderState.revealingEquationIds ?? [],
        strokes: motionRenderState.strokes || [],
        gestures: motionRenderState.gestures || [],
        focusState: motionRenderState.focusState || { activeEffects: [], globalDimLevel: 0, focusedObjectIds: new Set<string>() },
        narrationStatus: motionRenderState.narrationStatus || { progress: 0, state: "idle", isAudioSynced: false },
        phase: motionRenderState.phase || "idle",
      },
      narrationStatus: motionRenderState.narrationStatus || { progress: 0, state: "idle", isAudioSynced: false },
      arbiterState,
      metrics: {
        ...s.metrics,
        queueDepth: nextEventQueue.length,
        motionActors: motionRenderState.actors?.totalActors || 0,
        activeStrokes: ((motionRenderState.strokes || []).filter((st: any) => st.state === "growing").length) +
          Object.values(mergedObjects).filter((o: any) => (o.type === "draw_stroke" || o.type === "equation_write" || o.type === "stroke") && (authoritativeTimeMs - o.startMs < (o.data?.duration_ms || o.data?.total_duration_ms || 1000))).length,
        fps: motionRenderState.fps || 60,
        audioLatencyMs: audioMetrics.latencyOffsetMs || 0,
        clockDriftMs: audioMetrics.driftMs || 0,
      }
    });

    // ── 8. Cognitive Load Adjustments ─────────────────────────────
    // Throttled to ~12.5 Hz. dtMs is accumulated and passed as the sum so the
    // store's exponential-fatigue/time integral is unaffected by the lower rate;
    // density/complexity are instantaneous, so sampling them less often is fine.
    _densityAccumMs += deltaMs;
    if (_densityAccumMs >= 80) {
      useCognitiveDensityStore.getState().updateMetrics(
        { objectCount: Object.keys(mergedObjects).length, text: transcript.length * 0.1 },
        { reasoningSteps: ready.length * 0.05 },
        _densityAccumMs
      );
      _densityAccumMs = 0;
    }

    // Forward client-sensed load to the backend as a SENSOR reading. The backend
    // (cognitive_tracker) is the sole authority that decides adaptation from it;
    // the local overallLoad is used only for cursor pacing (presentation). This is
    // background telemetry (NOT a student doubt) feeding the long-term student
    // model. Throttled to ≥8s and only on a clearly meaningful change (≥0.15) to
    // keep /interaction quiet, and only during a live stream.
    _loadFwdAccumMs += deltaMs;
    if (_loadFwdAccumMs >= 8000) {
      _loadFwdAccumMs = 0;
      if (s.sessionId && s.runtimeState === RUNTIME_STATES.STREAMING) {
        const cd = useCognitiveDensityStore.getState();
        if (Math.abs(cd.overallLoad - _lastSentLoad) >= 0.15) {
          _lastSentLoad = cd.overallLoad;
          import("@/lib/api_sessions").then(({ sendInteractionSignal }) => {
            sendInteractionSignal(s.sessionId as string, "cognitive_load", {
              load: cd.overallLoad,
              visual_density: cd.visualDensity,
              cognitive_complexity: cd.cognitiveComplexity,
            }, "general");
          }).catch(() => { /* fire-and-forget */ });
        }
      }
    }
    cameraCognition.update(motionRenderState.cursor as any, mergedObjects, deltaMs);

    if (nextIndex % 50 === 0 && s.runtimeState === RUNTIME_STATES.STREAMING) {
      sceneManager.takeSnapshot({
        pedagogicalState: s.pedagogicalState,
        attentionState: s.attentionState,
        transitionContext: s.transitionContext,
        sceneGraphState: { mutations: [] },
        cameraState: s.camera,
        transcriptState: s.transcript,
        timelineIndex: nextIndex,
        timelineOffsetMs: authoritativeTimeMs
      }, "replay_checkpoint");
    }

    // ── Transition to COMPLETED state once all events, drawing and voice are complete ──
    if (
      s.runtimeState === RUNTIME_STATES.STREAMING &&
      nextIsGenerationCompleted &&
      !s._awaitingAutoResume &&
      nextEventQueue.length === 0 &&
      !ttsPlayer.isPlaying() &&
      (!motionRenderState.strokes || motionRenderState.strokes.length === 0 || motionRenderState.strokes.every((st: any) => st.state === "completed"))
    ) {
      console.info("[runtimeStore] Lesson complete! Transitioning state to COMPLETED.");
      get().setState(RUNTIME_STATES.COMPLETED);
    }
  },

  // ── Scene Restoration Subsystems ──────────────────────────────────

  restoreHistoricalScene: async (sceneId: string) => {
    get().setState(RUNTIME_STATES.REPLAYING);
    set({ activeSceneId: sceneId });
    try {
      const snapshot = await sceneManager.restoreScene(sceneId) as any; // FIX: Cast snapshot as any to avoid implicit type lookup checks
      set({
        pedagogicalState: snapshot.pedagogical_state,
        pedagogicalPlan: snapshot.pedagogical_plan || {},
        attentionState: snapshot.attention_state,
        transitionContext: snapshot.transition_context,
        sceneObjects: snapshot.scene_graph_state?.objects || {},
        visualPlan: snapshot.visual_plan || {},
        camera: snapshot.camera_state,
        transcript: snapshot.transcript_state,
        currentTimeMs: snapshot.timeline_offset,
        timelineIndex: snapshot.replay_cursor
      });
    } catch (e) {
      console.error("Failed to restore scene", e);
    }
  },

  returnToLive: () => {
    const buffer = get().liveBuffer;
    set({ eventQueue: [...get().eventQueue, ...buffer], liveBuffer: [], isRemediating: false, viewedScenePinned: false });
    get().setState(RUNTIME_STATES.STREAMING);
  },

  triggerRemediation: (metaphor: string = "analogy") => {
    const state = get();
    if (state.isRemediating) return;
    set({ isRemediating: true, activeMetaphor: metaphor, runtimeState: RUNTIME_STATES.REMEDIATING });
    metaphorEngine.setMetaphor(metaphor as MetaphorType);
    sceneManager.branchScene({ label: `Remediation: ${metaphor}`, metaphor_strategy: metaphor });
  },

  setMetaphor: (metaphor: string) => {
    set({ activeMetaphor: metaphor });
    metaphorEngine.setMetaphor(metaphor as MetaphorType);
  },

  seekTime: (targetTimeMs: number) => {
    const s = get();
    const newTime = Math.max(0, targetTimeMs);
    
    // Reconstruct the future event queue from the replay log to allow full playhead seek/replay
    const allLogEntries = replayEngine.exportLog().events || [];
    const futureEvents = allLogEntries
      .filter((entry: any) => entry.timeMs > newTime)
      .map((entry: any) => entry.event as TimelineEvent);

    const nextState = s.runtimeState === RUNTIME_STATES.COMPLETED ? RUNTIME_STATES.PAUSED : s.runtimeState;

    set({ 
      currentTimeMs: newTime, 
      cameraLocked: false,
      runtimeState: nextState,
      eventQueue: futureEvents,
      isGenerationCompleted: false
    });
    
    audioTimeline.seek(newTime);
    const result = replayEngine.seekTo(newTime) as any; // FIX: Assert result as any to ensure type transparency
    if (result && result.snapshot) {
      const snapshot = result.snapshot;
      set({
        sceneObjects: snapshot.scene_graph_state?.objects || {},
        visualPlan: snapshot.visual_plan || {},
        camera: snapshot.camera_state,
        transcript: snapshot.transcript_state,
        timelineIndex: snapshot.replay_cursor
      });
    }
  },

  togglePlayback: () => {
    const s = get();
    // Only PAUSED/STREAMING/COMPLETED are valid pause-toggle states
    if (s.runtimeState === RUNTIME_STATES.PAUSED) {
      set({ runtimeState: RUNTIME_STATES.STREAMING });
      // Order matters: resume the audio clock + AudioContext FIRST so the
      // master time is live again before the tick loop reads it.
      audioTimeline.resume();
      ttsPlayer.resume();
      teacherMotor.resume();
    } else if (s.runtimeState === RUNTIME_STATES.STREAMING) {
      set({ runtimeState: RUNTIME_STATES.PAUSED });
      // Freeze the master clock + suspend scheduled edge-tts so the voice stops
      // exactly where the ink does. tick() already early-returns while PAUSED.
      audioTimeline.pause();
      ttsPlayer.pause();
      teacherMotor.pause();
    } else if (s.runtimeState === RUNTIME_STATES.COMPLETED) {
      // Replay from start
      // get().seekTime(0);
      // set({ runtimeState: RUNTIME_STATES.STREAMING });
      // audioTimeline.resume();
      // ttsPlayer.resume();
      // teacherMotor.resume();
      console.info("[runtimeStore] togglePlayback: session completed, ignoring replay from start request in live session.");
    }
  },

  // ── Student Canvas Interaction Controls ─────────────────────────

  addStudentStroke: (stroke: any) => set((s) => ({ studentStrokes: [...s.studentStrokes, stroke] })),
  clearStudentStrokes: () => set({ studentStrokes: [] }),

  setInteractionMode: (mode: string) => {
    set({ interactionMode: mode });
    teacherMotor.setInteractionMode(mode);
  },
  setInteractionTool: (tool: string) => set({ interactionTool: tool }),

  triggerInterruption: async (context: any) => {
    const success = await teacherMotor.interrupt(context);
    if (success) get().setState(RUNTIME_STATES.INTERRUPTING);
    return success;
  },

  resumeFromInterruption: async () => {
    // Mark that a doubt pivot just finished playing; auto-resume (G3) is expected.
    // This prevents the COMPLETED transition from firing between G2 end and G3 arrival.
    set({ _awaitingAutoResume: true });
    await teacherMotor.resumeFromInterruption();
    get().returnToLive();
  },

  pinViewedScene: (sceneId: string) => set({ viewedSceneId: sceneId, viewedScenePinned: true }),

  unpinViewedScene: () => {
    const { activeSceneId } = get();
    set({ viewedSceneId: activeSceneId, viewedScenePinned: false });
  },

  toggleBoardTheme: () => set((s) => ({ boardTheme: s.boardTheme === "dark" ? "light" : "dark" })),

  setTTSRate: (rate: number) => {
    teacherMotor.setPlaybackRate?.(rate);
    set({ playbackRate: rate });
  },

  setTTSVolume: (vol: number) => {
    ttsPlayer.setVolume(vol);
  },

  applyMutations: (mutations: any[]) => {
    const objs = { ...get().sceneObjects };
    const activeSId = get().activeSceneId || "scene_0";
    const pgIndex = parseInt(activeSId.split("_")[1]) || 0;

    for (const m of mutations) {
      if (m.action === "CREATE_OBJECT") {
        Reflect.set(objs, m.id, {
          id: m.id, type: m.type, data: m.data,
          position: m.position, visible: true,
          opacity: 1, scale: 1, _fadeTarget: 1,
          startMs: get().currentTimeMs,
          sceneId: activeSId,
          pageIndex: pgIndex
        });
      } else if (m.action === "UPDATE_OBJECT") {
        if (Reflect.has(objs, m.id)) {
          Reflect.set(objs, m.id, { ...Reflect.get(objs, m.id), ...m.updates });
        }
      } else if (m.action === "DELETE_OBJECT") {
        if (Reflect.has(objs, m.id)) {
          Reflect.get(objs, m.id)._fadeTarget = 0;
        }
      }
    }
    set({ sceneObjects: objs });
  },

  appendTranscript: (entry: TranscriptEntry) => {
    set((s) => ({
      transcript: [...s.transcript, entry].slice(-200)
    }));
  },

  submitCheckpointAnswer: async (answer: string) => {
    const s = get();
    if (!s.checkpointState?.active) return;

    // We need to send this to the backend via WebSocket. 
    // The websocket service usually handles this. Let's fire a custom event that websocket service can pick up.
    if (typeof window !== "undefined") {
      const event = new CustomEvent("runtime:send-ws-message", {
        detail: {
          type: "checkpoint_response",
          payload: { text: answer, node_id: s.checkpointState.nodeId }
        }
      });
      window.dispatchEvent(event);
    }
  },

  clearCheckpoint: () => {
    set({ checkpointState: null });
    // Resume audio if it was paused for checkpoint
    if (audioTimeline.state === "paused") {
      audioTimeline.resume();
    }
  }
}));

// Expose runtime handles for interactive debugging in development
if (typeof window !== "undefined") {
  try {
    const w = window as any;
    w.__teacherMotor = w.__teacherMotor || teacherMotor;
    w.__useRuntimeStore = w.__useRuntimeStore || useRuntimeStore;
    // Alias without underscore — use in DevTools without imports
    w.useRuntimeStore = w.useRuntimeStore || useRuntimeStore;

    w.__getWritingDiagnostics = () => {
      const st = useRuntimeStore.getState();
      return computeWritingDiagnostics(
        st.sceneObjects,
        st.motionState,
        st.currentTimeMs
      );
    };

    w.__assertWritingQuality = (maxTipDistancePx = 3) => {
      const d = w.__getWritingDiagnostics();
      const ok =
        (d.distanceToTip === null || d.distanceToTip <= maxTipDistancePx) &&
        (d.inkAheadStrokes?.length ?? 0) === 0 &&
        d.violations.length === 0;
      console[ok ? "log" : "warn"]("[writing quality]", ok ? "PASS" : "FAIL", d);
      return ok;
    };
  } catch (e) {
    // swallow in case environment disallows assignment
  }
}
