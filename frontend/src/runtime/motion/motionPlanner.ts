/**
 * motionPlanner.ts — Interpolation and State transitions interface.
 *
 * Trajectory calculations, path planning, and cursor motion solving
 * have migrated to teacher_motion_planner.py on the backend.
 */

import { CURSOR_STATE } from "./cursorActor";

export interface MotorAction {
  type: "cursor_move" | "pen_down" | "pen_up" | "draw_stroke" | "hesitation" | string;
  targetX?: number;
  targetY?: number;
  durationMs?: number;
  easing?: string;
  startMs?: number;
  pressure?: number;
  strokeId?: string;
  path?: [number, number][];
  color?: string;
  thickness?: number;
  difficulty?: number;
  strength?: number;
  [key: string]: any;
}

export interface MotionPlannerStep {
  action?: string;
  target?: {
    x?: number;
    y?: number;
    width?: number;
    height?: number;
    [key: string]: any;
  };
  strokeId?: string;
  path?: [number, number][];
  durationMs?: number;
  total_duration_ms?: number;
  per_char_ms?: number;
  difficulty?: number;
  color?: string;
  thickness?: number;
  startMs?: number;
  emphasisTargets?: string[];
  latex?: string;
  text?: string;
  fontSize?: number;
  speechStress?: number;
  side?: "left" | "right" | string;
  metadata?: Record<string, any>;
  [key: string]: any;
}

export interface PlannerCharState {
  id: string;
  type: "glyph" | "stroke" | string;
  char?: string;
  startMs: number;
  endMs: number;
  strokeIndex?: number;
}

export interface MotionPlannerDependencies {
  cursor: any;
  strokeScheduler: any;
  hesitationEngine: any;
  narrationSync: any;
}

export interface ExtendedMotorActionArray extends Array<MotorAction> {
  charStates?: PlannerCharState[];
  layout?: any;
}

export class MotionPlanner {
  private _cursor: any;
  private _strokes: any;
  private _hesitation: any;
  private _narration: any;

  private _actionQueue: MotorAction[];
  private _currentAction: MotorAction | null;
  private _actionStartMs: number;

  constructor({ cursor, strokeScheduler, hesitationEngine, narrationSync }: MotionPlannerDependencies) {
    this._cursor = cursor;
    this._strokes = strokeScheduler;
    this._hesitation = hesitationEngine;
    this._narration = narrationSync;
    this._actionQueue = [];
    this._currentAction = null;
    this._actionStartMs = 0;
  }

  public planStep(step: MotionPlannerStep): ExtendedMotorActionArray {
    const actions: ExtendedMotorActionArray = [];
    const {
      action = "draw",
      strokeId,
      path = [],
      durationMs = 500,
      color = "#FFFFFF",
      thickness = 2,
    } = step;

    if (action === "cursor_move") {
      actions.push({
        type: "cursor_move",
        targetX: step.target?.x ?? 0,
        targetY: step.target?.y ?? 0,
        durationMs,
      });
    } else if (action === "draw" || action === "draw_stroke") {
      if (path && path.length > 0) {
        actions.push({
          type: "draw_stroke",
          strokeId,
          path,
          durationMs,
          color,
          thickness,
        });
      }
    }
    return actions;
  }

  public tick(absoluteTimeMs: number): void {
    if (!this._currentAction && this._actionQueue.length > 0) {
      this._currentAction = this._actionQueue.shift()!;
      this._actionStartMs = absoluteTimeMs;
      this._beginAction(this._currentAction);
    }

    if (this._currentAction) {
      const elapsed = absoluteTimeMs - this._actionStartMs;
      const duration = this._currentAction.durationMs || 100;

      if (elapsed >= duration) {
        this._completeAction(this._currentAction);
        this._currentAction = null;
      }
    }
  }

  public enqueueActions(actions: MotorAction[]): void {
    this._actionQueue.push(...actions);
  }

  public clearQueue(): void {
    this._actionQueue = [];
    this._currentAction = null;
  }

  public isIdle(): boolean {
    return this._actionQueue.length === 0 && !this._currentAction;
  }

  public reset(): void {
    this._actionQueue = [];
    this._currentAction = null;
    this._actionStartMs = 0;
  }

  private _beginAction(action: MotorAction): void {
    switch (action.type) {
      case "cursor_move":
        this._cursor.moveTo(
          action.targetX!, action.targetY!, action.durationMs!, action.easing || "human_accel_decel"
        );
        break;

      case "pen_down":
        this._cursor.penDownAt(action.pressure || 0.8);
        break;

      case "pen_up":
        this._strokes.forceCompleteAllGrowing();
        this._cursor.penUp();
        break;

      case "draw_stroke": {
        const startPt = action.path?.[0];
        if (startPt) {
          this._cursor.setPosition(startPt[0], startPt[1]);
          this._cursor.x = startPt[0];
          this._cursor.y = startPt[1];
        }
        this._strokes.scheduleStroke({
          strokeId: action.strokeId!,
          targetPath: action.path!,
          durationMs: action.durationMs!,
          color: action.color,
          thickness: action.thickness,
          difficulty: action.difficulty,
          startMs: this._actionStartMs,
        });
        this._strokes.beginStroke(
          action.strokeId!,
          this._actionStartMs,
          startPt ? { x: startPt[0], y: startPt[1] } : { x: this._cursor.x, y: this._cursor.y }
        );
        break;
      }

      case "hesitation":
        this._cursor.pause(action.durationMs!, action.strength!);
        break;
    }
  }

  private _completeAction(action: MotorAction): void {
    switch (action.type) {
      case "draw_stroke": {
        this._strokes.forceComplete(action.strokeId!);
        const tip = this._strokes.getStrokeTip(action.strokeId!);
        if (tip) {
          this._cursor.setPosition(tip.x, tip.y);
        }
        break;
      }
    }
  }
}
