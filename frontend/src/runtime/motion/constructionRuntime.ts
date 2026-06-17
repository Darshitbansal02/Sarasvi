/**
 * constructionRuntime.ts — Audio-Driven Construction Choreography
 *
 * Core authority driving real-time whiteboard drawing and choreography synchronization.
 * Preserves all internal engine logic while establishing type safety across motion domains.
 * Enhanced to support look-ahead eye gaze maps and mid-stroke startle skids.
 */

import { CursorActor, CURSOR_STATE } from "./cursorActor";
import { StrokeScheduler, StrokeRenderState } from "./strokeScheduler";
import { HesitationEngine } from "./hesitationEngine";
import { NarrationSync } from "./narrationSync";
import { FocusEngine } from "./focusEngine";
import { GestureDynamics } from "./gestureDynamics";
import { MotionPlanner } from "./motionPlanner";
import { ActorRegistry, ACTOR_TYPE } from "./actorRegistry";
import { TemporalScheduler } from "./temporalScheduler";
import { Spring2D, SPRING_PRESETS } from "./motionPhysics";
import { audioTimeline } from "../audio/audioTimeline";
import { audioEventBridge } from "../audio/audioEventBridge";
import { interactionArbiter, OWNER, OWNERSHIP_PRIORITY } from "../interaction/interactionArbiter";
import { useCognitiveDensityStore } from "../cognitiveDensity";
import { cameraCognition } from "./cameraCognition";
import { simulationEngine } from "./simulationEngine";
import {
  getPedagogicalWriteMode,
  pruneSupersededBoardObjects,
  resolvePedagogicalBoardId,
  resolveSceneStampFromPayload,
  shouldPatchBoard,
} from "./derivationBoard";
import {
  findCurrentWriteStroke,
  getEquationWriteEndMs,
  getRevealOrder,
  isTextObjectInWriteWindow,
  resolveActiveWritingEquationId,
} from "@/components/canvas/renderers/canvasRenderHelpers";
import { collectWhiteboardAuditFindings, reportWhiteboardAuditFindings } from "./whiteboardAudit";

// ── Construction Phase Definition ──────────────────────────────

export enum CONSTRUCTION_PHASE {
  IDLE = "idle",
  PLANNING = "planning",
  EXECUTING = "executing",
  PAUSING = "pausing",
  TRANSITIONING = "transitioning",
  COMPLETED = "completed",
}

// ── Structural Interactivity Interfaces ────────────────────────

export interface ConstructionEvent {
  type: string;
  payload?: Record<string, any>;
}

export interface CharStateEntry {
  id: string;
  type: "stroke" | "glyph" | string;
  startMs: number;
  endMs: number;
  strokeIndex?: number;
  char?: string;
  wordBoundaryIndex?: number;
  absoluteStartMs?: number;
  absoluteEndMs?: number;
}

export interface SceneObjectData {
  latex?: string;
  text?: string;
  font_size?: number;
  size?: number;
  total_duration_ms?: number;
  duration_ms?: number;
  position?: { x: number; y: number };
  width?: number;
  height?: number;
  color?: string;
  thickness?: number;
  difficulty?: number;
  intensity?: number;
  strategy?: string;
  focus_id?: string;
  target_ids?: string[];
  board_id?: string;
  board_role?: string;
  write_mode?: string;
  append_latex?: string;
  full_latex?: string;
  parent_board_id?: string;
  [key: string]: any;
}

export interface SceneObject {
  id: string;
  type: string;
  data?: SceneObjectData;
  position?: { x: number; y: number };
  width?: number;
  height?: number;
  x?: number;
  y?: number;
  visible?: boolean;
  opacity?: number;
  scale?: number;
  startMs: number;
  _fadeTarget?: number;
  _textProgress?: number;
  _label?: string;
  _textRevealMs?: number | null;
  _textStartMs?: number;
  _charStates?: CharStateEntry[];
  _glyphsLayout?: any[];
  _strokesLayout?: any[];
  _constructionSequence?: Array<{ type: string; index: number }>;
  _mergedLatex?: string;
  _boardCompletedStrokeMaxIndex?: number;
  _boardStepIds?: string[];
  _boardId?: string;
  _boardRole?: string;
  _writeMode?: string;
  _totalTextWidth?: number;
  _safeTextX?: number;
  _safeTextY?: number;
  /** static = linesGfx only; motion = strokeScheduler / mStrokeLayer only */
  _inkAuthority?: "static" | "motion";
  sceneId?: string;
  pageIndex?: number;
}

export interface NodeConstructionItem {
  type: "stroke" | "fill" | "text" | string;
  strokeId?: string;
  waypoints?: [number, number][];
  color?: string;
  durationMs?: number;
  startMs: number;
  difficulty?: number;
  node_id?: string;
  label?: string;
  duration_ms?: number;
}

export interface NarrationAnchor {
  anchorId: string;
  speechText: string;
  visualAction: string;
  visualTargetIds: string[];
  offsetMs?: number;
  durationMs: number;
}

// ── ConstructionRuntime Class ──────────────────────────────────

export class ConstructionRuntime {
  public cursor: CursorActor;
  public strokeScheduler: StrokeScheduler;
  public hesitationEngine: HesitationEngine;
  public narrationSync: NarrationSync;
  public focusEngine: FocusEngine;
  public gestureDynamics: GestureDynamics;
  public actorRegistry: ActorRegistry;
  public temporalScheduler: TemporalScheduler;
  public motionPlanner: MotionPlanner;
  public phase: CONSTRUCTION_PHASE;

  private _cursorSpring: Spring2D;
  private _constructionQueue: any[];
  private _nodeConstructionQueue: NodeConstructionItem[];
  private _sceneObjects: Record<string, SceneObject>;
  private _activeTextObjId: string | null;
  /** End of last static (equation/annotation) write — serializes concurrent start_ms:0 payloads. */
  private _staticWriteLaneEndMs: number;
  /** Board-space tip for static ink (nib sync); null when not writing text. */
  private _writingTip: { x: number; y: number } | null;
  private _compiledArtifact: any = null;

  public setCompiledArtifact(artifact: any): void {
    this._compiledArtifact = artifact;
  }

  constructor() {
    this.cursor = new CursorActor("teacher_main");
    this.strokeScheduler = new StrokeScheduler();
    this.hesitationEngine = new HesitationEngine();
    this.narrationSync = new NarrationSync();
    this.focusEngine = new FocusEngine();
    this.gestureDynamics = new GestureDynamics();
    this.actorRegistry = new ActorRegistry();
    this.temporalScheduler = new TemporalScheduler();

    this._cursorSpring = new Spring2D(SPRING_PRESETS.cursor_normal);

    this.motionPlanner = new MotionPlanner({
      cursor: this.cursor,
      strokeScheduler: this.strokeScheduler,
      hesitationEngine: this.hesitationEngine,
      narrationSync: this.narrationSync,
    });

    this.phase = CONSTRUCTION_PHASE.IDLE;
    this._constructionQueue = [];
    this._nodeConstructionQueue = [];
    this._sceneObjects = Object.create(null);
    this._activeTextObjId = null;
    this._staticWriteLaneEndMs = 0;
    this._writingTip = null;

    this.actorRegistry.register("teacher_main", ACTOR_TYPE.CURSOR, this.cursor);

    // FIX: Cast temporalScheduler as any to prevent private variable signature overlap conflicts safely
    audioEventBridge.connect({
      temporalScheduler: this.temporalScheduler as any,
      narrationSync: this.narrationSync,
      cursorActor: this.cursor,
      strokeScheduler: this.strokeScheduler,
    });
    this.narrationSync.connectToAudioBridge();

    interactionArbiter.request(OWNER.TEACHER, OWNERSHIP_PRIORITY.TEACHER_NORMAL, "runtime_init");

    this.temporalScheduler.onTick((timeMs: number, deltaMs: number) => this._onTick(timeMs, deltaMs));
  }

  /**
   * Router mapping discrete pedagogical action tokens safely.
   */
  public processEvent(evt: ConstructionEvent, absoluteTimeMs: number): any {
    const payload = evt.payload || {};
    const timeMs = (audioTimeline.state === "playing" ? audioTimeline.currentTimeMs : null) || absoluteTimeMs;

    switch (evt.type) {
      case "generation_start":
        if (payload.compiled_artifact) {
          this.setCompiledArtifact(payload.compiled_artifact);
        }
        return;
      case "speech":             return this._handleSpeech(payload, timeMs);
      case "pen_move":
      case "cursor_move":        return this._handleCursorMove(payload, timeMs);
      case "pen_state":          return this._handlePenState(payload);
      case "stroke_segment":     return this._handleStrokeSegment(payload, timeMs);
      case "cognitive_pause":    return this._handleCognitivePause(payload, timeMs);
      case "construction_step":  return this._handleConstructionStep(payload, timeMs);
      case "attention_focus":    return this._handleAttentionFocus(payload, timeMs);
      case "narration_sync":     return this._handleNarrationSync(payload);
      case "teacher_gesture":    return this._handleTeacherGesture(payload, timeMs);
      case "gesture_emphasis":   return this._handleGestureEmphasis(payload, timeMs);
      case "hover_indication":   return this._handleHoverIndication(payload, timeMs);
      case "focus_pulse":        return this._handleFocusPulse(payload, timeMs);
      case "draw_stroke":
      case "stroke":             return this._handleDrawStroke(payload, timeMs);
      case "annotation":         return this._handleTextWrite(payload, timeMs, "annotation");
      case "equation_write":     return this._handleEquationWrite(payload, timeMs);
      case "equation":           return this._handleTextWrite(payload, timeMs, "equation");
      case "stroke_reveal": {
        const objId = payload.object_id;
        const layoutAsset = this._compiledArtifact?.layout_assets?.[objId];
        if (layoutAsset) {
          payload.latex = payload.latex || layoutAsset.latex;
          payload.text = payload.text || layoutAsset.text;
          payload.position = payload.position || { x: layoutAsset.x, y: layoutAsset.y };
          payload.width = payload.width || layoutAsset.width;
          payload.height = payload.height || layoutAsset.height;
        }
        payload.equation_id = payload.equation_id || objId;
        payload.annotation_id = payload.annotation_id || objId;
        payload.id = payload.id || objId;
        if (layoutAsset?.type === "annotation") {
          return this._handleTextWrite(payload, timeMs, "annotation");
        } else {
          return this._handleEquationWrite(payload, timeMs);
        }
      }
      case "callout":
      case "code_block":
      case "algorithm_step":
      case "complexity_label":
      case "graph_function":
      case "molecular_geometry":
      case "electron_shell":
      case "bond_visualization":
      case "reaction_simulation":
      case "periodic_trend":
      case "vector_visualization":
      case "geometric_construction":
      case "procedural_sketch":
      case "physics_diagram":
      case "free_body_diagram":
      case "trajectory_diagram": return this._handleRenderableObject(evt.type, payload, timeMs);
      case "scene_mutation":     return this._handleSceneMutation(payload, timeMs);
      case "camera_move":        return this._handleCameraMove(payload, timeMs);
      case "pause_emphasis":     return this._handlePauseEmphasis(payload, timeMs);
      case "progressive_reveal": return this._handleProgressiveReveal(payload, timeMs);
      case "motor_sequence":     return this._handleMotorSequence(payload, timeMs);
      case "scene_start":        return this._handleSceneStart(payload, timeMs);
      case "node_construct":     return this._handleNodeConstruct(payload, timeMs);
      case "simulation_start":   return this._handleSimulationStart(payload, timeMs);
      case "simulation_step":    return this._handleSimulationStep(payload, timeMs);
      case "timeline_mutation":  return this._handleTimelineMutation(payload, timeMs);
    }
  }

  /**
   * Evaluates continuous physics ticks driving physical spring components.
   */
  private _onTick(absoluteTimeMs: number, deltaMs: number): void {
    const timeMs = (audioTimeline.state === "playing" ? audioTimeline.currentTimeMs : null) || absoluteTimeMs;

    this._cursorSpring.tick(deltaMs);

    this.focusEngine.tick(timeMs);
    this.gestureDynamics.tick(timeMs);
    this.motionPlanner.tick?.(timeMs);
    this._tickNodeConstruction(timeMs);
    simulationEngine.tick(this._sceneObjects, timeMs, deltaMs);
    this._processConstructionQueue(timeMs);

    this.cursor.tick(deltaMs, timeMs);

    const cursorPos = { x: this.cursor.x ?? 0, y: this.cursor.y ?? 0 };
    this.strokeScheduler.tick(timeMs, deltaMs, cursorPos);

    const activeTip = this.strokeScheduler.getActiveStrokeTip();
    if (activeTip) {
      this.cursor.setPosition(activeTip.x, activeTip.y);
      if (!this.cursor.penDown) {
        this.cursor.penDownAt(0.85);
      }
    } else {
      if (this.cursor.penDown && !this._activeTextObjId) {
        this.cursor.penUp();
      }
      this._cursorSpring.setPreset(SPRING_PRESETS.cursor_normal);
      this._calculateTextWritingCursorTrajectory(timeMs);
    }

    const firedAnchors = this.narrationSync.tick(timeMs);
    for (const a of firedAnchors) this._executeNarrationAnchor(a, timeMs);
  }

  /**
   * Procedural trajectory calculator routing writing paths safely.
   *
   * Glyph layout coordinates are already emitted in Pixi board-space pixels.
   * Keep the cursor/nib path in that same space so the pen tip traces the
   * exact vector glyph points that the renderer reveals.
   */
  private _calculateTextWritingCursorTrajectory(timeMs: number): void {
    const BOARD_WIDTH = 1200;
    const BOARD_HEIGHT = 750;

    const activeTextCandidates = Object.values(this._sceneObjects).filter((obj) =>
      isTextObjectInWriteWindow(obj, timeMs)
    );
    const activeTextObj = activeTextCandidates.length > 0
      ? activeTextCandidates.reduce((latest, obj) => (obj.startMs > latest.startMs ? obj : latest))
      : undefined;

    if (!activeTextObj) {
      this._writingTip = null;
      return;
    }

    if (activeTextObj) {
      if (!activeTextObj._charStates?.length || !activeTextObj._glyphsLayout?.length) {
        let strokes = [];
        let totalTextWidth = 0;
        let glyphs = [];
        let constructionSequence = [];
        let precomputedCharStates = undefined;
        let precomputedSafeX = undefined;
        let precomputedSafeY = undefined;

        if (this._compiledArtifact && this._compiledArtifact.stroke_assets && this._compiledArtifact.stroke_assets[activeTextObj.id]) {
          strokes = this._compiledArtifact.stroke_assets[activeTextObj.id] || [];
          const layoutAsset = this._compiledArtifact.layout_assets[activeTextObj.id];
          if (layoutAsset) {
            totalTextWidth = layoutAsset.width || 0;
            glyphs = layoutAsset.glyphs || [];
            constructionSequence = layoutAsset.constructionSequence || [];
            precomputedCharStates = layoutAsset._charStates;
            precomputedSafeX = layoutAsset._safeTextX;
            precomputedSafeY = layoutAsset._safeTextY;
          }
        }
        
        const pageIdx = activeTextObj.pageIndex ?? (activeTextObj.sceneId ? (parseInt(activeTextObj.sceneId.split("_")[1]) || 0) : 0);
        const pageOffset = pageIdx * BOARD_WIDTH;
        const fallbackX = pageOffset + BOARD_WIDTH / 2;
        const fallbackY = BOARD_HEIGHT / 2;
        const textX = activeTextObj.position?.x ?? fallbackX;
        const textY = activeTextObj.position?.y ?? fallbackY;
        
        const halfW = totalTextWidth / 2;
        const safeMinX = halfW + 15;
        const safeMaxX = BOARD_WIDTH - halfW - 15;
        
        const safeTextX = precomputedSafeX !== undefined ? precomputedSafeX : Math.max(safeMinX, Math.min(safeMaxX, textX));
        const safeTextY = precomputedSafeY !== undefined ? precomputedSafeY : Math.max(12, Math.min(BOARD_HEIGHT - 12, textY));

        let charStates: CharStateEntry[] = [];
        if (precomputedCharStates) {
          charStates = precomputedCharStates;
        }

        activeTextObj._charStates = charStates;
        activeTextObj._glyphsLayout = glyphs;
        activeTextObj._strokesLayout = strokes;
        activeTextObj._totalTextWidth = totalTextWidth;
        activeTextObj._constructionSequence = constructionSequence;
        activeTextObj._safeTextY = safeTextY;
        activeTextObj._safeTextX = safeTextX;

        // Teleport the cursor to the first stroke position and reset velocity to avoid old momentum trailing lines
        if (strokes.length > 0) {
          const firstStroke = strokes[0];
          const startPt = (firstStroke.points && firstStroke.points.length > 0) ? firstStroke.points[0] : [firstStroke.x1, firstStroke.y1];
          const targetX = safeTextX + startPt[0];
          const targetY = safeTextY + startPt[1];

          this.cursor.x = targetX;
          this.cursor.y = targetY;
          this._cursorSpring.reset(targetX, targetY);
          this.cursor.penDown = false;
          this.cursor.pressure = 0;
          this.cursor.state = CURSOR_STATE.HOVERING;
        }
      } else if (activeTextObj._safeTextX === undefined || activeTextObj._safeTextY === undefined) {
        const totalTextWidth = activeTextObj._totalTextWidth ?? 0;
        const halfW = totalTextWidth / 2;
        const safeMinX = halfW + 15;
        const safeMaxX = BOARD_WIDTH - halfW - 15;
        const textX = activeTextObj.position?.x ?? 0;
        const textY = activeTextObj.position?.y ?? 0;
        activeTextObj._safeTextX = Math.max(safeMinX, Math.min(safeMaxX, textX));
        activeTextObj._safeTextY = Math.max(12, Math.min(BOARD_HEIGHT - 12, textY));
      }
      
      const charStates = activeTextObj._charStates!;
      const strokes = activeTextObj._strokesLayout || [];
      const numStrokes = strokes.length;
      
      if (numStrokes > 0) {
        const safeTextX = activeTextObj._safeTextX!;
        const safeTextY = activeTextObj._safeTextY!;
        
        const revealOrder = getRevealOrder(strokes, activeTextObj._constructionSequence);
        const strokeTimeline = charStates
          .filter((c) => c.type === "stroke")
          .sort((a, b) => a.startMs - b.startMs);
        const currentWrite = findCurrentWriteStroke(revealOrder, strokes, charStates, timeMs);
        
        if (currentWrite && strokes.at(currentWrite.strokeIndex)) {
          const strokeIndex = currentWrite.strokeIndex;
          const activeStrokeState = charStates.find(
            (c) =>
              c.type === "stroke" &&
              (c.strokeIndex === strokeIndex || c.id === `line_${strokeIndex}`)
          ) ?? { ...currentWrite.cState, strokeIndex, type: "stroke" as const, id: `line_${strokeIndex}` };
 
          const s = strokes.at(strokeIndex)!;
          const strokeDur = activeStrokeState.endMs - activeStrokeState.startMs;
          const localElapsed = timeMs - activeStrokeState.startMs;
          const tau = strokeDur > 0 ? Math.min(1, Math.max(0, localElapsed / strokeDur)) : 1;
          const easedTau = tau * tau * (3 - 2 * tau);
          
          let tx: number, ty: number;
          if (s.points && s.points.length >= 2) {
            const pts = s.points;
            const totalPoints = pts.length;
            const idx = easedTau * (totalPoints - 1);
            const low = Math.floor(idx);
            const high = Math.min(totalPoints - 1, low + 1);
            const localTau = idx - low;
            const lx = pts[low][0] + (pts[high][0] - pts[low][0]) * localTau;
            const ly = pts[low][1] + (pts[high][1] - pts[low][1]) * localTau;
            
            tx = safeTextX + lx;
            ty = safeTextY + ly;
          } else {
            const lx = s.x1 + easedTau * (s.x2 - s.x1);
            const ly = s.y1 + easedTau * (s.y2 - s.y1);
            
            tx = safeTextX + lx;
            ty = safeTextY + ly;
          }
 
          const isDrawing = timeMs >= activeStrokeState.startMs && timeMs <= activeStrokeState.endMs;
 
          this._writingTip = { x: tx, y: ty };

          // Spring tracks the nib WITHOUT being reset — the spring's residual
          // velocity gives the cursor a subtle trailing lag (~2 px at 60 fps)
          // that reads as natural pen weight rather than a teleport.
          this._cursorSpring.setTarget(tx, ty);
          this._cursorSpring.setPreset(isDrawing ? SPRING_PRESETS.cursor_drawing : SPRING_PRESETS.cursor_normal);
          // Blend cursor toward exact nib position: 8% lag per frame during
          // active drawing, instant snap when lifting between strokes.
          const _prevCX = this.cursor.x ?? tx;
          const _prevCY = this.cursor.y ?? ty;
          this.cursor.setPosition(
            _prevCX + (tx - _prevCX) * (isDrawing ? 0.92 : 1.0),
            _prevCY + (ty - _prevCY) * (isDrawing ? 0.92 : 1.0),
          );

          this.cursor.penDown = isDrawing;
          this.cursor.pressure = isDrawing ? 0.45 + 0.45 * Math.sin(tau * Math.PI) : 0;
          this.cursor.state = isDrawing ? CURSOR_STATE.DRAWING : CURSOR_STATE.HOVERING;
          this._activeTextObjId = activeTextObj.id;
        } else {
          let transitionFound = false;
          for (let i = 0; i < strokeTimeline.length - 1; i++) {
            const curr = strokeTimeline.at(i)!;
            const next = strokeTimeline.at(i + 1)!;
            if (timeMs > curr.endMs && timeMs < next.startMs) {
              const currStrokeIndex = curr.strokeIndex ?? this._resolveStrokeIndexForCharState(curr, strokes, curr.endMs);
              const nextStrokeIndex = next.strokeIndex ?? this._resolveStrokeIndexForCharState(next, strokes, next.startMs);
              const prevS = currStrokeIndex >= 0 ? strokes.at(currStrokeIndex)! : null;
              const nextS = nextStrokeIndex >= 0 ? strokes.at(nextStrokeIndex)! : null;
              if (!prevS || !nextS) continue;
              
              const pStart = (prevS.points && prevS.points.length > 0) ? prevS.points[prevS.points.length - 1] : [prevS.x2, prevS.y2];
              const pEnd = (nextS.points && nextS.points.length > 0) ? nextS.points[0] : [nextS.x1, nextS.y1];

              const rawProgress = (timeMs - curr.endMs) / (next.startMs - curr.endMs || 1);
              // Smooth overall progress so it never snaps
              const smoothT = rawProgress * rawProgress * (3 - 2 * rawProgress);

              // ── Asymmetric pen-lift arc ─────────────────────────
              // Scale lift by distance: i-dot (short) ≈ 8px,
              // t-cross (medium) ≈ 18px, inter-word (long) ≈ 40px.
              const dx = pEnd[0] - pStart[0];
              const dy = pEnd[1] - pStart[1];
              const travelDist = Math.hypot(dx, dy);
              const maxLift = Math.min(48, Math.max(8, travelDist * 0.45));

              // Three phases:
              //   0.00 – 0.40  ascent  : quick ease-out rise
              //   0.40 – 0.58  hover   : plateau at peak (pen floats)
              //   0.58 – 1.00  descent : slow ease-in approach to paper
              let liftY: number;
              if (smoothT < 0.40) {
                const ascendNorm = smoothT / 0.40;          // 0 → 1
                const ascendEased = Math.sin(ascendNorm * Math.PI * 0.5); // ease-out
                liftY = -maxLift * ascendEased;
              } else if (smoothT < 0.58) {
                liftY = -maxLift;                            // hover at peak
              } else {
                const descendNorm = (smoothT - 0.58) / 0.42; // 0 → 1
                // Ease-in: slow at top, accelerates gently onto paper
                const descendEased = 1 - Math.cos(descendNorm * Math.PI * 0.5);
                liftY = -maxLift * (1 - descendEased);
              }

              // Lateral bow: pen arcs slightly outward perpendicular to travel.
              // This prevents perfectly straight lift paths (unrealistic).
              const lateralMaxPx = Math.min(4, travelDist * 0.06);
              const lateralT = Math.sin(smoothT * Math.PI); // 0 at ends, 1 at midpoint
              const perp = travelDist > 0.5
                ? { x: -dy / travelDist, y: dx / travelDist }
                : { x: 0, y: 0 };
              const lateralX = perp.x * lateralMaxPx * lateralT;
              const lateralY = perp.y * lateralMaxPx * lateralT;

              const lx = pStart[0] + dx * smoothT + lateralX;
              const ly = pStart[1] + dy * smoothT + lateralY;

              const tx = safeTextX + lx;
              const ty = safeTextY + ly + liftY;

              this._writingTip = { x: tx, y: ty };
              this._cursorSpring.reset(tx, ty);
              this._cursorSpring.setTarget(tx, ty);
              this._cursorSpring.setPreset(SPRING_PRESETS.cursor_normal);
              this.cursor.setPosition(tx, ty);

              this.cursor.penDown = false;
              this.cursor.pressure = 0;
              this.cursor.state = CURSOR_STATE.HOVERING;
              transitionFound = true;
              break;
            }
          }
          
          if (!transitionFound) {
            if (strokeTimeline.length > 0 && timeMs < strokeTimeline[0].startMs) {
              const firstIdx = strokeTimeline[0].strokeIndex ?? 0;
              const nextS = strokes[firstIdx] ?? strokes[0];
              const pEnd = (nextS.points && nextS.points.length > 0) ? nextS.points[0] : [nextS.x1, nextS.y1];
              // Pre-approach: cursor descends from hover height to the first stroke.
              // This gives the visual impression of the pen approaching the paper.
              const approachStart = strokeTimeline[0].startMs - 250; // 250ms approach window
              const approachRaw = approachStart < strokeTimeline[0].startMs
                ? Math.max(0, Math.min(1, (timeMs - approachStart) / 250))
                : 1;
              const approachLift = -12 * (1 - approachRaw * approachRaw); // quadratic descent
              const targetX = safeTextX + pEnd[0];
              const targetY = safeTextY + pEnd[1] + approachLift;

              this._writingTip = { x: targetX, y: targetY };
              this._cursorSpring.reset(targetX, targetY);
              this._cursorSpring.setTarget(targetX, targetY);
              this._cursorSpring.setPreset(SPRING_PRESETS.cursor_normal);
              this.cursor.setPosition(targetX, targetY);

              this.cursor.penDown = false;
              this.cursor.pressure = 0;
              this.cursor.state = CURSOR_STATE.HOVERING;
            } else {
              const lastS = strokes.at(numStrokes - 1)!;
              const pEnd = (lastS.points && lastS.points.length > 0) ? lastS.points.at(-1)! : [lastS.x2, lastS.y2];
              const tx = safeTextX + pEnd[0];
              const ty = safeTextY + pEnd[1];
 
              this._writingTip = { x: tx, y: ty };
              this._cursorSpring.reset(tx, ty);
              this._cursorSpring.setTarget(tx, ty);
              this.cursor.setPosition(tx, ty);
              
              this.cursor.penDown = false;
              this.cursor.pressure = 0;
              this.cursor.state = CURSOR_STATE.HOVERING;
            }
          }
          this._activeTextObjId = activeTextObj.id;
        }
      }
    } else if (this._activeTextObjId) {
      this._writingTip = null;
      this.cursor.penDown = false;
      this.cursor.pressure = 0;
      this.cursor.state = CURSOR_STATE.HOVERING;
      this.cursor.penUp();
      this._activeTextObjId = null;
    }
  }

  private _resolveStrokeIndexForCharState(charState: CharStateEntry, strokes: any[], timeMs: number): number {
    if (charState.strokeIndex !== undefined) return charState.strokeIndex;

    const idMatch = /^line_(\d+)$/.exec(charState.id || "");
    if (idMatch) return Number(idMatch[1]);

    const charMatch = /^char_(\d+)$/.exec(charState.id || "");
    if (charMatch) {
      const charIndex = Number(charMatch[1]);
      const matching = strokes
        .map((stroke, index) => ({ stroke, index }))
        .filter(({ stroke }) => stroke.charIndex === charIndex);

      if (matching.length > 0) {
        const progress = (timeMs - charState.startMs) / Math.max(1, charState.endMs - charState.startMs);
        const idx = Math.min(matching.length - 1, Math.max(0, Math.floor(progress * matching.length)));
        return matching[idx].index;
      }
    }

    return -1;
  }

  /**
   * Generates analytical structural scene maps consumed by downstream clients.
   */
  public getRenderState(): Record<string, any> {
    const timeMs = (audioTimeline.state === "playing" ? audioTimeline.currentTimeMs : null) || this.temporalScheduler.currentTimeMs;
    if (process.env.NODE_ENV !== "production") {
      reportWhiteboardAuditFindings(
        Object.values(this._sceneObjects).flatMap((obj) =>
          collectWhiteboardAuditFindings({ obj, currentTimeMs: timeMs, narrationStatus: this.narrationSync.getStatus() })
        ),
        "constructionRuntime.getRenderState"
      );
    }
    const cursorSnap = this.cursor.getSnapshot?.() || { visible: true, x: this.cursor.x, y: this.cursor.y, state: "idle" };
    const activeWritingEquationId = resolveActiveWritingEquationId(
      this._sceneObjects,
      { activeWritingEquationId: this._activeTextObjId },
      timeMs
    );
    const revealingEquationIds: string[] = [];
    for (const obj of Object.values(this._sceneObjects)) {
      if (
        obj.type !== "annotation" &&
        obj.type !== "equation" &&
        obj.type !== "equation_write"
      ) {
        continue;
      }
      const cs = obj._charStates;
      if (!cs?.length || timeMs < (obj.startMs || 0)) continue;
      const lastEnd = getEquationWriteEndMs(obj);
      if (timeMs >= lastEnd) continue;
      if (obj.id === activeWritingEquationId) continue;
      const hasPartialStroke = cs.some(
        (c) =>
          c.type === "stroke" &&
          timeMs >= c.startMs &&
          timeMs < c.endMs
      );
      if (hasPartialStroke) revealingEquationIds.push(obj.id);
    }
    return {
      cursor: {
        ...cursorSnap,
        x: this._writingTip?.x ?? cursorSnap.x,
        y: this._writingTip?.y ?? cursorSnap.y,
        writingTip: this._writingTip ? { ...this._writingTip } : null,
      },
      activeWritingEquationId,
      writingTipEquationId: activeWritingEquationId,
      revealingEquationIds,
      strokes: this.strokeScheduler.getAllRenderData(),
      gestures: this.gestureDynamics.tick?.(timeMs) || [],
      focusState: this.focusEngine.tick?.(timeMs) || { activeEffects: [], globalDimLevel: 0, focusedObjectIds: new Set() },
      narrationStatus: this.narrationSync.getStatus(),
      phase: this.phase,
      sceneObjects: this._sceneObjects,
      actors: this.actorRegistry.getMetrics(),
      time: timeMs,
      interactionState: interactionArbiter.getState(),
    };
  }

  public start(): void {
    this.cursor.show?.();
    this.temporalScheduler.start();
    this.phase = CONSTRUCTION_PHASE.IDLE;
    interactionArbiter.request(OWNER.TEACHER, OWNERSHIP_PRIORITY.TEACHER_NORMAL, "teaching_started");
  }

  public pause(): void {
    this.temporalScheduler.pause();
    this.phase = CONSTRUCTION_PHASE.PAUSING;
  }

  public resume(): void {
    this.temporalScheduler.start();
    if (this.phase === CONSTRUCTION_PHASE.PAUSING) this.phase = CONSTRUCTION_PHASE.EXECUTING;
  }

  public reset(): void {
    this.temporalScheduler.reset();
    this.cursor.hide?.();
    this.strokeScheduler.reset();
    this.narrationSync.reset();
    this.actorRegistry.reset();
    this.actorRegistry.register("teacher_main", ACTOR_TYPE.CURSOR, this.cursor);
    this._cursorSpring.reset(400, 300);
    this._sceneObjects = {};
    this._constructionQueue = [];
    this._nodeConstructionQueue = [];
    this._staticWriteLaneEndMs = 0;
    this._writingTip = null;
    this.phase = CONSTRUCTION_PHASE.IDLE;
    interactionArbiter.reset();
    audioEventBridge.reset();

    // Re-connect narration sync to the event bridge after resets have cleared the listeners
    this.narrationSync.connectToAudioBridge();
  }

  public takeSnapshot(): Record<string, any> {
    return {
      cursor: this.cursor.getSnapshot?.() || {},
      strokes: this.strokeScheduler.getAllRenderData(),
      phase: this.phase,
      sceneObjects: { ...this._sceneObjects },
      narration: this.narrationSync.getStatus(),
      timeMs: audioTimeline.currentTimeMs,
    };
  }

  // ── Static write lane (prevents overlapping charState timelines) ──

  private _allocateStaticWriteStartMs(requestedMs: number): number {
    if (requestedMs < this._staticWriteLaneEndMs) {
      return this._staticWriteLaneEndMs;
    }
    return requestedMs;
  }

  private _commitStaticWriteLane(startMs: number, durationMs: number): void {
    this._staticWriteLaneEndMs = Math.max(
      this._staticWriteLaneEndMs,
      startMs + Math.max(1, durationMs)
    );
  }

  // ── Private Event Handlers ────────────────────────────────────

  private _handleSpeech(payload: Record<string, any>, timeMs: number): void {
    const text = payload.text || payload.transcript_chunk || "";
    const segmentId = payload.segment_id || `seg_${timeMs}`;
    const durationMs = payload.estimated_duration_ms || payload.duration_ms || this._estimateSpeechDuration(text);

    this.narrationSync.startSpeech(text, timeMs, durationMs, segmentId);

    if (payload.word_triggers) {
      for (const { word, action, target_ids } of payload.word_triggers) {
        audioEventBridge.registerWordTrigger(word, action, target_ids);
      }
    }
  }

  private _handleCursorMove(payload: Record<string, any>, timeMs: number): void {
    const target = this._normalizePoint(payload.target ?? payload.position ?? payload.to_pos ?? payload);
    const tx = target.x;
    const ty = target.y;
    const baseDur = payload.duration_ms || 200;
    
    const loadState = useCognitiveDensityStore.getState ? (useCognitiveDensityStore.getState() as any) : null;
    const overallLoad = loadState ? loadState.overallLoad : 0.0;
    const pacingMultiplier = 1.0 + (overallLoad > 0.5 ? (overallLoad - 0.5) * 1.5 : 0.0);
    const dur = baseDur * pacingMultiplier;

    this._cursorSpring.setTarget(tx, ty);
    this.cursor.moveTo?.(tx, ty, dur, payload.easing || "humanDraw");
    interactionArbiter.request(OWNER.TEACHER, OWNERSHIP_PRIORITY.TEACHER_NORMAL, "cursor_move", dur);
  }

  private _handlePenState(payload: Record<string, any>): void {
    // FIX: Set values directly onto the state interface parameter tracks and call actor methods
    if (payload.state === "down") {
      this.cursor.penDownAt(payload.pressure || 0.8);
      this._cursorSpring.setPreset(SPRING_PRESETS.cursor_drawing);
    } else if (payload.state === "up") {
      this.cursor.penUp();
      this._cursorSpring.setPreset(SPRING_PRESETS.cursor_normal);
    } else if (payload.state === "thinking") {
      this.cursor.pause(payload.duration_ms || 400, payload.strength || 0.5);
      this._cursorSpring.setPreset(SPRING_PRESETS.cursor_thinking);
    }
  }

  private _handleStrokeSegment(payload: Record<string, any>, timeMs: number): void {
    const strokeId = payload.stroke_id || `seg_${timeMs}`;
    const points = payload.points || [];
    if (!points.length) return;

    const narrationStatus = this.narrationSync.getStatus();
    const baseDuration = payload.duration_ms || 300;
    const syncMultiplier = narrationStatus.isAudioSynced
      ? Math.max(0.9, Math.min(1.15, 1.08 - (narrationStatus.progress * 0.16)))
      : 1.0;
    const durationMs = Math.max(160, Math.floor(baseDuration * syncMultiplier));

    // Extract pressures and widths if they were included in the points from the backend
    const backendPressures = points.some((pt: any) => pt.length >= 3) ? points.map((pt: any) => pt[2] ?? 0.8) : undefined;
    const backendWidths = points.some((pt: any) => pt.length >= 4) ? points.map((pt: any) => pt[3] ?? payload.thickness ?? 2) : undefined;

    this.strokeScheduler.scheduleStroke({
      strokeId,
      waypoints: points.map((pt: any) => [pt[0], pt[1]] as [number, number]),
      targetPath: points.map((pt: any) => [pt[0], pt[1]] as [number, number]),
      durationMs,
      color: payload.color || "#FFFFFF",
      thickness: payload.thickness || 2,
      startMs: timeMs, difficulty: payload.difficulty || 0.5,
      pressures: backendPressures,
      widths: backendWidths,
    });
    const cursorPos = { x: this.cursor.x ?? 0, y: this.cursor.y ?? 0 };
    this.strokeScheduler.beginStroke(strokeId, timeMs, cursorPos);
  }

  private _handleCognitivePause(payload: Record<string, any>, timeMs: number): void {
    const baseDur = payload.duration_ms || 400;
    
    const loadState = useCognitiveDensityStore.getState ? (useCognitiveDensityStore.getState() as any) : null;
    const overallLoad = loadState ? loadState.overallLoad : 0.0;
    const pacingMultiplier = 1.0 + (overallLoad > 0.5 ? (overallLoad - 0.5) * 1.5 : 0.0);
    const dur = baseDur * pacingMultiplier;

    this.cursor.pause?.(dur, payload.hesitation_strength || 0.5);
    this._cursorSpring.setPreset(SPRING_PRESETS.cursor_thinking);
    this.phase = CONSTRUCTION_PHASE.PAUSING;
    setTimeout(() => {
      this._cursorSpring.setPreset(SPRING_PRESETS.cursor_normal);
      if (this.phase === CONSTRUCTION_PHASE.PAUSING) this.phase = CONSTRUCTION_PHASE.EXECUTING;
    }, dur);
  }

  private _handleConstructionStep(payload: Record<string, any>, timeMs: number): void {
    this._constructionQueue.push({ ...payload, startMs: timeMs });
    if (this.phase === CONSTRUCTION_PHASE.IDLE) this.phase = CONSTRUCTION_PHASE.EXECUTING;
    interactionArbiter.request(OWNER.TEACHER, OWNERSHIP_PRIORITY.TEACHER_HIGH, "construction_step", payload.duration_ms || 1000);
  }

  private _handleAttentionFocus(payload: Record<string, any>, timeMs: number): void {
    const loadState = useCognitiveDensityStore.getState ? (useCognitiveDensityStore.getState() as any) : null;
    const overallLoad = loadState ? loadState.overallLoad : 0.0;
    const pacingMultiplier = 1.0 + (overallLoad > 0.5 ? (overallLoad - 0.5) * 1.5 : 0.0);

    this.focusEngine.applyFocus?.({
      focusId: payload.focus_id || `focus_${timeMs}`,
      targetIds: payload.target_ids || [],
      strategy: payload.strategy || "pulse",
      durationMs: (payload.duration_ms || 800) * pacingMultiplier,
      intensity: Math.min(1.0, (payload.intensity || 0.7) * (1.0 + (overallLoad > 0.5 ? (overallLoad - 0.5) * 0.4 : 0.0))),
      startMs: timeMs,
    });
  }

  private _handleNarrationSync(payload: Record<string, any>): void {
    this.narrationSync.registerAnchor({
      anchorId: payload.anchor_id,
      speechText: payload.speech_text || "",
      visualAction: payload.visual_action || "draw",
      visualTargetIds: payload.visual_target_ids || [],
      offsetMs: payload.offset_ms || 0,
      durationMs: payload.duration_ms || 500,
    });
    if (payload.speech_text && payload.visual_target_ids?.length) {
      const kw = (payload.speech_text.split(/\s+/).find((w: string) => w.length > 3) || "").toLowerCase();
      if (kw) audioEventBridge.registerWordTrigger(kw, payload.visual_action || "draw", payload.visual_target_ids);
    }
  }

  private _handleTeacherGesture(payload: Record<string, any>, timeMs: number): void {
    if (!payload.target_region && !(payload.target_ids && payload.target_ids.length > 0) && !payload.target) {
      return;
    }

    let bounds = { x: 0, y: 0, width: 100, height: 50 };
    
    if (payload.target_region) {
      bounds = { x: payload.target_region[0], y: payload.target_region[1], width: payload.target_region[2], height: payload.target_region[3] };
    } else if (payload.target) {
      const target = this._normalizePoint(payload.target);
      bounds = { x: target.x - 30, y: target.y - 20, width: 60, height: 40 };
    } else if (payload.target_ids && payload.target_ids.length > 0) {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const id of payload.target_ids) {
        const obj = Reflect.get(this._sceneObjects, id);
        if (obj) {
          const ox = obj.position?.x ?? obj.x ?? 0;
          const oy = obj.position?.y ?? obj.y ?? 0;
          const ow = obj.width ?? 100;
          const oh = obj.height ?? 50;
          const left = obj.x !== undefined ? obj.x : ox - ow / 2;
          const top = obj.y !== undefined ? obj.y : oy - oh / 2;
          const right = left + ow;
          const bottom = top + oh;
          minX = Math.min(minX, left);
          minY = Math.min(minY, top);
          maxX = Math.max(maxX, right);
          maxY = Math.max(maxY, bottom);
        }
      }
      if (minX !== Infinity) {
        bounds = { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
      }
    }

    this.gestureDynamics.startGesture?.({
      gestureId: payload.gesture_id || `g_${timeMs}`,
      gestureType: payload.gesture_type || "circle",
      bounds, durationMs: payload.duration_ms || 600,
      emphasis: payload.emphasis || 0.7,
      color: typeof payload.color === "number" ? payload.color : parseInt((payload.color || "#f2cc60").replace("#", "0x"), 16),
      startMs: timeMs,
      path: payload.path,
    });
  }

  private _handleGestureEmphasis(payload: Record<string, any>, timeMs: number): void {
    this.focusEngine.applyFocus?.({
      focusId: `emp_${payload.target_id}_${timeMs}`,
      targetIds: [payload.target_id],
      strategy: payload.emphasis_type === "scale_pulse" ? "pulse" : "glow",
      durationMs: payload.duration_ms || 500,
      intensity: payload.intensity || 0.6,
      startMs: timeMs,
    });
  }

  private _handleHoverIndication(payload: Record<string, any>, timeMs: number): void {
    const t = payload.target || [0, 0];
    this._cursorSpring.setTarget(t[0], t[1]);
    this.cursor.moveTo?.(t[0], t[1], payload.duration_ms || 200, "overshoot_settle");
  }

  private _handleFocusPulse(payload: Record<string, any>, timeMs: number): void {
    this.focusEngine.applyFocus?.({
      focusId: `pulse_${timeMs}`,
      targetIds: payload.target_ids || [],
      strategy: "pulse",
      durationMs: payload.duration_ms || 600,
      intensity: payload.intensity || 0.8,
      startMs: timeMs,
    });
  }

  private _handleDrawStroke(payload: Record<string, any>, timeMs: number): void {
    const strokeId = payload.stroke_id || `stroke_${timeMs}`;
    const path = this._normalizePath(payload.path || []);
    const dur = payload.duration_ms || 400;

    if (path.length > 0) {
      const sp = path[0];

      // Teleport the cursor to the stroke origin immediately so the pen tip
      // is exactly at the ink start with no positional lag.  The old 120ms
      // setTimeout caused two bugs: (1) ink began 120ms after the cursor
      // moved, creating a visible gap, and (2) `timeMs + 120` used a stale
      // captured timestamp instead of the live audio clock.
      this.cursor.penUp();
      this.cursor.setPosition(sp[0], sp[1]);
      this.cursor.x = sp[0];
      this.cursor.y = sp[1];
      this._cursorSpring.reset(sp[0], sp[1]);

      // Extract pressures and widths if they were included in the points from the backend
      const backendPressures = path.some(pt => pt.length >= 3) ? path.map(pt => pt[2] ?? 0.8) : undefined;
      const backendWidths = path.some(pt => pt.length >= 4) ? path.map(pt => pt[3] ?? payload.thickness ?? 2) : undefined;

      this.strokeScheduler.scheduleStroke({
        strokeId,
        waypoints: path.map(pt => [pt[0], pt[1]] as [number, number]),
        targetPath: path.map(pt => [pt[0], pt[1]] as [number, number]),
        durationMs: dur, color: payload.color || "#FFFFFF",
        thickness: payload.thickness || 2, startMs: timeMs,
        difficulty: payload.difficulty || 0.5,
        pressures: backendPressures,
        widths: backendWidths,
      });
      // Begin immediately, locked to the live audio clock so ink stays in
      // sync with speech regardless of JS event-loop scheduling jitter.
      this.strokeScheduler.beginStroke(strokeId, timeMs, { x: sp[0], y: sp[1] });
    }
    // Motion ink only — no delayed strokeLayer duplicate (prevents double-stroke).
  }

  private _handleEquationWrite(payload: Record<string, any>, timeMs: number): void {
    const eqId = payload.equation_id || `eq_${timeMs}`;
    const latexStr = payload.latex || payload.data?.latex || payload.metadata?.latex || payload.latex_text || "";
    if (!String(latexStr).trim()) {
      console.warn("[diag][equation_payload_empty_skipped]", { eqId, raw: payload });
      return;
    }
    const narrationStatus = this.narrationSync.getStatus();
    const estimatedSpeechDuration = narrationStatus.progress > 0 && narrationStatus.elapsedMs > 0
      ? Math.round(narrationStatus.elapsedMs / narrationStatus.progress)
      : 0;
    const syncedDuration = narrationStatus.isAudioSynced
      ? Math.max(900, Math.floor((payload.total_duration_ms || payload.duration_ms || estimatedSpeechDuration || 1500) * 0.98))
      : (payload.total_duration_ms || payload.duration_ms || estimatedSpeechDuration || 1500);
    const effectiveStart = this._allocateStaticWriteStartMs(timeMs);
    const boardId = resolvePedagogicalBoardId(payload, eqId);
    const writeMode = getPedagogicalWriteMode(payload);
    const accumulate = shouldPatchBoard(payload, eqId);
    const latexForPlan = latexStr;

    const step = {
      action: "equation_write",
      target: payload.position || { x: 0, y: 0 },
      latex: latexForPlan,
      fontSize: payload.font_size || payload.fontSize || 32,
      durationMs: syncedDuration,
      difficulty: payload.difficulty || 0.5,
      color: payload.color || "#82AAFF",
      thickness: payload.thickness || 2,
      startMs: effectiveStart,
      strokeId: `stroke_${accumulate ? boardId : eqId}`,
    };
    const actions = this.motionPlanner.planStep(step);
    const pos = payload.position || { x: 0, y: 0 };
    const safeTextX = pos.x ?? 0;
    const safeTextY = pos.y ?? 0;

    const targetId = eqId;
    const existingBoard = this._sceneObjects[boardId] as SceneObject | undefined;
    const sceneStamp = resolveSceneStampFromPayload(payload, existingBoard);

    // Retrieve compiled asset coordinates directly from the backend Compiled Lesson Artifact
    let glyphs: any[] = [];
    let strokes: any[] = [];
    let constructionSequence: any[] = [];
    let totalTextWidth = 0;

    let plannedCharStates: CharStateEntry[] = [];
    if (this._compiledArtifact) {
      if (this._compiledArtifact.stroke_assets && this._compiledArtifact.stroke_assets[eqId]) {
        strokes = this._compiledArtifact.stroke_assets[eqId];
      }
      if (this._compiledArtifact.layout_assets && this._compiledArtifact.layout_assets[eqId]) {
        const layoutAsset = this._compiledArtifact.layout_assets[eqId];
        glyphs = layoutAsset.glyphs || [];
        totalTextWidth = layoutAsset.width || 0;
        constructionSequence = layoutAsset._constructionSequence || layoutAsset.constructionSequence || [];
        plannedCharStates = layoutAsset._charStates || [];
      }
    }

    this._sceneObjects[targetId] = {
      id: targetId,
      type: "equation_write",
      data: { ...payload, board_id: boardId, write_mode: writeMode },
      position: payload.position || { x: 0, y: 0 },
      width: payload.width,
      height: payload.height,
      visible: true,
      opacity: 1,
      scale: 1,
      startMs: effectiveStart,
      sceneId: sceneStamp.sceneId,
      pageIndex: sceneStamp.pageIndex,
      _inkAuthority: "static",
      _charStates: plannedCharStates,
      _glyphsLayout: glyphs,
      _strokesLayout: strokes,
      _totalTextWidth: totalTextWidth,
      _constructionSequence: constructionSequence,
      _boardId: boardId,
      _boardRole: payload.board_role || payload.metadata?.board_role,
      _writeMode: writeMode,
      _safeTextX: safeTextX,
      _safeTextY: safeTextY,
    };
    
    const finalCharStates = (this._sceneObjects[targetId]?._charStates ??
      plannedCharStates) as CharStateEntry[] | undefined;
    const laneDuration = Math.max(
      syncedDuration,
      getEquationWriteEndMs({ startMs: effectiveStart, _charStates: finalCharStates }) - effectiveStart
    );
    this._commitStaticWriteLane(effectiveStart, laneDuration);
    // Static ink on linesGfx only; cursor follows _calculateTextWritingCursorTrajectory.
  }

  private _handleTextWrite(payload: Record<string, any>, timeMs: number, objectType: "annotation" | "equation"): void {
    const id =
      payload.annotation_id ||
      payload.equation_id ||
      payload.id ||
      `${objectType}_${timeMs}`;
    const text = objectType === "equation"
      ? (payload.latex || payload.text || payload.data?.latex || "")
      : (payload.text || payload.body || payload.title || "");
    if (!text) {
      this._handleRenderableObject(objectType, payload, timeMs);
      return;
    }

    const position = this._normalizePoint(payload.position || payload.target || { x: 120, y: 120 });
    const durationMs = payload.total_duration_ms || payload.duration_ms || Math.max(900, text.length * 90);
    const effectiveStart = this._allocateStaticWriteStartMs(timeMs);

    let glyphs: any[] = [];
    let strokes: any[] = [];
    let constructionSequence: any[] = [];
    let totalTextWidth = 0;

    let precomputedCharStates: any[] = [];
    if (this._compiledArtifact) {
      if (this._compiledArtifact.stroke_assets && this._compiledArtifact.stroke_assets[id]) {
        strokes = this._compiledArtifact.stroke_assets[id];
      }
      if (this._compiledArtifact.layout_assets && this._compiledArtifact.layout_assets[id]) {
        const layoutAsset = this._compiledArtifact.layout_assets[id];
        glyphs = layoutAsset.glyphs || [];
        totalTextWidth = layoutAsset.width || 0;
        constructionSequence = layoutAsset._constructionSequence || layoutAsset.constructionSequence || [];
        precomputedCharStates = layoutAsset._charStates || [];
      }
    }

    const layoutWidth = totalTextWidth;
    const layoutHalfW = layoutWidth / 2;
    // Clamp within the object's OWN page — coords are absolute (page N spans
    // [N*1200, (N+1)*1200)), so a label on an overflow page keeps its offset
    // instead of being dragged back onto page 0.
    const _px = position.x ?? 0;
    const _pageOff = (_px > 0 ? Math.floor(_px / 1200) : 0) * 1200;
    const safeTextX = _pageOff + Math.max(layoutHalfW + 15, Math.min(1200 - layoutHalfW - 15, _px - _pageOff));
    const safeTextY = Math.max(12, Math.min(750 - 12, position.y ?? 0));
    const sceneStamp = resolveSceneStampFromPayload(payload, this._sceneObjects[id] as any);

    this._sceneObjects[id] = {
      id,
      type: objectType,
      data: objectType === "equation" ? { ...payload, latex: text } : { ...payload, text },
      position,
      width: payload.width,
      height: payload.height,
      visible: true,
      opacity: 1,
      scale: 1,
      startMs: effectiveStart,
      sceneId: sceneStamp.sceneId,
      pageIndex: sceneStamp.pageIndex,
      _inkAuthority: "static",
      _charStates: precomputedCharStates,
      _glyphsLayout: glyphs,
      _strokesLayout: strokes,
      _totalTextWidth: totalTextWidth,
      _constructionSequence: constructionSequence,
      _safeTextX: safeTextX,
      _safeTextY: safeTextY,
    };
    const laneDuration = durationMs;
    this._commitStaticWriteLane(effectiveStart, laneDuration);
  }

  private _handleRenderableObject(type: string, payload: Record<string, any>, timeMs: number): void {
    const id =
      payload.id ||
      payload[`${type}_id`] ||
      payload.diagram_id ||
      payload.callout_id ||
      payload.code_id ||
      `${type}_${timeMs}`;
    const position = this._normalizePoint(payload.position || payload.origin || { x: payload.x ?? 140, y: payload.y ?? 140 });
    const isNative = ["annotation", "equation", "code_block", "graph_function"].includes(type) || type.endsWith("_diagram") || type === "diagram";
    const renderType = isNative ? type : "annotation";
    const summarizedText = this._summarizeRenderablePayload(type, payload).trim();

    if (type === "code_block" && !summarizedText) {
      return;
    }

    const renderData = renderType === "annotation" && type !== "annotation"
      ? { ...payload, text: summarizedText }
      : type === "code_block"
        ? {
            ...payload,
            code: summarizedText,
            text: summarizedText,
            font_size: payload.font_size || payload.fontSize || payload.size || 18,
            size: payload.size || payload.font_size || payload.fontSize || 18,
          }
        : payload;

    this._sceneObjects[id] = {
      id,
      type: renderType,
      data: renderData,
      position,
      width: payload.width,
      height: payload.height,
      visible: true,
      opacity: 1,
      scale: 1,
      startMs: timeMs,
    };
  }

  private _summarizeRenderablePayload(type: string, payload: Record<string, any>): string {
    return payload.text || payload.label || payload.title || type.replace(/_/g, " ");
  }

  private _handleSceneMutation(payload: Record<string, any>, timeMs: number): void {
    const mutations = Array.isArray(payload.mutations)
      ? payload.mutations
      : payload.action
        ? [{
            action: payload.action,
            id: payload.id || payload.node_id,
            type: payload.type,
            data: payload.data || payload.properties || {},
            position: payload.position || { x: payload.x ?? 0, y: payload.y ?? 0 },
            width: payload.width,
            height: payload.height,
          }]
        : [];

    for (const m of mutations) {
      if (m.action === "CREATE_OBJECT") {
        if (m.type === "node" || (m.type && m.type.endsWith("_node"))) {
          this._handleNodeConstruct({ node_id: m.id, x: m.position?.x, y: m.position?.y, width: 120, height: 60, ...m.data }, timeMs);
        } else if (m.type === "annotation" || m.type === "equation") {
          this._constructionQueue.push({
            action: m.type === "equation" ? "equation_write" : "draw_label",
            target: m.position,
            latex: m.data?.latex || m.data?.text,
            text: m.data?.text,
            fontSize: m.data?.font_size || m.data?.size,
            durationMs: m.type === "equation" ? (m.data?.total_duration_ms || 1200) : (m.data?.duration_ms || 1500),
            color: m.data?.color || "#FFFFFF",
            thickness: m.data?.thickness || 2,
            equation_id: m.id,
            id: m.id,
            startMs: timeMs
          });
          
          Reflect.set(this._sceneObjects, m.id, {
            id: m.id, type: m.type, data: m.data,
            position: m.position, visible: true,
            opacity: 0, startMs: timeMs
          });
        } else {
          Reflect.set(this._sceneObjects, m.id, {
            id: m.id, type: m.type, data: m.data,
            position: m.position, visible: true,
            opacity: 0, scale: 0.9, _fadeTarget: 1, startMs: timeMs,
          });
        }
      } else if (m.action === "UPDATE_OBJECT") {
        if (Reflect.has(this._sceneObjects, m.id)) {
          Reflect.set(this._sceneObjects, m.id, { ...Reflect.get(this._sceneObjects, m.id), ...m.updates });
        }
      } else if (m.action === "DELETE_OBJECT") {
        if (Reflect.has(this._sceneObjects, m.id)) {
          Reflect.get(this._sceneObjects, m.id)._fadeTarget = 0;
        }
      }
    }
  }

  private _handleCameraMove(payload: Record<string, any>, timeMs: number): void {
    const path = payload.path;
    if (path && path.length > 0) {
      const targetPoint = path[path.length - 1];
      const cx = targetPoint.x;
      const cy = targetPoint.y;
      const targetZoom = payload.zoom_level || targetPoint.zoom || 1.0;
      cameraCognition.triggerReveal(cx, cy, targetZoom);
    } else {
      const targetId = payload.target;
      if (targetId && Reflect.has(this._sceneObjects, targetId)) {
        const obj = Reflect.get(this._sceneObjects, targetId);
        const targetZoom = payload.zoom_level || 1.0;
        const cx = obj.position?.x ?? ((obj.x ?? 0) + (obj.width ?? 100) / 2);
        const cy = obj.position?.y ?? ((obj.y ?? 0) + (obj.height ?? 50) / 2);
        cameraCognition.triggerReveal(cx, cy, targetZoom);
      }
    }
  }

  private _handlePauseEmphasis(payload: Record<string, any>, timeMs: number): void {
    const dur = payload.duration_ms || 500;
    this.cursor.pause?.(dur, 0.3);
    this._cursorSpring.setPreset(SPRING_PRESETS.cursor_thinking);
    setTimeout(() => this._cursorSpring.setPreset(SPRING_PRESETS.cursor_normal), dur);
  }

  private _handleProgressiveReveal(payload: Record<string, any>, timeMs: number): void {
    const ids = payload.target_ids || (payload.target_id ? [payload.target_id] : []);
    for (const id of ids) {
      if (Reflect.has(this._sceneObjects, id)) {
        const obj = Reflect.get(this._sceneObjects, id);
        obj._fadeTarget = 1;
        obj.startMs = timeMs;
      }
    }
  }

  private _handleMotorSequence(payload: Record<string, any>, timeMs: number): void {
    for (const a of (payload.actions || [])) this._constructionQueue.push({ ...a, startMs: timeMs });
    if (this.phase === CONSTRUCTION_PHASE.IDLE) this.phase = CONSTRUCTION_PHASE.EXECUTING;
  }

  private _handleSceneStart(payload: Record<string, any>, timeMs: number): void {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("scene_start", { detail: { ...payload, timeMs } }));
    }
  }

  private _handleSimulationStart(payload: Record<string, any>, timeMs: number): void {
    simulationEngine.startSimulation(payload, timeMs);
  }

  private _handleSimulationStep(payload: Record<string, any>, timeMs: number): void {
    simulationEngine.stepSimulation(payload, timeMs);
  }

  private _handleTimelineMutation(payload: Record<string, any>, timeMs: number): void {
    console.info(`[ConstructionRuntime] Pedagogical Timeline Mutation: ${payload.action || "UNKNOWN"}`, payload);
    
    if (payload.action === "REPLAN" && this.cursor.state === CURSOR_STATE.DRAWING) {
      if (typeof (this.cursor as any).triggerStartleInterruption === "function") {
        (this.cursor as any).triggerStartleInterruption();
        this.phase = CONSTRUCTION_PHASE.PAUSING;
      }
    }
  }

  // ── Procedural Node Construction ───────────────────────────

  private _handleNodeConstruct(payload: Record<string, any>, timeMs: number): void {
    const { node_id, x = 0, y = 0, width = 120, height = 60, label = "", color = "#FFFFFF" } = payload;
    if (!node_id) return;

    const loadState = useCognitiveDensityStore.getState ? (useCognitiveDensityStore.getState() as any) : null;
    const overallLoad = loadState ? loadState.overallLoad : 0.0;
    const pacingMultiplier = 1.0 + (overallLoad > 0.5 ? (overallLoad - 0.5) * 1.5 : 0.0);
    const msPerSide = 65 * pacingMultiplier;

    const r = Math.min(width, height) * 0.12; 

    const sides: [number, number][][] = [
      [[x + r, y], [x + width - r, y]],
      [[x + width, y + r], [x + width, y + height - r]],
      [[x + width - r, y + height], [x + r, y + height]],
      [[x, y + height - r], [x, y + r]],
    ];

    sides.forEach((pts, i) => {
      this._nodeConstructionQueue.push({
        type: "stroke", strokeId: `${node_id}_side_${i}`,
        waypoints: pts, color,
        durationMs: msPerSide, startMs: timeMs + i * msPerSide,
        difficulty: 0.2,
      });
    });

    const afterPerim = timeMs + sides.length * msPerSide;
    this._nodeConstructionQueue.push({ type: "fill", node_id, startMs: afterPerim });
    this._nodeConstructionQueue.push({ type: "text", node_id, label, startMs: afterPerim + 150, duration_ms: Math.max(200, (label?.length || 0) * 40 * pacingMultiplier) });

    Reflect.set(this._sceneObjects, node_id, {
      id: node_id, type: "node", data: payload,
      position: { x: x + width / 2, y: y + height / 2 },
      visible: true, opacity: 0, scale: 1, _fadeTarget: 0,
      _textProgress: 0, _label: label, startMs: timeMs,
    });

    if (this.phase === CONSTRUCTION_PHASE.IDLE) this.phase = CONSTRUCTION_PHASE.EXECUTING;
  }

  private _tickNodeConstruction(timeMs: number): void {
    const due = this._nodeConstructionQueue.filter(i => i.startMs <= timeMs);
    this._nodeConstructionQueue = this._nodeConstructionQueue.filter(i => i.startMs > timeMs);

    for (const item of due) {
      if (item.type === "stroke" && item.strokeId && item.waypoints && item.durationMs) {
        this.strokeScheduler.scheduleStroke({
          strokeId: item.strokeId, waypoints: item.waypoints,
          targetPath: item.waypoints, durationMs: item.durationMs,
          color: item.color || "#FFFFFF", thickness: 2, startMs: timeMs,
          difficulty: item.difficulty || 0.2,
        });
        const sp = item.waypoints[0];
        this._cursorSpring.setTarget(sp[0], sp[1]);
        if (this.cursor) {
          this.cursor.setPosition(sp[0], sp[1]);
          this.cursor.x = sp[0];
          this.cursor.y = sp[1];
        }
        this.strokeScheduler.beginStroke(item.strokeId, timeMs, { x: sp[0], y: sp[1] });
      } else if (item.type === "fill" && item.node_id) {
        const obj = Reflect.get(this._sceneObjects, item.node_id);
        if (obj) obj._fadeTarget = 0.08;
      } else if (item.type === "text" && item.node_id) {
        const obj = Reflect.get(this._sceneObjects, item.node_id);
        if (obj) { obj._textRevealMs = item.duration_ms; obj._textStartMs = timeMs; }
      }
    }

    for (const obj of Object.values(this._sceneObjects)) {
      if (obj._textRevealMs && obj._textStartMs) {
        const elapsed = timeMs - obj._textStartMs;
        obj._textProgress = Math.min(1, elapsed / obj._textRevealMs);
        if (obj._textProgress >= 1) { obj._textRevealMs = null; obj._textProgress = 1; }
      }

      if (obj._fadeTarget !== undefined) {
        const diff = obj._fadeTarget - (obj.opacity ?? 0);
        if (Math.abs(diff) > 0.001) {
          obj.opacity = (obj.opacity ?? 0) + diff * 0.15;
        } else {
          obj.opacity = obj._fadeTarget;
        }
      }
    }
  }

  private _processConstructionQueue(timeMs: number): void {
    if (this._constructionQueue.length === 0) {
      if (this.phase === CONSTRUCTION_PHASE.EXECUTING &&
          this.motionPlanner.isIdle?.() && !this.strokeScheduler.hasActiveStrokes()) {
        this.phase = CONSTRUCTION_PHASE.IDLE;
        interactionArbiter.request(OWNER.TEACHER, OWNERSHIP_PRIORITY.TEACHER_IDLE, "construction_done");
      }
      return;
    }
    if (this.motionPlanner.isIdle?.()) {
      const step = this._constructionQueue.shift();
      const actions = this.motionPlanner.planStep?.(step) || [];
      this.motionPlanner.enqueueActions?.(actions);
      this.phase = CONSTRUCTION_PHASE.EXECUTING;
    }
  }

  // FIX: Fixed location mapping context placement inside the proper class closure context boundary

  private _executeNarrationAnchor(anchor: NarrationAnchor, timeMs: number): void {
    switch (anchor.visualAction) {
      case "draw": 
      case "sync":
        for (const id of anchor.visualTargetIds) {
          if (Reflect.has(this._sceneObjects, id)) Reflect.get(this._sceneObjects, id)._fadeTarget = 1;
        }
        break;
      case "highlight":
        this.focusEngine.applyFocus?.({ focusId: `narr_${anchor.anchorId}`, targetIds: anchor.visualTargetIds, strategy: "pulse", durationMs: anchor.durationMs, intensity: 0.7, startMs: timeMs });
        break;
      case "focus":
        this.focusEngine.applyFocus?.({ focusId: `focus_${anchor.anchorId}`, targetIds: anchor.visualTargetIds, strategy: "dim_others", durationMs: anchor.durationMs, intensity: 0.6, startMs: timeMs });
        break;
      case "pause":
        this.cursor.pause?.(anchor.durationMs, 0.4);
        break;
    }
  }

  private _normalizePoint(value: any): { x: number; y: number } {
    if (Array.isArray(value)) {
      return { x: Number(value[0] ?? 0), y: Number(value[1] ?? 0) };
    }
    if (value && typeof value === "object") {
      return {
        x: Number(value.x ?? value[0] ?? 0),
        y: Number(value.y ?? value[1] ?? 0),
      };
    }
    return { x: 0, y: 0 };
  }

  private _normalizePath(path: any[]): any[] {
    if (!Array.isArray(path)) return [];
    return path
      .map((point) => {
        if (Array.isArray(point)) {
          return [
            Number(point[0] ?? 0),
            Number(point[1] ?? 0),
            point[2] !== undefined ? Number(point[2]) : undefined,
            point[3] !== undefined ? Number(point[3]) : undefined,
          ].filter((v) => v !== undefined);
        }
        if (point && typeof point === "object") {
          return [
            Number(point.x ?? 0),
            Number(point.y ?? 0),
            point.pressure !== undefined ? Number(point.pressure) : undefined,
            point.thickness !== undefined ? Number(point.thickness) : undefined,
          ].filter((v) => v !== undefined);
        }
        return [0, 0];
      })
      .filter((point) => Number.isFinite(point[0]) && Number.isFinite(point[1]));
  }

  private _estimateSpeechDuration(text: string): number {
    if (!text) return 0;
    // 12 chars/sec matches real TTS output rate better than the old 15 chars/sec
    // (which ran ~20% short, making visual actions fire before the teacher finished speaking).
    const baseMs = Math.floor((text.length / 12.0) * 1000);
    const punctuationPauseMs = (text.split(".").length - 1) * 300 + (text.split(",").length - 1) * 150;
    return baseMs + punctuationPauseMs;
  }
}
