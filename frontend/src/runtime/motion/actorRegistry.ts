/**
 * actorRegistry.ts — Manages all active motion actors in the scene.
 *
 * The registry is the central authority for actor lifecycles:
 * - Teacher cursor
 * - Active strokes
 * - Narration actor
 * - Emphasis actors
 * - Focus actors
 * - Gesture actors
 *
 * Actors are temporal entities with lifecycles, NOT static scene objects.
 */

// ── Actor Types & Enums ────────────────────────────────────────

export enum ACTOR_TYPE {
  CURSOR = "cursor",
  STROKE = "stroke",
  NARRATION = "narration",
  FOCUS = "focus",
  GESTURE = "gesture",
  EMPHASIS = "emphasis",
  CONSTRUCTION = "construction",
}

export enum ACTOR_LIFECYCLE {
  CREATED = "created",
  ACTIVE = "active",
  PAUSED = "paused",
  COMPLETING = "completing",
  DISPOSED = "disposed",
}

// ── Struct Data Interfaces ─────────────────────────────────────

export interface ActorInstance {
  getSnapshot?(): Record<string, any> | any;
  [key: string]: any; // Supports custom methods on derived/duck-typed actor subclasses
}

export interface ActorMetadata {
  createdAtMs?: number;
  [key: string]: any;
}

export interface ActorRegistryEntry {
  actorId: string;
  actorType: ACTOR_TYPE;
  instance: ActorInstance;
  lifecycle: ACTOR_LIFECYCLE;
  createdAtMs: number;
  metadata: ActorMetadata;
}

export interface RegistryMetrics {
  totalActors: number;
  totalCreated: number;
  totalDisposed: number;
  byType: Record<string, number>;
  pendingDisposals: number;
}

export interface ActorSnapshotEntry {
  actorId: string;
  actorType: ACTOR_TYPE;
  lifecycle: ACTOR_LIFECYCLE;
  metadata: ActorMetadata;
  state: Record<string, any> | null;
}

// ── ActorRegistry Class ────────────────────────────────────────

export class ActorRegistry {
  private _actors: Map<string, ActorRegistryEntry>;
  private _typeIndex: Map<ACTOR_TYPE, Set<string>>;
  private _disposalQueue: string[];
  private _totalCreated: number;
  private _totalDisposed: number;

  constructor() {
    this._actors = new Map();
    this._typeIndex = new Map();

    // Initialize type indices dynamically from the Enum keys
    for (const type of Object.values(ACTOR_TYPE)) {
      this._typeIndex.set(type as ACTOR_TYPE, new Set<string>());
    }

    // Disposal processing records
    this._disposalQueue = [];
    this._totalCreated = 0;
    this._totalDisposed = 0;
  }

  /**
   * Register a new actor or update an existing instance contract.
   *
   * @param actorId - Unique identifier
   * @param actorType - Evaluated type string from ACTOR_TYPE
   * @param instance - The polymorphic duck-typed actor instance (CursorActor, etc.)
   * @param metadata - Immutable initialization values or timeline tags
   * @returns The newly allocated or updated actor data record
   */
  public register(
    actorId: string,
    actorType: ACTOR_TYPE,
    instance: ActorInstance,
    metadata: ActorMetadata = {}
  ): ActorRegistryEntry {
    const existing = this._actors.get(actorId);
    
    if (existing) {
      // Safely perform mutations on the pre-existing allocation record
      existing.instance = instance;
      existing.metadata = { ...existing.metadata, ...metadata };
      return existing;
    }

    const entry: ActorRegistryEntry = {
      actorId,
      actorType,
      instance,
      lifecycle: ACTOR_LIFECYCLE.CREATED,
      createdAtMs: metadata.createdAtMs || 0,
      metadata,
    };

    this._actors.set(actorId, entry);
    this._typeIndex.get(actorType)?.add(actorId);
    this._totalCreated++;

    return entry;
  }

  /**
   * Advance an actor's runtime flag to active.
   */
  public activate(actorId: string): void {
    const entry = this._actors.get(actorId);
    if (entry) entry.lifecycle = ACTOR_LIFECYCLE.ACTIVE;
  }

  /**
   * Halt actor updates by modifying state flag to paused.
   */
  public pause(actorId: string): void {
    const entry = this._actors.get(actorId);
    if (entry) entry.lifecycle = ACTOR_LIFECYCLE.PAUSED;
  }

  /**
   * Queue an actor for garbage collection cleanup loops.
   */
  public dispose(actorId: string): void {
    const entry = this._actors.get(actorId);
    if (entry) {
      entry.lifecycle = ACTOR_LIFECYCLE.DISPOSED;
      this._disposalQueue.push(actorId);
    }
  }

  /**
   * Retrieve structured wrap record of an actor by ID.
   */
  public get(actorId: string): ActorRegistryEntry | undefined {
    return this._actors.get(actorId);
  }

  /**
   * Get the logic engine execution instance of an actor.
   */
  public getInstance(actorId: string): ActorInstance | undefined {
    return this._actors.get(actorId)?.instance;
  }

  /**
   * Gather a filtered collection of all records matching an actor category type.
   */
  public getByType(actorType: ACTOR_TYPE): ActorRegistryEntry[] {
    const ids = this._typeIndex.get(actorType);
    if (!ids) return [];
    
    const result: ActorRegistryEntry[] = [];
    for (const id of ids) {
      const entry = this._actors.get(id);
      if (entry && entry.lifecycle !== ACTOR_LIFECYCLE.DISPOSED) {
        result.push(entry);
      }
    }
    return result;
  }

  /**
   * Fetch elements matching the live state criteria.
   */
  public getActive(): ActorRegistryEntry[] {
    const result: ActorRegistryEntry[] = [];
    for (const [, entry] of this._actors) {
      if (entry.lifecycle === ACTOR_LIFECYCLE.ACTIVE) {
        result.push(entry);
      }
    }
    return result;
  }

  /**
   * Deallocate all references to actors flagged as disposed from cache maps.
   * Call on each game or clock ticker loop pass.
   */
  public flushDisposals(): void {
    for (const actorId of this._disposalQueue) {
      const entry = this._actors.get(actorId);
      if (entry) {
        this._typeIndex.get(entry.actorType)?.delete(actorId);
        this._actors.delete(actorId);
        this._totalDisposed++;
      }
    }
    this._disposalQueue = [];
  }

  /**
   * Extract historical diagnostic operational parameters.
   */
  public getMetrics(): RegistryMetrics {
    const counts: Record<string, number> = {};
    for (const [type, ids] of this._typeIndex) {
      // FIX: Cast enum key as string to bypass unintentional type overlap check safely
      const typeStr = type as string;
      if (typeStr !== "__proto__" && typeStr !== "constructor" && typeStr !== "prototype") {
        Reflect.set(counts, type, ids.size);
      }
    }
    return {
      totalActors: this._actors.size,
      totalCreated: this._totalCreated,
      totalDisposed: this._totalDisposed,
      byType: counts,
      pendingDisposals: this._disposalQueue.length,
    };
  }

  /**
   * Serialization footprint builder mapping runtime snapshots for video/replay.
   */
  public takeSnapshot(): Record<string, ActorSnapshotEntry> {
    const snapshot: Record<string, ActorSnapshotEntry> = {};
    for (const [actorId, entry] of this._actors) {
      if (entry.lifecycle === ACTOR_LIFECYCLE.DISPOSED) continue;
      
      if (actorId !== "__proto__" && actorId !== "constructor" && actorId !== "prototype") {
        Reflect.set(snapshot, actorId, {
          actorId,
          actorType: entry.actorType,
          lifecycle: entry.lifecycle,
          metadata: entry.metadata,
          state: entry.instance?.getSnapshot?.() || null,
        });
      }
    }
    return snapshot;
  }

  /**
   * Hard wipe the state configuration allocations.
   */
  public reset(): void {
    this._actors.clear();
    for (const [, ids] of this._typeIndex) {
      ids.clear();
    }
    this._disposalQueue = [];
  }
}