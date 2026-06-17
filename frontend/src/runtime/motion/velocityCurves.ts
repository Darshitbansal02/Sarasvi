/**
 * velocityCurves.ts — Humanized easing & velocity profiles for embodied motion.
 *
 * Provides type-safe, biologically-plausible curves: acceleration/deceleration,
 * anticipation, overshoot-settle, and difficulty-adaptive pacing profiles.
 */

import { Vector2D } from "./proceduralNoise";

export type EasingType =
  | "human_accel_decel"
  | "anticipation"
  | "overshoot_settle"
  | "pen_down"
  | "pen_up"
  | "linear"
  | "ease_in"
  | "ease_out"
  | "ease_in_out";

export interface DifficultyProfile {
  speed: (t: number) => number;
  pauseMs: number;
  hesitationChance: number;
}

// ── Core Easing Functions ──────────────────────────────────────

/** Human-like accel/decel — Hermite smoothstep S-curve */
export function humanAccelDecel(t: number): number {
  return t * t * (3 - 2 * t);
}

/** Anticipation: slight pullback before movement execution */
export function anticipation(t: number, strength: number = 0.15): number {
  if (t < 0.15) {
    return -strength * Math.sin((t / 0.15) * Math.PI);
  }
  const nt = (t - 0.15) / 0.85;
  return nt * nt * (3 - 2 * nt);
}

/** Overshoot then settle — cursor arrives at targets with inertia */
export function overshootSettle(t: number, overshootAmount: number = 0.08): number {
  if (t < 0.7) {
    const nt = t / 0.7;
    return (1 + overshootAmount) * (nt * nt * (3 - 2 * nt));
  }
  const nt = (t - 0.7) / 0.3;
  const overshootVal = 1 + overshootAmount;
  return overshootVal - overshootAmount * (nt * nt * (3 - 2 * nt));
}

/** Breathing idle — gentle sine oscillation for resting pointer states */
export function breathingIdle(t: number, amplitude: number = 0.003): number {
  return amplitude * Math.sin(t * Math.PI * 2);
}

/** Pen-down pressure ramp — simulates pressing pen tool to writing surface */
export function penDownRamp(t: number): number {
  if (t < 0.1) return t * 5; // fast initial contact 0 → 0.5
  return 0.5 + 0.5 * humanAccelDecel((t - 0.1) / 0.9);
}

/** Pen-up lift curve — simulates lifting pen away from surface boundaries */
export function penUpLift(t: number): number {
  return 1 - Math.pow(t, 0.5);
}

// ── Composite Velocity Profiles ────────────────────────────────

/**
 * Create a velocity profile for a stroke segment based on conceptual load parameters.
 */
export function difficultyProfile(difficulty: number): DifficultyProfile {
  const baseSpeed = 1.0 - difficulty * 0.5; // Bounds velocity from 0.5x to 1.0x
  const pauseMs = Math.floor(difficulty * 400);

  return {
    speed: (t: number) => baseSpeed * humanAccelDecel(t),
    pauseMs,
    hesitationChance: difficulty * 0.4,
  };
}

/**
 * Compute cursor velocity coordinates given source, target, and progress.
 */
export function interpolatePosition(
  sx: number,
  sy: number,
  tx: number,
  ty: number,
  t: number,
  easingName: EasingType | string = "human_accel_decel"
): { x: number; y: number } {
  const easedT = applyEasing(t, easingName);
  return {
    x: sx + (tx - sx) * easedT,
    y: sy + (ty - sy) * easedT,
  };
}

/**
 * Apply named easing function transformation parameters safely.
 */
export function applyEasing(t: number, name: EasingType | string = "human_accel_decel"): number {
  const clamped = Math.max(0, Math.min(1, t));
  switch (name) {
    case "human_accel_decel": return humanAccelDecel(clamped);
    case "anticipation":      return anticipation(clamped);
    case "overshoot_settle":  return overshootSettle(clamped);
    case "pen_down":          return penDownRamp(clamped);
    case "pen_up":            return penUpLift(clamped);
    case "linear":            return clamped;
    case "ease_in":           return clamped * clamped;
    case "ease_out":          return 1 - (1 - clamped) * (1 - clamped);
    case "ease_in_out":
      return clamped < 0.5
        ? 2 * clamped * clamped
        : 1 - Math.pow(-2 * clamped + 2, 2) / 2;
    default:                  return humanAccelDecel(clamped);
  }
}

/**
 * Generate a natural wobble offset vector for a given position timestamp index.
 */
export function naturalWobble(seed: number, t: number, amplitude: number = 0.8): Vector2D {
  const s1 = Math.sin(t * 0.4 + seed * 0.1) * amplitude;
  const s2 = Math.cos(t * 0.25 + seed * 0.2) * amplitude * 0.6;
  const c1 = Math.cos(t * 0.3 + seed * 0.15) * amplitude * 0.8;
  const c2 = Math.sin(t * 0.35 + seed * 0.05) * amplitude * 0.4;
  return {
    dx: s1 + s2,
    dy: c1 + c2,
  };
}

/**
 * Compute velocity-dependent stroke thickness profiles.
 */
export function velocityWidth(baseWidth: number, velocity: number, minRatio: number = 0.6, maxRatio: number = 1.4): number {
  // Normalize velocity scaling models: assume 0.5 px/ms represents human velocity norms
  const normalizedVelocity = Math.min(1, velocity / 0.5);
  const ratio = maxRatio - (maxRatio - minRatio) * normalizedVelocity;
  return baseWidth * ratio;
}