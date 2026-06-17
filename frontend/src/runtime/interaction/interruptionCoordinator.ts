/**
 * interruptionCoordinator.ts — Student Interruption & Resume Orchestration
 *
 * When a student interrupts a lecture mid-draw:
 *   1. Gracefully complete or checkpoint the current stroke
 *   2. Freeze the teacher cursor
 *   3. Freeze TTS audio at a natural pause point
 *   4. Allow student interaction
 *   5. On resume: smooth continuation from checkpoint
 */

import { interactionArbiter, OWNER, OWNERSHIP_PRIORITY, INTERACTION_MODE } from "./interactionArbiter";
import { audioTimeline } from "../audio/audioTimeline";
import { ttsPlayer } from "../audio/ttsPlayer";

export enum INTERRUPTION_STATE {
  IDLE = "idle",
  REQUESTED = "requested",        // Student initiated interrupt
  GRACEFUL_STOP = "graceful_stop", // Completing current stroke
  FROZEN = "frozen",               // Teaching paused, student active
  RESUMING = "resuming",           // Handoff back to teacher
  RESUMED = "resumed",             // Back to teaching
}

export interface InterruptionCheckpointData {
  timeMs: number;
  phase: string;
  cursor: any;
  activeStrokes: any[];
  narrationProgress: number;
  pendingEvents: any[];
}

class InterruptionCheckpoint implements InterruptionCheckpointData {
  public timeMs: number;
  public phase: string;
  public cursor: any;
  public activeStrokes: any[];
  public narrationProgress: number;
  public pendingEvents: any[];
  public createdAt: number;

  constructor({ timeMs, phase, cursor, activeStrokes, narrationProgress, pendingEvents }: InterruptionCheckpointData) {
    this.timeMs = timeMs;
    this.phase = phase;
    this.cursor = cursor;
    this.activeStrokes = activeStrokes;
    this.narrationProgress = narrationProgress;
    this.pendingEvents = pendingEvents;
    this.createdAt = Date.now();
  }
}

type ResumeCallback = (payload: { checkpoint: InterruptionCheckpoint | null }) => void;
type InterruptCallback = (payload: { checkpoint: InterruptionCheckpoint | null; context: any }) => void;

export class InterruptionCoordinator {
  private state: INTERRUPTION_STATE;
  private _checkpoint: InterruptionCheckpoint | null;
  private _teacherMotor: any;
  private _temporalScheduler: any;
  private _runtimeStore: any;
  private _gracePeriodMs: number;
  private _resumeCallbacks: ResumeCallback[];
  private _interruptCallbacks: InterruptCallback[];
  private _frozenEventQueue: any[];
  private _frozenNarrationMs: number;

  constructor() {
    this.state = INTERRUPTION_STATE.IDLE;
    this._checkpoint = null;
    this._teacherMotor = null;
    this._temporalScheduler = null;
    this._runtimeStore = null;
    this._gracePeriodMs = 300;
    this._resumeCallbacks = [];
    this._interruptCallbacks = [];
    this._frozenEventQueue = [];
    this._frozenNarrationMs = 0;
  }

  /**
   * Connect to runtime systems. Supports both positional and destructured object arguments.
   */
  public connect(
    teacherMotorOrObj: any,
    temporalScheduler?: any,
    runtimeStore?: any
  ): void {
    if (temporalScheduler === undefined && runtimeStore === undefined && teacherMotorOrObj && typeof teacherMotorOrObj === "object") {
      // Destructured object style
      this._teacherMotor = teacherMotorOrObj.teacherMotor;
      this._temporalScheduler = teacherMotorOrObj.temporalScheduler;
      this._runtimeStore = teacherMotorOrObj.runtimeStore;
    } else {
      // Positional parameters style
      this._teacherMotor = teacherMotorOrObj;
      this._temporalScheduler = temporalScheduler;
      this._runtimeStore = runtimeStore;
    }

    // Listen to arbiter ownership changes
    interactionArbiter.onStudentQueued(({ reason }) => {
      // Student tried to draw during teacher priority → check if we can gracefully stop
      this._checkGracefulStop(reason);
    });
  }

  /**
   * Request an interruption (student initiated interrupt).
   */
  public async interrupt(context: any): Promise<boolean> {
    if (this.state !== INTERRUPTION_STATE.IDLE) return false;

    this.state = INTERRUPTION_STATE.REQUESTED;

    // 1. Request ownership from arbiter (student priority)
    const result = interactionArbiter.request(
      OWNER.STUDENT,
      OWNERSHIP_PRIORITY.STUDENT_ACTIVE,
      `Student interrupted: ${context?.targetName || "unknown"}`,
      30000 // 30s max for interaction
    );

    if (!result.granted && !result.queued) {
      this.state = INTERRUPTION_STATE.IDLE;
      return false;
    }

    // 2. Wait for graceful stop if queued
    if (result.queued) {
      this.state = INTERRUPTION_STATE.GRACEFUL_STOP;
      await this._waitForGracefulStop(result.waitMs);
    }

    // 3. Take checkpoint
    this._checkpoint = this._takeCheckpoint();

    // 4. Freeze teacher systems
    this._freezeTeacher();

    // 5. Update mode
    interactionArbiter.setMode(INTERACTION_MODE.INTERRUPTED);
    this.state = INTERRUPTION_STATE.FROZEN;

    // 6. Notify callbacks
    this._interruptCallbacks.forEach(cb => cb({ checkpoint: this._checkpoint, context }));

    return true;
  }

  /**
   * Resume teaching after interruption.
   */
  public async resume({ rewindToCheckpoint = false } = {}): Promise<void> {
    if (this.state !== INTERRUPTION_STATE.FROZEN) return;

    this.state = INTERRUPTION_STATE.RESUMING;

    // 1. Release student ownership
    interactionArbiter.release(OWNER.STUDENT);
    interactionArbiter.setMode(INTERACTION_MODE.LECTURE);

    // 2. Resume teacher systems
    await this._resumeTeacher({ rewindToCheckpoint });

    // 3. Restore pending events
    if (this._frozenEventQueue.length > 0 && this._temporalScheduler) {
      this._temporalScheduler.enqueueEvents(this._frozenEventQueue);
      this._frozenEventQueue = [];
    }

    // 4. Request teacher ownership back
    interactionArbiter.request(
      OWNER.TEACHER,
      OWNERSHIP_PRIORITY.TEACHER_NORMAL,
      "Resuming explanation",
      0
    );

    this.state = INTERRUPTION_STATE.RESUMED;

    // 5. Notify callbacks
    this._resumeCallbacks.forEach(cb => cb({ checkpoint: this._checkpoint }));

    // Return to idle after a brief period
    setTimeout(() => {
      this.state = INTERRUPTION_STATE.IDLE;
      this._checkpoint = null;
    }, 1000);
  }

  /**
   * Check if currently interrupted.
   */
  public isInterrupted(): boolean {
    return this.state === INTERRUPTION_STATE.FROZEN;
  }

  /**
   * Get the current checkpoint (for UI display).
   */
  public getCheckpoint(): InterruptionCheckpoint | null {
    return this._checkpoint;
  }

  /**
   * Queue a live event for after resume.
   */
  public queueForResume(event: any): void {
    if (this.state === INTERRUPTION_STATE.FROZEN) {
      this._frozenEventQueue.push(event);
    }
  }

  /**
   * Register resume callback.
   */
  public onResume(callback: ResumeCallback): void {
    this._resumeCallbacks.push(callback);
  }

  /**
   * Register interrupt callback.
   */
  public onInterrupt(callback: InterruptCallback): void {
    this._interruptCallbacks.push(callback);
  }

  /**
   * Get current state.
   */
  public getState(): INTERRUPTION_STATE {
    return this.state;
  }

  /**
   * Reset to idle.
   */
  public reset(): void {
    this.state = INTERRUPTION_STATE.IDLE;
    this._checkpoint = null;
    this._frozenEventQueue = [];
    this._resumeCallbacks = [];
    this._interruptCallbacks = [];
  }

  // ── Private ────────────────────────────────────────────────

  private _takeCheckpoint(): InterruptionCheckpoint {
    const timeMs = audioTimeline.currentTimeMs;
    const motorState = this._teacherMotor?.takeSnapshot?.() || {};
    const pendingEvents = this._temporalScheduler
      ? [...this._temporalScheduler._eventQueue]
      : [];

    return new InterruptionCheckpoint({
      timeMs,
      phase: this._teacherMotor?.getPhase?.() || "idle",
      cursor: motorState.cursor || {},
      activeStrokes: motorState.strokes || [],
      narrationProgress: this._teacherMotor?.getNarrationStatus?.()?.progress || 0,
      pendingEvents,
    });
  }

  private _freezeTeacher(): void {
    // Pause audio
    audioTimeline.pause();
    ttsPlayer.pause();

    // Freeze motion
    this._teacherMotor?.pause?.();

    // Capture pending events
    if (this._temporalScheduler) {
      this._frozenEventQueue = [...this._temporalScheduler._eventQueue];
      this._temporalScheduler._eventQueue = [];
    }
  }

  private async _resumeTeacher({ rewindToCheckpoint }: { rewindToCheckpoint: boolean }): Promise<void> {
    // Resume audio
    audioTimeline.resume();
    ttsPlayer.resume();

    if (rewindToCheckpoint && this._checkpoint) {
      // Seek back to checkpoint with smooth transition
      audioTimeline.seek(this._checkpoint.timeMs);
      await new Promise(r => setTimeout(r, 100)); // Brief sync delay
    }

    // Resume motion
    this._teacherMotor?.resume?.();
  }

  private async _waitForGracefulStop(maxWaitMs: number): Promise<void> {
    const deadline = Date.now() + Math.min(maxWaitMs, this._gracePeriodMs);
    return new Promise(resolve => {
      const check = () => {
        // Check if current stroke has completed or deadline hit
        const hasActiveStrokes = this._teacherMotor?.runtime?.strokeScheduler?.hasActiveStrokes?.() ?? false;
        if (!hasActiveStrokes || Date.now() >= deadline) {
          resolve();
        } else {
          requestAnimationFrame(check);
        }
      };
      requestAnimationFrame(check);
    });
  }

  private _checkGracefulStop(reason: string): void {
    // If currently in a non-critical phase, initiate graceful stop
    const phase = this._teacherMotor?.getPhase?.() || "idle";
    if (phase === "idle" || phase === "pausing") {
      // Defer to next tick to break synchronous recursion stack overflow
      setTimeout(() => {
        interactionArbiter.onTeacherIdle();
      }, 0);
    }
  }
}

// ── Singleton ──────────────────────────────────────────────────
export const interruptionCoordinator = new InterruptionCoordinator();
