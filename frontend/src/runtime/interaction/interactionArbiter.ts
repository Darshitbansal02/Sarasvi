/**
 * interactionArbiter.ts — Pointer Ownership & Priority Controller
 *
 * Prevents cursor conflicts when teacher is drawing AND student tries to interact.
 * Enforces strict priority ordering:
 * 1. Critical narration (nothing interrupts)
 * 2. Teacher construction (student must wait)
 * 3. Emphasis moments (brief lock)
 * 4. Student interaction (allowed during pauses/idle)
 * 5. Background idle (anyone can take over)
 *
 * This is the single source of truth for who "owns" the canvas at any moment.
 */

// ── Ownership Priority ─────────────────────────────────────────

export enum OWNERSHIP_PRIORITY {
  LOCKED = 0,           // Nothing can interrupt (critical construction)
  TEACHER_HIGH = 1,     // Teacher drawing a key concept
  TEACHER_NORMAL = 2,   // Teacher drawing a detail
  TEACHER_IDLE = 3,     // Teacher paused between steps
  STUDENT_ACTIVE = 4,   // Student actively drawing
  STUDENT_HOVER = 5,    // Student hovering (no pointer conflict)
  FREE = 6,             // No owner
}

export enum OWNER {
  SYSTEM = "system",
  TEACHER = "teacher",
  STUDENT = "student",
  NONE = "none",
}

// ── Interaction Modes ──────────────────────────────────────────

export enum INTERACTION_MODE {
  LECTURE = "lecture",       // Teacher has full control
  PRACTICE = "practice",     // Student has full control
  SOCRATIC = "socratic",     // Alternating control
  INTERRUPTED = "interrupted", // Student interrupted lecture
  TRANSITIONING = "transitioning",
}

// ── Event Signature Payloads ───────────────────────────────────

export interface OwnerChangeEventPayload {
  from: OWNER | INTERACTION_MODE | string;
  to: OWNER | INTERACTION_MODE | string;
  priority?: OWNERSHIP_PRIORITY;
  reason?: string;
  owner?: OWNER;
}

export interface StudentQueuedEventPayload {
  reason: string;
  estimatedWaitMs: number;
}

export interface StudentGrantedEventPayload {
  reason: string;
  waitedMs: number;
}

export interface PendingStudentRequest {
  reason: string;
  durationMs: number;
  requestedAt: number;
}

export interface ArbiterStateSnapshot {
  owner: OWNER;
  priority: OWNERSHIP_PRIORITY;
  mode: INTERACTION_MODE;
  isLocked: boolean;
  lockReason: string | null;
  hasPendingStudent: boolean;
  canStudentDraw: boolean;
}

export interface ArbiterMetricsSnapshot {
  totalRequests: number;
  grantedRequests: number;
  deniedRequests: number;
  queuedRequests: number;
  grantRate: number;
  recentConflicts: PointerConflict[];
}

// ── PointerConflict ────────────────────────────────────────────

export class PointerConflict {
  public requester: OWNER;
  public currentOwner: OWNER;
  public reason: string;
  public resolvedTo: OWNER | null;
  public timestamp: number;

  constructor(requester: OWNER, currentOwner: OWNER, reason: string) {
    this.requester = requester;
    this.currentOwner = currentOwner;
    this.reason = reason;
    this.resolvedTo = null;
    this.timestamp = Date.now();
  }
}

// ── InteractionArbiter ─────────────────────────────────────────

export class InteractionArbiter {
  private _currentOwner: OWNER;
  private _currentPriority: OWNERSHIP_PRIORITY;
  private _ownershipStartMs: number;
  private _ownershipExpiryMs: number | null;

  private _mode: INTERACTION_MODE;

  private _isLocked: boolean;
  private _lockReason: string | null;
  private _lockExpiryMs: number | null;

  private _conflicts: PointerConflict[];
  private _maxConflicts: number;

  private _pendingStudentRequest: PendingStudentRequest | null;

  private _onOwnerChangeCallbacks: Array<(payload: OwnerChangeEventPayload) => void>;
  private _onConflictCallbacks: Array<(conflict: PointerConflict) => void>;
  private _onStudentQueuedCallbacks: Array<(payload: StudentQueuedEventPayload) => void>;
  private _onStudentGrantedCallbacks: Array<(payload: StudentGrantedEventPayload) => void>;

  private _idleFired: boolean;

  private _totalRequests: number;
  private _grantedRequests: number;
  private _deniedRequests: number;
  private _queuedRequests: number;

  constructor() {
    // Current ownership state
    this._currentOwner = OWNER.NONE;
    this._currentPriority = OWNERSHIP_PRIORITY.FREE;
    this._ownershipStartMs = 0;
    this._ownershipExpiryMs = null; 

    // Interaction mode
    this._mode = INTERACTION_MODE.LECTURE;

    // Lock state
    this._isLocked = false;
    this._lockReason = null;
    this._lockExpiryMs = null;

    // Conflict log track limits
    this._conflicts = [];
    this._maxConflicts = 50;

    // Pending state request registers
    this._pendingStudentRequest = null;

    // Callbacks collection tables
    this._onOwnerChangeCallbacks = [];
    this._onConflictCallbacks = [];
    this._onStudentQueuedCallbacks = [];
    this._onStudentGrantedCallbacks = [];

    // Idle event debounce gate
    this._idleFired = false;

    // Performance tracking metrics
    this._totalRequests = 0;
    this._grantedRequests = 0;
    this._deniedRequests = 0;
    this._queuedRequests = 0;
  }

  /**
   * Request ownership of the canvas.
   * Numerically lower values in OWNERSHIP_PRIORITY represent higher priority context.
   */
  public request(
    owner: OWNER, 
    priority: OWNERSHIP_PRIORITY, 
    reason: string = "", 
    durationMs: number = 0
  ): { granted: boolean; queued: boolean; waitMs: number } {
    this._totalRequests++;
    const nowMs = Date.now();

    // Verify hard lock constraints
    if (this._isLocked) {
      if (owner === OWNER.SYSTEM && priority === OWNERSHIP_PRIORITY.LOCKED) {
        // System overrides system lock structures atomically
        this._grantOwnership(owner, priority, reason, durationMs, nowMs);
        return { granted: true, queued: false, waitMs: 0 };
      }
      this._deniedRequests++;
      return { 
        granted: false, 
        queued: false, 
        waitMs: this._lockExpiryMs ? this._lockExpiryMs - nowMs : Infinity 
      };
    }

    // Process real-time temporal ownership expiries
    if (this._ownershipExpiryMs && nowMs > this._ownershipExpiryMs) {
      this._release(this._currentOwner);
    }

    // Grant canvas access if unallocated or priority holds greater value
    if (this._currentOwner === OWNER.NONE || priority <= this._currentPriority) {
      this._grantOwnership(owner, priority, reason, durationMs, nowMs);
      this._grantedRequests++;
      return { granted: true, queued: false, waitMs: 0 };
    }

    // Capture student interactions inside lecture paths into the buffer queue
    if (owner === OWNER.STUDENT && this._mode === INTERACTION_MODE.LECTURE) {
      this._pendingStudentRequest = { reason, durationMs, requestedAt: nowMs };
      this._queuedRequests++;

      const conflict = new PointerConflict(owner, this._currentOwner, reason);
      this._logConflict(conflict);
      this._onStudentQueuedCallbacks.forEach(cb => cb({ 
        reason, 
        estimatedWaitMs: this._estimateWait(nowMs) 
      }));

      return { granted: false, queued: true, waitMs: this._estimateWait(nowMs) };
    }

    // Absolute Denial execution path
    this._deniedRequests++;
    this._logConflict(new PointerConflict(owner, this._currentOwner, reason));
    return { granted: false, queued: false, waitMs: 0 };
  }

  /**
   * Release ownership cleanly.
   */
  public release(owner: OWNER): void {
    if (this._currentOwner !== owner && owner !== OWNER.SYSTEM) return;
    this._release(owner);
  }

  /**
   * Hard lock the canvas layout engine.
   */
  public lock(reason: string, durationMs: number = 0): void {
    this._isLocked = true;
    this._lockReason = reason;
    this._lockExpiryMs = durationMs > 0 ? Date.now() + durationMs : null;
    this._grantOwnership(OWNER.SYSTEM, OWNERSHIP_PRIORITY.LOCKED, reason, durationMs, Date.now());
  }

  /**
   * Deallocate current hard lock constraints.
   */
  public unlock(): void {
    this._isLocked = false;
    this._lockReason = null;
    this._lockExpiryMs = null;
    this._release(OWNER.SYSTEM);
  }

  /**
   * Check if a specific owner currently holds control.
   */
  public owns(owner: OWNER): boolean {
    return this._currentOwner === owner;
  }

  /**
   * Evaluates if student pointer interaction paths can currently update layouts.
   */
  public canStudentDraw(): boolean {
    if (this._isLocked) return false;
    if (this._mode === INTERACTION_MODE.PRACTICE) return true;
    if (this._mode === INTERACTION_MODE.LECTURE) {
      return (this._currentOwner === OWNER.TEACHER &&
             this._currentPriority >= OWNERSHIP_PRIORITY.TEACHER_IDLE) ||
             this._currentOwner === OWNER.NONE ||
             this._currentOwner === OWNER.STUDENT;
    }
    return this._currentOwner === OWNER.NONE || this._currentOwner === OWNER.STUDENT;
  }

  /**
   * Switch session interactivity strategies safely.
   */
  public setMode(mode: INTERACTION_MODE): void {
    const prev = this._mode;
    this._mode = mode;

    if (mode === INTERACTION_MODE.PRACTICE) {
      this._release(OWNER.TEACHER);
    } else if (mode === INTERACTION_MODE.LECTURE) {
      this._release(OWNER.STUDENT);
    }

    this._onOwnerChangeCallbacks.forEach(cb => cb({
      from: prev,
      to: mode,
      owner: this._currentOwner,
    }));
  }

  /**
   * Called when teacher construction phase pauses or ends.
   * Flushes buffered downstream student interaction pipelines.
   */
  public onTeacherIdle(): void {
    if (this._pendingStudentRequest) {
      const req = this._pendingStudentRequest;
      this._pendingStudentRequest = null;

      const result = this.request(OWNER.STUDENT, OWNERSHIP_PRIORITY.STUDENT_ACTIVE, req.reason, req.durationMs);
      if (result.granted) {
        this._onStudentGrantedCallbacks.forEach(cb => cb({ 
          reason: req.reason, 
          waitedMs: Date.now() - req.requestedAt 
        }));
      }
    } else {
      // GAP-1 FIX: Notify structural event system frameworks to wake core continuation loops
      if (!this._idleFired) {
        this._idleFired = true;
        if (typeof window !== "undefined") {
          window.dispatchEvent(new CustomEvent("interaction_idle"));
        }
      }
    }
  }

  /**
   * Time ticks processor hook driving lifecycle structural mutations.
   */
  public tick(absoluteTimeMs: number): void {
    const nowMs = Date.now();

    // Check lock boundary parameters
    if (this._isLocked && this._lockExpiryMs && nowMs > this._lockExpiryMs) {
      this.unlock();
    }

    // Check ownership duration parameters
    if (this._ownershipExpiryMs && nowMs > this._ownershipExpiryMs) {
      this._release(this._currentOwner);
      this.onTeacherIdle();
    }
  }

  /**
   * Get an atomic state model snapshot.
   */
  public getState(): ArbiterStateSnapshot {
    return {
      owner: this._currentOwner,
      priority: this._currentPriority,
      mode: this._mode,
      isLocked: this._isLocked,
      lockReason: this._lockReason,
      hasPendingStudent: !!this._pendingStudentRequest,
      canStudentDraw: this.canStudentDraw(),
    };
  }

  /**
   * Get operational diagnostic telemetry tracking variables.
   */
  public getMetrics(): ArbiterMetricsSnapshot {
    return {
      totalRequests: this._totalRequests,
      grantedRequests: this._grantedRequests,
      deniedRequests: this._deniedRequests,
      queuedRequests: this._queuedRequests,
      grantRate: this._totalRequests > 0 ? this._grantedRequests / this._totalRequests : 0,
      recentConflicts: this._conflicts.slice(-5),
    };
  }

  // ── Event Subscription Registration Methods ──────────────────

  public onOwnerChange(cb: (payload: OwnerChangeEventPayload) => void): void { this._onOwnerChangeCallbacks.push(cb); }
  public onConflict(cb: (conflict: PointerConflict) => void): void { this._onConflictCallbacks.push(cb); }
  public onStudentQueued(cb: (payload: StudentQueuedEventPayload) => void): void { this._onStudentQueuedCallbacks.push(cb); }
  public onStudentGranted(cb: (payload: StudentGrantedEventPayload) => void): void { this._onStudentGrantedCallbacks.push(cb); }

  /**
   * Flush all allocation tables.
   */
  public reset(): void {
    this._currentOwner = OWNER.NONE;
    this._currentPriority = OWNERSHIP_PRIORITY.FREE;
    this._isLocked = false;
    this._pendingStudentRequest = null;
    this._mode = INTERACTION_MODE.LECTURE;
    this._conflicts = [];
    this._idleFired = false;
  }

  /**
   * Clear active idle debouncer tracking gates.
   */
  public resetIdle(): void {
    this._idleFired = false;
  }

  // ── Private Internal Atomic Modification Blocks ─────────────

  private _grantOwnership(
    owner: OWNER, 
    priority: OWNERSHIP_PRIORITY, 
    reason: string, 
    durationMs: number, 
    nowMs: number
  ): void {
    const prev = this._currentOwner;
    this._currentOwner = owner;
    this._currentPriority = priority;
    this._ownershipStartMs = nowMs;
    this._ownershipExpiryMs = durationMs > 0 ? nowMs + durationMs : null;

    if (owner === OWNER.TEACHER && priority <= OWNERSHIP_PRIORITY.TEACHER_NORMAL) {
      this._idleFired = false;
    }

    if (prev !== owner) {
      this._onOwnerChangeCallbacks.forEach(cb => cb({ 
        from: prev, 
        to: owner, 
        priority, 
        reason 
      }));
    }
  }

  private _release(owner: OWNER): void {
    const prev = this._currentOwner;
    this._currentOwner = OWNER.NONE;
    this._currentPriority = OWNERSHIP_PRIORITY.FREE;
    this._ownershipExpiryMs = null;

    if (prev !== OWNER.NONE) {
      this._onOwnerChangeCallbacks.forEach(cb => cb({ 
        from: prev, 
        to: OWNER.NONE, 
        reason: "released" 
      }));
    }
  }

  private _estimateWait(nowMs: number): number {
    if (this._ownershipExpiryMs) {
      return Math.max(0, this._ownershipExpiryMs - nowMs);
    }
    return 2000; // Base baseline guess constraint: 2000ms fallback
  }

  private _logConflict(conflict: PointerConflict): void {
    this._conflicts.push(conflict);
    if (this._conflicts.length > this._maxConflicts) {
      this._conflicts.shift();
    }
    this._onConflictCallbacks.forEach(cb => cb(conflict));
  }
}

// ── Singleton Allocation ───────────────────────────────────────
export const interactionArbiter = new InteractionArbiter();