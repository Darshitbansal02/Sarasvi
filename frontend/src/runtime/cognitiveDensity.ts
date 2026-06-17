import { create } from "zustand";

const COGNITIVE_FATIGUE_K = 0.005; // exponential growth constant

export interface VisualMetrics {
  objectCount?: number;
  spatialOverlap?: number;
  motion?: number;
  text?: number;
}

export interface CognitiveMetrics {
  abstractionDepth?: number;
  reasoningSteps?: number;
  symbolComplexity?: number;
  branchingDepth?: number;
  memoryDependency?: number;
}

export interface CognitiveDensityState {
  visualDensity: number;
  cognitiveComplexity: number;
  overallLoad: number;
  sceneDurationMs: number;

  objectCountWeight: number;
  spatialOverlapWeight: number;
  motionWeight: number;
  textWeight: number;

  abstractionDepthWeight: number;
  reasoningStepsWeight: number;
  symbolComplexityWeight: number;
  branchingDepthWeight: number;
  memoryDependencyWeight: number;

  updateMetrics: (
    visualMetrics: VisualMetrics,
    cognitiveMetrics: CognitiveMetrics,
    dtMs: number
  ) => void;
  resetSession: () => void;
}

export const useCognitiveDensityStore = create<CognitiveDensityState>(
  (set, get) => ({
    visualDensity: 0.0,
    cognitiveComplexity: 0.0,
    overallLoad: 0.0,
    sceneDurationMs: 0,

    objectCountWeight: 0.4,
    spatialOverlapWeight: 0.2,
    motionWeight: 0.2,
    textWeight: 0.2,

    abstractionDepthWeight: 0.3,
    reasoningStepsWeight: 0.3,
    symbolComplexityWeight: 0.2,
    branchingDepthWeight: 0.1,
    memoryDependencyWeight: 0.1,

    updateMetrics: (visualMetrics, cognitiveMetrics, dtMs) => {
      set((state) => {
        const newDuration = state.sceneDurationMs + dtMs;

        const vDensity =
          (visualMetrics.objectCount || 0) * state.objectCountWeight +
          (visualMetrics.spatialOverlap || 0) * state.spatialOverlapWeight +
          (visualMetrics.motion || 0) * state.motionWeight +
          (visualMetrics.text || 0) * state.textWeight;

        const cComplexity =
          (cognitiveMetrics.abstractionDepth || 0) *
            state.abstractionDepthWeight +
          (cognitiveMetrics.reasoningSteps || 0) *
            state.reasoningStepsWeight +
          (cognitiveMetrics.symbolComplexity || 0) *
            state.symbolComplexityWeight +
          (cognitiveMetrics.branchingDepth || 0) *
            state.branchingDepthWeight +
          (cognitiveMetrics.memoryDependency || 0) *
            state.memoryDependencyWeight;

        // Fatigue grows exponentially
        const tSeconds = newDuration / 1000.0;
        const fatigue = 1.0 - Math.exp(-COGNITIVE_FATIGUE_K * tSeconds);

        // Calculate overall load including fatigue.
        // NOTE: this value is PRESENTATION-ONLY — it is consumed solely by
        // constructionRuntime to compute a cursor pacing multiplier (the teacher's
        // hand slows down on dense scenes). It is NOT a pedagogical authority:
        // adaptation decisions are owned by the backend (cognitive_tracker +
        // /interaction + /adapt). The former `cognitive-soft-warning` /
        // `cognitive-transition-trigger` window events were removed — nothing
        // listened to them and they duplicated backend decisioning.
        const baseLoad = vDensity * 0.45 + cComplexity * 0.55;
        const overallLoad = Math.min(1.0, baseLoad + fatigue * 0.2);

        return {
          visualDensity: vDensity,
          cognitiveComplexity: cComplexity,
          overallLoad,
          sceneDurationMs: newDuration,
        };
      });
    },

    resetSession: () =>
      set({
        visualDensity: 0,
        cognitiveComplexity: 0,
        overallLoad: 0,
        sceneDurationMs: 0,
      }),
  })
);
