/**
 * motionPhysics.ts — Physically-Based Motion Simulation
 *
 * Provides spring dynamics, inertia, overshoot, and damping
 * for cursor and object motion. This is what makes the AI teacher
 * feel like a BODY moving, not a robot plotting coordinates.
 *
 * Based on critically-damped and underdamped spring models.
 * All math is in world units (canvas pixels per ms).
 */

// ── Type Interfaces & Domain Contracts ─────────────────────────

export interface SpringPreset {
  stiffness: number;
  damping: number;
  mass: number;
}

export type SpringPresetKey =
  | "cursor_normal"
  | "cursor_drawing"
  | "cursor_thinking"
  | "object_appear"
  | "camera_pan"
  | "emphasis_pulse";

export interface Vector2D {
  x: number;
  y: number;
}

export interface InertiaSnapshot {
  x: number;
  y: number;
  active: boolean;
}

export interface VelocitySnapshot {
  vx: number;
  vy: number;
  speed: number;
}

interface PositionSample {
  x: number;
  y: number;
  t: number;
}

interface InertiaOptions {
  friction?: number;
  minSpeed?: number;
}

// ── Spring Constants ───────────────────────────────────────────

const SPRING_PRESETS: Record<SpringPresetKey, SpringPreset> = Object.freeze({
  // cursor_normal: Snappy but overshoots slightly (human hand feel)
  cursor_normal: { stiffness: 320, damping: 40, mass: 0.55 },
  // cursor_drawing: Tighter when pen is down (pressure increases stiffness)
  cursor_drawing: { stiffness: 448, damping: 46, mass: 0.495 },
  // cursor_thinking: Loose wandering motion during hesitation
  cursor_thinking: { stiffness: 60, damping: 12, mass: 1.5 },
  // object_appear: Elastic entry (overshot then settle)
  object_appear: { stiffness: 240, damping: 18, mass: 1.0 },
  // camera_pan: Smooth, overdamped
  camera_pan: { stiffness: 100, damping: 30, mass: 2.0 },
  // emphasis_pulse: Quick pulse and return
  emphasis_pulse: { stiffness: 400, damping: 35, mass: 0.5 },
});

// ── SpringSimulator Class ──────────────────────────────────────

export class SpringSimulator {
  public stiffness: number;
  public damping: number;
  public mass: number;

  private _position: number;
  private _velocity: number;
  private _target: number;
  private _settled: boolean;
  private _accumulator: number;

  constructor(preset: SpringPreset = SPRING_PRESETS.cursor_normal) {
    this.stiffness = preset.stiffness;
    this.damping = preset.damping;
    this.mass = preset.mass;

    // Linear tracking allocations
    this._position = 0;
    this._velocity = 0;
    this._target = 0;
    this._settled = true;
    this._accumulator = 0; // Fixed time-step accumulator
  }

  /**
   * Set the target position.
   */
  public setTarget(target: number): void {
    this._target = target;
    if (Math.abs(target - this._position) > 0.01) {
      this._settled = false;
    }
  }

  /**
   * Get current position.
   */
  public get position(): number {
    return this._position;
  }

  /**
   * Get current velocity.
   */
  public get velocity(): number {
    return this._velocity;
  }

  /**
   * Set current velocity.
   */
  public setVelocity(velocity: number): void {
    this._velocity = velocity;
    if (Math.abs(velocity) > 0.01) {
      this._settled = false;
    }
  }

  /**
   * Whether the spring has settled.
   */
  public get isSettled(): boolean {
    return this._settled;
  }

  /**
   * Apply an impulse (sudden velocity change).
   */
  public applyImpulse(impulse: number): void {
    let currentMass = this.mass;
    if (currentMass <= 0) currentMass = 1; // Safeguard configuration limits
    
    this._velocity += impulse / currentMass;
    this._settled = false;
  }

  /**
   * Advance simulation by deltaMs using a fixed time-step accumulator.
   * Uses semi-implicit Euler integration for absolute stability.
   */
  public tick(deltaMs: number): number {
    if (this._settled) return this._position;

    const fixedStep = 8; // ms slices (~125Hz) reduce visible numeric jitter on high-DPI displays
    const dt = fixedStep / 1000; // seconds representation

    this._accumulator += Math.min(deltaMs, 100);

    let stiffness = this.stiffness;
    let damping = this.damping;
    let mass = this.mass;

    // Handle global multi-pass emotional layout adaptations type-safely
    if (typeof window !== "undefined" && (window as any).__emotionEngine) {
      const mod = (window as any).__emotionEngine.getModulators();
      stiffness *= mod.springStiffnessMultiplier ?? 1;
      damping *= mod.springDampingMultiplier ?? 1;
      mass *= mod.springMassMultiplier ?? 1;
    }

    // Defensive safeguard tracking preventing zero-division crash scenarios
    if (mass <= 0) mass = 1;

    while (this._accumulator >= fixedStep) {
      this._accumulator -= fixedStep;

      const displacement = this._position - this._target;
      const springForce = -stiffness * displacement;
      const dampingForce = -damping * this._velocity;
      const totalForce = springForce + dampingForce;

      const acceleration = totalForce / mass;
      this._velocity += acceleration * dt;
      this._position += this._velocity * dt;

      // Close structural settling thresholds down tightly to avoid micro-vibration
      const positionThreshold = 0.25; // px
      const velocityThreshold = 0.25; // px/ms
      if (Math.abs(displacement) < positionThreshold && Math.abs(this._velocity) < velocityThreshold) {
        this._position = this._target;
        this._velocity = 0;
        this._settled = true;
        this._accumulator = 0;
        break;
      }
    }

    return this._position;
  }

  /**
   * Snap to target coordinates immediately.
   */
  public snap(): void {
    this._position = this._target;
    this._velocity = 0;
    this._settled = true;
    this._accumulator = 0;
  }

  /**
   * Reset tracking registers.
   */
  public reset(initialPosition: number = 0): void {
    this._position = initialPosition;
    this._target = initialPosition;
    this._velocity = 0;
    this._settled = true;
    this._accumulator = 0;
  }

  /**
   * Switch the tracking matrix tuning configurations.
   */
  public setPreset(preset: SpringPreset | SpringPresetKey): void {
    let p: SpringPreset | undefined;
    
    if (typeof preset === "string") {
      p = SPRING_PRESETS[preset as SpringPresetKey];
    } else if (preset && typeof preset === "object") {
      p = preset as SpringPreset;
    }

    if (p) {
      this.stiffness = p.stiffness;
      this.damping = p.damping;
      this.mass = p.mass;
    }
  }
}

// ── Spring2D Class ─────────────────────────────────────────────

export class Spring2D {
  public x: SpringSimulator;
  public y: SpringSimulator;

  constructor(preset: SpringPreset = SPRING_PRESETS.cursor_normal) {
    this.x = new SpringSimulator(preset);
    this.y = new SpringSimulator(preset);
  }

  public setTarget(x: number, y: number): void {
    this.x.setTarget(x);
    this.y.setTarget(y);
  }

  public tick(deltaMs: number): Vector2D {
    return {
      x: this.x.tick(deltaMs),
      y: this.y.tick(deltaMs),
    };
  }

  public setVelocity(vx: number, vy: number): void {
    this.x.setVelocity(vx);
    this.y.setVelocity(vy);
  }

  public applyImpulse(vx: number, vy: number): void {
    this.x.applyImpulse(vx);
    this.y.applyImpulse(vy);
  }

  public get position(): Vector2D {
    return { x: this.x.position, y: this.y.position };
  }

  public get velocity(): Vector2D {
    return { x: this.x.velocity, y: this.y.velocity };
  }

  public get isSettled(): boolean {
    return this.x.isSettled && this.y.isSettled;
  }

  public setPreset(preset: SpringPreset | SpringPresetKey): void {
    this.x.setPreset(preset);
    this.y.setPreset(preset);
  }

  public reset(x: number = 0, y: number = 0): void {
    this.x.reset(x);
    this.y.reset(y);
  }
}

// ── InertiaSimulator Class ─────────────────────────────────────

export class InertiaSimulator {
  private _friction: number;
  private _minSpeed: number;
  private _vx: number;
  private _vy: number;
  private _x: number;
  private _y: number;
  private _active: boolean;

  constructor({ friction = 0.88, minSpeed = 0.5 }: InertiaOptions = {}) {
    this._friction = friction;
    this._minSpeed = minSpeed;
    this._vx = 0;
    this._vy = 0;
    this._x = 0;
    this._y = 0;
    this._active = false;
  }

  /**
   * Propel an object down a trajectory vector with initial force parameters.
   */
  public throw(x: number, y: number, vx: number, vy: number): void {
    this._x = x;
    this._y = y;
    this._vx = vx;
    this._vy = vy;
    this._active = true;
  }

  /**
   * Evaluates continuous exponential dampening tracking frames.
   */
  public tick(deltaMs: number): InertiaSnapshot {
    if (!this._active) return { x: this._x, y: this._y, active: false };

    this._x += this._vx * deltaMs;
    this._y += this._vy * deltaMs;
    this._vx *= Math.pow(this._friction, deltaMs / 16);
    this._vy *= Math.pow(this._friction, deltaMs / 16);

    const speed = Math.sqrt(this._vx * this._vx + this._vy * this._vy);
    if (speed < this._minSpeed) {
      this._active = false;
      this._vx = 0;
      this._vy = 0;
    }

    return { x: this._x, y: this._y, active: this._active };
  }

  public stop(): void { 
    this._active = false; 
    this._vx = 0; 
    this._vy = 0; 
  }
  
  public get active(): boolean { return this._active; }
  public get position(): Vector2D { return { x: this._x, y: this._y }; }
}

// ── Motion Easing Library ──────────────────────────────────────

export const Easing = {
  /**
   * Core numerical evaluation compiling precise analytical Cubic Bézier layouts.
   */
  cubicBezier(t: number, p1x: number, p1y: number, p2x: number, p2y: number): number {
    const cx = 3 * p1x;
    const bx = 3 * (p2x - p1x) - cx;
    const ax = 1 - cx - bx;
    const cy = 3 * p1y;
    const by = 3 * (p2y - p1y) - cy;
    const ay = 1 - cy - by;

    const sampleX = (tVal: number) => ((ax * tVal + bx) * tVal + cx) * tVal;
    const sampleY = (tVal: number) => ((ay * tVal + by) * tVal + cy) * tVal;

    let tGuess = t;
    for (let i = 0; i < 8; i++) {
      const x = sampleX(tGuess) - t;
      if (Math.abs(x) < 1e-6) break;
      const d = (3 * ax * tGuess * tGuess + 2 * bx * tGuess + cx);
      if (d === 0) break; // Infinite slope derivative fallback protection
      tGuess -= x / d;
    }
    return sampleY(tGuess);
  },

  // Anthropomorphic physical travel curve profiles
  humanDraw: (t: number): number => Easing.cubicBezier(t, 0.25, 0.1, 0.25, 1.0),
  humanReturn: (t: number): number => Easing.cubicBezier(t, 0.4, 0.0, 0.2, 1.0),
  penDown: (t: number): number => Easing.cubicBezier(t, 0.0, 0.0, 0.58, 1.0),
  penUp: (t: number): number => Easing.cubicBezier(t, 0.42, 0.0, 1.0, 1.0),
  hesitate: (t: number): number => Easing.cubicBezier(t, 0.6, 0.04, 0.98, 0.335),
  springy: (t: number): number => {
    const decay = Math.exp(-6 * t);
    const osc = Math.cos(20 * t);
    return 1 - decay * osc;
  },

  // Standard Mathematical Baselines
  linear: (t: number): number => t,
  easeOut: (t: number): number => 1 - Math.pow(1 - t, 3),
  easeIn: (t: number): number => t * t * t,
  easeInOut: (t: number): number => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2,
};

// ── Velocity Tracker Class ─────────────────────────────────────

export class VelocityTracker {
  private _window: number;
  private _samples: PositionSample[];

  constructor(windowMs: number = 100) {
    this._window = windowMs;
    this._samples = [];
  }

  public addSample(x: number, y: number, t: number = performance.now()): void {
    this._samples.push({ x, y, t });
    
    // Clear chronological entries trailing past the active sample window boundary
    const cutoff = t - this._window;
    while (this._samples.length > 1 && this._samples[0].t < cutoff) {
      this._samples.shift();
    }
  }

  /**
   * Derive instant directional velocity snapshots from sliding histories.
   */
  public getVelocity(): VelocitySnapshot {
    if (this._samples.length < 2) return { vx: 0, vy: 0, speed: 0 };
    
    const first = this._samples[0];
    const last = this._samples[this._samples.length - 1];
    const dt = Math.max(1, last.t - first.t);
    
    const vx = (last.x - first.x) / dt;
    const vy = (last.y - first.y) / dt;
    
    return { vx, vy, speed: Math.sqrt(vx * vx + vy * vy) };
  }

  public reset(): void { 
    this._samples = []; 
  }
}

export { SPRING_PRESETS };