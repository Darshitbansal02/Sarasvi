/**
 * sceneManager.ts — Scene lifecycle and snapshot management.
 *
 * Snapshots are kept in-memory during the session.  A lightweight
 * localStorage fallback persists the last N snapshots so the student
 * can reload without losing the scene list (no IndexedDB required).
 */

import { useRuntimeStore } from "./runtimeStore";

// ── In-memory snapshot store ─────────────────────────────────────
// Key: scene_id  →  Value: full snapshot object
const _snapshots = new Map<string, any>();
const STORAGE_KEY_PREFIX = "Sarasvi_snap_";
const MAX_LOCAL_SNAPSHOTS = 20;

function _saveToLocal(sceneId: string, snap: any): void {
  try {
    localStorage.setItem(STORAGE_KEY_PREFIX + sceneId, JSON.stringify(snap));
  } catch {
    // localStorage may be full — ignore
  }
}

function _loadFromLocal(sceneId: string): any | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_PREFIX + sceneId);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

// ── Types ────────────────────────────────────────────────────────

export interface ContextAnchor {
  anchor_id: string;
  semantic_role: string;
  visual_representation?: any;
  persistence_priority: "high" | "low" | string;
  carry_forward_rules: { always?: boolean;[key: string]: any };
}

export interface PedagogicalState {
  active_concept: string;
  confusion_level: number;
  remediation_active: boolean;
  metaphor_strategy: string;
  explanation_depth?: number;
  teaching_mode?: string;
}

export interface TransitionContext {
  scene_id?: string;
  label?: string;
  metaphor_strategy?: string;
}

// ── SceneManager ─────────────────────────────────────────────────

export class SceneManager {
  private currentSceneId: string | null = null;
  private sessionId: string | null = null;
  private activeAnchors = new Map<string, ContextAnchor>();

  public init(sessionId: string): void {
    this.sessionId = sessionId;
  }

  // ── Scene lifecycle ───────────────────────────────────────────

  public createScene(
    pedagogicalState: PedagogicalState,
    transitionContext: TransitionContext = {}
  ): string {
    this.currentSceneId =
      transitionContext.scene_id || `scene_${Date.now()}`;

    const store = useRuntimeStore.getState();
    store.addScene({
      scene_id: this.currentSceneId,
      label:
        transitionContext.label ||
        `Page ${store.scenes.length + 1}`,
      concept: pedagogicalState.active_concept,
      confusion_level: pedagogicalState.confusion_level || 0,
      timeline_offset: store.currentTimeMs,
      camera_x: store.scenes.length * 1200,  // PAGE_W = 1200
    });

    return this.currentSceneId;
  }

  public branchScene(transitionContext: TransitionContext = {}): string {
    this.currentSceneId = `scene_branch_${Date.now()}`;
    return this.currentSceneId;
  }

  public freezeScene(): void { }   // no-op — in-memory store is always live

  public restoreScene(sceneId: string): Promise<any> {
    // 1. Try in-memory store
    if (_snapshots.has(sceneId)) {
      return Promise.resolve(_snapshots.get(sceneId));
    }

    // 2. Try localStorage
    const local = _loadFromLocal(sceneId);
    if (local) {
      _snapshots.set(sceneId, local);
      return Promise.resolve(local);
    }

    // 3. Construct from current store state (fallback)
    const store = useRuntimeStore.getState();
    const fallback = {
      scene_id: sceneId,
      session_id: this.sessionId,
      concept_id: store.pedagogicalState?.active_concept || "",
      schema_version: "1.0.0",
      pedagogical_state: store.pedagogicalState || {},
      pedagogical_plan: store.pedagogicalPlan || {},
      attention_state: store.attentionState || {},
      transition_context: store.transitionContext || {},
      scene_graph_state: { objects: store.sceneObjects || {} },
      visual_plan: store.visualPlan || {},
      camera_state: store.camera || {},
      transcript_state: store.transcript || [],
      semantic_summary: null,
      replay_cursor: store.timelineIndex || 0,
      timeline_offset: store.currentTimeMs || 0,
    };
    return Promise.resolve(fallback);
  }

  public archiveScene(): void { }
  public disposeScene(): void {
    this.currentSceneId = null;
    this.activeAnchors.clear();
  }

  // ── Snapshot pipeline ─────────────────────────────────────────

  public async takeSnapshot(runtimeState: any, _type?: string): Promise<any> {
    if (!this.currentSceneId || !this.sessionId) return null;

    const snap = {
      scene_id: this.currentSceneId,
      session_id: this.sessionId,
      concept_id: runtimeState.pedagogicalState?.active_concept,
      schema_version: "1.0.0",
      pedagogical_state: runtimeState.pedagogicalState || {},
      pedagogical_plan: runtimeState.pedagogicalPlan || {},
      attention_state: runtimeState.attentionState || {},
      transition_context: runtimeState.transitionContext || {},
      scene_graph_state: { objects: runtimeState.sceneObjects || {} },
      visual_plan: runtimeState.visualPlan || {},
      camera_state:
        runtimeState.camera || runtimeState.cameraState || {},
      transcript_state:
        runtimeState.transcript || runtimeState.transcriptState || {},
      semantic_summary: runtimeState.semanticSummary || null,
      replay_cursor: runtimeState.timelineIndex || 0,
      timeline_offset:
        runtimeState.currentTimeMs || runtimeState.timelineOffsetMs || 0,
      cognitive_load:
        runtimeState.pedagogicalState?.confusion_level ?? 0.5,
    };

    // Persist in-memory + localStorage
    _snapshots.set(this.currentSceneId, snap);
    _saveToLocal(this.currentSceneId, snap);

    // Trim localStorage if it grows too large
    try {
      const keys = Object.keys(localStorage).filter(k =>
        k.startsWith(STORAGE_KEY_PREFIX)
      );
      if (keys.length > MAX_LOCAL_SNAPSHOTS) {
        keys.slice(0, keys.length - MAX_LOCAL_SNAPSHOTS).forEach(k =>
          localStorage.removeItem(k)
        );
      }
    } catch {
      // ignore
    }

    return snap;
  }

  // ── Context anchors ───────────────────────────────────────────

  public registerAnchor(anchor: ContextAnchor): void {
    this.activeAnchors.set(anchor.anchor_id, anchor);
  }

  public setAnchor(anchor: ContextAnchor): void {
    this.activeAnchors.set(anchor.anchor_id, anchor);
  }

  public getAnchor(id: string): ContextAnchor | undefined {
    return this.activeAnchors.get(id);
  }

  public getCurrentSceneId(): string | null {
    return this.currentSceneId;
  }

  public reset(): void {
    this.currentSceneId = null;
    this.sessionId = null;
    this.activeAnchors.clear();
    _snapshots.clear();
  }
}

export const sceneManager = new SceneManager();
