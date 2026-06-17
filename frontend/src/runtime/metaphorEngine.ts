/**
 * metaphorEngine.ts — Semantic Mapping and Visual Representation Transitions
 *
 * Handles the semantic mapping and transition logic between different visual
 * representations of the same concept.
 */

export enum MetaphorType {
  FORMAL = "formal",
  ANALOGICAL = "analogy",
  MINECRAFT = "minecraft",
  ABSTRACTION = "abstract",
}

export interface PrimitiveMapping {
  component: string;
  style: string;
}

interface ConceptMappings {
  [conceptType: string]: Record<MetaphorType, PrimitiveMapping>;
}

interface MetaphorListener {
  (oldMetaphor: MetaphorType, newMetaphor: MetaphorType): void;
}

export const METAPHORS = {
  FORMAL: MetaphorType.FORMAL,
  ANALOGICAL: MetaphorType.ANALOGICAL,
  MINECRAFT: MetaphorType.MINECRAFT,
  ABSTRACTION: MetaphorType.ABSTRACTION,
};

class MetaphorEngine {
  private currentMetaphor: MetaphorType = MetaphorType.FORMAL;
  private listeners: MetaphorListener[] = [];

  getPrimitiveMapping(conceptType: string, baseData?: any): PrimitiveMapping {
    const conceptMapping = baseData?.metaphor_mapping || {};
    return (
      conceptMapping[this.currentMetaphor] || {
        component: baseData?.metaphor_mapping?.[this.currentMetaphor]?.component || conceptType,
        style: baseData?.metaphor_mapping?.[this.currentMetaphor]?.style || "default",
      }
    );
  }

  /**
   * Set the active metaphor and notify listeners.
   */
  setMetaphor(metaphor: MetaphorType): void {
    if (!Object.values(MetaphorType).includes(metaphor)) {
      console.error(`Invalid metaphor: ${metaphor}`);
      return;
    }

    const oldMetaphor = this.currentMetaphor;
    this.currentMetaphor = metaphor;

    // Selects which backend-provided metaphor_mapping to render — no semantics
    // are computed here; the representation set is authored on the backend.
    this.listeners.forEach((listener) => listener(oldMetaphor, metaphor));
  }

  /**
   * Get the current active metaphor.
   */
  getMetaphor(): MetaphorType {
    return this.currentMetaphor;
  }

  /**
   * Register a listener for metaphor changes.
   */
  onTransition(callback: MetaphorListener): () => void {
    this.listeners.push(callback);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== callback);
    };
  }

  reset(): void {
    this.currentMetaphor = MetaphorType.FORMAL;
    this.listeners = [];
  }
}

export const metaphorEngine = new MetaphorEngine();
