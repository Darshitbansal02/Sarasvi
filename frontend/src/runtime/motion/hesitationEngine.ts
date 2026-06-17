/**
 * hesitationEngine.ts — Cognitive hesitation and pacing modulator.
 *
 * Humans hesitate. This engine injects naturalistic pauses, slowdowns,
 * and tremor based on concept difficulty, drawing complexity, and
 * narrative pacing cues.
 */

import { difficultyProfile } from "./velocityCurves";
import { seededRandom } from "./proceduralNoise";

// ── Gesture & Hesitation Types ─────────────────────────────────

export enum HESITATION_TYPE {
  MICRO_PAUSE = "micro_pause",         // 50-200ms — brief thinking moment
  HOVER_DELAY = "hover_delay",         // 100-400ms — hovering before stroke
  DIFFICULTY_PAUSE = "difficulty_pause", // 200-800ms — hard concept processing
  EMPHASIS_SLOW = "emphasis_slow",       // Slower drawing for emphasis
  TRANSITION_PAUSE = "transition_pause", // Between major sections
  REVISIT = "revisit",                   // Return to highlight something
}

// ── Struct Data & Domain Interfaces ───────────────────────────

export interface ConstructionStep {
  difficulty?: number;
  action?: string;
  emphasis_targets?: string[];
  duration_ms?: number;
  concept_complexity?: number;
  drawing_complexity?: number;
  transition_density?: number;
}

export interface HesitationEvent {
  type: HESITATION_TYPE;
  durationMs: number;
  position: "before" | "during" | "after" | string;
  strength: number;
  speedMultiplier?: number;
}

export interface HesitationMetrics {
  totalPauseMs: number;
  hesitationCount: number;
  averageDifficulty: number;
  pacingMultiplier: number;
}

// ── HesitationEngine Class ─────────────────────────────────────

export class HesitationEngine {
  private _pacingMultiplier: number;
  private _recentDifficulties: number[];
  private _maxDifficultyWindow: number;
  private _rng: () => number;
  private _totalPauseMs: number;
  private _hesitationCount: number;

  constructor() {
    this._pacingMultiplier = 1.0;
    this._recentDifficulties = [];
    this._maxDifficultyWindow = 10;
    this._rng = seededRandom(42);
    this._totalPauseMs = 0;
    this._hesitationCount = 0;
  }

  /**
   * Set global pacing multiplier modifier boundaries.
   * @param multiplier - Speed scaling coefficient factor (1.0 = baseline normal)
   */
  public setPacing(multiplier: number): void {
    this._pacingMultiplier = Math.max(0.2, Math.min(3.0, multiplier));
  }

  /**
   * Generate hesitation events for a single step block.
   * Compiles cognitive pacing adjustments onto downstream motion layers.
   *
   * @param step - Whitespace layout metadata payload
   * @returns Array collection containing procedurally calculated hesitation markers
   */
  public generateHesitations(step: ConstructionStep): HesitationEvent[] {
    const hesitations: HesitationEvent[] = [];
    const {
      difficulty = 0.5,
      emphasis_targets = [],
      duration_ms = 500,
      concept_complexity = difficulty,
      drawing_complexity = Math.min(1, duration_ms / 1800),
      transition_density = emphasis_targets.length > 0 ? 0.7 : 0.2,
    } = step;

    // Push execution records onto moving context array frames
    this._recentDifficulties.push(difficulty);
    if (this._recentDifficulties.length > this._maxDifficultyWindow) {
      this._recentDifficulties.shift();
    }

    const avgDifficulty = this._getAverageDifficulty();
    const profile = difficultyProfile(difficulty) as { hesitationChance: number; [key: string]: any };
    const complexityFactor = Math.max(0.4, Math.min(1.8, 0.7 + concept_complexity * 0.45 + drawing_complexity * 0.35));
    const transitionFactor = Math.max(0.5, Math.min(1.6, 0.75 + transition_density * 0.5 + Math.abs(difficulty - avgDifficulty) * 0.2));

    // 1. Compute pre-action hover delay structures (elevated frequencies on heavy nodes)
    if (this._rng() < profile.hesitationChance * 1.2) {
      const hoverMs = this._scaleDuration((80 + difficulty * 220) * complexityFactor);
      hesitations.push({
        type: HESITATION_TYPE.HOVER_DELAY,
        durationMs: hoverMs,
        position: "before",
        strength: difficulty * 0.8,
      });
      this._totalPauseMs += hoverMs;
      this._hesitationCount++;
    }

    // 2. Compute microscopic tracking tremors across complex elements
    if (difficulty > 0.4 && this._rng() < difficulty * 0.5) {
      const pauseMs = this._scaleDuration((50 + difficulty * 140) * complexityFactor);
      hesitations.push({
        type: HESITATION_TYPE.MICRO_PAUSE,
        durationMs: pauseMs,
        position: "during",
        strength: difficulty * 0.6,
      });
      this._totalPauseMs += pauseMs;
      this._hesitationCount++;
    }

    // 3. Compute distinct concept difficulty delays
    if (difficulty > 0.7) {
      const pauseMs = this._scaleDuration((200 + (difficulty - 0.7) * 1800) * complexityFactor);
      hesitations.push({
        type: HESITATION_TYPE.DIFFICULTY_PAUSE,
        durationMs: pauseMs,
        position: "before",
        strength: difficulty,
      });
      this._totalPauseMs += pauseMs;
      this._hesitationCount++;
    }

    // 4. Ingress emphasis slowing coefficients to amplify optical anchor weights
    if (emphasis_targets.length > 0) {
      hesitations.push({
        type: HESITATION_TYPE.EMPHASIS_SLOW,
        durationMs: 0, // Instantaneous: acts directly down scale interpolation loops
        position: "during",
        strength: Math.max(0.45, Math.min(0.85, 0.45 + concept_complexity * 0.2)),
        speedMultiplier: Math.max(0.45, 0.6 + (1 - difficulty) * 0.25 - drawing_complexity * 0.1),
      });
    }

    // 5. Evaluate transition friction milestones inside macro context changes
    if (this._recentDifficulties.length >= 3) {
      const recentAvg = (this._recentDifficulties.slice(-3).reduce((a, b) => a + b, 0)) / 3;
      const diffShift = Math.abs(difficulty - recentAvg);
      
      if (diffShift > 0.3 || transition_density > 0.55) {
        const pauseMs = this._scaleDuration((150 + diffShift * 360) * transitionFactor);
        hesitations.push({
          type: HESITATION_TYPE.TRANSITION_PAUSE,
          durationMs: pauseMs,
          position: "before",
          strength: diffShift,
        });
        this._totalPauseMs += pauseMs;
        this._hesitationCount++;
      }
    }

    return hesitations;
  }

  /**
   * Refines dynamic trace velocity multipliers across individual pixel step segments.
   * Matches the natural movement behavior of a real physical hand.
   *
   * @param strokeProgress - Normalized interpolation value along the stroke path (0..1)
   * @param difficulty - Core target block analytical value weight multiplier
   * @param curvature - Instantaneous directional change vector metrics (radians / px)
   * @returns Transformed speed scale step modifier
   */
  public getSpeedMultiplier(strokeProgress: number, difficulty: number, curvature: number = 0): number {
    let speed = 1.0;

    // Apply baseline global structural resistance
    speed *= (1.0 - difficulty * 0.4);

    // Apply geometric curvature penalty limits to decelerate tightly rounded contours
    const curvaturePenalty = Math.min(0.5, curvature * 10);
    speed *= (1.0 - curvaturePenalty);

    // Smooth entry acceleration and exit terminal dampening ramps
    if (strokeProgress < 0.1) {
      speed *= 0.5 + strokeProgress * 5; 
    } else if (strokeProgress > 0.9) {
      speed *= 0.5 + (1 - strokeProgress) * 5; 
    }

    // Direct pacing override multiplier inject pass
    speed *= this._pacingMultiplier;

    return Math.max(0.1, speed);
  }

  /**
   * Evaluates historical parameters to check if review highlighting markers are valid.
   */
  public shouldRevisit(difficulty: number, emphasisCount: number): boolean {
    if (emphasisCount === 0) return false;
    return this._rng() < difficulty * 0.25 * emphasisCount;
  }

  /**
   * Harvest continuous system pacing records snapshot.
   */
  public getMetrics(): HesitationMetrics {
    return {
      totalPauseMs: this._totalPauseMs,
      hesitationCount: this._hesitationCount,
      averageDifficulty: this._getAverageDifficulty(),
      pacingMultiplier: this._pacingMultiplier,
    };
  }

  /**
   * Wipe active tracking registers clean.
   */
  public reset(): void {
    this._recentDifficulties = [];
    this._totalPauseMs = 0;
    this._hesitationCount = 0;
    this._rng = seededRandom(42);
  }

  // ── Private Interpolation Helpers ────────────────────────────

  private _getAverageDifficulty(): number {
    if (this._recentDifficulties.length === 0) return 0.5;
    return this._recentDifficulties.reduce((a, b) => a + b, 0) / this._recentDifficulties.length;
  }

  private _scaleDuration(ms: number): number {
    // Zero-division protection safeguarding math limits if active pacing multipliers flatline
    if (this._pacingMultiplier === 0) return Math.max(16, Math.floor(ms));
    return Math.max(16, Math.floor(ms / this._pacingMultiplier));
  }
}