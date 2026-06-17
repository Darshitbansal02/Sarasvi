/**
 * StudentDrawingController.ts — Student input capture for the teaching canvas.
 *
 * Owns pointer capture, eraser/highlighter stroke creation, and simple gesture
 * analysis so PixiCanvas can stay focused on rendering.
 */

import * as PIXI from "pixi.js";
import { useRuntimeStore } from "@/runtime/runtimeStore";
import { gestureEngine, GestureType } from "@/runtime/gestureEngine";
import { pointerOwnership } from "@/runtime/interaction/pointerOwnership";
import { interactionArbiter, OWNER, OWNERSHIP_PRIORITY } from "@/runtime/interaction/interactionArbiter";
import { drawInkPhysicsRibbon } from "../renderers/inkPhysics";

interface StudentDrawingControllerOptions {
  app: PIXI.Application;
  boardWidth: number;
  boardHeight: number;
}

interface StrokeDraft {
  id: string;
  path: [number, number][];
  color: number;
  thickness: number;
  alpha: number;
  sceneId: string;
}

export class StudentDrawingController {
  private _app: PIXI.Application;
  private _boardWidth: number;
  private _boardHeight: number;
  private _activeStroke: StrokeDraft | null;
  private _isErasing: boolean;
  private _tempGraphics: PIXI.Graphics | null = null;
  private _boundPointerDown: (e: PointerEvent) => void;
  private _boundPointerMove: (e: PointerEvent) => void;
  private _boundPointerUp: (e: PointerEvent) => void;
  private _boundPointerCancel: (e: PointerEvent) => void;

  constructor({ app, boardWidth, boardHeight }: StudentDrawingControllerOptions) {
    this._app = app;
    this._boardWidth = boardWidth;
    this._boardHeight = boardHeight;
    this._activeStroke = null;
    this._isErasing = false;

    this._boundPointerDown = this._onPointerDown.bind(this);
    this._boundPointerMove = this._onPointerMove.bind(this);
    this._boundPointerUp = this._onPointerUp.bind(this);
    this._boundPointerCancel = this._onPointerCancel.bind(this);
  }

  public attach(): void {
    this._app.canvas.addEventListener("contextmenu", (e) => e.preventDefault());
    this._app.canvas.addEventListener("wheel", (e) => e.preventDefault(), { passive: false });
    this._app.canvas.addEventListener("pointerdown", this._boundPointerDown);
    this._app.canvas.addEventListener("pointermove", this._boundPointerMove);
    this._app.canvas.addEventListener("pointerup", this._boundPointerUp);
    this._app.canvas.addEventListener("pointercancel", this._boundPointerCancel);
  }

  public detach(): void {
    this._app.canvas.removeEventListener("pointerdown", this._boundPointerDown);
    this._app.canvas.removeEventListener("pointermove", this._boundPointerMove);
    this._app.canvas.removeEventListener("pointerup", this._boundPointerUp);
    this._app.canvas.removeEventListener("pointercancel", this._boundPointerCancel);
    this._activeStroke = null;
    this._isErasing = false;
    pointerOwnership.clearStudentPointer();
    if (this._tempGraphics) {
      try {
        this._tempGraphics.destroy();
      } catch {
        // Ignore destruction errors
      }
      this._tempGraphics = null;
    }
  }

  private _toWorldPoint(event: PointerEvent): { wx: number; wy: number } {
    const rect = this._app.canvas.getBoundingClientRect();
    const canvasX = event.clientX - rect.left;
    const canvasY = event.clientY - rect.top;
    const wx = (canvasX - this._app.stage.position.x) / this._app.stage.scale.x;
    const wy = (canvasY - this._app.stage.position.y) / this._app.stage.scale.y;
    return { wx, wy };
  }

  private _filterEraserStrokes(wx: number, wy: number): void {
    const state = useRuntimeStore.getState();
    const targetSceneId = state.viewedSceneId || state.activeSceneId || "scene_0";
    const threshold = 20;

    const remainingStrokes = state.studentStrokes.filter(stroke => {
      if ((stroke.sceneId || "scene_0") !== targetSceneId) return true;
      for (const pt of stroke.path || []) {
        const dx = pt[0] - wx;
        const dy = pt[1] - wy;
        if ((dx * dx + dy * dy) <= (threshold * threshold)) return false;
      }
      return true;
    });

    if (remainingStrokes.length !== state.studentStrokes.length) {
      useRuntimeStore.setState({ studentStrokes: remainingStrokes });
    }
  }

  private _onPointerDown(event: PointerEvent): void {
    const state = useRuntimeStore.getState();
    if (state.runtimeState === "REPLAYING") return;

    const { wx, wy } = this._toWorldPoint(event);

    if (wx < 0 || wx > this._boardWidth || wy < 0 || wy > this._boardHeight) return;
    if (state.interactionTool === "hand" || event.button !== 0) return;

    const canDraw = pointerOwnership.setStudentPointer(wx, wy, true);
    if (!canDraw) return;

    const { granted } = interactionArbiter.request(
      OWNER.STUDENT,
      OWNERSHIP_PRIORITY.STUDENT_ACTIVE,
      "Student drawing",
      5000
    );
    if (!granted && !interactionArbiter.canStudentDraw()) return;

    if (state.interactionTool === "eraser") {
      this._isErasing = true;
      this._filterEraserStrokes(wx, wy);
      return;
    }

    const isHighlighter = state.interactionTool === "highlighter";
    this._activeStroke = {
      id: `student_${Date.now()}`,
      path: [[wx, wy]],
      color: isHighlighter ? 0xfffac2 : state.boardTheme === "light" ? 0x1b365d : 0x7dd3fc,
      thickness: isHighlighter ? 12 : 3,
      alpha: isHighlighter ? 0.45 : 1.0,
      sceneId: state.viewedSceneId || state.activeSceneId || "scene_0",
    };

    if (!this._tempGraphics) {
      this._tempGraphics = new PIXI.Graphics();
      const studentLayer = this._app.stage.children.find(c => c.label === "studentLayer") || this._app.stage;
      studentLayer.addChild(this._tempGraphics);
    }
    this._tempGraphics.clear();

    try {
      (event.target as any).setPointerCapture?.(event.pointerId);
    } catch {
      // Ignore pointer-capture failures.
    }
  }

  private _onPointerMove(event: PointerEvent): void {
    const state = useRuntimeStore.getState();
    const { wx, wy } = this._toWorldPoint(event);

    pointerOwnership.setStudentPointer(wx, wy, !!this._activeStroke);

    if (this._isErasing && state.interactionTool === "eraser") {
      this._filterEraserStrokes(wx, wy);
      return;
    }

    if (this._activeStroke) {
      const cx = Math.max(0, Math.min(this._boardWidth, wx));
      const cy = Math.max(0, Math.min(this._boardHeight, wy));
      const newPath = (this._activeStroke.path || []).concat([[cx, cy]]);
      this._activeStroke = { ...this._activeStroke, path: newPath };

      if (this._tempGraphics) {
        this._tempGraphics.clear();
        if (newPath.length >= 2) {
          drawInkPhysicsRibbon(this._tempGraphics, newPath, {
            baseWidth: Math.max(3, (this._activeStroke.thickness || 2) * 1.8),
            color: (this._activeStroke.color as number) || 0xffffff,
            alpha: 0.9,
            taperStart: 0.02,
            taperEnd: 0.04,
            wobbleAmount: 0.006,
          });
        }
      }
    }
  }

  private _onPointerUp(event: PointerEvent): void {
    this._finishPointerInteraction(event);
  }

  private _onPointerCancel(event: PointerEvent): void {
    this._finishPointerInteraction(event);
  }

  private _finishPointerInteraction(event: PointerEvent): void {
    this._isErasing = false;
    try {
      (event.target as any).releasePointerCapture?.(event.pointerId);
    } catch {
      // Ignore pointer-capture failures.
    }

    pointerOwnership.clearStudentPointer();

    if (this._activeStroke) {
      // Commit the completed stroke to the Zustand store
      const state = useRuntimeStore.getState();
      state.addStudentStroke({ ...this._activeStroke, path: this._activeStroke.path.slice() });

      if (this._tempGraphics) {
        this._tempGraphics.clear();
      }

      if (this._activeStroke.path && this._activeStroke.path.length >= 3) {
        const points = this._activeStroke.path.map(([x, y]) => ({ x, y }));
        const gesture = gestureEngine.analyzeStroke(points);
        if (gesture.type === GestureType.CIRCLE) {
          const storeState = useRuntimeStore.getState();
          const targetId = gestureEngine.findTarget(gesture, storeState.sceneObjects as any);
          const targetObj = targetId ? storeState.sceneObjects[targetId] : null;

          // Always set lastStudentGesture when a circle is detected — even when
          // no specific object was hit.  Without this, the student gets zero
          // feedback and the interrupt modal never opens.
          useRuntimeStore.setState({
            lastStudentGesture: {
              type: "circle",
              target_id: targetId || null,
              target_type: targetObj?.type || "area",
              // Pass gesture bounds so the modal can say "about this region"
              bounds: gesture.bounds || null,
              center: gesture.center || null,
            }
          });

          // Circle gesture = strong confusion signal regardless of whether a
          // specific object was identified as the target.
          const sessionId = storeState.sessionId;
          if (sessionId) {
            import("@/lib/api_sessions").then(({ sendInteractionSignal }) => {
              sendInteractionSignal(
                sessionId,
                "hesitation_indicator",
                { intensity: targetId ? 0.65 : 0.45 },
                targetObj?.type || "general"
              );
            }).catch(() => { /* fire-and-forget */ });
          }
        }
      }

      interactionArbiter.release(OWNER.STUDENT);
      this._activeStroke = null;
    }
  }
}
