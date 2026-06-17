/**
 * proceduralNoise.ts — Deterministic noise generators for embodied motion.
 *
 * Produces replay-safe, seed-deterministic noise for hand instability,
 * cursor breathing, tremor, pressure variation, and chalk/biomechanical drift.
 *
 * All functions are pure: same seed + same t = same output.
 */

export interface Vector2D {
  dx: number;
  dy: number;
}

export interface WobbleSnapshot extends Vector2D {
  settled: boolean;
}

export interface DriftSnapshot {
  dy: number;
  compressionScale: number;
}

// ── Deterministic Hash ─────────────────────────────────────────

/**
 * Hash a string to a numeric seed. Deterministic.
 * @param str - Input text identifier
 */
export function hashSeed(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

/**
 * Seeded pseudo-random number generator (Mulberry32).
 * Returns a function that produces a deterministic sequence.
 * @param seed - Numeric seed parameter
 * @returns Floating-point values in [0, 1)
 */
export function seededRandom(seed: number): () => number {
  let state = seed | 0;
  return (): number => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ── Noise & Humanization Generators ────────────────────────────

/**
 * Hand instability noise — micro-jitter during active drawing.
 * Amplitude scales with speed: fast drawing = less jitter.
 */
export function handInstability(seed: number, t: number, speed: number = 0.5, amplitude: number = 1.2): Vector2D {
  // Reduce jitter at higher speeds (motor smoothing)
  const effectiveAmp = amplitude * (1 - speed * 0.6);

  const phase1 = seed * 0.1;
  const phase2 = seed * 0.17;

  // Multiple frequency components for organic feel
  const dx =
    Math.sin(t * 0.023 + phase1) * effectiveAmp * 0.6 +
    Math.sin(t * 0.089 + phase1 * 2.3) * effectiveAmp * 0.3 +
    Math.cos(t * 0.157 + phase2) * effectiveAmp * 0.1;

  const dy =
    Math.cos(t * 0.019 + phase2) * effectiveAmp * 0.5 +
    Math.sin(t * 0.071 + phase2 * 1.7) * effectiveAmp * 0.35 +
    Math.cos(t * 0.131 + phase1 * 0.8) * effectiveAmp * 0.15;

  return { dx, dy };
}

/**
 * Cursor breathing — gentle idle oscillation when not drawing.
 * Gives the cursor a "living" feel.
 */
export function cursorBreathing(timeMs: number, amplitudeX: number = 1.5, amplitudeY: number = 2.0): Vector2D {
  const t = timeMs * 0.001; // Convert to seconds representation
  return {
    dx: Math.sin(t * 1.2) * amplitudeX + Math.sin(t * 0.7) * amplitudeX * 0.3,
    dy: Math.cos(t * 0.9) * amplitudeY + Math.cos(t * 0.5) * amplitudeY * 0.4,
  };
}

/**
 * Hesitation tremor — intensified jitter during cognitive pauses.
 * Stronger hesitation = more visible trembling.
 */
export function hesitationTremor(seed: number, t: number, strength: number = 0.5): Vector2D {
  const amp = strength * 3.0; // Max 3px tremor threshold
  const freq = 0.15 + strength * 0.2; // Higher freq for stronger hesitation
  const phase = seed * 0.13;

  return {
    dx: Math.sin(t * freq + phase) * amp + Math.sin(t * freq * 2.3 + phase * 1.5) * amp * 0.4,
    dy: Math.cos(t * freq * 1.1 + phase * 0.7) * amp + Math.cos(t * freq * 1.8 + phase * 2.1) * amp * 0.3,
  };
}

/**
 * Pressure variation along a stroke — simulates natural pen pressure.
 * Start with light contact, build pressure, ease off at end.
 */
export function strokePressure(t: number, basePressure: number = 0.8, seed: number = 0): number {
  let pressure: number;
  if (t < 0.1) {
    // Initial contact — light contact dampening
    pressure = basePressure * 0.5 * (t / 0.1);
  } else if (t < 0.3) {
    // Pressure buildup ramp
    const nt = (t - 0.1) / 0.2;
    pressure = basePressure * (0.5 + 0.5 * nt);
  } else if (t > 0.85) {
    // Trailing off near limits
    const nt = (t - 0.85) / 0.15;
    pressure = basePressure * (1 - 0.3 * nt);
  } else {
    // Sustained writing pressure
    pressure = basePressure;
  }

  // Add micro-variation (deterministic)
  const microVar = Math.sin(t * 17.3 + seed * 0.1) * 0.05;
  return Math.max(0.1, Math.min(1, pressure + microVar));
}

/**
 * Direction momentum — models the tendency of hand movement to continue in the same direction.
 */
export function directionMomentum(prevDx: number, prevDy: number, targetDx: number, targetDy: number, momentum: number = 0.3): Vector2D {
  return {
    dx: prevDx * momentum + targetDx * (1 - momentum),
    dy: prevDy * momentum + targetDy * (1 - momentum),
  };
}

/**
 * Pen landing wobble — the initial instability when pen contacts whiteboard surface.
 */
export function penLandingWobble(seed: number, timeSinceLandingMs: number): WobbleSnapshot {
  const settleTimeMs = 120; // Stabilizes within a 120ms window
  if (timeSinceLandingMs >= settleTimeMs) {
    return { dx: 0, dy: 0, settled: true };
  }

  const decay = 1 - timeSinceLandingMs / settleTimeMs;
  const amp = decay * 2.5;
  const freq = 0.3;
  const phase = seed * 0.11;

  return {
    dx: Math.sin(timeSinceLandingMs * freq + phase) * amp,
    dy: Math.cos(timeSinceLandingMs * freq * 1.3 + phase * 0.7) * amp * 0.8,
    settled: false,
  };
}

/**
 * NEW: Chalk Bluntness Degradation
 * Models physical marker/chalk tip flattening over cumulative drawing length.
 * As wear accumulates, lines naturally broaden until a rotational micro-pause occurs.
 *
 * @param cumulativeLength - Total distance written since last tip rotation/reset
 * @param maxWearLength - Distance threshold after which tip is completely flattened
 */
export function chalkBluntnessDegradation(cumulativeLength: number, maxWearLength: number = 6000): number {
  const wearFactor = Math.min(1.0, cumulativeLength / maxWearLength);
  return 1.0 + wearFactor * 0.35; // Broadens stroke width up to 1.35x naturally
}

/**
 * NEW: Biomechanical Line Drift & Margin Compression
 * Models the natural row slanting and horizontal spatial compression that occurs
 * when a human approaches the edge boundaries of a physical writing space.
 *
 * @param x - Absolute canvas horizontal position
 * @param rowProgress - Factor indicating duration spent writing current structural segment
 * @param fatigue - Teacher physical reach fatigue multiplier (0..1)
 */
export function biomechanicalLineDrift(x: number, rowProgress: number, fatigue: number = 0.4): DriftSnapshot {
  // Calculate vertical sag/climb driven by arm pivot radius drift thresholds
  const driftY = Math.sin(x * 0.0006) * 16 * fatigue * Math.min(2.0, rowProgress);
  
  // Margin compression: compress font layout horizontally up to 28% near right canvas border
  let compressionScale = 1.0;
  if (x > 860) {
    const overflowFactor = (x - 860) / 220;
    compressionScale = 1.0 - Math.min(0.28, overflowFactor * 0.45);
  }

  return { dy: driftY, compressionScale };
}