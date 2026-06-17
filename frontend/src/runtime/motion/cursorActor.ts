/**
 * cursorActor.ts — Embodied teacher cursor simulation.
 *
 * The teacher cursor handles physical velocity travel, noise-modulated tremors,
 * and organic overshoot behavior using second-order spring dynamics.
 * Enhanced to support preemptive saccadic look-ahead gaze anchors and raw
 * mid-stroke startle interruption trace skids.
 */

import { interpolatePosition, applyEasing, EasingType } from "./velocityCurves";
import { cursorBreathing, hesitationTremor, penLandingWobble, Vector2D, WobbleSnapshot } from "./proceduralNoise";
import { emotionEngine } from "./emotionEngine";
import { Spring2D, SPRING_PRESETS } from "./motionPhysics";

// ── Cursor States & Enums ──────────────────────────────────────

export enum CURSOR_STATE {
  IDLE = "idle",           // Resting, gentle breathing
  MOVING = "moving",       // Traveling to target
  HOVERING = "hovering",   // Over target, not drawing
  DRAWING = "drawing",     // Actively drawing (pen down)
  PAUSING = "pausing",     // Cognitive pause with tremor
  STARTLED = "startled",   // NEW: Involuntary physical task switch jerk
  HIDDEN = "hidden",       // Not visible
}

// ── Struct Data & Domain Interfaces ───────────────────────────

export interface CursorActorOptions {
  initialX?: number;
  initialY?: number;
  radius?: number;
  color?: number;
}

export interface CursorSnapshot {
  id: string;
  x: number;
  y: number;
  gazeX: number;
  gazeY: number;
  state: CURSOR_STATE;
  penDown: boolean;
  pressure: number;
  visible: boolean;
  alpha: number;
  scale: number;
  radius: number;
  color: number;
  velocityX: number;
  velocityY: number;
  isEyeAhead: boolean;
}

// ── CursorActor Class ──────────────────────────────────────────

export class CursorActor {
  public id: string;
  public x: number;
  public y: number;
  public state: CURSOR_STATE;
  public penDown: boolean;
  public pressure: number;
  public radius: number;
  public color: number;
  public alpha: number;
  public scale: number;
  public visible: boolean;

  // HUMAN ENHANCEMENT: Saccadic Pre-Vision look-ahead gaze tracking indicators
  public gazeX: number;
  public gazeY: number;

  private _targetX: number;
  private _targetY: number;
  private _sourceX: number;
  private _sourceY: number;

  private _moveStartMs: number;
  private _moveDurationMs: number;
  private _moveEasing: EasingType | string;
  private _moveProgress: number;

  private _pauseStartMs: number;
  private _pauseDurationMs: number;
  private _pauseStrength: number;

  private _velocityX: number;
  private _velocityY: number;
  private _lastX: number;
  private _lastY: number;

  private _penDownTimeMs: number;
  private _absoluteTimeMs: number;
  private _rhythmMultiplier: number;
  private _motorSpring: Spring2D;

  // HUMAN ENHANCEMENT: Interruption startle reaction kinematic registers
  private _startleDx: number;
  private _startleDy: number;
  private _startleDurationMs: number;
  private _startleStartMs: number;

  /**
   * @param cursorId - Unique identifier
   * @param options - Configuration overrides
   */
  constructor(cursorId: string = "teacher_main", options: CursorActorOptions = {}) {
    this.id = cursorId;

    // Current position (world space)
    this.x = options.initialX ?? 400;
    this.y = options.initialY ?? 300;

    // Initialize look-ahead gaze targets directly over starting position coordinates
    this.gazeX = this.x;
    this.gazeY = this.y;

    // Motion target mapping
    this._targetX = this.x;
    this._targetY = this.y;
    this._sourceX = this.x;
    this._sourceY = this.y;

    // Initial state allocations
    this.state = CURSOR_STATE.HIDDEN;
    this.penDown = false;
    this.pressure = 0;

    // Temporal travel trackers
    this._moveStartMs = 0;
    this._moveDurationMs = 0;
    this._moveEasing = "human_accel_decel";
    this._moveProgress = 1;

    // Hesitation trackers
    this._pauseStartMs = 0;
    this._pauseDurationMs = 0;
    this._pauseStrength = 0.5;

    // Velocity state tracking
    this._velocityX = 0;
    this._velocityY = 0;
    this._lastX = this.x;
    this._lastY = this.y;

    // Whiteboard landing kinematics
    this._penDownTimeMs = 0;
    this._absoluteTimeMs = 0;

    // Visual attributes
    this.radius = options.radius ?? 6;
    this.color = options.color ?? 0x2f81f7;
    this.alpha = 0;
    this.scale = 1;
    this.visible = false;

    // Speech-synchronized rhythm multipliers
    this._rhythmMultiplier = 1.0;
    this._motorSpring = new Spring2D(SPRING_PRESETS.cursor_normal);

    // Kinematic startle variables
    this._startleDx = 0;
    this._startleDy = 0;
    this._startleDurationMs = 0;
    this._startleStartMs = 0;
  }

  // ── Public API ─────────────────────────────────────────────

  /**
   * Move cursor to a target position using unconstrained spring physics.
   * Immediately snaps gaze vectors to simulate saccadic target look-ahead mechanisms.
   */
  public moveTo(tx: number, ty: number, durationMs: number = 300, easing: EasingType | string = "human_accel_decel"): void {
    const vx = this._velocityX;
    const vy = this._velocityY;

    this._sourceX = this.x;
    this._sourceY = this.y;
    this._targetX = tx;
    this._targetY = ty;
    this._moveDurationMs = Math.max(8, durationMs);
    this._moveStartMs = this._absoluteTimeMs;
    this._moveEasing = easing;
    this._moveProgress = 0;

    // HUMAN ENHANCEMENT: Saccadic Pre-Vision gaze jump. Teacher's eyes snap instantly to target coordinates
    this.gazeX = tx;
    this.gazeY = ty;
    
    // Warm up and sync spring parameters to inherit structural momentum paths cleanly
    this._motorSpring.setPreset(SPRING_PRESETS.cursor_normal);
    this._motorSpring.reset(this.x, this.y);
    this._motorSpring.setVelocity(vx, vy); 
    this._motorSpring.setTarget(tx, ty);
    
    this.state = CURSOR_STATE.MOVING;
    this.visible = true;
    this.alpha = 1;
  }

  /**
   * Set pen down and lock spring parameters into drawing configurations.
   */
  public penDownAt(pressure: number = 0.8): void {
    const vx = this._velocityX;
    const vy = this._velocityY;

    this.penDown = true;
    this.pressure = pressure;
    this._penDownTimeMs = this._absoluteTimeMs;
    this.state = CURSOR_STATE.DRAWING;

    this._motorSpring.setPreset(SPRING_PRESETS.cursor_drawing);
    this._motorSpring.setVelocity(vx, vy);
  }

  /**
   * Lift pen up and return internal parameters back to hovering physics.
   */
  public penUp(): void {
    const vx = this._velocityX;
    const vy = this._velocityY;

    this.penDown = false;
    this.pressure = 0;
    this.state = CURSOR_STATE.HOVERING;

    this._motorSpring.setPreset(SPRING_PRESETS.cursor_normal);
    this._motorSpring.setVelocity(vx, vy);
  }

  /**
   * Enter cognitive pause and trigger localized hesitation tremor elements.
   */
  public pause(durationMs: number = 400, strength: number = 0.5): void {
    this._pauseStartMs = this._absoluteTimeMs;
    this._pauseDurationMs = durationMs;
    this._pauseStrength = strength;
    this.state = CURSOR_STATE.PAUSING;
  }

  /**
   * HUMAN ENHANCEMENT: Kinematic Interruption Startle
   * Triggers a fast kinetic startle skid or ink slash across the board space,
   * simulating an arm jerk response when suddenly interrupted mid-task.
   */
  public triggerStartleInterruption(durationMs: number = 160): void {
    this._startleStartMs = this._absoluteTimeMs;
    this._startleDurationMs = durationMs;
    
    // Extrapolate involuntary push direction based directly on incoming trajectory momentum vectors
    const mod = emotionEngine.getModulators() as any;
    const forceFactor = 8.5 * (1.0 + mod.wobbleIntensity);
    
    // If cursor was at relative rest, jerk randomly, otherwise multiply existing momentum vectors
    const speed = Math.hypot(this._velocityX, this._velocityY);
    if (speed < 0.05) {
      const angle = Math.random() * Math.PI * 2;
      this._startleDx = Math.cos(angle) * forceFactor;
      this._startleDy = Math.sin(angle) * forceFactor;
    } else {
      this._startleDx = (this._velocityX / speed) * forceFactor * 1.5;
      this._startleDy = (this._velocityY / speed) * forceFactor * 1.5;
    }

    this.state = CURSOR_STATE.STARTLED;
    this._motorSpring.setPreset(SPRING_PRESETS.cursor_thinking);
  }

  /** Hide entity layer components. */
  public hide(): void {
    this.state = CURSOR_STATE.HIDDEN;
    this.visible = false;
    this.alpha = 0;
  }

  /** Reveal component elements. */
  public show(): void {
    this.visible = true;
    this.state = CURSOR_STATE.IDLE;
    this.alpha = 1;
  }

  /** Set phoneme-synchronized speech frequency modifiers. */
  public setRhythmMultiplier(val: number): void {
    this._rhythmMultiplier = val || 1.0;
  }

  // ── Core Lifecycle Tick ────────────────────────────────────

  public tick(deltaMs: number, absoluteTimeMs: number): CursorSnapshot {
    this._absoluteTimeMs = absoluteTimeMs;

    // Extrapolate internal derivative directional momentum bounds (px/ms)
    const baseDelta = Math.max(1, deltaMs);
    this._velocityX = (this.x - this._lastX) / baseDelta;
    this._velocityY = (this.y - this._lastY) / baseDelta;
    this._lastX = this.x;
    this._lastY = this.y;

    // Gradually pull gaze tracking inputs back down near coordinate centers if resting
    if (this.state !== CURSOR_STATE.MOVING && this.state !== CURSOR_STATE.HIDDEN) {
      this.gazeX = this.gazeX * 0.82 + this.x * 0.18;
      this.gazeY = this.gazeY * 0.82 + this.y * 0.18;
    }

    switch (this.state) {
      case CURSOR_STATE.MOVING:
        this._tickMoving(deltaMs);
        break;
      case CURSOR_STATE.PAUSING:
        this._tickPausing(deltaMs);
        break;
      case CURSOR_STATE.STARTLED:
        this._tickStartled(deltaMs);
        break;
      case CURSOR_STATE.IDLE:
        this._tickIdle(deltaMs);
        break;
      case CURSOR_STATE.HOVERING:
        this._tickHovering(deltaMs);
        break;
      case CURSOR_STATE.DRAWING:
        this._tickDrawing(deltaMs);
        break;
      case CURSOR_STATE.HIDDEN:
        break;
    }

    return this.getSnapshot();
  }

  public getSnapshot(): CursorSnapshot {
    return {
      id: this.id,
      x: this.x,
      y: this.y,
      gazeX: this.gazeX,
      gazeY: this.gazeY,
      state: this.state,
      penDown: this.penDown,
      pressure: this.pressure,
      visible: this.visible,
      alpha: this.alpha,
      scale: this.scale,
      radius: this.radius,
      color: this.color,
      velocityX: this._velocityX,
      velocityY: this._velocityY,
      isEyeAhead: Math.hypot(this.gazeX - this.x, this.gazeY - this.y) > 35,
    };
  }

  // ── Internal Tick Handlers ─────────────────────────────────

  private _tickMoving(deltaMs: number): void {
    const elapsed = this._absoluteTimeMs - this._moveStartMs;
    this._moveProgress = Math.min(1, elapsed / this._moveDurationMs);

    // FIX: Typed tracking targets to absolute point vectors to clear Vector2D shape mismatch errors
    const physicsPos: { x: number; y: number } = this._motorSpring.tick(deltaMs);
    this.x = physicsPos.x;
    this.y = physicsPos.y;

    this.scale = 1 + Math.sin(this._moveProgress * Math.PI) * 0.08;

    if (this._motorSpring.isSettled) {
      this.x = this._targetX;
      this.y = this._targetY;
      this.scale = 1;
      this.state = this.penDown ? CURSOR_STATE.DRAWING : CURSOR_STATE.HOVERING;
    }
  }

  private _tickPausing(deltaMs: number): void {
    const elapsed = this._absoluteTimeMs - this._pauseStartMs;
    if (elapsed >= this._pauseDurationMs) {
      this.state = this.penDown ? CURSOR_STATE.DRAWING : CURSOR_STATE.HOVERING;
      return;
    }

    const mod = emotionEngine.getModulators() as any;
    const tremor: Vector2D = hesitationTremor(
      this.id.length * 7,
      elapsed,
      this._pauseStrength * mod.wobbleIntensity
    );
    this.x = this._targetX + tremor.dx;
    this.y = this._targetY + tremor.dy;

    this.scale = 1 + Math.sin(elapsed * 0.01) * 0.04 * this._pauseStrength * mod.wobbleIntensity;
  }

  private _tickStartled(deltaMs: number): void {
    const elapsed = this._absoluteTimeMs - this._startleStartMs;
    if (elapsed >= this._startleDurationMs) {
      this._startleDx = 0;
      this._startleDy = 0;
      this.penUp();
      return;
    }

    // Kinematically decay involuntary startle velocities exponentially
    const decay = 1.0 - elapsed / this._startleDurationMs;
    this.x += this._startleDx * decay * (deltaMs / 16.66);
    this.y += this._startleDy * decay * (deltaMs / 16.66);

    // Apply erratic trailing slash pressure
    this.pressure = 0.55 * decay;
    this.scale = 0.85 + this.pressure * 0.3;
    this.alpha = 1.0;
  }

  private _tickIdle(deltaMs: number): void {
    const mod = emotionEngine.getModulators() as any;
    const breath: Vector2D = cursorBreathing(this._absoluteTimeMs, 1.5, 2.0 * mod.wobbleIntensity);
    this.x = this._targetX + breath.dx;
    this.y = this._targetY + breath.dy;
    this.scale = 1;

    this.alpha = 0.7 + Math.sin(this._absoluteTimeMs * 0.002) * 0.15;
  }

  private _tickHovering(deltaMs: number): void {
    const mod = emotionEngine.getModulators() as any;
    const breath: Vector2D = cursorBreathing(this._absoluteTimeMs, 1.0, 1.2 * mod.wobbleIntensity);
    this.x = this._targetX + breath.dx;
    this.y = this._targetY + breath.dy;
    this.alpha = 0.85;
    this.scale = 1;
  }

  private _tickDrawing(deltaMs: number): void {
    const timeSinceLanding = this._absoluteTimeMs - this._penDownTimeMs;
    const wobble: WobbleSnapshot = penLandingWobble(this.id.length * 3, timeSinceLanding);

    if (!wobble.settled) {
      const mod = emotionEngine.getModulators() as any;
      this.x += wobble.dx * mod.wobbleIntensity;
      this.y += wobble.dy * mod.wobbleIntensity;
    }

    this.alpha = 1;
    this.scale = 0.9 + this.pressure * 0.2; 
  }

  public setPosition(x: number, y: number): void {
    this.x = x;
    this.y = y;
    this._targetX = x;
    this._targetY = y;
  }
}