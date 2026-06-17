/**
 * simulationEngine.ts — Continuous Pedagogical Simulation
 *
 * Runs physics, algorithmic, and mathematical simulations in real time
 * by mutating scene objects on every tick, creating a continuously evolving
 * visual environment rather than replaying static frames.
 */

import { audioTimeline } from "../audio/audioTimeline";
import { useRuntimeStore } from "../runtimeStore";
import * as math from "mathjs";

// ── Type Interfaces & Domain Contracts ─────────────────────────

export interface SimulationParams {
  speed?: number;
  center?: { x: number; y: number };
  radius?: number;
  frequency?: number;
  amplitude?: number;
  intensity?: number;
  [key: string]: any;
}

export interface SimulationInstance {
  id: string;
  type: "planetary" | "wave" | "force_directed" | string;
  targetIds: string[];
  params: SimulationParams;
  startMs: number;
  durationMs: number;
  state: {
    elapsedPacedMs?: number;
    angles?: Record<string, number>;
    baseY?: Record<string, number>;
    [key: string]: any;
  };
  specification?: {
    simulation_type: string;
    entities: Array<{
      id: string;
      type: string;
      properties: Record<string, any>;
    }>;
    rules: Array<{
      name: string;
      formula: string;
    }>;
    initial_state: {
      variables: Record<string, any>;
    };
    transitions: Array<{
      trigger: string;
      target_state: string;
    }>;
    justification?: string;
  };
}

export interface StartSimulationPayload {
  simulation_id?: string;
  simulation_type?: string;
  target_ids?: string[];
  parameters?: SimulationParams;
  duration_ms?: number;
}

export interface StepSimulationPayload {
  simulation_id: string;
  updates: Record<string, any>;
}

export interface SimulatedSceneObject {
  id: string;
  type: string;
  position?: { x: number; y: number };
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  [key: string]: any;
}

// ── SimulationEngine Class ─────────────────────────────────────

export class SimulationEngine {
  public activeSimulations: Map<string, SimulationInstance>;

  constructor() {
    this.activeSimulations = new Map<string, SimulationInstance>();
  }

  /**
   * Start a new real-time simulation instance.
   * Accepts broad parameter types to prevent upstream orchestration casting friction.
   */
  public startSimulation(payload: any, timeMs: number): void {
    const simId = payload?.simulation_id || `sim_${timeMs}`;
    const spec = payload?.simulation_specification;

    const initialState: Record<string, any> = {
      elapsedPacedMs: 0,
    };

    if (spec?.initial_state?.variables) {
      Object.assign(initialState, spec.initial_state.variables);
    }

    if (spec?.entities) {
      spec.entities.forEach((entity: any) => {
        if (entity.id && entity.properties) {
          initialState[entity.id] = { ...entity.properties };
        }
      });
    }

    this.activeSimulations.set(simId, {
      id: simId,
      type: payload?.simulation_type || spec?.simulation_type || "force_directed",
      targetIds: payload?.target_ids || (spec?.entities ? spec.entities.map((e: any) => e.id) : []),
      params: payload?.parameters || {},
      startMs: timeMs,
      durationMs: payload?.duration_ms || 5000,
      state: initialState,
      specification: spec,
    });
  }

  /**
   * Process a discrete simulation step modification update event.
   */
  public stepSimulation(payload: any, timeMs: number): void {
    const simId = payload?.simulation_id;
    if (!simId) return;
    
    const sim = this.activeSimulations.get(simId);
    if (sim) {
      const updates = payload.updates || {};
      sim.state = { ...sim.state, ...updates };
    }
  }

  /**
   * Advance all active simulation engines by deltaMs.
   * Mutates sceneObjects directly for absolute performance optimization.
   */
  public tick(sceneObjects: Record<string, SimulatedSceneObject>, timeMs: number, deltaMs: number): void {
    // Query the authoritative runtime state store to get the verified playback multiplier safely
    const activeRate = useRuntimeStore.getState().playbackRate ?? 1.0;
    const dt = (deltaMs / 1000) * activeRate; 

    for (const [id, sim] of this.activeSimulations.entries()) {
      if (timeMs - sim.startMs > sim.durationMs) {
        this.activeSimulations.delete(id);
        continue;
      }

      if (sim.state.elapsedPacedMs === undefined) {
        sim.state.elapsedPacedMs = 0;
      }
      sim.state.elapsedPacedMs += deltaMs * activeRate;

      if (sim.specification && sim.specification.rules && sim.specification.rules.length > 0) {
        this._tickDynamicSimulation(sim, sceneObjects, dt);
      } else {
        switch (sim.type) {
          case "planetary":
            this._tickPlanetary(sim, sceneObjects, dt, sim.state.elapsedPacedMs);
            break;
          case "wave":
            this._tickWave(sim, sceneObjects, dt, sim.state.elapsedPacedMs);
            break;
          case "force_directed":
            this._tickForceDirected(sim, sceneObjects, dt);
            break;
        }
      }
    }
  }

  private _tickDynamicSimulation(
    sim: SimulationInstance,
    sceneObjects: Record<string, SimulatedSceneObject>,
    dt: number
  ): void {
    if (!sim.specification) return;

    // 1. Build context/scope for evaluation
    const scope: Record<string, any> = {
      dt,
      elapsedPacedMs: sim.state.elapsedPacedMs,
    };

    // Copy global variables/state keys
    for (const key of Object.keys(sim.state)) {
      if (key !== "elapsedPacedMs") {
        scope[key] = sim.state[key];
      }
    }

    // Sync entities current visual coordinates from sceneObjects if they exist
    sim.specification.entities.forEach((entity) => {
      const obj = sceneObjects[entity.id];
      const entityState = sim.state[entity.id] || { ...entity.properties };
      
      if (obj) {
        if (obj.position) {
          entityState.x = obj.position.x;
          entityState.y = obj.position.y;
        } else {
          entityState.x = obj.x ?? entityState.x ?? 0;
          entityState.y = obj.y ?? entityState.y ?? 0;
        }
      }

      scope[entity.id] = entityState;

      // Provide flat bindings (e.g. body1_x) for ease of formula design
      Object.keys(entityState).forEach((propKey) => {
        scope[`${entity.id}_${propKey}`] = entityState[propKey];
      });
    });

    // 2. Evaluate all rules sequentially
    sim.specification.rules.forEach((rule) => {
      try {
        math.evaluate(rule.formula, scope);
      } catch (err) {
        console.warn(`Failed to evaluate simulation rule [${rule.name}]: ${rule.formula}`, err);
      }
    });

    // 3. Write updates back to sim.state and sceneObjects
    sim.specification.entities.forEach((entity) => {
      const entityState = scope[entity.id] || {};
      
      // Sync flat bindings back to entityState in case formulas modified flat keys
      Object.keys(scope).forEach((scopeKey) => {
        if (scopeKey.startsWith(`${entity.id}_`)) {
          const propKey = scopeKey.slice(entity.id.length + 1);
          entityState[propKey] = scope[scopeKey];
        }
      });

      sim.state[entity.id] = entityState;

      const obj = sceneObjects[entity.id];
      if (obj) {
        // Only update coordinate positions if they are numbers
        if (typeof entityState.x === "number") {
          if (obj.position) {
            obj.position.x = entityState.x;
          } else {
            obj.x = entityState.x;
          }
        }
        if (typeof entityState.y === "number") {
          if (obj.position) {
            obj.position.y = entityState.y;
          } else {
            obj.y = entityState.y;
          }
        }
      }
    });

    // Write back any updated global state keys
    Object.keys(scope).forEach((key) => {
      if (key !== "dt" && key !== "elapsedPacedMs" && !sim.specification?.entities.some((e) => e.id === key || key.startsWith(`${e.id}_`))) {
        sim.state[key] = scope[key];
      }
    });
  }

  // ── Private Physics Tick Systems ─────────────────────────────

  private _tickPlanetary(
    sim: SimulationInstance, 
    sceneObjects: Record<string, SimulatedSceneObject>, 
    dt: number, 
    timeMs: number
  ): void {
    const speed = sim.params.speed || 1.0;
    const center = sim.params.center || { x: 400, y: 300 };
    
    if (!sim.state.angles) {
      sim.state.angles = Object.create(null);
    }

    const hasOwn = (obj: any, key: string) => Object.prototype.hasOwnProperty.call(obj, key);
    for (let i = 0; i < sim.targetIds.length; i++) {
      const objId = sim.targetIds[i];
      const obj = (objId && hasOwn(sceneObjects, objId)) ? sceneObjects[objId] : null;
      if (!obj) continue;

      if (!hasOwn(sim.state.angles!, objId)) {
        sim.state.angles![objId] = Math.random() * Math.PI * 2;
      }

      const radius = sim.params.radius ? (sim.params.radius * (i + 1)) : 100 + (i * 50);
      
      sim.state.angles![objId] += speed * dt / Math.sqrt(radius / 100);
      
      const angle = sim.state.angles![objId];
      
      const targetX = center.x + Math.cos(angle) * radius;
      const targetY = center.y + Math.sin(angle) * radius;

      if (obj.position) {
        obj.position.x = targetX;
        obj.position.y = targetY;
      } else {
        obj.x = targetX - (obj.width || 0) / 2;
        obj.y = targetY - (obj.height || 0) / 2;
      }
    }
  }

  private _tickWave(
    sim: SimulationInstance, 
    sceneObjects: Record<string, SimulatedSceneObject>, 
    dt: number, 
    timeMs: number
  ): void {
    const frequency = sim.params.frequency || 2.0;
    const amplitude = sim.params.amplitude || 20.0;
    const speed = sim.params.speed || 5.0;

    const hasOwn = (obj: any, key: string) => Object.prototype.hasOwnProperty.call(obj, key);
    for (let i = 0; i < sim.targetIds.length; i++) {
      const objId = sim.targetIds[i];
      const obj = (objId && hasOwn(sceneObjects, objId)) ? sceneObjects[objId] : null;
      if (!obj) continue;

      if (!sim.state.baseY) {
        sim.state.baseY = Object.create(null);
      }
      if (!hasOwn(sim.state.baseY!, objId)) {
        sim.state.baseY![objId] = obj.position?.y ?? obj.y ?? 0;
      }

      const phase = (i * 0.5) - ((timeMs / 1000) * speed);
      const dy = Math.sin(phase * frequency) * amplitude;

      const newY = sim.state.baseY![objId] + dy;

      if (obj.position) {
        obj.position.y = newY;
      } else {
        obj.y = newY;
      }
    }
  }

  private _tickForceDirected(
    sim: SimulationInstance, 
    sceneObjects: Record<string, SimulatedSceneObject>, 
    dt: number
  ): void {
    const intensity = sim.params.intensity || 5.0;
    for (const objId of sim.targetIds) {
      const obj = sceneObjects[objId];
      if (!obj) continue;

      const dx = (Math.random() - 0.5) * intensity * dt * 60;
      const dy = (Math.random() - 0.5) * intensity * dt * 60;

      if (obj.position) {
        obj.position.x += dx;
        obj.position.y += dy;
      } else {
        if (obj.x !== undefined) obj.x += dx;
        if (obj.y !== undefined) obj.y += dy;
      }
    }
  }
}

// ── Singleton Allocation ───────────────────────────────────────
export const simulationEngine = new SimulationEngine();