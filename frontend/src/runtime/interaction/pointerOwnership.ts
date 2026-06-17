/**
 * pointerOwnership.ts — Fine-Grained Pointer State Tracker
 *
 * Tracks which system owns each input modality at any given moment:
 *   - Primary pointer (mouse/touch/stylus)
 *   - Cursor position authority
 *   - Gesture recognition rights
 *   - Canvas write permission
 *
 * Works in conjunction with InteractionArbiter (which handles
 * high-level ownership) to provide per-pointer state.
 */

import { interactionArbiter } from "./interactionArbiter";

// ── Pointer State ──────────────────────────────────────────────

export enum POINTER_MODE {
  TEACHER_DRAWING = "teacher_drawing",   // Teacher cursor active, pen down
  TEACHER_HOVERING = "teacher_hovering", // Teacher cursor visible, pen up
  STUDENT_DRAWING = "student_drawing",   // Student drawing
  STUDENT_HOVERING = "student_hovering", // Student hovering (preview)
  PANNING = "panning",                   // Canvas pan (no ownership conflict)
  IDLE = "idle",                         // No active pointer
}

export interface ConflictDetails {
  studentX: number;
  studentY: number;
  teacherX: number;
  teacherY: number;
  mode: POINTER_MODE;
  type?: string;
  distance?: number;
}

export interface CursorHintResult {
  style: string;
  blocked: boolean;
}

export interface PointerMetrics {
  mode: POINTER_MODE;
  teacherVisible: boolean;
  teacherPos: { x: number; y: number };
  studentDown: boolean;
  studentPos: { x: number; y: number };
  pointerDistance: number;
  conflictCount: number;
  isStudentBlocked: boolean;
}

type ModeChangePayload = { from: POINTER_MODE; to: POINTER_MODE };
type ModeCallback = (payload: ModeChangePayload) => void;
type ConflictCallback = (conflict: ConflictDetails) => void;

// ── PointerOwnership ───────────────────────────────────────────

export class PointerOwnership {
  private _mode: POINTER_MODE;
  private _teacherCursorVisible: boolean;
  private _teacherCursorX: number;
  private _teacherCursorY: number;
  private _studentPointerX: number;
  private _studentPointerY: number;
  private _studentPointerDown: boolean;
  private _isPanning: boolean;

  // Callbacks
  private _modeCallbacks: ModeCallback[];
  private _conflictCallbacks: ConflictCallback[];

  // Conflict tracking
  private _lastConflictMs: number;
  private _conflictCount: number;

  constructor() {
    this._mode = POINTER_MODE.IDLE;
    this._teacherCursorVisible = false;
    this._teacherCursorX = 0;
    this._teacherCursorY = 0;
    this._studentPointerX = 0;
    this._studentPointerY = 0;
    this._studentPointerDown = false;
    this._isPanning = false;

    // Callbacks
    this._modeCallbacks = [];
    this._conflictCallbacks = [];

    // Conflict tracking
    this._lastConflictMs = 0;
    this._conflictCount = 0;
  }

  /**
   * Notify that teacher cursor is now at position.
   */
  public setTeacherCursor(x: number, y: number, penDown: boolean): void {
    this._teacherCursorX = x;
    this._teacherCursorY = y;
    this._teacherCursorVisible = true;

    const newMode = penDown ? POINTER_MODE.TEACHER_DRAWING : POINTER_MODE.TEACHER_HOVERING;
    this._setMode(newMode);
  }

  /**
   * Notify that teacher cursor is hidden.
   */
  public hideTeacherCursor(): void {
    this._teacherCursorVisible = false;
    if (this._mode === POINTER_MODE.TEACHER_DRAWING || this._mode === POINTER_MODE.TEACHER_HOVERING) {
      this._setMode(POINTER_MODE.IDLE);
    }
  }

  /**
   * Notify of student pointer event.
   * @returns Whether the student is allowed to draw
   */
  public setStudentPointer(x: number, y: number, pointerDown: boolean): boolean {
    this._studentPointerX = x;
    this._studentPointerY = y;
    this._studentPointerDown = pointerDown;

    if (!pointerDown) {
      this._setMode(POINTER_MODE.STUDENT_HOVERING);
      return true;
    }

    // Check with arbiter if student can draw
    const canDraw = interactionArbiter.canStudentDraw();
    if (!canDraw) {
      // Conflict!
      const nowMs = Date.now();
      if (nowMs - this._lastConflictMs > 500) { // Throttle conflict events
        this._lastConflictMs = nowMs;
        this._conflictCount++;
        this._conflictCallbacks.forEach(cb => cb({
          studentX: x,
          studentY: y,
          teacherX: this._teacherCursorX,
          teacherY: this._teacherCursorY,
          mode: this._mode,
        }));
      }
      return false;
    }

    this._setMode(POINTER_MODE.STUDENT_DRAWING);
    return true;
  }

  /**
   * Clear student pointer.
   */
  public clearStudentPointer(): void {
    this._studentPointerDown = false;
    if (this._mode === POINTER_MODE.STUDENT_DRAWING) {
      this._setMode(this._teacherCursorVisible ? POINTER_MODE.TEACHER_HOVERING : POINTER_MODE.IDLE);
    }
  }

  /**
   * Set panning mode (no ownership conflict).
   */
  public setPanning(active: boolean): void {
    this._isPanning = active;
    if (active) {
      this._setMode(POINTER_MODE.PANNING);
    } else {
      this._setMode(this._teacherCursorVisible ? POINTER_MODE.TEACHER_HOVERING : POINTER_MODE.IDLE);
    }
  }

  /**
   * Get current pointer mode.
   */
  public get mode(): POINTER_MODE { 
    return this._mode; 
  }

  /**
   * Whether student is currently blocked from drawing.
   */
  public get isStudentBlocked(): boolean {
    return this._mode === POINTER_MODE.TEACHER_DRAWING &&
      !interactionArbiter.canStudentDraw();
  }

  /**
   * Get visual hint for cursor display.
   */
  public getCursorHint(): CursorHintResult {
    switch (this._mode) {
      case POINTER_MODE.TEACHER_DRAWING:
        return { style: "none", blocked: false }; // Hide default cursor
      case POINTER_MODE.STUDENT_DRAWING:
        return { style: "crosshair", blocked: false };
      case POINTER_MODE.PANNING:
        return { style: "grabbing", blocked: false };
      case POINTER_MODE.IDLE:
      case POINTER_MODE.STUDENT_HOVERING:
        return { 
          style: interactionArbiter.canStudentDraw() ? "crosshair" : "default", 
          blocked: this.isStudentBlocked 
        };
      default:
        return { style: "default", blocked: false };
    }
  }

  /**
   * Distance between teacher and student pointers.
   * Used to detect near-collision.
   */
  public getPointerDistance(): number {
    if (!this._teacherCursorVisible) return Infinity;
    const dx = this._studentPointerX - this._teacherCursorX;
    const dy = this._studentPointerY - this._teacherCursorY;
    return Math.sqrt(dx * dx + dy * dy);
  }

  /**
   * Tick — check for proximity conflicts.
   */
  public tick(absoluteTimeMs: number): void {
    const dist = this.getPointerDistance();
    if (dist < 30 && this._studentPointerDown && this._teacherCursorVisible) {
      // Pointers are very close — signal conflict
      if (Date.now() - this._lastConflictMs > 1000) {
        this._lastConflictMs = Date.now();
        this._conflictCallbacks.forEach(cb => cb({
          type: "proximity",
          distance: dist,
          studentX: this._studentPointerX,
          studentY: this._studentPointerY,
          teacherX: this._teacherCursorX,
          teacherY: this._teacherCursorY,
          mode: this._mode,
        }));
      }
    }
  }

  /**
   * Get metrics.
   */
  public getMetrics(): PointerMetrics {
    return {
      mode: this._mode,
      teacherVisible: this._teacherCursorVisible,
      teacherPos: { x: this._teacherCursorX, y: this._teacherCursorY },
      studentDown: this._studentPointerDown,
      studentPos: { x: this._studentPointerX, y: this._studentPointerY },
      pointerDistance: this.getPointerDistance(),
      conflictCount: this._conflictCount,
      isStudentBlocked: this.isStudentBlocked,
    };
  }

  public onModeChange(cb: ModeCallback): void { 
    this._modeCallbacks.push(cb); 
  }

  public onConflict(cb: ConflictCallback): void { 
    this._conflictCallbacks.push(cb); 
  }

  public reset(): void {
    this._mode = POINTER_MODE.IDLE;
    this._teacherCursorVisible = false;
    this._studentPointerDown = false;
    this._isPanning = false;
    this._conflictCount = 0;
  }

  // ── Private ────────────────────────────────────────────────

  private _setMode(newMode: POINTER_MODE): void {
    if (newMode === this._mode) return;
    const prev = this._mode;
    this._mode = newMode;
    this._modeCallbacks.forEach(cb => cb({ from: prev, to: newMode }));
  }
}

// ── Singleton ──────────────────────────────────────────────────
export const pointerOwnership = new PointerOwnership();
