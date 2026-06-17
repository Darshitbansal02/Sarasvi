/**
 * focusEngine.ts — Visual attention choreography.
 *
 * Guides student attention through:
 * - Dynamic focus pulses (highlighting active elements)
 * - Contextual dimming (de-emphasizing inactive elements)
 * - Gaze simulation (cursor pointing at what's being discussed)
 * - Revisit highlighting (returning to previously drawn elements)
 */

import { useCognitiveDensityStore } from "../cognitiveDensity";

// ── Focus Strategies & Enums ───────────────────────────────────

export enum FOCUS_STRATEGY {
  PULSE = "pulse",           // Glow/scale pulse on target
  DIM_OTHERS = "dim_others", // Dim everything except target
  CIRCLE = "circle",         // Draw attention circle around target
  UNDERLINE = "underline",   // Underline target (for text/equations)
  GLOW = "glow",             // Sustained glow effect
  ARROW = "arrow",           // Draw arrow pointing to target
}

// ── Struct Data & Domain Interfaces ───────────────────────────

export interface FocusEffect {
  focusId: string;
  targetIds: string[];
  strategy: FOCUS_STRATEGY | string;
  durationMs: number;
  intensity: number;
  startMs: number;
  progress: number;
  active: boolean;
}

export interface FocusHistoryEntry {
  objectId: string;
  timeMs: number;
}

export interface ApplyFocusParams {
  focusId: string;
  targetIds: string[];
  strategy?: FOCUS_STRATEGY | string;
  durationMs?: number;
  intensity?: number;
  startMs?: number;
}

export interface ComputedVisualState {
  color: number;
  pulseValue: number;
}

export interface ActiveFocusRenderState extends ComputedVisualState {
  focusId: string;
  targetIds: string[];
  strategy: FOCUS_STRATEGY | string;
  progress: number;
}

export interface FocusEngineTickResult {
  activeEffects: ActiveFocusRenderState[];
  globalDimLevel: number;
  focusedObjectIds: Set<string>;
}

export interface ObjectFocusState {
  alpha: number;
  scale: number;
  glowIntensity: number;
  glowColor: number;
  isFocused: boolean;
}

// ── FocusEngine Class ──────────────────────────────────────────

export class FocusEngine {
  private _activeFoci: Map<string, FocusEffect>;
  private _globalDimLevel: number;
  private _focusHistory: FocusHistoryEntry[];
  private _maxHistory: number;
  private _importanceMap: Map<string, number>;

  constructor() {
    // Active focus effects mapping table
    this._activeFoci = new Map<string, FocusEffect>();

    // Global dim tracking scalars
    this._globalDimLevel = 0; // 0 = no dimming, 1 = fully dimmed

    // Focus chronological array limits for repetition evaluation
    this._focusHistory = [];
    this._maxHistory = 20;

    // Heat maps tracking node usage histories over time
    this._importanceMap = new Map<string, number>();
  }

  /**
   * Inject and initialize an attention accent profile on target IDs.
   */
  public applyFocus({
    focusId,
    targetIds,
    strategy = FOCUS_STRATEGY.PULSE,
    durationMs = 800,
    intensity = 0.7,
    startMs = 0
  }: ApplyFocusParams): void {
    const effect: FocusEffect = {
      focusId,
      targetIds: [...targetIds],
      strategy,
      durationMs,
      intensity,
      startMs,
      progress: 0,
      active: true,
    };

    this._activeFoci.set(focusId, effect);

    // Track sequential interaction footprints to calculate significance
    for (const tid of targetIds) {
      this._focusHistory.push({ objectId: tid, timeMs: startMs });
      if (this._focusHistory.length > this._maxHistory) {
        this._focusHistory.shift();
      }
      
      const current = this._importanceMap.get(tid) || 0;
      this._importanceMap.set(tid, current + intensity);
    }

    // Force background shading variables under specific layout protocols
    if (strategy === FOCUS_STRATEGY.DIM_OTHERS) {
      this._globalDimLevel = intensity * 0.6;
    }
  }

  /**
   * Deallocate an active focus profile immediately by its explicit ID.
   */
  public removeFocus(focusId: string): void {
    const effect = this._activeFoci.get(focusId);
    if (effect && effect.strategy === FOCUS_STRATEGY.DIM_OTHERS) {
      this._globalDimLevel = 0;
    }
    this._activeFoci.delete(focusId);
  }

  /**
   * Advances layout animation state paths. Updates progression counters.
   * Call on every high frequency render step frame pass.
   *
   * @param absoluteTimeMs - Authoritative master line timestamp tracking calculations
   * @returns Transformed coordinate modifiers consumed by the drawing canvas
   */
  public tick(absoluteTimeMs: number): FocusEngineTickResult {
    const expiredIds: string[] = [];
    const activeEffects: ActiveFocusRenderState[] = [];

    for (const [focusId, effect] of this._activeFoci) {
      const elapsed = absoluteTimeMs - effect.startMs;
      effect.progress = Math.min(1, elapsed / Math.max(1, effect.durationMs));

      if (effect.progress >= 1) {
        expiredIds.push(focusId);
        continue;
      }

      const visualState = this._computeVisualState(effect);
      activeEffects.push({
        focusId,
        targetIds: effect.targetIds,
        strategy: effect.strategy,
        progress: effect.progress,
        ...visualState,
      });
    }

    // Safely cleanup finished references
    for (const id of expiredIds) {
      this.removeFocus(id);
    }

    // Seamlessly exponential decay opacity overrides if workspace filters drop out
    if (this._globalDimLevel > 0 && this._activeFoci.size === 0) {
      this._globalDimLevel *= 0.95;
      if (this._globalDimLevel < 0.01) this._globalDimLevel = 0;
    }

    return {
      activeEffects,
      globalDimLevel: this._globalDimLevel,
      focusedObjectIds: this._getAllFocusedIds(),
    };
  }

  /**
   * Returns calculated rendering vectors specifying accent bounds for unique canvas items.
   *
   * @param objectId - Explicit identifier of target scene element node
   */
  public getObjectFocusState(objectId: string): ObjectFocusState {
    let alpha = 1;
    let scale = 1;
    let glowIntensity = 0;
    let glowColor = 0x2f81f7;
    let isFocused = false;

    // Read real-time processing constraints driven by session load profiles
    const loadState = useCognitiveDensityStore.getState ? (useCognitiveDensityStore.getState() as any) : null;
    const overallLoad = loadState ? loadState.overallLoad : 0.0;
    const visualDensity = loadState ? loadState.visualDensity : 0.0;

    for (const [, effect] of this._activeFoci) {
      if (effect.targetIds.includes(objectId)) {
        isFocused = true;
        const vs = this._computeVisualState(effect);

        if (effect.strategy === FOCUS_STRATEGY.PULSE) {
          const scaleMultiplier = 1.0 + (overallLoad > 0.5 ? (overallLoad - 0.5) * 0.4 : 0.0);
          scale = 1 + vs.pulseValue * 0.08 * scaleMultiplier;
          glowIntensity = vs.pulseValue * effect.intensity * (1.0 + (overallLoad > 0.5 ? (overallLoad - 0.5) * 0.5 : 0.0));
        } else if (effect.strategy === FOCUS_STRATEGY.GLOW) {
          glowIntensity = effect.intensity * (1 - effect.progress * 0.3) * (1.0 + (overallLoad > 0.5 ? (overallLoad - 0.5) * 0.3 : 0.0));
        }

        glowColor = vs.color || 0x2f81f7;
      }
    }

    // Apply dimming configurations strictly down non-targeted layout pathways
    if (this._globalDimLevel > 0 && !isFocused) {
      const minAlphaLimit = visualDensity > 0.65 ? 0.05 : 0.15;
      alpha = Math.max(minAlphaLimit, 1 - this._globalDimLevel);
    }

    return { alpha, scale, glowIntensity, glowColor, isFocused };
  }

  /**
   * Evaluates if old structural nodes carry sufficient baseline weight to justify repeat accent flashes.
   */
  public shouldRevisit(objectId: string): boolean {
    const importance = this._importanceMap.get(objectId) || 0;
    return importance > 1.5;
  }

  /**
   * Hard flush running variables.
   */
  public reset(): void {
    this._activeFoci.clear();
    this._globalDimLevel = 0;
    this._focusHistory = [];
    this._importanceMap.clear();
  }

  // ── Private Interpolation Math Blocks ──────────────────────

  private _computeVisualState(effect: FocusEffect): ComputedVisualState {
    const t = effect.progress;
    const result: ComputedVisualState = { color: 0x2f81f7, pulseValue: 0 };

    switch (effect.strategy) {
      case FOCUS_STRATEGY.PULSE: {
        const decay = 1 - t * 0.5;
        result.pulseValue = Math.sin(t * Math.PI * 4) * decay * effect.intensity;
        result.color = 0xf2cc60; // amber
        break;
      }
      case FOCUS_STRATEGY.DIM_OTHERS: {
        result.pulseValue = effect.intensity;
        break;
      }
      case FOCUS_STRATEGY.GLOW: {
        result.pulseValue = (0.7 + Math.sin(t * Math.PI * 2) * 0.3) * effect.intensity;
        result.color = 0x2f81f7;
        break;
      }
      case FOCUS_STRATEGY.CIRCLE: {
        result.pulseValue = t < 0.3 ? t / 0.3 : 1 - (t - 0.3) / 0.7;
        result.color = 0xf59e0b;
        break;
      }
      case FOCUS_STRATEGY.UNDERLINE: {
        result.pulseValue = t < 0.4 ? t / 0.4 : Math.max(0, 1 - (t - 0.6) / 0.4);
        result.color = 0xef4444;
        break;
      }
      default:
        result.pulseValue = effect.intensity * (1 - t);
    }

    return result;
  }

  private _getAllFocusedIds(): Set<string> {
    const ids = new Set<string>();
    for (const [, effect] of this._activeFoci) {
      for (const id of effect.targetIds) {
        ids.add(id);
      }
    }
    return ids;
  }
}